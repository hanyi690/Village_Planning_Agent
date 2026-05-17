"""
Experiment Dependencies - Dependency Injection Container
实验依赖注入容器

提供实验所需的各项服务的注入和回退机制。
"""

import logging
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class ExperimentDependencies:
    """实验依赖注入容器"""

    def __init__(self):
        self._embedding_provider = None
        self._rag_service = None
        self._settings = None

    def get_embedding_provider(self):
        """获取Embedding服务

        Returns:
            EmbeddingProvider实例，失败时返回Mock实现
        """
        if self._embedding_provider is not None:
            return self._embedding_provider

        # 尝试加载真实服务
        try:
            from scripts.experiments.cascade_consistency.consistency_checker import EmbeddingProvider
            self._embedding_provider = EmbeddingProvider(provider_type="aliyun")
            logger.info("[Dependencies] Loaded AliyunEmbeddingProvider")
            return self._embedding_provider
        except Exception as e:
            logger.warning(f"[Dependencies] Failed to load AliyunEmbeddingProvider: {e}")

        # 回退到Mock
        self._embedding_provider = MockEmbeddingProvider()
        logger.info("[Dependencies] Using MockEmbeddingProvider as fallback")
        return self._embedding_provider

    def get_rag_service(self):
        """获取RAG服务

        Returns:
            RAG服务实例，失败时返回None
        """
        if self._rag_service is not None:
            return self._rag_service

        try:
            from app.services.modules.rag.service import RAGService
            self._rag_service = RAGService()
            logger.info("[Dependencies] Loaded RAGService")
            return self._rag_service
        except Exception as e:
            logger.warning(f"[Dependencies] Failed to load RAGService: {e}")
            return None

    def get_settings(self) -> Optional[Dict[str, Any]]:
        """获取应用设置

        Returns:
            设置字典，失败时返回None
        """
        if self._settings is not None:
            return self._settings

        try:
            from app.core.settings import settings
            self._settings = {
                "dashscope_api_key": getattr(settings, "DASHSCOPE_API_KEY", ""),
                "rag_enabled": getattr(settings, "RAG_ENABLED", True),
            }
            return self._settings
        except Exception as e:
            logger.warning(f"[Dependencies] Failed to load settings: {e}")
            return None


class MockEmbeddingProvider:
    """Mock Embedding服务（用于测试和回退）"""

    def __init__(self, embedding_dim: int = 768):
        self.embedding_dim = embedding_dim

    def embed(self, texts: list) -> list:
        """返回零向量"""
        import numpy as np
        return [np.zeros(self.embedding_dim) for _ in texts]

    def similarity(self, vec1, vec2) -> float:
        """返回中性相似度"""
        return 0.5

    def calibrate(self, sample_pairs: list, expected_scores: list = None):
        """无操作"""
        pass

    def clear_cache(self):
        """无操作"""
        pass


# 全局依赖容器
_dependencies: Optional[ExperimentDependencies] = None


def get_dependencies() -> ExperimentDependencies:
    """获取全局依赖容器

    Returns:
        ExperimentDependencies实例
    """
    global _dependencies
    if _dependencies is None:
        _dependencies = ExperimentDependencies()
    return _dependencies


def reset_dependencies():
    """重置依赖容器（用于测试）"""
    global _dependencies
    _dependencies = None