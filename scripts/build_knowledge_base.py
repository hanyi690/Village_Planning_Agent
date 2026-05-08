"""
知识库构建 CLI 脚本

迁移来源：src/rag/build.py

使用新架构的服务层和工具层构建知识库。
支持语义标注、摘要生成、进度追踪。

Usage:
    python scripts/build_knowledge_base.py [--semantic] [--skip-confirm] [--full]
"""
import os
import sys
import asyncio
import argparse
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

# 确保 src 在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.settings import (
    CHUNK_SIZE, CHUNK_OVERLAP, CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR, DATA_DIR, EMBEDDING_PROVIDER,
    EMBEDDING_MODEL_NAME, EMBEDDING_DEVICE, EMBEDDING_DIMENSIONS,
    DASHSCOPE_API_KEY, ALIYUN_EMBEDDING_BASE_URL, ALIYUN_EMBEDDING_MODEL,
    DEFAULT_PROVIDER,
)
from src.utils.logger import get_logger
from src.utils.text_splitter import SlicingStrategyFactory
from src.utils.context_manager import DocumentContextManager

logger = get_logger(__name__)


@dataclass
class TimingStats:
    """构建各阶段耗时统计"""
    document_loading: float = 0.0
    slicing: float = 0.0
    embedding_init: float = 0.0
    metadata_injection: float = 0.0
    vector_store_build: float = 0.0
    index_build: float = 0.0
    summary_generation: Dict[str, float] = field(default_factory=dict)
    total: float = 0.0

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
        from src.utils.document_loader import load_documents_from_directory as load_knowledge_base
        documents = load_knowledge_base(DATA_DIR)
        return documents
    except ImportError as e:
        logger.error(f"无法导入 load_knowledge_base: {e}")
        return []
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return []


def infer_doc_type(source: str, content: str) -> str:
    """推断文档类型"""
    source_lower = source.lower()

    if "政策" in source or "policy" in source_lower or "法规" in source:
        return "policy"
    if "案例" in source or "case" in source_lower:
        return "case"
    if "标准" in source or "standard" in source_lower or "规范" in source:
        return "standard"
    if "指南" in source or "guide" in source_lower:
        return "guide"
    if "教材" in source or "textbook" in source_lower:
        return "textbook"

    if "第条" in content or "本法" in content:
        return "laws"
    if "规划" in content and "村庄" in content:
        return "plans"

    return "default"


def slice_documents(documents):
    """使用统一切片策略切分文档"""
    print("\n✂️  正在切分文档...")
    print(f"   配置: 使用 UnifiedMarkdownSlicer（差异化策略）")

    from langchain_core.documents import Document

    all_splits = []
    for doc in documents:
        source = doc.metadata.get("source", "")
        content = doc.page_content

        doc_type = infer_doc_type(source, content)
        print(f"   [{doc_type}] {source}")

        slices = SlicingStrategyFactory.slice_document(
            content, doc_type, {"source": source}
        )

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


def _init_local_embedding():
    """初始化本地 HuggingFace Embedding 模型"""
    try:
        from src.core.settings import setup_huggingface_env
        setup_huggingface_env()
    except ImportError:
        pass

    from langchain_huggingface import HuggingFaceEmbeddings

    print(f"   Provider: local (HuggingFace)")
    print(f"   Model: {EMBEDDING_MODEL_NAME}")
    print(f"   设备: {EMBEDDING_DEVICE}")

    embedding_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": EMBEDDING_DEVICE},
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

    from langchain_core.embeddings import Embeddings
    from openai import OpenAI

    class AliyunEmbeddingsCLI(Embeddings):
        """阿里云 DashScope Embedding API（CLI 专用）"""

        def __init__(self, api_key, base_url, model, dimensions, batch_size=10):
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            self.model = model
            self.dimensions = dimensions
            self.batch_size = batch_size

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
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
            response = self.client.embeddings.create(
                model=self.model,
                input=[text],
                dimensions=self.dimensions,
            )
            return response.data[0].embedding

    print(f"   Provider: aliyun (DashScope)")
    print(f"   Model: {ALIYUN_EMBEDDING_MODEL}")
    print(f"   Dimensions: {EMBEDDING_DIMENSIONS}")

    embedding_model = AliyunEmbeddingsCLI(
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
    embedding_model=None,
    persist_dir: Path = None,
    collection_name: str = None,
    batch_size: int = 20,
):
    """创建 Chroma 向量存储（分批添加）"""
    from langchain_chroma import Chroma

    if embedding_model is None:
        embedding_model = get_embedding_model()

    persist_dir = persist_dir or CHROMA_PERSIST_DIR
    persist_dir.mkdir(parents=True, exist_ok=True)

    collection_name = collection_name or CHROMA_COLLECTION_NAME

    vectorstore = Chroma(
        embedding_function=embedding_model,
        collection_name=collection_name,
        persist_directory=str(persist_dir),
    )

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


