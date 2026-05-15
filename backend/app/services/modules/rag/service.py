"""
RAG Service - Dynamic knowledge retrieval and management

Design:
- LLM-generated query based on dimension config and state
- Uses ParentChildVectorStore for retrieval
- Small-to-Big architecture: retrieve child, return parent
- Returns formatted context string for prompt injection
- Knowledge base management: add/delete/list documents

来源合并：
- src/services/rag_service.py (原有检索功能)
- src/rag/core/kb_manager.py (知识库管理)
- src/rag/core/summarization.py (摘要生成)
"""

import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.utils.logger import get_logger
from .context import DocumentContextManager, DocumentIndex
from app.core.llm import create_flash_llm
from app.core.settings import (
    CHUNK_SIZE, CHUNK_OVERLAP, CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR, DATA_DIR, DEFAULT_PROVIDER,
)

logger = get_logger(__name__)


@dataclass
class DocumentSummary:
    """文档摘要数据结构"""
    source: str
    executive_summary: str
    chapter_summaries: list
    key_points: list


class RagService:
    """
    Dynamic RAG Retrieval and Knowledge Management Service

    Features:
    - LLM-generated queries (context-aware)
    - Vector similarity search
    - Small-to-Big retrieval
    - Knowledge base management: add/delete/list documents
    """

    _instance: Optional["RagService"] = None
    _vector_store = None
    _cache = None
    _text_splitter = None

    def __init__(self):
        """Initialize RAG service"""
        try:
            from .vector_store import ParentChildVectorStore, get_vector_cache
            self._vector_store = ParentChildVectorStore()
            self._cache = get_vector_cache()
            logger.info("[RagService] Vector store initialized")
        except ImportError as e:
            logger.warning(f"[RagService] Vector store unavailable: {e}")
            self._vector_store = None
            self._cache = None

        self._context_manager = DocumentContextManager()

    @property
    def vectorstore(self):
        """Get vector store"""
        if self._cache:
            return self._cache.get_vectorstore()
        return self._vector_store

    @property
    def text_splitter(self):
        """Get text splitter"""
        if self._text_splitter is None:
            self._text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP,
                length_function=len, add_start_index=True,
            )
        return self._text_splitter

    @classmethod
    def get_instance(cls) -> "RagService":
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def generate_queries(
        self,
        cfg: Any,
        state: Dict[str, Any]
    ) -> List[str]:
        """
        使用 LLM-Flash 基于依赖信息动态生成多条 RAG 查询

        Args:
            cfg: Dimension config (has name, rag_query, depends_on, etc.)
            state: Current agent state (has session_id, completed_dimensions, etc.)

        Returns:
            多条检索查询字符串
        """
        from app.services.report_store import ReportStore

        dim_key = cfg.key if hasattr(cfg, 'key') else "unknown"
        dim_name = cfg.name if hasattr(cfg, 'name') else dim_key
        task_desc = cfg.rag_query if hasattr(cfg, 'rag_query') else ""
        session_id = state.get("session_id", "")

        # 加载依赖摘要
        depends_on = getattr(cfg, 'depends_on', [])
        layer_depends_on = getattr(cfg, 'layer_depends_on', [])
        phase_depends_on = getattr(cfg, 'phase_depends_on', [])

        all_deps = depends_on + layer_depends_on + phase_depends_on
        store = ReportStore.get_instance()

        # 批量加载依赖摘要（避免 N+1 查询）
        if all_deps:
            layer_reports = await store.get_layer_reports(session_id, 1)
            layer_reports_2 = await store.get_layer_reports(session_id, 2) if phase_depends_on else {}
            layer_reports_3 = await store.get_layer_reports(session_id, 3) if depends_on else {}

            dependency_summaries = []
            for dep_key in all_deps:
                summary = layer_reports.get(dep_key) or layer_reports_2.get(dep_key) or layer_reports_3.get(dep_key)
                if summary:
                    dependency_summaries.append(f"【{dep_key}】{summary}")
        else:
            dependency_summaries = []

        if not dependency_summaries:
            # 无依赖时，使用维度名称生成简单查询
            logger.info(f"[RagService] No dependencies for {dim_key}, using fallback query")
            return [f"{dim_name} 规划 技术标准"]

        # 使用 Flash LLM 生成查询
        llm = create_flash_llm(max_tokens=200, temperature=0.3)

        prompt = f"""你是一个专业的规划信息检索助手。根据以下背景信息，为规划任务生成 5-8 条中文检索查询。

## 规划任务
- 维度：{dim_name}
- 描述：{task_desc}

## 背景信息
{chr(10).join(dependency_summaries)}

## 生成要求
生成 5-8 条中文查询，覆盖不同侧面（政策法规、技术标准、地方规划、相似案例），直接输出查询（每行一条），不要编号或解释。"""

        try:
            response = await llm.ainvoke(prompt)
            queries = [q.strip() for q in response.content.split("\n") if q.strip()]
            logger.info(f"[RagService] Generated {len(queries)} queries for {dim_key}: {queries[:3]}...")
            return queries[:8]
        except Exception as e:
            logger.error(f"[RagService] Query generation failed: {e}")
            return [f"{dim_name} 规划 技术标准"]

    async def generate_query(
        self,
        cfg: Any,
        state: Dict[str, Any]
    ) -> str:
        """
        Generate single search query (backward compatible)

        Args:
            cfg: Dimension config
            state: Current agent state

        Returns:
            Single search query string
        """
        queries = await self.generate_queries(cfg, state)
        return queries[0] if queries else f"{cfg.name if hasattr(cfg, 'name') else 'unknown'} 规划 技术标准"

    async def search(
        self,
        query: str,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search vector store for relevant documents

        Args:
            query: Search query
            top_k: Number of results

        Returns:
            List of {content, metadata, score}
        """
        if self._vector_store is None:
            logger.warning("[RagService] Vector store not available")
            return []

        try:
            results = self._vector_store.search(query, k=top_k)
            logger.info(f"[RagService] Found {len(results)} results for: {query[:50]}")
            return results
        except Exception as e:
            logger.error(f"[RagService] Search failed: {e}")
            return []

    async def get_context(
        self,
        dim_key: str,
        state: Dict[str, Any],
        cfg: Optional[Any] = None
    ) -> str:
        """
        Get formatted knowledge context for dimension

        Args:
            dim_key: Dimension key
            state: Current agent state
            cfg: Optional dimension config

        Returns:
            Formatted context string for prompt injection
        """
        if cfg is None:
            try:
                from app.config import get_dimension_config
                cfg = get_dimension_config(dim_key)
            except Exception:
                cfg = None

        query = await self.generate_query(cfg or {}, state)
        results = await self.search(query, top_k=3)

        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results):
            content = result.get("content", "")
            metadata = result.get("metadata", {})
            source = metadata.get("source", "Unknown")
            doc_type = metadata.get("doc_type", "法规")

            if len(content) > 500:
                content = content[:500] + "..."

            context_parts.append(f"【参考{i+1} - {doc_type}】\n来源: {source}\n内容:\n{content}\n")

        return "\n".join(context_parts)

    @staticmethod
    def format_for_prompt(results: List[Dict[str, Any]]) -> str:
        """
        Format search results for prompt injection

        Args:
            results: Search results

        Returns:
            Formatted string
        """
        if not results:
            return "【知识检索】无相关法规或技术标准。"

        parts = ["【知识检索】以下法规和技术标准与本维度相关：\n"]
        for i, result in enumerate(results):
            content = result.get("content", "")
            source = result.get("metadata", {}).get("source", "未知")
            parts.append(f"\n### 参考 {i+1}: {source}")
            parts.append(content[:300])

        return "\n".join(parts)

    # ==========================================
    # Knowledge Base Management Methods
    # ==========================================

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents in knowledge base"""
        try:
            if self._cache is None:
                return []
            collection = self.vectorstore._collection
            results = collection.get(include=["metadatas"])
            if not results or not results.get("ids"):
                return []
            doc_stats: Dict[str, Dict] = {}
            for idx, doc_id in enumerate(results["ids"]):
                metadata = results["metadatas"][idx] if results.get("metadatas") else {}
                source = metadata.get("source", "unknown")
                if source not in doc_stats:
                    doc_stats[source] = {
                        "source": source,
                        "chunk_count": 0,
                        "doc_type": metadata.get("document_type", "unknown"),
                    }
                doc_stats[source]["chunk_count"] += 1
            return list(doc_stats.values())
        except Exception as e:
            logger.error(f"[RagService] List documents failed: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        try:
            docs = self.list_documents()
            total_chunks = sum(d["chunk_count"] for d in docs)
            return {
                "total_documents": len(docs),
                "total_chunks": total_chunks,
                "documents": docs,
                "vector_db_path": str(CHROMA_PERSIST_DIR),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_document(self, source_name: str) -> Dict[str, Any]:
        """Delete document from knowledge base"""
        try:
            collection = self.vectorstore._collection
            collection.delete(where={"source": source_name})
            if source_name in self._context_manager.doc_index:
                del self._context_manager.doc_index[source_name]
                self._context_manager.save()
            if self._cache:
                self._cache.clear_cache()
            return {"status": "success", "message": f"Deleted: {source_name}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def add_document(
        self,
        file_path: str,
        category: Optional[str] = None,
        skip_summary: bool = True,
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list] = None,
        terrain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add single document to knowledge base (incremental)

        Args:
            file_path: Document path
            category: Document category (policies/cases)
            skip_summary: Skip summary generation
            doc_type: Document type (textbook/guide/policy/standard/case/report)
            dimension_tags: Dimension tags to inject
            terrain: Terrain type to inject

        Returns:
            Result with status, chunks_added, message
        """
        from .utils.document_loader import FileTypeDetector, _create_loader
        from .utils.text_splitter import SlicingStrategyFactory
        from .injector import MetadataInjector

        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        source_name = path.name
        existing = self._check_document_exists(source_name)
        if existing:
            logger.warning(f"Document exists, deleting old version: {source_name}")
            self.delete_document(source_name)

        try:
            logger.info(f"Processing document: {source_name}")
            real_type = FileTypeDetector.detect(path)
            logger.info(f"Type: {real_type}")

            loader = _create_loader(path, real_type, category=category)
            if loader is None:
                return {"status": "error", "message": f"Unsupported file type: {real_type}"}

            documents = loader.load()
            if not documents:
                return {"status": "error", "message": "Document content empty or unparseable"}

            logger.info(f"Loaded {len(documents)} document fragments")
            full_content = "\n\n".join(doc.page_content for doc in documents)

            if doc_type is None:
                doc_type = self._infer_doc_type(source_name, full_content)
                logger.info(f"Inferred doc_type: {doc_type}")

            splits = SlicingStrategyFactory.slice_document(
                full_content, doc_type, {"source": source_name}
            )
            logger.info(f"Sliced into {len(splits)} fragments (strategy: {doc_type})")

            split_docs = []
            for idx, split in enumerate(splits):
                start_index = full_content.find(split) if idx == 0 else 0
                doc = Document(
                    page_content=split,
                    metadata={
                        "source": source_name,
                        "type": real_type,
                        "chunk_index": idx,
                        "total_chunks": len(splits),
                        "category": category or "policies",
                        "start_index": start_index,
                        "file_hash": self._compute_file_hash(path),
                    }
                )
                split_docs.append(doc)

            logger.info("Injecting metadata...")
            injector = MetadataInjector()
            injector.inject_batch(
                split_docs,
                category=category,
                doc_type=doc_type,
                dimension_tags=dimension_tags,
                terrain=terrain,
            )

            # 根据配置判断是否使用 Parent-Child 架构
            if self._should_use_parent_child(doc_type):
                parent_child_chunks = self._create_parent_child_chunks(
                    split_docs, source_name, real_type, category
                )
                from .vector_store import ParentChildVectorStore
                if isinstance(self._vector_store, ParentChildVectorStore):
                    self._vector_store.add_chunks(parent_child_chunks)
                    logger.info(f"Added {len(parent_child_chunks)} child chunks (Parent-Child mode for {doc_type})")
                else:
                    self.vectorstore.add_documents(split_docs)
                    logger.info(f"Added {len(split_docs)} vectors (fallback mode)")
            else:
                self.vectorstore.add_documents(split_docs)
                logger.info(f"Added {len(split_docs)} vectors (standard mode for {doc_type})")
            self._update_document_index(source_name, documents, split_docs)

            if self._cache:
                self._cache.clear_cache()

            return {
                "status": "success",
                "message": f"Successfully added: {source_name}",
                "source": source_name,
                "chunks_added": len(split_docs),
                "doc_type": real_type,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"Add document failed: {str(e)}"}

    def add_document_with_progress(
        self,
        file_path: str,
        progress_callback: Callable[[float, str], None],
        category: Optional[str] = None,
        doc_type: Optional[str] = None,
        dimension_tags: Optional[list] = None,
        terrain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add document with progress callback (for async task manager)"""
        from .utils.document_loader import FileTypeDetector, _create_loader
        from .utils.text_splitter import SlicingStrategyFactory
        from .injector import MetadataInjector

        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        source_name = path.name
        existing = self._check_document_exists(source_name)
        if existing:
            progress_callback(5.0, "Deleting old version")
            self.delete_document(source_name)

        try:
            progress_callback(5.0, "File type detection")
            real_type = FileTypeDetector.detect(path)
            logger.info(f"Type: {real_type}")

            progress_callback(15.0, "Loading document")
            loader = _create_loader(path, real_type, category=category)
            if loader is None:
                return {"status": "error", "message": f"Unsupported file type: {real_type}"}

            documents = loader.load()
            if not documents:
                return {"status": "error", "message": "Document content empty"}

            logger.info(f"Loaded {len(documents)} fragments")
            progress_callback(20.0, "Merging content")
            full_content = "\n\n".join(doc.page_content for doc in documents)

            progress_callback(30.0, "Inferring doc type")
            if doc_type is None:
                doc_type = self._infer_doc_type(source_name, full_content)
                logger.info(f"Inferred doc_type: {doc_type}")

            progress_callback(40.0, "Slicing document")
            splits = SlicingStrategyFactory.slice_document(
                full_content, doc_type, {"source": source_name}
            )
            progress_callback(50.0, "Slicing complete")

            progress_callback(55.0, "Creating documents")
            split_docs = []
            for idx, split in enumerate(splits):
                start_index = full_content.find(split) if idx == 0 else 0
                doc = Document(
                    page_content=split,
                    metadata={
                        "source": source_name,
                        "type": real_type,
                        "chunk_index": idx,
                        "total_chunks": len(splits),
                        "category": category or "policies",
                        "start_index": start_index,
                        "file_hash": self._compute_file_hash(path),
                    }
                )
                split_docs.append(doc)

            progress_callback(60.0, "Injecting metadata")
            injector = MetadataInjector()
            injector.inject_batch(
                split_docs,
                category=category,
                doc_type=doc_type,
                dimension_tags=dimension_tags,
                terrain=terrain,
            )
            progress_callback(70.0, "Metadata injection complete")

            progress_callback(75.0, "Generating vectors")
            # 根据配置判断是否使用 Parent-Child 架构
            if self._should_use_parent_child(doc_type):
                parent_child_chunks = self._create_parent_child_chunks(
                    split_docs, source_name, real_type, category
                )
                from .vector_store import ParentChildVectorStore
                if isinstance(self._vector_store, ParentChildVectorStore):
                    self._vector_store.add_chunks(parent_child_chunks)
                    logger.info(f"Added {len(parent_child_chunks)} child chunks (Parent-Child mode for {doc_type})")
                else:
                    self.vectorstore.add_documents(split_docs)
            else:
                self.vectorstore.add_documents(split_docs)
                logger.info(f"Added {len(split_docs)} vectors (standard mode for {doc_type})")
            progress_callback(85.0, "Vector generation complete")

            progress_callback(90.0, "Updating index")
            self._update_document_index(source_name, documents, split_docs)

            progress_callback(95.0, "Clearing cache")
            if self._cache:
                self._cache.clear_cache()

            progress_callback(100.0, "Complete")
            return {
                "status": "success",
                "message": f"Successfully added: {source_name}",
                "source": source_name,
                "chunks_added": len(split_docs),
                "doc_type": real_type,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"Add document failed: {str(e)}"}

    def _check_document_exists(self, source_name: str) -> bool:
        """Check if document exists in knowledge base"""
        docs = self.list_documents()
        return any(d["source"] == source_name for d in docs)

    def _infer_doc_type(self, filename: str, content: str = "") -> str:
        """Infer document type from filename keywords"""
        import re
        name_lower = filename.lower()

        if content and re.search(r'第[一二三四五六七八九十\d]+章', content):
            return "textbook"

        textbook_kw = ["教材", "原理", "教程", "导论", "基础", "入门", "读本"]
        if any(kw in filename for kw in textbook_kw):
            return "textbook"

        guide_kw = ["指南", "手册", "指导", "操作", "规程"]
        if any(kw in filename for kw in guide_kw):
            return "guide"

        policy_kw = ["条例", "规定", "办法", "通知", "意见", "决定", "批复"]
        if any(kw in filename for kw in policy_kw):
            return "policy"

        standard_kw = ["标准", "规范", "gb", "cjj", "cj", "hg", "jc", "jg", "jt"]
        for kw in standard_kw:
            if kw in name_lower:
                return "standard"

        case_kw = ["规划", "设计", "方案", "案例", "实例", "工程"]
        if any(kw in filename for kw in case_kw):
            return "case"

        return "report"

    def _update_document_index(
        self,
        source_name: str,
        original_docs: List[Document],
        split_docs: List[Document]
    ) -> None:
        """Update document index"""
        try:
            self._context_manager._ensure_loaded()

            from .context import ChunkInfo
            chunks_info = []
            for idx, split in enumerate(split_docs):
                chunks_info.append(ChunkInfo(
                    chunk_index=idx,
                    start_index=split.metadata.get("start_index", 0),
                    content_preview=split.page_content[:100] + "..." if len(split.page_content) > 100 else split.page_content,
                ))

            doc_type = split_docs[0].metadata.get("type", "unknown") if split_docs else "unknown"

            self._context_manager.doc_index[source_name] = DocumentIndex(
                source=source_name,
                doc_type=doc_type,
                total_chunks=len(split_docs),
                chunks_info=chunks_info,
            )

            self._context_manager.save()
            logger.info("Document index updated")

        except Exception as e:
            logger.warning(f"Update index failed: {e}")

    def _should_use_parent_child(self, doc_type: str) -> bool:
        """根据文档类型配置判断是否启用 Parent-Child"""
        from .chunker import UnifiedMarkdownSlicer
        config = UnifiedMarkdownSlicer.CONFIGS.get(doc_type, UnifiedMarkdownSlicer.CONFIGS["default"])
        return config.parent_child

    def _create_parent_child_chunks(
        self,
        parent_docs: List[Document],
        source_name: str,
        real_type: str,
        category: Optional[str] = None,
    ) -> List[Any]:
        """
        将父块切分为子块，创建 ParentChildChunk 列表

        Args:
            parent_docs: 父块文档列表
            source_name: 文档来源名称
            real_type: 文档类型
            category: 文档分类

        Returns:
            ParentChildChunk 列表
        """
        from .vector_store import ParentChildChunk

        CHILD_SIZE = 400  # 子块大小
        CHILD_OVERLAP = 100  # 子块重叠

        all_chunks = []

        for parent_idx, parent_doc in enumerate(parent_docs):
            parent_content = parent_doc.page_content
            parent_id = f"{source_name}_{parent_idx}_{hashlib.md5(parent_content.encode()).hexdigest()[:8]}"

            # 切分父块为子块
            child_splits = self.text_splitter.split_text(parent_content)

            for child_idx, child_content in enumerate(child_splits):
                child_id = f"{parent_id}_child_{child_idx}"
                chunk = ParentChildChunk(
                    child_content=child_content,
                    child_id=child_id,
                    parent_content=parent_content,
                    parent_id=parent_id,
                    child_index=child_idx,
                    total_children=len(child_splits),
                    metadata={
                        "source": source_name,
                        "type": real_type,
                        "category": category or "policies",
                        **parent_doc.metadata,
                    },
                )
                all_chunks.append(chunk)

        return all_chunks

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute file MD5 hash"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()[:8]


__all__ = ["RagService", "DocumentSummary"]