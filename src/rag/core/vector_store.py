"""
Small-to-Big 向量存储架构

检索子块，返回父块完整上下文。

核心设计：
- 子块：用于精确检索（较小的 chunk size，如 400 字符）
- 父块：用于返回上下文（较大的 parent size，如 2000 字符）

优势：
- 提高检索命中率（小块语义更聚焦）
- 提供完整上下文（返回父块而非碎片）
"""
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.rag.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
)
from src.rag.core.cache import get_vector_cache
from src.utils.logger import get_logger

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


class ParentChildVectorStore:
    """
    Small-to-Big 检索架构

    流程：
    1. 添加文档时：切分为父块 → 父块再切分为子块 → 子块存向量，父块存缓存
    2. 检索时：检索子块 → 获取子块的 parent_id → 返回对应的父块内容
    """

    # 父块缓存文件名
    PARENT_CACHE_FILE = "parent_chunks_cache.json"

    # LRU 缓存最大数量
    MAX_PARENT_CACHE_SIZE = 1000

    def __init__(
        self,
        child_collection_name: str = None,
        persist_dir: Path = None,
    ):
        """
        初始化 Small-to-Big 向量存储

        Args:
            child_collection_name: 子块集合名称
            persist_dir: 持久化目录
        """
        self.persist_dir = persist_dir or CHROMA_PERSIST_DIR
        self.child_collection_name = child_collection_name or f"{CHROMA_COLLECTION_NAME}_children"

        # 子块向量存储（复用 cache 的 vectorstore）
        self._child_store = None

        # 父块内容缓存：使用 OrderedDict 实现 LRU（最后访问的在末尾）
        self._parent_cache: OrderedDict[str, str] = OrderedDict()
        self._parent_metadata: OrderedDict[str, Dict] = OrderedDict()

        # 加载父块缓存
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
        """
        添加父子块到向量存储（带 LRU 缓存淘汰）

        Args:
            chunks: 父子块列表

        Returns:
            添加的子块数量
        """
        if not chunks:
            return 0

        from langchain_core.documents import Document

        # 1. 存储父块到缓存（带 LRU 淘汰）
        for chunk in chunks:
            # 检查并淘汰旧条目
            while len(self._parent_cache) >= self.MAX_PARENT_CACHE_SIZE:
                # 删除最旧的（第一个）
                oldest_id = next(iter(self._parent_cache))
                del self._parent_cache[oldest_id]
                del self._parent_metadata[oldest_id]
                logger.debug(f"LRU 淘汰父块: {oldest_id}")

            self._parent_cache[chunk.parent_id] = chunk.parent_content
            self._parent_metadata[chunk.parent_id] = {
                "source": chunk.metadata.get("source", ""),
                "parent_id": chunk.parent_id,
                "total_children": chunk.total_children,
                **chunk.metadata,
            }

        # 2. 创建子块 Document 对象
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

        # 3. 存储子块向量
        self.child_store.add_documents(child_docs)

        # 4. 持久化父块缓存
        self._save_parent_cache()

        logger.info(f"已添加 {len(chunks)} 个子块，{len(self._parent_cache)} 个父块缓存")
        return len(chunks)

    def retrieve(
        self,
        query: str,
        k: int = 5,
        return_parents: bool = True,
    ) -> List[Dict]:
        """
        Small-to-Big 检索：检索子块，返回父块

        Args:
            query: 查询文本
            k: 返回结果数量
            return_parents: True 返回父块，False 返回子块

        Returns:
            检索结果列表（父块或子块）
        """
        # 1. 检索子块
        child_results = self.child_store.similarity_search(query, k=k)

        if not return_parents:
            # 直接返回子块
            return [
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": 0,  # Chroma similarity_search 不返回分数
                }
                for doc in child_results
            ]

        # 2. 获取父块（去重，更新 LRU 顺序）
        parent_ids_seen = set()
        parent_results = []

        for child_doc in child_results:
            parent_id = child_doc.metadata.get("parent_id", "")

            if parent_id and parent_id not in parent_ids_seen:
                parent_ids_seen.add(parent_id)

                # 从缓存获取父块内容
                parent_content = self._parent_cache.get(parent_id, "")
                parent_metadata = self._parent_metadata.get(parent_id, {})

                if parent_content:
                    # 移动到末尾（标记为最近使用）
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

        logger.info(f"检索返回 {len(parent_results)} 个父块（来自 {len(child_results)} 个子块匹配）")
        return parent_results

    def retrieve_with_scores(
        self,
        query: str,
        k: int = 5,
        return_parents: bool = True,
    ) -> List[Tuple[Dict, float]]:
        """
        带分数的检索

        Args:
            query: 查询文本
            k: 返回结果数量
            return_parents: True 返回父块，False 返回子块

        Returns:
            检索结果列表（带分数）
        """
        # 检索子块（带分数）
        child_results = self.child_store.similarity_search_with_score(query, k=k)

        if not return_parents:
            return [
                ({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                }, score)
                for doc, score in child_results
            ]

        # 获取父块（去重，保留最高分数，更新 LRU 顺序）
        parent_ids_seen = {}  # {parent_id: (parent_result, max_score)}

        for child_doc, score in child_results:
            parent_id = child_doc.metadata.get("parent_id", "")

            if parent_id:
                if parent_id not in parent_ids_seen or score < parent_ids_seen[parent_id][1]:
                    parent_content = self._parent_cache.get(parent_id, "")
                    parent_metadata = self._parent_metadata.get(parent_id, {})

                    if parent_content:
                        # 移动到末尾（标记为最近使用）
                        self._parent_cache.move_to_end(parent_id)
                        self._parent_metadata.move_to_end(parent_id)

                        parent_ids_seen[parent_id] = (
                            {
                                "content": parent_content,
                                "metadata": {
                                    **parent_metadata,
                                    "matched_child_id": child_doc.metadata.get("child_id", ""),
                                },
                                "parent_id": parent_id,
                            },
                            score,  # Chroma 返回的是距离，越小越好
                        )

        # 按分数排序返回
        results = sorted(parent_ids_seen.values(), key=lambda x: x[1])
        return results[:k]

    def delete_by_parent_id(self, parent_id: str) -> int:
        """
        删除指定父块及其所有子块

        Args:
            parent_id: 父块 ID

        Returns:
            删除的子块数量
        """
        # 1. 从父块缓存删除
        if parent_id in self._parent_cache:
            del self._parent_cache[parent_id]
        if parent_id in self._parent_metadata:
            del self._parent_metadata[parent_id]

        # 2. 从向量存储删除子块
        collection = self.child_store._collection
        collection.delete(where={"parent_id": parent_id})

        # 3. 持久化缓存
        self._save_parent_cache()

        logger.info(f"已删除父块 {parent_id} 及其子块")
        return 0  # Chroma delete 不返回数量

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
        """加载父块缓存（转换为 OrderedDict）"""
        cache_file = self.persist_dir / self.PARENT_CACHE_FILE

        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 转换为 OrderedDict（保持加载顺序）
                self._parent_cache = OrderedDict(data.get("contents", {}))
                self._parent_metadata = OrderedDict(data.get("metadata", {}))
                logger.info(f"已加载 {len(self._parent_cache)} 个父块缓存")
            except Exception as e:
                logger.warning(f"加载父块缓存失败: {e}")
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
            logger.info(f"父块缓存已保存: {cache_file}")
        except Exception as e:
            logger.warning(f"保存父块缓存失败: {e}")


# ==================== 工厂函数 ====================

_parent_child_store: Optional[ParentChildVectorStore] = None


def get_parent_child_store() -> ParentChildVectorStore:
    """获取 Small-to-Big 向量存储单例"""
    global _parent_child_store
    if _parent_child_store is None:
        _parent_child_store = ParentChildVectorStore()
    return _parent_child_store