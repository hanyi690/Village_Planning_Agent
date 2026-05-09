"""
Small-to-Big 向量存储架构

检索子块，返回父块完整上下文。

核心设计：
- 子块：用于精确检索（较小的 chunk size，如 400 字符）
- 父块：用于返回上下文（较大的 parent size，如 2000 字符）

来源：src/rag/core/vector_store.py
"""
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json

from app.core.settings import (
    CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, EMBEDDING_PROVIDER,
    EMBEDDING_MODEL_NAME, DASHSCOPE_API_KEY, HF_ENDPOINT,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ParentChildChunk:
    """父子块数据结构"""
    child_content: str
    child_id: str
    parent_content: str
    parent_id: str
    child_index: int
    total_children: int
    metadata: Dict


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


# 全局缓存实例
_vector_cache: Optional[VectorStoreCache] = None


def get_vector_cache() -> VectorStoreCache:
    """获取全局向量缓存实例"""
    global _vector_cache
    if _vector_cache is None:
        from app.core.settings import QUERY_CACHE_TTL
        _vector_cache = VectorStoreCache(cache_ttl=QUERY_CACHE_TTL)
    return _vector_cache


class ParentChildVectorStore:
    """
    Small-to-Big 检索架构

    流程：
    1. 添加文档时：切分为父块 -> 父块再切分为子块 -> 子块存向量，父块存缓存
    2. 检索时：检索子块 -> 获取子块的 parent_id -> 返回对应的父块内容
    """

    PARENT_CACHE_FILE = "parent_chunks_cache.json"
    MAX_PARENT_CACHE_SIZE = 1000

    def __init__(self, child_collection_name: str = None, persist_dir: Path = None):
        self.persist_dir = persist_dir or CHROMA_PERSIST_DIR
        self.child_collection_name = child_collection_name or f"{CHROMA_COLLECTION_NAME}_children"
        self._child_store = None
        self._parent_cache: OrderedDict[str, str] = OrderedDict()
        self._parent_metadata: OrderedDict[str, Dict] = OrderedDict()
        self._load_parent_cache()

    @property
    def child_store(self):
        """获取子块向量存储"""
        if self._child_store is None:
            cache = get_vector_cache()
            self._child_store = cache.get_vectorstore()
        return self._child_store

    @property
    def embedding_model(self):
        """获取 Embedding 模型"""
        cache = get_vector_cache()
        return cache.get_embedding_model()

    def add_chunks(self, chunks: List[ParentChildChunk]) -> int:
        """添加父子块到向量存储"""
        if not chunks:
            return 0

        from langchain_core.documents import Document

        for chunk in chunks:
            while len(self._parent_cache) >= self.MAX_PARENT_CACHE_SIZE:
                oldest_id = next(iter(self._parent_cache))
                del self._parent_cache[oldest_id]
                del self._parent_metadata[oldest_id]

            self._parent_cache[chunk.parent_id] = chunk.parent_content
            self._parent_metadata[chunk.parent_id] = {
                "source": chunk.metadata.get("source", ""),
                "parent_id": chunk.parent_id,
                "total_children": chunk.total_children,
                **chunk.metadata,
            }

        child_docs = []
        for chunk in chunks:
            doc = Document(
                page_content=chunk.child_content,
                metadata={
                    "parent_id": chunk.parent_id,
                    "child_id": chunk.child_id,
                    "child_index": chunk.child_index,
                    "total_children": chunk.total_children,
                    **chunk.metadata,
                },
            )
            child_docs.append(doc)

        self.child_store.add_documents(child_docs)
        self._save_parent_cache()

        logger.info(f"[ParentChildVectorStore] 已添加 {len(chunks)} 个子块")
        return len(chunks)

    def retrieve(self, query: str, k: int = 5, return_parents: bool = True) -> List[Dict]:
        """Small-to-Big 检索：检索子块，返回父块"""
        child_results = self.child_store.similarity_search(query, k=k)

        if not return_parents:
            return [{"content": doc.page_content, "metadata": doc.metadata, "score": 0} for doc in child_results]

        parent_ids_seen = set()
        parent_results = []

        for child_doc in child_results:
            parent_id = child_doc.metadata.get("parent_id", "")
            if parent_id and parent_id not in parent_ids_seen:
                parent_ids_seen.add(parent_id)
                parent_content = self._parent_cache.get(parent_id, "")
                parent_metadata = self._parent_metadata.get(parent_id, {})

                if parent_content:
                    self._parent_cache.move_to_end(parent_id)
                    self._parent_metadata.move_to_end(parent_id)
                    parent_results.append({
                        "content": parent_content,
                        "metadata": {
                            **parent_metadata,
                            "matched_child_id": child_doc.metadata.get("child_id", ""),
                            "matched_child_index": child_doc.metadata.get("child_index", 0),
                        },
                        "parent_id": parent_id,
                    })

        return parent_results

    def retrieve_with_scores(self, query: str, k: int = 5, return_parents: bool = True) -> List[Tuple[Dict, float]]:
        """带分数的检索"""
        child_results = self.child_store.similarity_search_with_score(query, k=k)

        if not return_parents:
            return [({"content": doc.page_content, "metadata": doc.metadata}, score) for doc, score in child_results]

        parent_ids_seen: Dict[str, Tuple[Dict, float]] = {}

        for child_doc, score in child_results:
            parent_id = child_doc.metadata.get("parent_id", "")
            if parent_id:
                if parent_id not in parent_ids_seen or score < parent_ids_seen[parent_id][1]:
                    parent_content = self._parent_cache.get(parent_id, "")
                    parent_metadata = self._parent_metadata.get(parent_id, {})
                    if parent_content:
                        self._parent_cache.move_to_end(parent_id)
                        self._parent_metadata.move_to_end(parent_id)
                        parent_ids_seen[parent_id] = (
                            {"content": parent_content, "metadata": {**parent_metadata}, "parent_id": parent_id},
                            score,
                        )

        return sorted(parent_ids_seen.values(), key=lambda x: x[1])[:k]

    def search(self, query: str, k: int = 5) -> List[Dict]:
        """简化搜索方法（向后兼容）"""
        return self.retrieve(query, k=k, return_parents=True)

    def add_documents(self, documents: List) -> int:
        """添加文档（向后兼容）"""
        self.child_store.add_documents(documents)
        return len(documents)

    def delete_by_parent_id(self, parent_id: str) -> int:
        """删除指定父块及其所有子块"""
        if parent_id in self._parent_cache:
            del self._parent_cache[parent_id]
        if parent_id in self._parent_metadata:
            del self._parent_metadata[parent_id]

        collection = self.child_store._collection
        collection.delete(where={"parent_id": parent_id})
        self._save_parent_cache()

        logger.info(f"[ParentChildVectorStore] 已删除父块 {parent_id}")
        return 0

    def get_stats(self) -> Dict:
        """获取存储统计"""
        collection = self.child_store._collection
        count = collection.count()
        return {
            "child_count": count,
            "parent_count": len(self._parent_cache),
            "collection_name": self.child_collection_name,
            "persist_dir": str(self.persist_dir),
        }

    def _load_parent_cache(self) -> None:
        """加载父块缓存"""
        cache_file = self.persist_dir / self.PARENT_CACHE_FILE
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._parent_cache = OrderedDict(data.get("contents", {}))
                self._parent_metadata = OrderedDict(data.get("metadata", {}))
                logger.info(f"[ParentChildVectorStore] 已加载 {len(self._parent_cache)} 个父块缓存")
            except Exception as e:
                logger.warning(f"[ParentChildVectorStore] 加载父块缓存失败: {e}")
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
            logger.warning(f"[ParentChildVectorStore] 保存父块缓存失败: {e}")


# 全局单例
_parent_child_store: Optional[ParentChildVectorStore] = None


def get_parent_child_store() -> ParentChildVectorStore:
    """获取 Small-to-Big 向量存储单例"""
    global _parent_child_store
    if _parent_child_store is None:
        _parent_child_store = ParentChildVectorStore()
    return _parent_child_store


__all__ = [
    "ParentChildVectorStore", "ParentChildChunk", "get_parent_child_store",
    "VectorStoreCache", "get_vector_cache", "AliyunEmbeddings",
]