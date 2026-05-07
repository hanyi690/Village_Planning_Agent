"""
知识库构建脚本
符合 LangChain 最佳实践，支持 Docker 部署
针对 Planning Agent 优化：使用统一切片策略
"""
import os
import sys
import asyncio
import argparse
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

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


@dataclass
class TimingStats:
    """构建各阶段耗时统计"""
    document_loading: float = 0.0
    slicing: float = 0.0
    embedding_init: float = 0.0
    metadata_injection: float = 0.0
    vector_store_build: float = 0.0
    index_build: float = 0.0
    summary_generation: Dict[str, float] = None  # 文档名 -> 耗时
    total: float = 0.0

    def __post_init__(self):
        if self.summary_generation is None:
            self.summary_generation = {}

    def print_summary(self):
        """打印耗时汇总"""
        print("\n" + "=" * 60)
        print("📊 构建耗时统计")
        print("=" * 60)
        print(f"   ⏱️  文档加载:      {self.document_loading:.2f}秒")
        print(f"   ⏱️  文档切片:      {self.slicing:.2f}秒")
        print(f"   ⏱️  Embedding初始化: {self.embedding_init:.2f}秒")
        print(f"   ⏱️  维度标注:      {self.metadata_injection:.2f}秒")
        print(f"   ⏱️  向量库构建:    {self.vector_store_build:.2f}秒")
        print(f"   ⏱️  文档索引:      {self.index_build:.2f}秒")

        if self.summary_generation:
            total_summary = sum(self.summary_generation.values())
            avg_summary = total_summary / len(self.summary_generation)
            print(f"   ⏱️  摘要生成:      {total_summary:.2f}秒 ({len(self.summary_generation)}个文档, 平均{avg_summary:.2f}秒/文档)")
            for doc, t in self.summary_generation.items():
                print(f"       - {doc}: {t:.2f}秒")

        # 计算向量构建总耗时（embedding + metadata + chroma）
        vector_total = self.embedding_init + self.metadata_injection + self.vector_store_build
        print(f"\n   🔍 向量构建总耗时: {vector_total:.2f}秒")
        print(f"   📋 总体耗时:      {self.total:.2f}秒")
        print("=" * 60)


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
    """初始化阿里云 DashScope Embedding API（自定义实现，兼容阿里云）"""
    if not DASHSCOPE_API_KEY:
        raise ValueError(
            "EMBEDDING_PROVIDER=aliyun 但未设置 DASHSCOPE_API_KEY。"
            "请在 .env 中配置 DASHSCOPE_API_KEY=your_api_key"
        )

    from langchain_core.embeddings import Embeddings
    from openai import OpenAI

    class AliyunEmbeddings(Embeddings):
        """阿里云 DashScope Embedding API（兼容模式）"""

        def __init__(self, api_key, base_url, model, dimensions, batch_size=10):
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            self.model = model
            self.dimensions = dimensions
            self.batch_size = batch_size

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            """批量生成 embeddings"""
            embeddings = []
            for i in range(0, len(texts), self.batch_size):
                batch = texts[i:i + self.batch_size]
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions,
                )
                for item in response.data:
                    embeddings.append(item.embedding)
            return embeddings

        def embed_query(self, text: str) -> list[float]:
            """生成单个文本的 embedding"""
            response = self.client.embeddings.create(
                model=self.model,
                input=[text],
                dimensions=self.dimensions,
            )
            return response.data[0].embedding

    print(f"   Provider: aliyun (DashScope)")
    print(f"   Model: {ALIYUN_EMBEDDING_MODEL}")
    print(f"   Dimensions: {EMBEDDING_DIMENSIONS}")
    print(f"   Base URL: {ALIYUN_EMBEDDING_BASE_URL}")

    embedding_model = AliyunEmbeddings(
        api_key=DASHSCOPE_API_KEY,
        base_url=ALIYUN_EMBEDDING_BASE_URL,
        model=ALIYUN_EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        batch_size=10,  # 阿里云推荐单次不超过10条
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
    batch_size: int = 20,  # 文档分批添加（embedding 内部已分批10条）
):
    """创建 Chroma 向量存储（分批添加，避免API超限）"""
    if embedding_model is None:
        embedding_model = get_embedding_model()

    persist_dir = persist_dir or CHROMA_PERSIST_DIR
    persist_dir.mkdir(parents=True, exist_ok=True)

    collection_name = collection_name or CHROMA_COLLECTION_NAME

    # 创建空的 Chroma 集合
    vectorstore = Chroma(
        embedding_function=embedding_model,
        collection_name=collection_name,
        persist_directory=str(persist_dir),
    )

    # 分批添加文档（避免阿里云 Embedding API 500 错误）
    total_docs = len(documents)
    print(f"   分批添加文档，每批 {batch_size} 条，共 {total_docs} 条...")

    for i in range(0, total_docs, batch_size):
        batch = documents[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total_docs + batch_size - 1) // batch_size
        print(f"   批次 {batch_num}/{total_batches}: 添加 {len(batch)} 条文档...")
        vectorstore.add_documents(batch)

    print(f"✅ Chroma 数据库构建完成！")
    print(f"   集合名称: {collection_name}")
    print(f"   持久化路径: {persist_dir}")
    print(f"   文档总数: {total_docs}")

    return vectorstore


