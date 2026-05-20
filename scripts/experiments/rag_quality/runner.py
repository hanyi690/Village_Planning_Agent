"""RAG quality runner — 4-group RAG experiment with text quality metrics."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..framework.cache import ExperimentCache
from ..framework.config import ExperimentConfig
from ..framework.data_accessor import ExperimentDataAccessor
from ..framework.metrics import MetricsSuite
from ..framework.runner import ExperimentRunner

logger = logging.getLogger(__name__)


class RAGQualityRunner(ExperimentRunner):
    """Runs a single RAG group experiment.

    Flow:
    1. Generate or load cached reports for the given RAG config
    2. Evaluate text quality (faithfulness + depth) and citation quality
    3. Save results

    Use ParallelExperimentScheduler to run multiple groups concurrently.
    """

    def __init__(
        self,
        config: ExperimentConfig,
        group_name: str,
        iteration: int = 0,
    ):
        super().__init__(config)
        self.group_name = group_name
        self.iteration = iteration
        self.metrics = MetricsSuite()
        self._rag_config = config.rag_groups.get(group_name, {1: True, 2: True, 3: True})
        self._cached_knowledge: Dict[str, Any] = {}

    async def run(self) -> Dict[str, Any]:
        """Execute RAG quality experiment for one group."""
        tag = f"rag_{self.group_name}_iter{self.iteration}"
        session_id = self.new_session_id(tag)

        logger.info(
            "[RAG] Starting %s iter%d: RAG config=%s",
            self.group_name, self.iteration, self._rag_config,
        )

        # 1. Get reports (cached or fresh)
        reports, from_cache = await self._get_reports(session_id)

        # 2. Evaluate metrics
        metrics_result = await self._evaluate_metrics(reports)

        # 3. Save results
        output_dir = self.config.output_dir / self.group_name / f"iter{self.iteration}"
        output_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "group_name": self.group_name,
            "iteration": self.iteration,
            "session_id": session_id,
            "rag_config": self._rag_config,
            "from_cache": from_cache,
            "metrics": metrics_result,
            "generated_at": __import__("datetime").datetime.now().isoformat(),
        }

        result_path = output_dir / "rag_result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # Save reports separately for easy reuse
        reports_path = output_dir / "reports.json"
        reports_path.write_text(
            json.dumps(
                {"session_id": session_id, "group": self.group_name, "reports": reports},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

        # Generate planning text
        try:
            await self.generate_planning_text(
                session_id, output_dir,
                f"金田村_{self.group_name}_iter{self.iteration}",
            )
        except Exception as e:
            logger.warning("[RAG] Planning text skipped: %s", e)

        logger.info(
            "[RAG] %s iter%d done: avg_faithfulness=%.3f, avg_depth=%.3f",
            self.group_name, self.iteration,
            metrics_result.get("summary", {}).get("avg_faithfulness", 0),
            metrics_result.get("summary", {}).get("avg_depth", 0),
        )
        return result

    # ---- report generation ----

    async def _get_reports(self, session_id: str) -> tuple[Dict[str, str], bool]:
        """Get reports from cache or run planning graph."""
        # Check ExperimentCache
        cache_key = self.cache.key_for(
            "rag", f"{self.group_name}_iter{self.iteration}",
        )
        cached = self.cache.load(cache_key)
        if cached and self.config.use_cache:
            reports = cached.get("reports", {})
            self._cached_knowledge = cached.get("injected_knowledge", {})
            if reports:
                logger.info("[RAG] Cache hit: %s", cache_key)
                return reports, True

        # Run fresh
        reports = await self.run_planning_graph(
            session_id=session_id,
            project_name=f"金田村_{self.group_name.upper()}",
            rag_config=self._rag_config,
        )

        # Cache reports + knowledge
        self.cache.save(cache_key, {
            "session_id": session_id,
            "group": self.group_name,
            "iteration": self.iteration,
            "rag_config": self._rag_config,
            "reports": reports,
            "injected_knowledge": self._cached_knowledge,
        })

        return reports, False

    # ---- metrics evaluation ----

    async def _evaluate_metrics(self, reports: Dict[str, str]) -> Dict[str, Any]:
        """Evaluate text quality + citation quality for all dimensions."""
        from app.config.loader import get_layer_dimensions, get_dimension_name

        l1_dims = get_layer_dimensions(1)
        l3_dims = get_layer_dimensions(3)
        eval_dims = l1_dims + l3_dims
        dim_names = {d: get_dimension_name(d) for d in eval_dims}

        metrics = {"dimensions": {}, "summary": {}}
        total_faithfulness = []
        total_depth = []
        total_citations = []

        for dim_key in eval_dims:
            content = reports.get(dim_key, "")
            if not content:
                continue

            # Faithfulness — use cached RAG knowledge as context
            kb_context = self._get_kb_context(dim_key, content)
            faithfulness = await self.metrics.evaluate_text_quality(
                content, kb_context, dim_key,
            )

            # Citation quality
            citation = self.metrics.evaluate_citation_quality(content, dim_key)

            dim_metrics = {
                "text_length": len(content),
                "faithfulness": faithfulness.get("faithfulness_score", 0),
                "depth_score": faithfulness.get("depth_score", 0),
                "total_citations": citation.get("total_citations", 0),
                "existence_rate": citation.get("existence_rate", 0),
                "supportive_rate": citation.get("supportive_rate", 0),
            }
            metrics["dimensions"][dim_key] = dim_metrics

            total_faithfulness.append(dim_metrics["faithfulness"])
            total_depth.append(dim_metrics["depth_score"])
            total_citations.append(dim_metrics["total_citations"])

        if total_faithfulness:
            metrics["summary"] = {
                "avg_faithfulness": sum(total_faithfulness) / len(total_faithfulness),
                "avg_depth": sum(total_depth) / len(total_depth),
                "total_citations": sum(total_citations),
            }

        return metrics

    def _get_kb_context(self, dim_key: str, content: str) -> str:
        """Get knowledge base context for faithfulness evaluation."""
        dim_know = self._cached_knowledge.get("dimension_knowledge", {}).get(dim_key, {})
        snippets = dim_know.get("snippets", [])
        if snippets:
            return " ".join(snippets)
        return content[:500]