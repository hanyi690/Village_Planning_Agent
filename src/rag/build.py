"""
知识库构建脚本
符合 LangChain 最佳实践，支持 Docker 部署
针对 Planning Agent 优化：使用统一切片策略
"""
import os
import sys
import asyncio
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from langchain_chroma import Chroma

from src.rag.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    DATA_DIR,
    EMBEDDING_MODEL_NAME,
    EMBEDDING_DEVICE,
    EMBEDDING_PROVIDER,
    DASHSCOPE_API_KEY,
    ALIYUN_EMBEDDING_BASE_URL,
    ALIYUN_EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    VECTOR_DB_TYPE,
    DEFAULT_PROVIDER,
    is_docker,
    setup_huggingface_env,
)
from src.rag.utils import load_knowledge_base
from src.rag.visualize import SliceInspector
from src.rag.core.context_manager import DocumentContextManager
from src.rag.core.summarization import DocumentSummarizer, DocumentSummary
from src.rag.metadata.injector import MetadataInjector, CategoryDetector, InjectionParams
from src.rag.slicing.slicer import SlicingStrategyFactory
from src.rag.core.kb_manager import infer_doc_type


def load_documents():
    """加载文档（支持分类）"""
    if not DATA_DIR.exists():
        print(f"❌ 错误：数据目录不存在: {DATA_DIR}")
        print(f"\n请按以下结构组织数据:")
        print(f"  {DATA_DIR}/")
        print(f"  ├── policies/")
        print(f"  │   ├── 文件1.md")
        print(f"  │   ├── 文件2.pdf")
        print(f"  │   └── 文件3.docx")
        print(f"  └── cases/")
        print(f"      ├── 案例1.md")
        print(f"      ├── 案例2.pptx")
        print(f"      └── 案例3.txt")
        return []

    try:
        documents = load_knowledge_base(DATA_DIR)
        return documents
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return []


def slice_documents(documents):
    """使用统一切片策略切分文档"""
    print("\n✂️  正在切分文档...")
    print(f"   配置: 使用 UnifiedMarkdownSlicer（差异化策略）")

    from langchain_core.documents import Document

    all_splits = []
    for doc in documents:
        source = doc.metadata.get("source", "")
        content = doc.page_content

        # 推断文档类型
        doc_type = infer_doc_type(source, content)
        print(f"   [{doc_type}] {source}")

        # 使用统一切片策略
        slices = SlicingStrategyFactory.slice_document(
            content, doc_type, {"source": source}
        )

        # 创建 Document 对象
        for idx, slice_text in enumerate(slices):
            split_doc = Document(
                page_content=slice_text,
                metadata={
                    "source": source,
                    "chunk_index": idx,
                    "total_chunks": len(slices),
                    "type": doc_type,
                    **doc.metadata,
                },
            )
            all_splits.append(split_doc)

    print(f"✅ 切分完成，共 {len(all_splits)} 个切片")
    return all_splits


def visualize_splits(splits):
    """可视化切片结果"""
    print("\n📊 切片可视化分析\n")

    inspector = SliceInspector(splits)
    inspector.print_summary()

    print("\n" + "="*60)
    inspector.print_slice_details(start_idx=0, end_idx=3, show_content=True)

    print("\n" + "="*60)
    inspector.print_issues(max_issues=10)

    output_json = CHROMA_PERSIST_DIR / "slices_analysis.json"
    inspector.export_to_json(output_json)

    return inspector


def _init_local_embedding():
    """初始化本地 HuggingFace Embedding 模型"""
    setup_huggingface_env()

    from langchain_huggingface import HuggingFaceEmbeddings

    print(f"   Provider: local (HuggingFace)")
    print(f"   Model: {EMBEDDING_MODEL_NAME}")

    if is_docker():
        print("🐳 检测到 Docker 环境，使用 CPU 推理")
        device = "cpu"
    else:
        device = EMBEDDING_DEVICE
        print(f"💻 设备: {device}")

    embedding_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"✅ 本地 Embedding 模型已加载")
    return embedding_model


def _init_aliyun_embedding():
    """初始化阿里云 DashScope Embedding API"""
    if not DASHSCOPE_API_KEY:
        raise ValueError(
            "EMBEDDING_PROVIDER=aliyun 但未设置 DASHSCOPE_API_KEY。"
            "请在 .env 中配置 DASHSCOPE_API_KEY=your_api_key"
        )

    from langchain_openai import OpenAIEmbeddings

    print(f"   Provider: aliyun (DashScope)")
    print(f"   Model: {ALIYUN_EMBEDDING_MODEL}")
    print(f"   Dimensions: {EMBEDDING_DIMENSIONS}")
    print(f"   Base URL: {ALIYUN_EMBEDDING_BASE_URL}")

    embedding_model = OpenAIEmbeddings(
        api_key=DASHSCOPE_API_KEY,
        base_url=ALIYUN_EMBEDDING_BASE_URL,
        model=ALIYUN_EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
    )

    print(f"✅ 阿里云 Embedding API 已连接")
    return embedding_model


def get_embedding_model(provider: str = None):
    """获取 Embedding 模型实例"""
    provider = provider or EMBEDDING_PROVIDER
    if provider == "aliyun":
        return _init_aliyun_embedding()
    else:
        return _init_local_embedding()


