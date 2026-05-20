"""
RAG Service - Dynamic knowledge retrieval and management

Design:
- LLM-generated query based on dimension config and state
- Uses HierarchyVectorStore for retrieval
- Small-to-Big architecture: retrieve child, return parent
- Returns formatted context string for prompt injection
- Knowledge base management: add/delete/list documents

2026-05-16: 重写，集成层级切片
"""

import re
import hashlib
import time
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass

from langchain_core.documents import Document

from app.utils.logger import get_logger
from app.core.llm import create_flash_llm
from app.core.settings import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR, DATA_DIR, DEFAULT_PROVIDER, OUTLINE_INDEX_DIR,
)
from .utils.metadata_extractor import MetadataExtractor, ExtractedMetadata

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
    _lock: threading.Lock = threading.Lock()
    _vector_store = None
    _cache = None

    def __init__(self):
        """Initialize RAG service"""
        try:
            from .vector_store import HierarchyVectorStore, get_vector_cache
            self._vector_store = HierarchyVectorStore()
            self._cache = get_vector_cache()
            logger.info("[RagService] HierarchyVectorStore initialized")
        except ImportError as e:
            logger.warning(f"[RagService] Vector store unavailable: {e}")
            self._vector_store = None
            self._cache = None

    @classmethod
    def get_instance(cls) -> "RagService":
        """Get singleton instance (thread-safe)"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _build_query_prompt(self, dim_name: str, task_desc: str, layer: int,
                            dependency_summaries: List[str],
                            dim_key: str = "",
                            village_context: str = "",
                            extra_keywords: str = "") -> str:
        """根据 Layer 和维度构建不同的 Prompt"""
        # Special case: superior_planning needs planning documents, not tech standards
        if dim_key == "superior_planning" and layer == 1:
            loc_line = f"\n## 村庄位置\n{village_context}\n" if village_context else ""
            kw_line = f"\n## 已知上位规划关键词\n{extra_keywords}\n" if extra_keywords else ""
            return f"""你是一个专业的国土空间规划专家。为村庄规划的上位规划分析生成精准的检索查询。
{loc_line}{kw_line}
## 分析任务
- 维度：{dim_name}
- 关键词：{task_desc}

## 检索目标（按优先级）
检索村庄上位规划分析所需的：
1. 省/市/县各级国土空间总体规划文本
2. 上级政府对乡镇总体规划的批复文件
3. 与村庄规划相关的省级/市级专项规划和政策文件
4. 三区三线划定方案和规划管控要求

## 生成要求
生成 4-6 条精准查询（每条 10-20 字），要求：
1. 包含具体的地名（如省/市/县名称），以检索到地方性规划文件
2. 使用上位规划专业术语（如"国土空间总体规划""三区三线""镇村体系规划"）
3. 侧重规划文件本身而非技术指标

直接输出查询（每行一条），不要编号或解释。"""

        if layer == 1:
            # Layer 1: 现状分析 - 侧重分析方法和技术标准
            return f"""你是一个专业的村庄规划现状分析专家。为以下分析任务生成精准的检索查询。

## 分析任务
- 维度：{dim_name}
- 关键词：{task_desc}

## 检索目标
检索村庄规划现状分析所需的：
1. 技术规范和标准（如《村庄规划技术规范》）
2. 数据采集和分析方法
3. 评价指标和计算公式

## 生成要求
生成 4-6 条精准查询（每条 10-20 字），要求：
1. 使用专业术语（如"人均建设用地指标""村庄人口规模预测"）
2. 侧重技术方法和标准规范
3. 避免泛化查询（如"村庄规划""经济发展"）

直接输出查询（每行一条），不要编号或解释。"""

        elif layer == 3:
            # Layer 3: 详细规划 - 侧重规划编制标准和案例
            deps_text = chr(10).join(dependency_summaries[:3]) if dependency_summaries else "无"
            return f"""你是一个专业的村庄规划编制专家。根据以下背景信息，生成精准的检索查询。

## 规划任务
- 维度：{dim_name}
- 关键词：{task_desc}

## 已知背景
{deps_text}

## 检索目标
检索村庄规划编制所需的：
1. 规划编制技术标准（用地指标、设施配置标准等）
2. 政策法规要求（审批流程、用地政策等）
3. 相似案例参考（其他村庄规划实践）

## 生成要求
生成 4-6 条精准查询（每条 10-20 字），要求：
1. 使用专业术语（如"村庄建设用地指标""公共服务设施配置标准"）
2. 结合背景信息中的村庄特点
3. 覆盖技术标准和政策要求

