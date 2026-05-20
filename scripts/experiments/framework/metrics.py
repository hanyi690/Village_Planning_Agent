"""Unified metrics suite — lazy-loading facade over experiment-specific metrics."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MetricsSuite:
    """Single entry point for all experiment metrics.

    Lazily imports heavy modules (embedding models, etc.) only when needed.
    """

    def __init__(self):
        self._text_quality = None
        self._citation_quality = None
        self._consistency = None

    # ---- text quality (RAG experiment) ----

    async def evaluate_text_quality(
        self,
        text: str,
        context: str,
        dim_key: str,
    ) -> Dict[str, Any]:
        """Evaluate faithfulness + content depth."""
        if self._text_quality is None:
            from scripts.experiments.rag_text_quality.text_quality_metrics import TextQualityMetrics
            self._text_quality = TextQualityMetrics()
        return await self._text_quality.evaluate(text, context, dim_key)

    # ---- citation quality (RAG experiment) ----

    def evaluate_citation_quality(
        self,
        text: str,
        dim_key: str,
    ) -> Dict[str, Any]:
        """Evaluate citation quality in a report."""
        if self._citation_quality is None:
            from scripts.experiments.rag_text_quality.citation_quality import CitationQualityEvaluator
            self._citation_quality = CitationQualityEvaluator()
        return self._citation_quality.evaluate(text, dim_key)

    # ---- consistency (cascade experiment) ----

    def check_consistency(
        self,
        old_text: str,
        new_text: str,
        feedback: str,
        keywords: Dict[str, List[str]],
    ) -> float:
        """Check cascade consistency between old and new reports."""
        if self._consistency is None:
            from scripts.experiments.cascade.consistency_checker import ConsistencyChecker
            self._consistency = ConsistencyChecker()
        return self._consistency.check(old_text, new_text, feedback, keywords)

    def check_consistency_detailed(
        self,
        old_text: str,
        new_text: str,
        feedback: str,
        keywords: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """Detailed consistency check with per-keyword breakdown."""
        if self._consistency is None:
            from scripts.experiments.cascade.consistency_checker import ConsistencyChecker
            self._consistency = ConsistencyChecker()
        return self._consistency.check_detailed(old_text, new_text, feedback, keywords)

    def check_feedback_response(
        self,
        old_text: str,
        new_text: str,
        feedback: str,
        keywords: Dict[str, List[str]],
    ) -> float:
        """Check feedback response for target dimension.

        Args:
            old_text: Baseline content
            new_text: Revised content
            feedback: Feedback text
            keywords: {"positive": [...], "negative": [...]}

        Returns:
            Response score (0-1)
        """
        if self._consistency is None:
            from scripts.experiments.cascade.consistency_checker import ConsistencyChecker
            self._consistency = ConsistencyChecker()
        return self._consistency.check_feedback_response(old_text, new_text, feedback, keywords)

    def check_semantic_alignment(
        self,
        target_content: str,
        downstream_content: str,
        downstream_dim: str,
    ) -> float:
        """Check semantic alignment between target and downstream dimension.

        Args:
            target_content: Revised target dimension content
            downstream_content: Revised downstream dimension content
            downstream_dim: Downstream dimension key

        Returns:
            Alignment score (0-1)
        """
        if self._consistency is None:
            from scripts.experiments.cascade.consistency_checker import ConsistencyChecker
            self._consistency = ConsistencyChecker()
        result = self._consistency.check_semantic_alignment(
            target_content, downstream_content, downstream_dim
        )
        return result.score