def create_chroma_store(
    documents,
    embedding_model = None,
    persist_dir: Path = None,
    collection_name: str = None,
):
    """创建 Chroma 向量存储"""
    if embedding_model is None:
        embedding_model = get_embedding_model()

    persist_dir = persist_dir or CHROMA_PERSIST_DIR
    persist_dir.mkdir(parents=True, exist_ok=True)

    collection_name = collection_name or CHROMA_COLLECTION_NAME

    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embedding_model,
        collection_name=collection_name,
        persist_directory=str(persist_dir),
    )

    print(f"✅ Chroma 数据库构建完成！")
    print(f"   集合名称: {collection_name}")
    print(f"   持久化路径: {persist_dir}")

    return vectorstore


async def build_vector_store(
    splits,
    documents = None,
    use_semantic: bool = False,
    embedding_model = None,
):
    """构建向量存储（支持语义标注）"""
    print(f"\n🧠 正在初始化 Embedding 模型...")

    if embedding_model is None:
        embedding_model = get_embedding_model()

    print(f"\n🏷️  正在进行维度标注...")
    print(f"   模式: {'语义标注 (Flash模型)' if use_semantic else '关键词匹配'}")
    print(f"   切片数: {len(splits)}")

    injector = MetadataInjector(use_semantic=use_semantic)

    if use_semantic:
        print(f"   提示: 语义标注需要调用 LLM API，可能需要几分钟")
        tagged_docs = await injector.inject_batch_async(splits, use_semantic=True)
    else:
        tagged_docs = injector.inject_batch(splits)

    print(f"✅ 维度标注完成")

    return create_chroma_store(documents=tagged_docs, embedding_model=embedding_model)


def main(use_semantic: bool = False):
    """主函数（支持语义标注模式）"""
    print("=" * 60)
    print(f"🚀 开始构建知识库（{'语义标注' if use_semantic else '标准'}模式）")
    print("=" * 60)

    documents = load_documents()
    if not documents:
        print("\n❌ 没有加载到文档，退出构建")
        return

    splits = slice_documents(documents)
    inspector = visualize_splits(splits)

    print("\n" + "=" * 60)
    user_input = input("是否继续构建向量数据库？(y/n): ").strip().lower()
    if user_input not in ['y', 'yes', '是']:
        print("❌ 已取消构建")
        return

    print("\n🔨 开始构建向量数据库...")
    vectorstore = asyncio.run(build_vector_store(
        splits=splits,
        documents=documents,
        use_semantic=use_semantic,
    ))

    print("\n📚 正在构建文档索引（支持全文上下文查询）...")
    context_manager = DocumentContextManager()
    context_manager.build_index(documents, splits)

    print("\n" + "=" * 60)
    print("📝 阶段2：生成层次化摘要（可选）")
    print("=" * 60)
    print("提示：摘要生成需要调用 LLM API，可能需要几分钟时间")
    print("      如果不需要摘要功能，可以跳过此步骤\n")

    user_input = input("是否生成文档摘要？（推荐）(y/n): ").strip().lower()

    if user_input in ['y', 'yes', '是']:
        print("\n⏳ 正在生成文档摘要...")
        print(f"   模型: {DEFAULT_PROVIDER}")
        print(f"   文档数: {len(documents)}\n")

        try:
            summarizer = DocumentSummarizer(provider=DEFAULT_PROVIDER)

            summary_count = 0
            for doc in documents:
                source = doc.metadata.get("source", "unknown")

                if source in context_manager.doc_index:
                    try:
                        print(f"   [{summary_count + 1}/{len(documents)}] 生成摘要: {source}")
                        summary = summarizer.generate_summary(doc)

                        doc_index = context_manager.doc_index[source]
                        doc_index.executive_summary = summary.executive_summary
                        doc_index.chapter_summaries = [
                            {
                                "title": ch.title,
                                "level": ch.level,
                                "summary": ch.summary,
                                "key_points": ch.key_points,
                                "start_index": ch.start_index,
                                "end_index": ch.end_index
                            }
                            for ch in summary.chapter_summaries
                        ]
                        doc_index.key_points = summary.key_points

                        summary_count += 1

                    except Exception as e:
                        print(f"   ⚠️  {source} 摘要生成失败: {str(e)}")
                        continue

            print(f"\n✅ 摘要生成完成: {summary_count}/{len(documents)} 个文档")

        except Exception as e:
            print(f"\n❌ 摘要生成失败: {str(e)}")
            print("   索引将不包含摘要信息，但仍可正常使用")
            import traceback
            traceback.print_exc()

    else:
        print("⏭️  已跳过摘要生成")
        print("   提示：可以稍后运行 build.py 重新生成摘要")

    context_manager.save()
    print(f"✅ 文档索引已保存")

    print("\n" + "=" * 60)
    print("🎉 知识库构建完成！")
    print("=" * 60)
    print(f"\n📊 统计信息:")
    print(f"   • 原始文档数: {len(documents)}")
    print(f"   • 切片数量: {len(splits)}")
    print(f"   • 标注模式: {'语义标注' if use_semantic else '关键词匹配'}")
    print(f"   • 平均切片大小: {inspector.stats['avg_chars']:.0f} 字符")
    print(f"\n💾 数据库位置: {CHROMA_PERSIST_DIR}")
    print(f"📊 切片分析报告: {CHROMA_PERSIST_DIR / 'slices_analysis.json'}")
    print(f"📖 文档索引: {CHROMA_PERSIST_DIR / 'document_index.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic", action="store_true", help="使用语义标注")
    args = parser.parse_args()
    main(use_semantic=args.semantic)