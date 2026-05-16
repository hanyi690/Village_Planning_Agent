"""
层级向量存储

Small-to-Big 检索架构 + 层级感知。
利用 HierarchyChunk 的层级信息，实现更智能的检索。

2026-05-16: 重写，删除旧的 ParentChildVectorStore 实现
"""
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json

from app.core.settings import (
    CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, EMBEDDING_PROVIDER,
    EMBEDDING_MODEL_NAME, DASHSCOPE_API_KEY, HF_ENDPOINT, OUTLINE_INDEX_DIR,
    RETRIEVE_SCORE_THRESHOLD, MAX_MERGE_CONTENT_LENGTH,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AliyunEmbeddings:
    """阿里云 Embedding API 封装类（OpenAI 兼容格式）"""
    BATCH_SIZE = 10

    def __init__(self, api_key: str, base_url: str, model: str = "text-embedding-v4"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        all_embeddings = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            response = self.client.embeddings.create(model=self.model, input=batch)
            all_embeddings.extend([item.embedding for item in response.data])
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        response = self.client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding


class VectorStoreCache:
    """向量数据库缓存管理器"""

    def __init__(self, cache_ttl: int = 0):
        self.cache_ttl = cache_ttl
        self._embedding_model = None
        self._vectorstore = None
        self._query_cache: Dict = {}

    def get_embedding_model(self):
        """懒加载并缓存 Embedding 模型"""
        if self._embedding_model is None:
            if EMBEDDING_PROVIDER == "aliyun":
                if not DASHSCOPE_API_KEY:
                    raise ValueError("EMBEDDING_PROVIDER=aliyun 但未设置 DASHSCOPE_API_KEY")
                self._embedding_model = AliyunEmbeddings(
                    api_key=DASHSCOPE_API_KEY,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model="text-embedding-v4",
                )
                logger.info(f"[VectorStore] 阿里云 Embedding 已就绪")
            else:
                self._init_local_embedding()

        return self._embedding_model

    def _init_local_embedding(self):
        """初始化本地 HuggingFace Embedding 模型"""
        import os
        if HF_ENDPOINT:
            os.environ["HF_ENDPOINT"] = HF_ENDPOINT

        from langchain_huggingface import HuggingFaceEmbeddings
        self._embedding_model = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info(f"[VectorStore] 本地 Embedding 模型已缓存: {EMBEDDING_MODEL_NAME}")

    def get_vectorstore(self):
        """懒加载并缓存向量数据库"""
        if self._vectorstore is None:
            from langchain_chroma import Chroma
            self._vectorstore = Chroma(
                persist_directory=str(CHROMA_PERSIST_DIR),
                embedding_function=self.get_embedding_model(),
                collection_name=CHROMA_COLLECTION_NAME,
            )
            logger.info(f"[VectorStore] 向量数据库已缓存: {CHROMA_COLLECTION_NAME}")

        return self._vectorstore

    def clear_cache(self) -> None:
        """清理缓存"""
        self._query_cache.clear()
        logger.info("[VectorStore] 查询缓存已清理")

    def get_cached_query(self, query: str, context_params: Dict) -> Optional[List]:
        """从缓存获取查询结果"""
        cache_key = self._make_cache_key(query, context_params)
        return self._query_cache.get(cache_key)

    def cache_query_result(self, query: str, results: List, context_params: Dict) -> None:
        """缓存查询结果"""
        cache_key = self._make_cache_key(query, context_params)
        self._query_cache[cache_key] = results
        logger.debug(f"[VectorStore] 缓存查询结果: {query[:50]}...")

    def _make_cache_key(self, query: str, context_params: Dict) -> str:
        """生成缓存键"""
        params_str = json.dumps(context_params, sort_keys=True)
        return hashlib.md5(f"{query}:{params_str}".encode()).hexdigest()


# 全局缓存实例
_vector_cache: Optional[VectorStoreCache] = None


def get_vector_cache() -> VectorStoreCache:
    """获取全局向量缓存实例"""
    global _vector_cache
    if _vector_cache is None:
        from app.core.settings import QUERY_CACHE_TTL
        _vector_cache = VectorStoreCache(cache_ttl=QUERY_CACHE_TTL)
    return _vector_cache


class HierarchyVectorStore:
    """
    层级向量存储：Small-to-Big + 层级感知

    核心设计：
    - 子块：用于精确检索（层级切片）
    - 父块：用于返回上下文（上级标题内容）
    - 元数据：包含完整祖先路径（章节导航）

    流程：
    1. 添加文档时：存储层级切片 -> 子块存向量，父块存缓存
    2. 检索时：检索子块 -> 获取 parent_id -> 返回父块（含祖先路径）
    """

    PARENT_CACHE_FILE = "hierarchy_chunks_cache.json"
    MAX_PARENT_CACHE_SIZE = 2000

    def __init__(self, collection_name: str = None, persist_dir: Path = None):
        self.persist_dir = persist_dir or CHROMA_PERSIST_DIR
        self.collection_name = collection_name or CHROMA_COLLECTION_NAME
        self._vectorstore = None
        # 父块缓存：chunk_id -> content
        self._parent_cache: OrderedDict[str, str] = OrderedDict()
        # 父块元数据：chunk_id -> metadata
        self._parent_metadata: OrderedDict[str, Dict] = OrderedDict()
        # 树形索引：按文档隔离存储（source_name -> tree_index）
        self._tree_indices: Dict[str, Dict] = {}
        self._load_parent_cache()

    @property
    def vectorstore(self):
        """获取向量存储"""
        if self._vectorstore is None:
            cache = get_vector_cache()
            self._vectorstore = cache.get_vectorstore()
        return self._vectorstore

    @property
    def embedding_model(self):
        """获取 Embedding 模型"""
        cache = get_vector_cache()
        return cache.get_embedding_model()

    def load_tree_index(self, source_name: str) -> None:
        """从 outline_index 加载单个文档的树形索引

        Args:
            source_name: 源文件名（如 "xxx.md"）
        """
        index_file = OUTLINE_INDEX_DIR / f"{Path(source_name).stem}_index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                tree_index = data.get("tree_index", {})
                if tree_index:
                    self._tree_indices[source_name] = tree_index
                    by_id_count = len(tree_index.get("by_id", {}))
                    logger.info(f"[HierarchyVectorStore] 加载树形索引: {source_name} ({by_id_count} 个节点)")
            except Exception as e:
                logger.warning(f"[HierarchyVectorStore] 加载树形索引失败: {e}")
        else:
            logger.debug(f"[HierarchyVectorStore] 索引文件不存在: {index_file}")

    def load_all_tree_indices(self) -> None:
        """加载所有 outline_index 中的树形索引（按文档隔离）"""
        if not OUTLINE_INDEX_DIR.exists():
            return

        self._tree_indices = {}

        for index_file in OUTLINE_INDEX_DIR.glob("*_index.json"):
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                source_name = data.get("source_name", "")
                tree_index = data.get("tree_index", {})
                if tree_index and source_name:
                    self._tree_indices[source_name] = tree_index
            except Exception as e:
                logger.warning(f"[HierarchyVectorStore] 加载索引失败 {index_file}: {e}")

        logger.info(f"[HierarchyVectorStore] 加载 {len(self._tree_indices)} 个文档的树形索引")

    def _find_parent_chunk(self, child_doc, target_depth: int) -> Optional[Dict]:
        """查找指定层级的父块

        Args:
            child_doc: 子块文档
            target_depth: 目标父块层级

        Returns:
            父块字典，包含 content、chunk_id、metadata 等
        """
        child_chunk_id = child_doc.metadata.get("chunk_id", "")
        source = child_doc.metadata.get("source", "")

        # 优先使用树形索引（按文档隔离）
        tree_index = self._tree_indices.get(source, {})
        if tree_index:
            by_id = tree_index.get("by_id", {})
            by_section = tree_index.get("by_section", {})
            chunk = by_id.get(child_chunk_id)

            if chunk:
                # 如果当前块就是目标层级，直接返回
                if chunk.get("depth") == target_depth:
                    return chunk

                # 策略1: 向上遍历 parent_id 链
                current = chunk
                while current:
                    parent_id = current.get("parent_id")
                    if parent_id:
                        parent = by_id.get(parent_id)
                        if parent:
                            if parent.get("depth") == target_depth:
                                return parent
                            current = parent
                        else:
                            break
                    else:
                        break

                # 策略2: 使用 ancestors 数组查找（解决跳跃问题）
                ancestors = chunk.get("ancestors", [])
                if isinstance(ancestors, list) and len(ancestors) >= target_depth:
                    # ancestors[target_depth - 1] 是目标层级的标题
                    target_section = ancestors[target_depth - 1]
                    # 通过 section_title 查找
                    target_chunk_id = by_section.get(target_section)
                    if target_chunk_id and target_chunk_id in by_id:
                        return by_id[target_chunk_id]

        # Fallback: 使用文档元数据中的 ancestors
        ancestors_str = child_doc.metadata.get("ancestors", "[]")
        try:
            ancestors = json.loads(ancestors_str) if isinstance(ancestors_str, str) else ancestors_str
        except:
            ancestors = []

        if len(ancestors) >= target_depth:
            parent_section = ancestors[target_depth - 1]
            # 在缓存中查找
            for chunk_id, meta in self._parent_metadata.items():
                if meta.get("section_title") == parent_section and meta.get("depth") == target_depth:
                    return {
                        "content": self._parent_cache.get(chunk_id, ""),
                        "chunk_id": chunk_id,
                        "metadata": meta,
                    }

        return None

    def add_hierarchy_chunks(self, chunks: List) -> int:
        """添加层级切片到向量存储

        Args:
            chunks: HierarchyChunk 列表

        Returns:
            添加的切片数量
        """
        if not chunks:
            return 0

        from langchain_core.documents import Document

        # 缓存父块（层级更低的块）
        for chunk in chunks:
            # LRU 淘汰
            while len(self._parent_cache) >= self.MAX_PARENT_CACHE_SIZE:
                oldest_id = next(iter(self._parent_cache))
                del self._parent_cache[oldest_id]
                del self._parent_metadata[oldest_id]

            # 存储当前块作为潜在的父块
            self._parent_cache[chunk.chunk_id] = chunk.content
            self._parent_metadata[chunk.chunk_id] = {
                "source": chunk.metadata.get("source", ""),
                "depth": chunk.depth,
                "section_title": chunk.section_title,
                "ancestors": chunk.ancestors,
                "parent_id": chunk.parent_id,
                **chunk.metadata,
            }

        # 创建向量文档
        docs = []
        for chunk in chunks:
            doc = Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": chunk.chunk_id,
                    "depth": chunk.depth,
                    "section_title": chunk.section_title,
                    "ancestors": json.dumps(chunk.ancestors, ensure_ascii=False),
                    "parent_id": chunk.parent_id or "",
                    "source": chunk.metadata.get("source", ""),
                    "has_table": chunk.metadata.get("has_table", False),
                },
            )
            docs.append(doc)

        # 添加到向量存储
        self.vectorstore.add_documents(docs)
        self._save_parent_cache()

        logger.info(f"[HierarchyVectorStore] 已添加 {len(chunks)} 个层级切片")
        return len(chunks)

    def retrieve(self, query: str, k: int = 5, score_threshold: float = None,
                 return_parents: bool = True, parent_level: int = -1,
                 max_merge_length: int = None) -> List[Dict]:
        """Small-to-Big 检索：返回子块 + ancestors 上下文

        Args:
            query: 查询字符串
            k: 返回结果数量
            score_threshold: L2距离阈值（距离越小越相似，过滤距离大的结果）
                            默认从配置读取 RETRIEVE_SCORE_THRESHOLD
            return_parents: 保留参数（兼容性）
            parent_level: 保留参数（兼容性）
            max_merge_length: 子块合并最大长度（防止撑爆 LLM 窗口）
                             默认从配置读取 MAX_MERGE_CONTENT_LENGTH

        Returns:
            检索结果列表，每项包含 content、metadata、score
            - content: 子块的完整内容
            - metadata.ancestors: 层级上下文 ["一级标题", "二级标题", ...]
            - metadata.parent_section_title: 直接父块标题
            - metadata.depth: 当前块深度
            - score: L2距离分数（越小越相似）
        """
        # 使用配置默认值
        if score_threshold is None:
            score_threshold = RETRIEVE_SCORE_THRESHOLD
        if max_merge_length is None:
            max_merge_length = MAX_MERGE_CONTENT_LENGTH
        # 确保树形索引已加载
        if not self._tree_indices:
            self.load_all_tree_indices()

        # 使用带分数的检索
        child_results = self.vectorstore.similarity_search_with_score(query, k=k * 2)

        # 过滤距离大的结果（L2距离越小越相似）
        filtered_results = [(doc, score) for doc, score in child_results if score <= score_threshold]

        results = []
        seen_chunks: set = set()

        for child_doc, score in filtered_results[:k]:
            child_chunk_id = child_doc.metadata.get("chunk_id", "")
            if child_chunk_id in seen_chunks:
                continue
            seen_chunks.add(child_chunk_id)

            # 根据 source 获取对应文档的树形索引
            source = child_doc.metadata.get("source", "")
            tree_index = self._tree_indices.get(source, {})
            by_id = tree_index.get("by_id", {})
            children_map = tree_index.get("children", {})

            # 从树形索引获取完整信息
            chunk = by_id.get(child_chunk_id, {})
            is_placeholder = chunk.get("metadata", {}).get("is_placeholder", False)
            char_count = chunk.get("metadata", {}).get("char_count", 999)

            # 判断是否需要合并子块内容：
            # 1. 显式标记为占位切片
            # 2. 内容很短（只有标题，char_count < 50）
            need_merge_children = is_placeholder or char_count < 50

            # 确定返回内容
            if need_merge_children:
                # 占位切片或只有标题的切片：查找子块并合并内容
                child_ids = children_map.get(child_chunk_id, [])
                if child_ids:
                    # 合并子块内容（限制总长度）
                    merged_content = chunk.get("content", "")  # 当前切片的标题
                    total_length = len(merged_content)

                    for cid in child_ids:
                        child_chunk = by_id.get(cid, {})
                        child_content = child_chunk.get("content", "")
                        if child_content:
                            new_content = "\n\n" + child_content
                            # 检查长度限制
                            if total_length + len(new_content) <= max_merge_length:
                                merged_content += new_content
                                total_length += len(new_content)
                            else:
                                # 达到长度限制，截断并添加提示
                                remaining = max_merge_length - total_length
                                if remaining > 100:
                                    merged_content += new_content[:remaining] + "\n...[内容已截断]"
                                break

                    content = merged_content
                else:
                    content = chunk.get("content", child_doc.page_content)
                    if children_map == {}:
                        logger.warning(f"[HierarchyVectorStore] children_map 为空，占位切片合并失效: {child_chunk_id}")
            else:
                # 非占位切片：返回子块本身的内容
                content = child_doc.page_content

            # 获取 ancestors
            ancestors = chunk.get("ancestors", [])
            if not ancestors:
                # 从文档 metadata 获取
                ancestors_str = child_doc.metadata.get("ancestors", "[]")
                try:
                    ancestors = json.loads(ancestors_str) if isinstance(ancestors_str, str) else ancestors_str
                except:
                    ancestors = []

            # 获取父块标题
            parent_section_title = ancestors[-2] if len(ancestors) >= 2 else None

            results.append({
                "content": content,
                "score": score,
                "metadata": {
                    "ancestors": ancestors[:-1] if len(ancestors) > 1 else ancestors,  # 不包含自己
                    "parent_section_title": parent_section_title,
                    "depth": chunk.get("depth", child_doc.metadata.get("depth", 1)),
                    "section_title": chunk.get("section_title", child_doc.metadata.get("section_title", "")),
                    "is_placeholder": is_placeholder,
                    "source": chunk.get("metadata", {}).get("source", child_doc.metadata.get("source", "")),
                },
            })

        return results[:k]

    def retrieve_with_scores(self, query: str, k: int = 5, return_parents: bool = True,
                             parent_level: int = -1) -> List[Tuple[Dict, float]]:
        """带分数的检索

        Args:
            query: 查询字符串
            k: 返回结果数量
            return_parents: 是否返回父块
            parent_level: 父块层级 (-1=直接父块, 1=一级标题, ...)
        """
        # 确保树形索引已加载
        if not self._tree_indices:
            self.load_all_tree_indices()

        child_results = self.vectorstore.similarity_search_with_score(query, k=k)

        if not return_parents:
            return [({"content": doc.page_content, "metadata": doc.metadata}, score) for doc, score in child_results]

        parent_ids_seen: Dict[str, Tuple[Dict, float]] = {}

        for child_doc, score in child_results:
            child_chunk_id = child_doc.metadata.get("chunk_id", "")
            child_depth = child_doc.metadata.get("depth", 1)

            # 确定目标父块层级
            if parent_level == -1:
                target_parent_depth = child_depth - 1 if child_depth > 1 else 1
            else:
                target_parent_depth = parent_level

            # 通过树形索引查找父块
            parent_chunk = self._find_parent_chunk(child_doc, target_parent_depth)

            if parent_chunk:
                parent_id = parent_chunk.get("chunk_id", "")

                # 保留最佳分数
                if parent_id not in parent_ids_seen or score < parent_ids_seen[parent_id][1]:
                    parent_content = parent_chunk.get("content", "")
                    if not parent_content and parent_id in self._parent_cache:
                        parent_content = self._parent_cache.get(parent_id, "")

                    parent_metadata = parent_chunk.get("metadata", {})
                    if not parent_metadata and parent_id in self._parent_metadata:
                        parent_metadata = self._parent_metadata.get(parent_id, {})

                    # 解析 ancestors
                    ancestors = parent_metadata.get("ancestors", [])
                    if isinstance(ancestors, str):
                        try:
                            ancestors = json.loads(ancestors)
                        except:
                            ancestors = []

                    parent_ids_seen[parent_id] = (
                        {
                            "content": parent_content,
                            "metadata": {
                                **parent_metadata,
                                "ancestors": ancestors,
                                "matched_child": child_chunk_id,
                                "matched_child_depth": child_depth,
                                "parent_depth": target_parent_depth,
                            },
                            "parent_id": parent_id,
                        },
                        score,
                    )
            else:
                # Fallback: 使用子块本身
                ancestors_str = child_doc.metadata.get("ancestors", "[]")
                try:
                    ancestors = json.loads(ancestors_str) if isinstance(ancestors_str, str) else ancestors_str
                except:
                    ancestors = []

                fallback_key = f"fallback_{child_chunk_id}"
                parent_ids_seen[fallback_key] = (
                    {
                        "content": child_doc.page_content,
                        "metadata": {
                            **child_doc.metadata,
                            "ancestors": ancestors,
                            "no_parent": True,
                            "matched_child_depth": child_depth,
                        },
                        "parent_id": None,
                    },
                    score,
                )

        if parent_ids_seen:
            return sorted(parent_ids_seen.values(), key=lambda x: x[1])[:k]

        return [({"content": doc.page_content, "metadata": doc.metadata}, score) for doc, score in child_results]

    def add_documents(self, documents: List) -> int:
        """添加文档（向后兼容）"""
        self.vectorstore.add_documents(documents)
        return len(documents)

    def delete_by_source(self, source: str) -> int:
        """删除指定来源的所有切片"""
        collection = self.vectorstore._collection
        collection.delete(where={"source": source})

        # 清理缓存
        to_delete = [cid for cid, meta in self._parent_metadata.items() if meta.get("source") == source]
        for cid in to_delete:
            if cid in self._parent_cache:
                del self._parent_cache[cid]
            if cid in self._parent_metadata:
                del self._parent_metadata[cid]

        self._save_parent_cache()
        logger.info(f"[HierarchyVectorStore] 已删除来源 {source} 的 {len(to_delete)} 个切片")
        return len(to_delete)

    def clear_all(self) -> int:
        """清空所有数据"""
        count = len(self._parent_cache)

        # 清空向量存储
        collection = self.vectorstore._collection
        collection.delete()

        # 清空缓存
        self._parent_cache.clear()
        self._parent_metadata.clear()
        self._save_parent_cache()

        logger.info(f"[HierarchyVectorStore] 已清空所有数据（{count} 个切片）")
        return count

    def get_stats(self) -> Dict:
        """获取存储统计"""
        collection = self.vectorstore._collection
        count = collection.count()
        return {
            "chunk_count": count,
            "parent_cache_size": len(self._parent_cache),
            "collection_name": self.collection_name,
            "persist_dir": str(self.persist_dir),
        }

    def list_sources(self) -> List[Dict]:
        """列出所有文档来源及其统计信息"""
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
                    "doc_type": metadata.get("doc_type", "unknown"),
                }
            doc_stats[source]["chunk_count"] += 1

        return list(doc_stats.values())

    def get_collection(self):
        """获取底层 Chroma 集合（谨慎使用）"""
        return self.vectorstore._collection

    def _load_parent_cache(self) -> None:
        """加载父块缓存"""
        cache_file = self.persist_dir / self.PARENT_CACHE_FILE
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._parent_cache = OrderedDict(data.get("contents", {}))
                self._parent_metadata = OrderedDict(data.get("metadata", {}))
                logger.info(f"[HierarchyVectorStore] 已加载 {len(self._parent_cache)} 个父块缓存")
            except Exception as e:
                logger.warning(f"[HierarchyVectorStore] 加载父块缓存失败: {e}")
                self._parent_cache = OrderedDict()
                self._parent_metadata = OrderedDict()

    def _save_parent_cache(self) -> None:
        """持久化父块缓存"""
        cache_file = self.persist_dir / self.PARENT_CACHE_FILE
        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "contents": self._parent_cache,
                    "metadata": self._parent_metadata,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[HierarchyVectorStore] 保存父块缓存失败: {e}")


# 全局单例
_hierarchy_store: Optional[HierarchyVectorStore] = None


def get_hierarchy_store() -> HierarchyVectorStore:
    """获取层级向量存储单例"""
    global _hierarchy_store
    if _hierarchy_store is None:
        _hierarchy_store = HierarchyVectorStore()
    return _hierarchy_store


__all__ = [
    "HierarchyVectorStore",
    "get_hierarchy_store",
    "VectorStoreCache",
    "get_vector_cache",
    "AliyunEmbeddings",
]