直接输出查询（每行一条），不要编号或解释。"""

        else:
            # Layer 2 或其他：通用 Prompt
            deps_text = chr(10).join(dependency_summaries[:2]) if dependency_summaries else "无"
            return f"""你是一个专业的规划信息检索专家。根据以下信息生成检索查询。

## 任务
- 维度：{dim_name}
- 描述：{task_desc}

## 背景
{deps_text}

生成 3-5 条精准查询，直接输出（每行一条），不要编号或解释。"""

    def _expand_query(self, query: str) -> List[str]:
        """查询扩展：生成同义查询

        Args:
            query: 原始查询

        Returns:
            扩展后的查询列表（包含原始查询）
        """
        # 领域同义词词典
        SYNONYMS = {
            "村庄": ["农村", "乡村", "村镇"],
            "规划": ["规划编制", "规划设计", "空间规划"],
            "用地": ["土地", "建设用地", "用地分类"],
            "标准": ["规范", "技术规范", "标准规范"],
            "指标": ["控制指标", "规划指标", "技术指标"],
        }

        expanded = [query]
        for term, synonyms in SYNONYMS.items():
            if term in query:
                for syn in synonyms[:2]:  # 每个词最多扩展2个
                    expanded.append(query.replace(term, syn))

        return expanded[:3]  # 最多返回3条

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

        # 获取 Layer 信息
        dim_layer = 1  # 默认 Layer 1
        if hasattr(cfg, 'phase_id'):
            phase_id = getattr(cfg, 'phase_id', 'layer1')
            if phase_id.startswith('layer'):
                try:
                    dim_layer = int(phase_id.replace('layer', ''))
                except ValueError:
                    pass

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

        # Extract village location context from state config (structured fields)
        village_context = ""
        extra_keywords = ""
        if dim_key == "superior_planning":
            config = state.get("config", {})
            province = config.get("province", "")
            city = config.get("city", "")
            county = config.get("county", "")
            township = config.get("township", "")
            location_parts = [province, city, county, township]
            village_context = ''.join(p for p in location_parts if p)

            # Fallback: regex extraction from village_data
            if not village_context:
                village_data = config.get("village_data", "")
                if village_data:
                    loc_match = re.search(r'([^\s]+省)([^\s]+市)([^\s]+县)([^\s]+镇)', village_data[:2000])
                    if loc_match:
                        village_context = f"{loc_match.group(1)}{loc_match.group(2)}{loc_match.group(3)}{loc_match.group(4)}"

            if not village_context:
                village_name = state.get("village_name", "") or config.get("village_name", "")
                village_context = village_name

            # Flash LLM preprocessing: extract superior planning keywords
            village_data = config.get("village_data", "")
            if village_data:
                try:
                    kw_prompt = f"""从以下村庄现状报告中提取所有涉及上位规划的文档名称和关键词。只输出名称，每行一个，不要解释。

{village_data[:2000]}