async def inject_metadata(splits, use_semantic: bool = False):
    """注入维度元数据"""
    print(f"\n🏷️  正在进行维度标注...")
    print(f"   模式: {'语义标注 (Flash模型)' if use_semantic else '关键词匹配'}")
    print(f"   切片数: {len(splits)}")

    try:
        from src.services.metadata_injector import MetadataInjector
        injector = MetadataInjector(use_semantic=use_semantic)

        if use_semantic:
            print(f"   提示: 语义标注需要调用 LLM API，可能需要几分钟")
            tagged_docs = await injector.inject_batch_async(splits, use_semantic=True)
        else:
            tagged_docs = injector.inject_batch(splits)

        print(f"✅ 维度标注完成")
        return tagged_docs
    except ImportError:
        logger.warning("无法导入 MetadataInjector，跳过维度标注")
        return splits


async def build_vector_store(
    splits,
    documents=None,
    use_semantic: bool = False,
    embedding_model=None,
    timing: TimingStats = None,
):
    """构建向量存储"""
    if timing is None:
        timing = TimingStats()

    emb_start = time.time()
    print(f"\n🧠 正在初始化 Embedding 模型...")

    if embedding_model is None:
        embedding_model = get_embedding_model()

    timing.embedding_init = time.time() - emb_start
    print(f"   ⏱️  Embedding初始化耗时: {timing.embedding_init:.2f}秒")

    meta_start = time.time()
    tagged_docs = await inject_metadata(splits, use_semantic)
    timing.metadata_injection = time.time() - meta_start
    print(f"   ⏱️  维度标注耗时: {timing.metadata_injection:.2f}秒")

    chroma_start = time.time()
    vectorstore = create_chroma_store(documents=tagged_docs, embedding_model=embedding_model)
    timing.vector_store_build = time.time() - chroma_start
    print(f"   ⏱️  Chroma构建耗时: {timing.vector_store_build:.2f}秒")

    return vectorstore, timing


def main(use_semantic: bool = False, skip_confirm: bool = False, skip_summary: bool = True):
    """主函数"""
    total_start = time.time()
    timing = TimingStats()

    print("=" * 60)
    print(f"🚀 开始构建知识库（{'语义标注' if use_semantic else '标准'}模式）")
    print("=" * 60)

    stage_start = time.time()
    documents = load_documents()
    timing.document_loading = time.time() - stage_start
    print(f"   ⏱️  文档加载耗时: {timing.document_loading:.2f}秒")

    if not documents:
        print("\n❌ 没有加载到文档，退出构建")
        return

    stage_start = time.time()
    splits = slice_documents(documents)
    timing.slicing = time.time() - stage_start
    print(f"   ⏱️  切片耗时: {timing.slicing:.2f}秒")

    try:
        from src.utils.slice_inspector import SliceInspector
        inspector = SliceInspector(splits)
        inspector.print_summary()
        inspector.print_issues(max_issues=10)
    except ImportError:
        logger.info("SliceInspector 不可用，跳过可视化")

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

    stage_start = time.time()
    print("\n📚 正在构建文档索引...")
    context_manager = DocumentContextManager()
    context_manager.build_index(documents, splits)
    timing.index_build = time.time() - stage_start
    print(f"   ⏱️  文档索引构建耗时: {timing.index_build:.2f}秒")

    if not skip_summary:
        print("\n📝 正在生成文档摘要...")
        try:
            from src.services.document_summarizer import DocumentSummarizer
            summarizer = DocumentSummarizer(provider=DEFAULT_PROVIDER)

            for doc in documents:
                source = doc.metadata.get("source", "unknown")
                if source in context_manager.doc_index:
                    try:
                        doc_start = time.time()
                        print(f"   生成摘要: {source}")
                        summary = summarizer.generate_summary(doc)

                        doc_index = context_manager.doc_index[source]
                        doc_index.executive_summary = summary.executive_summary
                        doc_index.chapter_summaries = [
                            {
                                "title": ch.title,
                                "level": ch.level,
                                "summary": ch.summary,
                                "key_points": ch.key_points,
                            }
                            for ch in summary.chapter_summaries
                        ]
                        doc_index.key_points = summary.key_points

                        timing.summary_generation[source] = time.time() - doc_start
                    except Exception as e:
                        logger.warning(f"{source} 摘要生成失败: {e}")

        except ImportError:
            logger.warning("DocumentSummarizer 不可用，跳过摘要生成")

    context_manager.save()
    print(f"✅ 文档索引已保存")

    timing.total = time.time() - total_start

    print("\n" + "=" * 60)
    print("🎉 知识库构建完成！")
    print("=" * 60)

    timing.print_summary()

    print(f"\n📊 统计信息:")
    print(f"   • 原始文档数: {len(documents)}")
    print(f"   • 切片数量: {len(splits)}")
    print(f"   • 标注模式: {'语义标注' if use_semantic else '关键词匹配'}")
    print(f"\n💾 数据库位置: {CHROMA_PERSIST_DIR}")
    print(f"📖 文档索引: {CHROMA_PERSIST_DIR / 'document_index.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识库构建脚本")
    parser.add_argument("--semantic", action="store_true", help="使用语义标注")
    parser.add_argument("--skip-confirm", action="store_true", help="跳过交互确认")
    parser.add_argument("--skip-summary", action="store_true", help="跳过摘要生成")
    parser.add_argument("--full", action="store_true", help="全量构建（包含摘要生成）")
    args = parser.parse_args()
    main(
        use_semantic=args.semantic,
        skip_confirm=args.skip_confirm,
        skip_summary=args.skip_summary or not args.full,
    )