async def build_vector_store(
    splits,
    documents = None,
    use_semantic: bool = False,
    embedding_model = None,
    timing: TimingStats = None,
):
    """构建向量存储（支持语义标注），并记录各阶段耗时"""
    if timing is None:
        timing = TimingStats()

    # Embedding初始化
    emb_start = time.time()
    print(f"\n🧠 正在初始化 Embedding 模型...")

    if embedding_model is None:
        embedding_model = get_embedding_model()

    timing.embedding_init = time.time() - emb_start
    print(f"   ⏱️  Embedding初始化耗时: {timing.embedding_init:.2f}秒")

    # 维度标注
    meta_start = time.time()
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
    timing.metadata_injection = time.time() - meta_start
    print(f"   ⏱️  维度标注耗时: {timing.metadata_injection:.2f}秒")

    # Chroma向量库构建
    chroma_start = time.time()
    vectorstore = create_chroma_store(documents=tagged_docs, embedding_model=embedding_model)
    timing.vector_store_build = time.time() - chroma_start
    print(f"   ⏱️  Chroma构建耗时: {timing.vector_store_build:.2f}秒")

    return vectorstore, timing


def main(use_semantic: bool = False, skip_confirm: bool = False, skip_summary: bool = True):
    """主函数（支持语义标注模式）

    Args:
        use_semantic: 使用语义标注
        skip_confirm: 跳过交互确认，直接构建
        skip_summary: 跳过摘要生成（默认跳过，--full时生成）
    """
    total_start = time.time()
    timing = TimingStats()

    print("=" * 60)
    print(f"🚀 开始构建知识库（{'语义标注' if use_semantic else '标准'}模式）")
    print("=" * 60)

    # 阶段1：文档加载
    stage_start = time.time()
    documents = load_documents()
    timing.document_loading = time.time() - stage_start
    print(f"   ⏱️  文档加载耗时: {timing.document_loading:.2f}秒")

    if not documents:
        print("\n❌ 没有加载到文档，退出构建")
        return

    # 阶段2：文档切片
    stage_start = time.time()
    splits = slice_documents(documents)
    timing.slicing = time.time() - stage_start
    print(f"   ⏱️  切片耗时: {timing.slicing:.2f}秒")

    inspector = visualize_splits(splits)

    # 交互确认（可跳过）
    if not skip_confirm:
        print("\n" + "=" * 60)
        user_input = input("是否继续构建向量数据库？(y/n): ").strip().lower()
        if user_input not in ['y', 'yes', '是']:
            print("❌ 已取消构建")
            return

    print("\n🔨 开始构建向量数据库...")
    vectorstore, timing = asyncio.run(build_vector_store(
        splits=splits,
        documents=documents,
        use_semantic=use_semantic,
        timing=timing,
    ))

    # 阶段4：文档索引构建
    stage_start = time.time()
    print("\n📚 正在构建文档索引（支持全文上下文查询）...")
    context_manager = DocumentContextManager()
    context_manager.build_index(documents, splits)
    timing.index_build = time.time() - stage_start
    print(f"   ⏱️  文档索引构建耗时: {timing.index_build:.2f}秒")

    # 摘要生成（可选，默认跳过）
    if not skip_summary:
        print("\n" + "=" * 60)
        print("📝 阶段2：生成层次化摘要（可选）")
        print("=" * 60)
        print("提示：摘要生成需要调用 LLM API，可能需要几分钟时间")
        print("      如果不需要摘要功能，可以跳过此步骤\n")

        if not skip_confirm:
            user_input = input("是否生成文档摘要？（推荐）(y/n): ").strip().lower()
            generate_summary = user_input in ['y', 'yes', '是']
        else:
            generate_summary = True  # skip_confirm模式下默认生成

        if generate_summary:
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
                            doc_start = time.time()
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

                            doc_time = time.time() - doc_start
                            timing.summary_generation[source] = doc_time
                            print(f"      ⏱️  耗时: {doc_time:.2f}秒")
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
        print("\n⏭️  已跳过摘要生成")
        print("   提示：可以稍后运行 build.py --full 重新生成摘要")

    context_manager.save()
    print(f"✅ 文档索引已保存")

    # 计算总体耗时
    timing.total = time.time() - total_start

    print("\n" + "=" * 60)
    print("🎉 知识库构建完成！")
    print("=" * 60)

    # 打印耗时统计
    timing.print_summary()

    print(f"\n📊 统计信息:")
    print(f"   • 原始文档数: {len(documents)}")
    print(f"   • 切片数量: {len(splits)}")
    print(f"   • 标注模式: {'语义标注' if use_semantic else '关键词匹配'}")
    print(f"   • 平均切片大小: {inspector.stats['avg_chars']:.0f} 字符")
    print(f"\n💾 数据库位置: {CHROMA_PERSIST_DIR}")
    print(f"📊 切片分析报告: {CHROMA_PERSIST_DIR / 'slices_analysis.json'}")
    print(f"📖 文档索引: {CHROMA_PERSIST_DIR / 'document_index.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识库构建脚本")
    parser.add_argument("--semantic", action="store_true", help="使用语义标注")
    parser.add_argument("--skip-confirm", action="store_true", help="跳过交互确认，直接构建")
    parser.add_argument("--skip-summary", action="store_true", help="跳过摘要生成")
    parser.add_argument("--full", action="store_true", help="全量构建（包含摘要生成）")
    args = parser.parse_args()
    main(
        use_semantic=args.semantic,
        skip_confirm=args.skip_confirm,
        skip_summary=args.skip_summary or not args.full,
    )