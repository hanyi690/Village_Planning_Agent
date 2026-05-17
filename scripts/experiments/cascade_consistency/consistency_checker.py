"""
Consistency Checker - Semantic consistency validation
一致性检验器 - 语义一致性验证

检验方法：
1. 反馈响应度：检验修订内容是否响应了反馈意见
2. 语义对齐度：使用Embedding计算目标维度与下游维度的语义相似度
3. 关键词覆盖率：检验期望关键词是否出现在修订内容中（补充）

Usage:
    from scripts.experiments.cascade_consistency.consistency_checker import ConsistencyChecker

    checker = ConsistencyChecker()
    score = checker.check_feedback_response(old, new, feedback, keywords)
"""

import re
import hashlib
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyResult:
    """一致性检验结果"""
    dimension_key: str
    score: float
    embedding_similarity: float = 0.0
    keyword_coverage: float = 0.0
    content_change: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class EmbeddingProvider:
    """Embedding服务封装 - 支持校准和缓存"""

    # 默认归一化参数（可基于实际数据调整）
    DEFAULT_OFFSET = 0.3
    DEFAULT_SCALE = 0.7

    def __init__(self, provider_type: str = "aliyun",
                 offset: float = None, scale: float = None):
        """
        初始化Embedding服务

        Args:
            provider_type: 服务类型 ("aliyun" | "local")
            offset: 归一化偏移量（默认0.3）
            scale: 归一化缩放因子（默认0.7）
        """
        self.provider_type = provider_type
        self.offset = offset or self.DEFAULT_OFFSET
        self.scale = scale or self.DEFAULT_SCALE
        self._client = None
        self._cache: Dict[str, np.ndarray] = {}  # 文本hash -> embedding

    def calibrate(self, sample_pairs: List[tuple],
                  expected_scores: List[float] = None) -> None:
        """基于样本对校准归一化参数

        Args:
            sample_pairs: [(text1, text2), ...] 样本对列表
            expected_scores: 预期相似度（可选，用于回归校准）
        """
        if not sample_pairs:
            return

        try:
            embeddings = self.embed([t for pair in sample_pairs for t in pair])
            raw_sims = []

            for i in range(0, len(embeddings), 2):
                sim = np.dot(embeddings[i], embeddings[i+1]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i+1])
                )
                raw_sims.append(sim)

            # 使用中位数作为偏移量
            self.offset = float(np.median(raw_sims))
            self.scale = 1 - self.offset

            logger.info(f"[Embedding] Calibrated: offset={self.offset:.3f}, scale={self.scale:.3f}")

        except Exception as e:
            logger.warning(f"[Embedding] Calibration failed: {e}")

    def _init_client(self):
        """延迟初始化客户端"""
        if self._client is not None:
            return

        if self.provider_type == "aliyun":
            try:
                import sys
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "backend"))
                from app.services.modules.rag.vector_store import AliyunEmbeddings
                from app.core.settings import DASHSCOPE_API_KEY

                self._client = AliyunEmbeddings(
                    api_key=DASHSCOPE_API_KEY,
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model="text-embedding-v4",
                )
            except Exception as e:
                logger.warning(f"Failed to init AliyunEmbeddings: {e}")
                self._client = None
        else:
            # 本地模型（备用）
            try:
                from sentence_transformers import SentenceTransformer
                self._client = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            except Exception as e:
                logger.warning(f"Failed to init local model: {e}")
                self._client = None

    def embed(self, texts: List[str]) -> np.ndarray:
        """生成Embedding向量（带缓存）"""
        self._init_client()

        if self._client is None:
            # 返回零向量作为fallback
            return np.zeros((len(texts), 768))

        results = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            text_hash = hashlib.md5(text.encode()).hexdigest()
            if text_hash in self._cache:
                results.append((i, self._cache[text_hash]))
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        # 批量获取未缓存的embedding
        if uncached_texts:
            if self.provider_type == "aliyun":
                new_embeddings = self._client.embed_documents(uncached_texts)
            else:
                new_embeddings = self._client.encode(uncached_texts)

            for j, (text, emb) in enumerate(zip(uncached_texts, new_embeddings)):
                text_hash = hashlib.md5(text.encode()).hexdigest()
                self._cache[text_hash] = np.array(emb)
                results.append((uncached_indices[j], self._cache[text_hash]))

        # 按原始顺序返回
        results.sort(key=lambda x: x[0])
        return np.array([r[1] for r in results])

    def similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算余弦相似度（使用校准参数）"""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        cosine_sim = dot_product / (norm1 * norm2)

        # 使用校准参数归一化到0-1范围
        normalized = max(0, (cosine_sim - self.offset) / self.scale)
        return min(normalized, 1.0)

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
        logger.info("[Embedding] Cache cleared")


class ConsistencyChecker:
    """一致性检验器 - 支持Embedding语义相似度"""

    # 语义对齐关键词映射（作为补充）
    ALIGNMENT_KEYWORDS = {
        "planning_positioning": {
            "development_orientation": ["生态保育", "渐进式发展", "微改造"],
            "population_scale": ["500人", "小规模"],
            "industry_planning": ["特色南药", "林下经济", "客家文化"],
        },
        "natural_environment": {
            "disaster_prevention": ["地质灾害", "隐患点", "风险评估"],
            "ecological": ["生态保护", "生态红线"],
        },
        "resource_endowment": {
            "planning_positioning": ["资源禀赋", "发展定位"],
            "development_goals": ["发展目标", "规划策略"],
        },
    }

    def __init__(self, embedding_provider: EmbeddingProvider = None):
        """
        初始化检验器

        Args:
            embedding_provider: Embedding服务实例
        """
        self.embedding_provider = embedding_provider or EmbeddingProvider()

    def check_feedback_response(
        self,
        old_content: str,
        new_content: str,
        feedback: str,
        keywords: Dict[str, List[str]],
    ) -> float:
        """
        检验反馈响应度

        评分规则：
        1. 正向关键词覆盖率（期望出现的关键词）
        2. 负向关键词清除率（期望移除的关键词）
        3. 内容变化度（确保有实质性修改）

        Args:
            old_content: 修订前内容
            new_content: 修订后内容
            feedback: 反馈意见
            keywords: {"positive": [...], "negative": [...]}

        Returns:
            响应度评分 (0-1)
        """
        if not new_content:
            return 0.0

        positive_kw = keywords.get("positive", [])
        negative_kw = keywords.get("negative", [])

        # 1. 正向关键词覆盖率
        positive_found = sum(1 for kw in positive_kw if kw in new_content)
        positive_coverage = positive_found / len(positive_kw) if positive_kw else 0.5

        # 2. 负向关键词清除率
        negative_in_old = sum(1 for kw in negative_kw if kw in old_content)
        negative_in_new = sum(1 for kw in negative_kw if kw in new_content)
        if negative_in_old > 0:
            negative_removal = 1 - (negative_in_new / negative_in_old)
        else:
            negative_removal = 1.0 if negative_in_new == 0 else 0.5

        # 3. 内容变化度
        content_changed = self._calculate_content_change(old_content, new_content)

        # 综合评分
        score = (
            positive_coverage * 0.5 +
            negative_removal * 0.3 +
            content_changed * 0.2
        )

        return min(score, 1.0)

    def check_semantic_alignment(
        self,
        target_content: str,
        downstream_content: str,
        downstream_dim: str,
        use_embedding: bool = True,
    ) -> ConsistencyResult:
        """检验语义对齐度

        使用Embedding计算目标维度与下游维度的语义相似度

        Args:
            target_content: 目标维度修订后内容
            downstream_content: 下游维度修订后内容
            downstream_dim: 下游维度key
            use_embedding: 是否使用Embedding（默认True）

        Returns:
            一致性检验结果
        """
        if not downstream_content:
            return ConsistencyResult(
                dimension_key=downstream_dim,
                score=0.0,
                details={"error": "下游维度内容为空"},
            )

        embedding_similarity = None  # 使用None标记失败
        keyword_coverage = 0.0
        details = {
            "embedding_weight": 0.7,
            "keyword_weight": 0.3,
        }

        # 1. Embedding语义相似度（权重70%）
        if use_embedding:
            try:
                embeddings = self.embedding_provider.embed([target_content, downstream_content])
                embedding_similarity = self.embedding_provider.similarity(embeddings[0], embeddings[1])
            except Exception as e:
                # 记录失败信息
                logger.warning(f"[Consistency] Embedding failed for {downstream_dim}: {e}")
                details["embedding_failed"] = True
                details["embedding_error"] = str(e)

        # 2. 关键词覆盖率（权重30%，作为补充）
        keyword_coverage = self._check_keyword_alignment(target_content, downstream_content, downstream_dim)

        # 3. 混合评分（失败时仅使用关键词）
        if embedding_similarity is None:
            score = keyword_coverage  # 退化为纯关键词
            details["fallback_to_keyword"] = True
        else:
            score = embedding_similarity * 0.7 + keyword_coverage * 0.3

        return ConsistencyResult(
            dimension_key=downstream_dim,
            score=score,
            embedding_similarity=embedding_similarity or 0.0,
            keyword_coverage=keyword_coverage,
            details=details,
        )

    def _calculate_content_change(self, old: str, new: str) -> float:
        """计算内容变化度"""
        if not old and not new:
            return 0.0
        if not old:
            return 1.0
        if not new:
            return 0.0

        # 使用SequenceMatcher计算相似度
        similarity = SequenceMatcher(None, old, new).ratio()
        change = 1 - similarity

        # 变化度归一化：太小（<0.1）视为无实质修改，太大（>0.8）视为重写
        if change < 0.1:
            return 0.3  # 轻微修改
        elif change > 0.8:
            return 1.0  # 重写
        else:
            return change

    def _check_keyword_alignment(self, target: str, downstream: str, downstream_dim: str) -> float:
        """检查关键词对齐度（作为补充）"""
        # 查找关键词映射
        expected_keywords = []
        for target_dim, downstream_map in self.ALIGNMENT_KEYWORDS.items():
            if downstream_dim in downstream_map:
                expected_keywords = downstream_map[downstream_dim]
                break

        if not expected_keywords:
            # 无映射关系，使用通用对齐检验
            return self._check_general_alignment(target, downstream)

        # 检查期望关键词是否出现
        found = sum(1 for kw in expected_keywords if kw in downstream)
        return found / len(expected_keywords)

    def _check_general_alignment(self, target: str, downstream: str) -> float:
        """通用对齐检验（无关键词映射时使用）"""
        # 提取目标内容的关键短语（2-4字的中文短语）
        target_phrases = re.findall(r'[一-龥]{2,4}', target)
        if not target_phrases:
            return 0.5

        # 统计在下游内容中出现的比例
        # 只检查高频短语（出现次数>=2）
        phrase_counts = {}
        for phrase in target_phrases:
            phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

        frequent_phrases = [p for p, c in phrase_counts.items() if c >= 2]

        if not frequent_phrases:
            return 0.5

        found = sum(1 for p in frequent_phrases if p in downstream)
        return found / len(frequent_phrases)

    def check_keyword_coverage(
        self,
        content: str,
        expected_keywords: List[str],
        forbidden_keywords: List[str] = None,
    ) -> ConsistencyResult:
        """
        检验关键词覆盖率

        Args:
            content: 待检验内容
            expected_keywords: 期望出现的关键词
            forbidden_keywords: 禁止出现的关键词

        Returns:
            检验结果
        """
        forbidden_keywords = forbidden_keywords or []

        # 期望关键词覆盖率
        expected_found = [kw for kw in expected_keywords if kw in content]
        expected_coverage = len(expected_found) / len(expected_keywords) if expected_keywords else 1.0

        # 禁止关键词残留
        forbidden_found = [kw for kw in forbidden_keywords if kw in content]
        forbidden_residual = len(forbidden_found) / len(forbidden_keywords) if forbidden_keywords else 0.0

        # 综合评分
        score = expected_coverage * (1 - forbidden_residual)

        return ConsistencyResult(
            dimension_key="",
            score=score,
            keyword_coverage=expected_coverage,
            details={
                "expected_found": expected_found,
                "forbidden_found": forbidden_found,
            },
        )


def check_semantic_alignment(
    target_content: str,
    downstream_content: str,
    downstream_dim: str,
) -> float:
    """便捷函数：检验语义对齐度

    Returns:
        一致性评分 (0-1)
    """
    checker = ConsistencyChecker()
    result = checker.check_semantic_alignment(target_content, downstream_content, downstream_dim)
    return result.score


if __name__ == "__main__":
    # 测试
    checker = ConsistencyChecker()

    # 测试反馈响应度
    old = "规划定位为打造大型旅游景区，发展商业旅游经济。"
    new = "规划定位转向生态保育优先，采用渐进式发展路径，实施客家文化微改造。"
    feedback = "应转向生态保育优先的发展路径"
    keywords = {
        "positive": ["生态保育", "渐进式发展", "微改造"],
        "negative": ["大规模旅游", "商业开发"],
    }

    score = checker.check_feedback_response(old, new, feedback, keywords)
    print(f"反馈响应度: {score:.2%}")

    # 测试语义对齐度
    target = "规划定位转向生态保育优先，渐进式发展。"
    downstream = "产业发展以特色南药和林下经济为主，结合客家文化微改造。"

    alignment = checker.check_semantic_alignment(target, downstream, "industry_planning")
    print(f"语义对齐度: {alignment:.2%}")