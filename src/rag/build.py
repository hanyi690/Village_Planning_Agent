"""
知识库构建脚本
符合 LangChain 最佳实践，支持 Docker 部署
针对 Planning Agent 优化：更大的 chunk_size 保留上下文
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.append(str(Path(__file__).parent.parent.parent))

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

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
from src.rag.metadata.injector import MetadataInjector, CategoryDetector
from src.rag.slicing.strategies import SlicingStrategyFactory


def load_documents():
    """
    加载文档（支持分类）
    目录结构:
    src/data/
    ├── policies/
    │   ├── *.md
    │   ├── *.txt
    │   ├── *.pptx
    │   ├── *.pdf
    │   └── *.docx
    └── cases/
        ├── *.md
        ├── *.txt
        ├── *.pptx
        ├── *.pdf
        └── *.docx
    """
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

    # 使用新的分类加载函数
    try:
        documents = load_knowledge_base(DATA_DIR)
        return documents
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return []


def split_documents(documents):
    """
    切分文档
    针对 Planning Agent 优化：使用更大的 chunk_size
    """
    print("\n✂️  正在切分文档...")
    print(f"   配置: chunk_size={CHUNK_SIZE}, chunk_overlap={CHUNK_OVERLAP}")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        add_start_index=True,  # 添加字符索引用于引用
    )

    splits = text_splitter.split_documents(documents)
    print(f"✅ 切分完成，共 {len(splits)} 个切片")

    return splits


def visualize_splits(splits):
    """
    可视化切片结果
    帮助发现冗余和垃圾信息
    """
    print("\n📊 切片可视化分析\n")

    inspector = SliceInspector(splits)

    # 打印统计摘要
    inspector.print_summary()

    # 打印前 3 个切片的详情
    print("\n" + "="*60)
    inspector.print_slice_details(start_idx=0, end_idx=3, show_content=True)

    # 查找并打印潜在问题
    print("\n" + "="*60)
    inspector.print_issues(max_issues=10)

    # 导出完整数据到 JSON（可选）
    output_json = CHROMA_PERSIST_DIR / "slices_analysis.json"
    inspector.export_to_json(output_json)

    return inspector


def build_vector_store(splits):
    """
    构建向量存储
    支持多种向量数据库（Chroma/FAISS/Qdrant）
    支持 Embedding 模式: local (HuggingFace) / aliyun (DashScope API)
    """
    print(f"\n🧠 正在初始化 Embedding 模型...")

    # 初始化 Embedding 模型
    if EMBEDDING_PROVIDER == "aliyun":
        embedding_model = _init_aliyun_embedding()
    else:
        embedding_model = _init_local_embedding()

    # 根据配置选择向量数据库
    if VECTOR_DB_TYPE == "chroma":
        print(f"💾 使用 Chroma 向量数据库")
        print(f"   持久化路径: {CHROMA_PERSIST_DIR}")

        # 确保目录存在
        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)

        vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=embedding_model,
            collection_name=CHROMA_COLLECTION_NAME,
            persist_directory=str(CHROMA_PERSIST_DIR),
        )

        print(f"✅ Chroma 数据库构建完成！")
        print(f"   集合名称: {CHROMA_COLLECTION_NAME}")

        return vectorstore

    elif VECTOR_DB_TYPE == "faiss":
        print("💾 使用 FAISS 向量数据库（暂未实现）")
        raise NotImplementedError("FAISS 支持即将推出")

    elif VECTOR_DB_TYPE == "qdrant":
        print("💾 使用 Qdrant 向量数据库（暂未实现）")
        raise NotImplementedError("Qdrant 支持即将推出")

    else:
        raise ValueError(f"不支持的向量数据库类型: {VECTOR_DB_TYPE}")


def _init_local_embedding():
    """初始化本地 HuggingFace Embedding 模型"""
    # 配置 HuggingFace 环境（离线模式/镜像站点）
    setup_huggingface_env()

    from langchain_huggingface import HuggingFaceEmbeddings

    print(f"   Provider: local (HuggingFace)")
    print(f"   Model: {EMBEDDING_MODEL_NAME}")

    # 检测是否在 Docker 中运行
    if is_docker():
        print("🐳 检测到 Docker 环境，使用 CPU 推理")
        device = "cpu"
    else:
        device = EMBEDDING_DEVICE
        print(f"💻 设备: {device}")

    embedding_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True},  # 归一化向量
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


def main():
    """主函数"""
    print("="*60)
    print("🚀 开始构建知识库（Planning Agent 优化版）")
    print("="*60)

    # 1. 加载文档
    documents = load_documents()
    if not documents:
        print("\n❌ 没有加载到文档，退出构建")
        return

    # 2. 切分文档
    splits = split_documents(documents)

    # 3. 可视化切片（帮助发现问题和优化）
    inspector = visualize_splits(splits)

    # 询问用户是否继续
    print("\n" + "="*60)
    user_input = input("是否继续构建向量数据库？(y/n): ").strip().lower()
    if user_input not in ['y', 'yes', '是']:
        print("❌ 已取消构建")
        return

    # 4. 构建向量存储
    print("\n🔨 开始构建向量数据库...")
    vectorstore = build_vector_store(splits)

    # 5. 构建并保存文档索引（用于上下文管理）
    print("\n📚 正在构建文档索引（支持全文上下文查询）...")
    context_manager = DocumentContextManager()
    context_manager.build_index(documents, splits)

    # 阶段2新增：生成文档摘要
    print("\n" + "="*60)
    print("📝 阶段2：生成层次化摘要（可选）")
    print("="*60)
    print("提示：摘要生成需要调用 LLM API，可能需要几分钟时间")
    print("      如果不需要摘要功能，可以跳过此步骤\n")

    user_input = input("是否生成文档摘要？（推荐）(y/n): ").strip().lower()

    if user_input in ['y', 'yes', '是']:
        print("\n⏳ 正在生成文档摘要...")
        print(f"   模型: {DEFAULT_PROVIDER}")
        print(f"   文档数: {len(documents)}\n")

        try:
            # 初始化摘要生成器
            summarizer = DocumentSummarizer(provider=DEFAULT_PROVIDER)

            # 为每个文档生成摘要
            summary_count = 0
            for doc in documents:
                source = doc.metadata.get("source", "unknown")

                # 检查该文档是否已在索引中
                if source in context_manager.doc_index:
                    try:
                        print(f"   [{summary_count + 1}/{len(documents)}] 生成摘要: {source}")
                        summary = summarizer.generate_summary(doc)

                        # 更新索引中的摘要字段
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

    # 保存索引（无论是否生成摘要）
    context_manager.save()
    print(f"✅ 文档索引已保存")

    # 6. 完成
    print("\n" + "="*60)
    print("🎉 知识库构建完成！")
    print("="*60)
    print(f"\n📊 统计信息:")
    print(f"   • 原始文档数: {len(documents)}")
    print(f"   • 切片数量: {len(splits)}")
    print(f"   • 平均切片大小: {inspector.stats['avg_chars']:.0f} 字符")
    print(f"\n💾 数据库位置: {CHROMA_PERSIST_DIR}")
    print(f"📊 切片分析报告: {CHROMA_PERSIST_DIR / 'slices_analysis.json'}")
    print(f"📖 文档索引: {CHROMA_PERSIST_DIR / 'document_index.json'}")
    print(f"\n✅ 可以通过以下方式使用知识库:")
    print(f"   from src.rag.core.tools import planning_knowledge_tool")
    print(f"   planning_knowledge_tool.run('你的问题')")
    print(f"\n✅ 阶段1工具（全文上下文查询）:")
    print(f"   cm.get_full_document('文件名')")
    print(f"   cm.get_chapter_by_header('文件名', '章节关键词')")
    print(f"\n✅ 阶段2工具（层次化摘要，如果已生成）:")
    print(f"   cm.get_executive_summary('文件名')")
    print(f"   cm.list_chapter_summaries('文件名')")
    print(f"   cm.get_chapter_summary('文件名', '章节关键词')")
    print(f"   cm.search_key_points('关键词')")


if __name__ == "__main__":
    main()
