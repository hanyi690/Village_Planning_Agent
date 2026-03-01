"""
向量数据库缓存管理器
基于 references/agent_skills 的 Context Optimization 最佳实践

核心功能：
1. Embedding 模型缓存（进程级单例）
2. 向量数据库连接缓存
3. 查询结果缓存（可选，使用 LRU 策略）
"""
import hashlib
import pickle
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.rag.config import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    EMBEDDING_MODEL_NAME,
    setup_huggingface_env,
)


class VectorStoreCache:
    """
    向量数据库缓存管理器

    功能：
    1. Embedding 模型缓存（进程级单例）
    2. 向量数据库连接缓存
    3. 查询结果缓存（可选）

    使用场景：
    - 减少 Embedding 模型重复加载
    - 加速向量数据库查询
    - 缓存常见查询结果
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        enable_query_cache: bool = True,
        cache_ttl: int = 3600  # 缓存有效期（秒），默认 1 小时
    ):
        """
        初始化缓存管理器

        Args:
            cache_dir: 缓存目录，默认使用 knowledge_base/cache
            enable_query_cache: 是否启用查询结果缓存
            cache_ttl: 缓存有效期（秒）
        """
        self.cache_dir = cache_dir or (CHROMA_PERSIST_DIR / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.enable_query_cache = enable_query_cache
        self.cache_ttl = cache_ttl

        # 缓存实例
        self._embedding_model = None
        self._vectorstore = None
        self._query_cache = {}  # 内存缓存：{query_hash: (result, timestamp)}
        self._cache_metadata = {}  # 缓存元数据：{query_hash: timestamp}

        print(f"✅ 缓存管理器初始化完成（目录: {self.cache_dir}）")

    def get_embedding_model(self):
        """
        懒加载并缓存 Embedding 模型

        Returns:
            HuggingFaceEmbeddings 实例
        """
        if self._embedding_model is None:
            # 配置 HuggingFace 环境（离线模式/镜像站点）
            setup_huggingface_env()

            from langchain_huggingface import HuggingFaceEmbeddings

            print("📥 正在加载 Embedding 模型...")
            self._embedding_model = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL_NAME,
                encode_kwargs={"normalize_embeddings": True},
            )
            print(f"✅ Embedding 模型已缓存: {EMBEDDING_MODEL_NAME}")

        return self._embedding_model

    def get_vectorstore(self):
        """
        懒加载并缓存向量数据库

        Returns:
            Chroma 向量数据库实例
        """
        if self._vectorstore is None:
            from langchain_chroma import Chroma

            print("📥 正在连接向量数据库...")
            self._vectorstore = Chroma(
                persist_directory=str(CHROMA_PERSIST_DIR),
                embedding_function=self.get_embedding_model(),
                collection_name=CHROMA_COLLECTION_NAME,
            )
            print(f"✅ 向量数据库已缓存: {CHROMA_COLLECTION_NAME}")

        return self._vectorstore

    def cache_query_result(
        self,
        query: str,
        results: list,
        context_params: dict = None
    ) -> None:
        """
        缓存查询结果

        Args:
            query: 查询字符串
            results: 查询结果列表
            context_params: 上下文参数（如 top_k, context_mode）
        """
        if not self.enable_query_cache:
            return

        # 生成缓存键（包含查询和参数）
        cache_key = self._generate_cache_key(query, context_params)
        timestamp = datetime.now()

        # 内存缓存
        self._query_cache[cache_key] = (results, timestamp)

        # 持久化缓存（可选）
        cache_file = self.cache_dir / f"query_{cache_key}.pkl"
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump({
                    'results': results,
                    'timestamp': timestamp,
                    'query': query,
                    'params': context_params
                }, f)
        except Exception as e:
            print(f"⚠️  持久化缓存失败: {e}")

    def get_cached_query(
        self,
        query: str,
        context_params: dict = None
    ) -> Optional[list]:
        """
        获取缓存的查询结果

        Args:
            query: 查询字符串
            context_params: 上下文参数

        Returns:
            缓存的查询结果，如果不存在或已过期则返回 None
        """
        if not self.enable_query_cache:
            return None

        cache_key = self._generate_cache_key(query, context_params)

        # 先检查内存缓存
        if cache_key in self._query_cache:
            results, timestamp = self._query_cache[cache_key]

            # 检查是否过期
            if datetime.now() - timestamp < timedelta(seconds=self.cache_ttl):
                print(f"🎯 内存缓存命中: {query[:50]}...")
                return results
            else:
                # 过期，删除缓存
                del self._query_cache[cache_key]

        # 检查持久化缓存
        cache_file = self.cache_dir / f"query_{cache_key}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    cached_data = pickle.load(f)

                # 检查是否过期
                cache_time = cached_data['timestamp']
                if datetime.now() - cache_time < timedelta(seconds=self.cache_ttl):
                    print(f"🎯 持久化缓存命中: {query[:50]}...")
                    # 加载到内存缓存
                    self._query_cache[cache_key] = (
                        cached_data['results'],
                        cache_time
                    )
                    return cached_data['results']
                else:
                    # 过期，删除缓存文件
                    cache_file.unlink()
            except Exception as e:
                print(f"⚠️  读取持久化缓存失败: {e}")

        return None

    def _generate_cache_key(self, query: str, params: dict = None) -> str:
        """
        生成缓存键

        Args:
            query: 查询字符串
            params: 上下文参数

        Returns:
            MD5 哈希值（8 位）
        """
        # 将参数标准化
        if params is None:
            params = {}

        # 生成哈希输入
        hash_input = f"{query}_{sorted(params.items())}"

        # 返回 MD5 哈希的前 8 位
        return hashlib.md5(hash_input.encode()).hexdigest()[:8]

    def clear_cache(self, older_than: int = None) -> int:
        """
        清理缓存

        Args:
            older_than: 清理早于 N 秒的缓存，None 表示清理全部

        Returns:
            清理的缓存数量
        """
        count = 0
        current_time = datetime.now()

        # 清理内存缓存
        if older_than is None:
            count = len(self._query_cache)
            self._query_cache.clear()
        else:
            expired_keys = [
                key for key, (_, timestamp) in self._query_cache.items()
                if (current_time - timestamp).total_seconds() > older_than
            ]
            for key in expired_keys:
                del self._query_cache[key]
                count += 1

        # 清理持久化缓存
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("query_*.pkl"):
                try:
                    if older_than is None:
                        cache_file.unlink()
                        count += 1
                    else:
                        # 检查文件修改时间
                        file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                        if (current_time - file_time).total_seconds() > older_than:
                            cache_file.unlink()
                            count += 1
                except Exception as e:
                    print(f"⚠️  删除缓存文件失败: {e}")

        print(f"🧹 清理了 {count} 个缓存项")
        return count

    def get_cache_stats(self) -> dict:
        """
        获取缓存统计信息

        Returns:
            包含缓存统计的字典
        """
        # 统计持久化缓存文件
        persistent_cache_count = 0
        persistent_cache_size = 0
        if self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("query_*.pkl"):
                persistent_cache_count += 1
                persistent_cache_size += cache_file.stat().st_size

        return {
            "memory_cache_count": len(self._query_cache),
            "persistent_cache_count": persistent_cache_count,
            "persistent_cache_size_mb": round(persistent_cache_size / 1024 / 1024, 2),
            "cache_dir": str(self.cache_dir),
            "query_cache_enabled": self.enable_query_cache,
            "cache_ttl_seconds": self.cache_ttl
        }


# 全局缓存实例
_vector_cache = None


def get_vector_cache() -> VectorStoreCache:
    """
    获取全局向量缓存实例

    Returns:
        VectorStoreCache 单例
    """
    global _vector_cache
    if _vector_cache is None:
        _vector_cache = VectorStoreCache()
    return _vector_cache


if __name__ == "__main__":
    # 测试代码
    print("测试 VectorStoreCache")
    cache = VectorStoreCache()

    # 测试缓存统计
    stats = cache.get_cache_stats()
    print(f"\n缓存统计：")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 测试清理缓存（清理早于 1 小时的缓存）
    cache.clear_cache(older_than=3600)