上位规划文档名称和关键词："""
                    flash_llm = create_flash_llm(max_tokens=150, temperature=0.1)
                    kw_response = await flash_llm.ainvoke(kw_prompt)
                    extra_keywords = kw_response.content.strip()[:300] if hasattr(kw_response, 'content') else ""
                except Exception:
                    pass

        # 使用分 Layer Prompt
        prompt = self._build_query_prompt(dim_name, task_desc, dim_layer, dependency_summaries,
                                          dim_key=dim_key, village_context=village_context,
                                          extra_keywords=extra_keywords)

        # 使用 Flash LLM 生成查询
        llm = create_flash_llm(max_tokens=200, temperature=0.3)

        try:
            response = await llm.ainvoke(prompt)
            queries = [q.strip() for q in response.content.split("\n") if q.strip()]
            logger.info(f"[RagService] Generated {len(queries)} queries for {dim_key} (layer={dim_layer}): {queries[:3]}...")
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
        top_k: int = 3,
        prefer_doc_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search vector store for relevant documents

        Args:
            query: Search query
            top_k: Number of results
            prefer_doc_types: Optional list of doc_types to prefer (e.g. ["policy", "standard"])

        Returns:
            List of {content, metadata, score}
        """
        if self._vector_store is None:
            logger.warning("[RagService] Vector store not available")
            return []

        try:
            results = self._vector_store.retrieve(
                query, k=top_k, doc_types=prefer_doc_types
            )
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
            parts.append(content)

        return "\n".join(parts)

    # ==========================================
    # Knowledge Base Management Methods
    # ==========================================

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents in knowledge base"""
        try:
            if self._vector_store is None:
                return []
            return self._vector_store.list_sources()
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
            # 1. 删除向量库数据
            if self._vector_store:
                self._vector_store.delete_by_source(source_name)
                # 清理内存中的树索引
                if source_name in self._vector_store._tree_indices:
                    del self._vector_store._tree_indices[source_name]

            # 2. 删除 JSON 缓存文件
            from .context import OutlineIndexManager
            OutlineIndexManager().delete(source_name)

            # 3. 删除临时 MD 文件（如果存在）
            temp_md = OUTLINE_INDEX_DIR / f"{Path(source_name).stem}.md"
            if temp_md.exists():
                temp_md.unlink()

            # 4. 清理查询缓存
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
        terrain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add single document to knowledge base (incremental)

        Args:
            file_path: Document path
            category: Document category (policies/cases)
            skip_summary: Skip summary generation
            doc_type: Document type (textbook/guide/policy/standard/case/report)
            terrain: Terrain type to inject

        Returns:
            Result with status, chunks_added, message
        """
        from .utils.document_loader import FileTypeDetector, _create_loader
        from .chunker import HierarchySlicer

        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        source_name = path.name
        file_hash = self._compute_file_hash(path)

        # 增量更新：检查文件是否变化
        if not self._should_update_document(source_name, file_hash):
            logger.info(f"Document unchanged, skipping: {source_name}")
            return {
                "status": "skipped",
                "message": f"Document unchanged: {source_name}",
                "source": source_name,
                "chunks_added": 0,
            }

        # 删除旧版本（如果存在）
        if self._check_document_exists(source_name):
            logger.info(f"Document changed, updating: {source_name}")
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

            # 将内容保存为临时 Markdown 文件以使用缓存
            # 注意：source_name 可能已经包含 .md 后缀，需要处理
            temp_md_path = OUTLINE_INDEX_DIR / source_name
            OUTLINE_INDEX_DIR.mkdir(parents=True, exist_ok=True)
            temp_md_path.write_text(full_content, encoding="utf-8")

            # 使用层级切片器（带缓存）
            slicer = HierarchySlicer()
            chunks, index = slicer.slice_with_cache(str(temp_md_path), source_name)
            logger.info(f"Hierarchy sliced into {len(chunks)} chunks (with cache)")

            # 注入元数据
            for chunk in chunks:
                chunk.metadata["doc_type"] = doc_type
                chunk.metadata["category"] = category or "policies"
                if terrain:
                    chunk.metadata["terrain"] = terrain

            # 添加到层级向量存储
            from .vector_store import HierarchyVectorStore
            if isinstance(self._vector_store, HierarchyVectorStore):
                self._vector_store.add_hierarchy_chunks(chunks)
                logger.info(f"Added {len(chunks)} hierarchy chunks")
            else:
                # Fallback: 直接添加文档
                docs = [Document(page_content=c.content, metadata=c.metadata) for c in chunks]
                if self._cache:
                    self._cache.get_vectorstore().add_documents(docs)
                logger.info(f"Added {len(docs)} documents (fallback mode)")

            if self._cache:
                self._cache.clear_cache()

            return {
                "status": "success",
                "message": f"Successfully added: {source_name}",
                "source": source_name,
                "chunks_added": len(chunks),
                "doc_type": real_type,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"Add document failed: {str(e)}"}

    async def add_markdown_document(
        self,
        file_path: str,
        use_llm_inference: bool = True,
    ) -> Dict[str, Any]:
        """
        Add Markdown document directly to knowledge base

        This method is optimized for pre-parsed Markdown files in _doc_md/.
        It extracts metadata from file path and uses LLM Flash for doc_type inference.

        Args:
            file_path: Path to Markdown file
            use_llm_inference: Whether to use LLM Flash for doc_type inference

        Returns:
            Result with status, chunks_added, message
        """
        from .chunker import HierarchySlicer
        from .vector_store import HierarchyVectorStore

        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        if path.suffix.lower() != ".md":
            return {"status": "error", "message": f"Not a Markdown file: {path.suffix}"}

        source_name = path.name
        file_hash = self._compute_file_hash(path)

        # Check if document needs update
        if not self._should_update_document(source_name, file_hash):
            logger.info(f"Document unchanged, skipping: {source_name}")
            return {
                "status": "skipped",
                "message": f"Document unchanged: {source_name}",
                "source": source_name,
                "chunks_added": 0,
            }

        # Delete old version if exists
        if self._check_document_exists(source_name):
            logger.info(f"Document changed, updating: {source_name}")
            self.delete_document(source_name)

        try:
            logger.info(f"Processing Markdown document: {source_name}")

            # Read content
            content = path.read_text(encoding="utf-8")
            if not content or len(content.strip()) < 10:
                return {"status": "error", "message": "Document content empty or too short"}

            # Extract metadata from path and filename
            extracted = MetadataExtractor.extract(path, content)
            logger.info(f"Extracted metadata: category={extracted.category}, title={extracted.title}")

            # Use LLM Flash to infer doc_type from title
            if use_llm_inference and extracted.title:
                inferred = await MetadataExtractor.infer_doc_type_with_llm(
                    extracted.title, content[:500]
                )
                extracted.doc_type = inferred.get("doc_type", "report")
                extracted.keywords = inferred.get("keywords", [])
                logger.info(f"LLM inferred doc_type: {extracted.doc_type}")
            elif not extracted.doc_type:
                # Fallback to rule-based inference
                inferred = MetadataExtractor._infer_doc_type_rules(extracted.title, content[:500])
                extracted.doc_type = inferred.get("doc_type", "report")

            # Hierarchy slicing with cache
            slicer = HierarchySlicer()
            chunks, index = slicer.slice_with_cache(str(path), source_name)
            logger.info(f"Hierarchy sliced into {len(chunks)} chunks")

            # Merge extracted metadata into each chunk
            extracted_dict = extracted.to_dict()
            for chunk in chunks:
                chunk.metadata.update(extracted_dict)

            # Add to vector store
            if isinstance(self._vector_store, HierarchyVectorStore):
                self._vector_store.add_hierarchy_chunks(chunks)
                logger.info(f"Added {len(chunks)} hierarchy chunks")
            else:
                docs = [Document(page_content=c.content, metadata=c.metadata) for c in chunks]
                if self._cache:
                    self._cache.get_vectorstore().add_documents(docs)
                logger.info(f"Added {len(docs)} documents (fallback mode)")

            if self._cache:
                self._cache.clear_cache()

            return {
                "status": "success",
                "message": f"Successfully added: {source_name}",
                "source": source_name,
                "chunks_added": len(chunks),
                "doc_type": extracted.doc_type,
                "category": extracted.category,
                "title": extracted.title,
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"Add Markdown document failed: {str(e)}"}

    def add_document_with_progress(
        self,
        file_path: str,
        progress_callback: Callable[[float, str], None],
        category: Optional[str] = None,
        doc_type: Optional[str] = None,
        terrain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add document with progress callback (for async task manager)"""
        from .utils.document_loader import FileTypeDetector, _create_loader
        from .chunker import HierarchySlicer

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

            progress_callback(40.0, "Hierarchy slicing")
            slicer = HierarchySlicer()
            chunks = slicer.slice(full_content, source_name)
            progress_callback(50.0, f"Sliced into {len(chunks)} chunks")

            progress_callback(55.0, "Injecting metadata")
            for chunk in chunks:
                chunk.metadata["doc_type"] = doc_type
                chunk.metadata["category"] = category or "policies"
                if terrain:
                    chunk.metadata["terrain"] = terrain
            progress_callback(60.0, "Metadata injection complete")

            progress_callback(70.0, "Generating vectors")
            from .vector_store import HierarchyVectorStore
            if isinstance(self._vector_store, HierarchyVectorStore):
                self._vector_store.add_hierarchy_chunks(chunks)
                logger.info(f"Added {len(chunks)} hierarchy chunks")
            else:
                docs = [Document(page_content=c.content, metadata=c.metadata) for c in chunks]
                if self._cache:
                    self._cache.get_vectorstore().add_documents(docs)
            progress_callback(85.0, "Vector generation complete")

            progress_callback(95.0, "Clearing cache")
            if self._cache:
                self._cache.clear_cache()

            progress_callback(100.0, "Complete")
            return {
                "status": "success",
                "message": f"Successfully added: {source_name}",
                "source": source_name,
                "chunks_added": len(chunks),
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

    def _get_document_hash(self, source_name: str) -> Optional[str]:
        """Get stored file hash for document"""
        if self._vector_store is None:
            return None
        try:
            collection = self._vector_store.vectorstore._collection
            results = collection.get(
                where={"source": source_name},
                limit=1,
                include=["metadatas"]
            )
            if results and results.get("metadatas"):
                return results["metadatas"][0].get("file_hash")
        except Exception:
            pass
        return None

    def _should_update_document(self, source_name: str, new_hash: str) -> bool:
        """Check if document needs update (hash changed or not exists)"""
        existing = self._check_document_exists(source_name)
        if not existing:
            return True  # 新文档，需要添加

        stored_hash = self._get_document_hash(source_name)
        if not stored_hash:
            return True  # 无哈希记录，需要更新

        return stored_hash != new_hash  # 哈希变化，需要更新

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

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute file MD5 hash (full 32-char hexdigest)"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()


__all__ = ["RagService", "DocumentSummary"]