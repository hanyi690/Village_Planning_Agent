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
        reuse_baseline: bool = False,
        baseline_session_id: Optional[str] = None,
    ):
        super().__init__(config)
        self.group_name = group_name
        self.iteration = iteration
        self.reuse_baseline = reuse_baseline
        self.baseline_session_id = baseline_session_id
        self.metrics = MetricsSuite()
        self._rag_config = config.rag_groups.get(group_name, {1: True, 2: True, 3: True})
        self._cached_knowledge: Dict[str, Any] = {}

    async def run(self) -> Dict[str, Any]:
        """Execute RAG quality experiment for one group."""
        tag = f"rag_{self.group_name}_iter{self.iteration}"
        session_id = self.new_session_id(tag)

        logger.info(
            "[RAG] Starting %s iter%d: session=%s RAG config=%s",
            self.group_name, self.iteration, session_id, self._rag_config,
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

        # Export full content similar to baseline folder
        await self._export_full_content(session_id, output_dir, reports)

        logger.info(
            "[RAG] %s iter%d done: avg_faithfulness=%.3f, avg_depth=%.3f",
            self.group_name, self.iteration,
            metrics_result.get("summary", {}).get("avg_faithfulness", 0),
            metrics_result.get("summary", {}).get("avg_depth", 0),
        )
        return result

    # ---- report generation ----

    async def _get_reports(self, session_id: str) -> tuple[Dict[str, str], bool]:
        """Get reports from cache, baseline, or run planning graph."""
        # If reuse_baseline, load from baseline session instead of running
        if self.reuse_baseline and self.baseline_session_id:
            reports = await self._load_baseline_reports()
            if reports:
                logger.info(
                    "[RAG] Reused baseline reports for %s iter%d",
                    self.group_name, self.iteration,
                )
                return reports, True

        # Check RAG-specific cache (contains rag_config + injected_knowledge)
        rag_cache_key = self.cache.key_for(
            "rag", f"{self.group_name}_iter{self.iteration}",
        )
        rag_cached = self.cache.load(rag_cache_key)
        if rag_cached and self.config.use_cache:
            self._cached_knowledge = rag_cached.get("injected_knowledge", {})
            # Get reports from data_accessor (which has its own cache)
            reports = await self.data_accessor.get_reports(session_id)
            if reports:
                logger.info("[RAG] Cache hit: %s", rag_cache_key)
                return reports, True

        # Run fresh
        reports = await self.run_planning_graph(
            session_id=session_id,
            project_name=f"金田村_{self.group_name.upper()}",
            rag_config=self._rag_config,
        )

        # Cache only RAG-specific metadata (reports are cached by data_accessor)
        self.cache.save(rag_cache_key, {
            "session_id": session_id,
            "group": self.group_name,
            "iteration": self.iteration,
            "rag_config": self._rag_config,
            "injected_knowledge": self._cached_knowledge,
        })

        return reports, False

    async def _load_baseline_reports(self) -> Dict[str, str]:
        """Load reports from baseline session via database."""
        if not self.baseline_session_id:
            return {}

        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        reports = {}
        for layer in [1, 2, 3]:
            layer_reports = await store.get_layer_reports(self.baseline_session_id, layer)
            reports.update(layer_reports)

        # Also load knowledge sources
        for layer in [1, 2, 3]:
            with_sources = await store.get_layer_reports_with_sources(self.baseline_session_id, layer)
            for dim_key, data in with_sources.items():
                if data.get("knowledge_sources"):
                    self._cached_knowledge.setdefault("dimension_knowledge", {})
                    self._cached_knowledge["dimension_knowledge"][dim_key] = {
                        "snippets": data["knowledge_sources"]
                    }

        return reports

    # ---- full content export ----

    async def _export_full_content(
        self,
        session_id: str,
        output_dir: Path,
        reports: Dict[str, str],
    ) -> None:
        """Export full content: layer reports JSON + RAG knowledge + layer MD + planning text."""
        from app.agent.state import get_layer_dimensions, get_layer_name, LAYER_NAMES_BY_NUMBER
        from app.config.loader import get_dimension_name

        # 1. Export layer reports as separate JSON files
        for layer in [1, 2, 3]:
            dims = get_layer_dimensions(layer)
            layer_reports = {d: reports[d] for d in dims if d in reports}
            if layer_reports:
                layer_path = output_dir / f"layer{layer}_reports.json"
                layer_path.write_text(
                    json.dumps(
                        {"session_id": session_id, "layer": layer, "reports": layer_reports},
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
                logger.info("[RAG] Layer %d JSON: %s", layer, layer_path)

        # 2. Export RAG knowledge
        await self._export_rag_knowledge(session_id, output_dir)

        # 3. Export layer markdown documents
        for layer in [1, 2, 3]:
            dims = get_layer_dimensions(layer)
            layer_reports = {d: reports[d] for d in dims if d in reports}
            if layer_reports:
                layer_name = LAYER_NAMES_BY_NUMBER.get(layer, f"Layer{layer}")
                md_lines = [f"# {layer_name} 报告\n"]
                for dim_key, content in layer_reports.items():
                    try:
                        dim_name = get_dimension_name(dim_key)
                    except Exception:
                        dim_name = dim_key
                    md_lines.append(f"## {dim_name}\n")
                    md_lines.append(content)
                    md_lines.append("\n")
                md_path = output_dir / f"{layer_name}_报告.md"
                md_path.write_text("\n".join(md_lines), encoding="utf-8")
                logger.info("[RAG] Layer %d MD: %s", layer, md_path)

        # 4. Generate planning text
        try:
            await self.generate_planning_text(
                session_id, output_dir,
                f"金田村_{self.group_name}_iter{self.iteration}",
            )
        except Exception as e:
            logger.warning("[RAG] Planning text skipped: %s", e)

    async def _export_rag_knowledge(self, session_id: str, output_dir: Path) -> None:
        """Export RAG knowledge sources per layer."""
        rag_entries: Dict[str, Any] = {}
        for layer in [1, 2, 3]:
            try:
                with_sources = await self.data_accessor.get_reports_with_sources(session_id, layer)
                if with_sources:
                    rag_entries[f"layer{layer}"] = with_sources
            except Exception as e:
                logger.warning("[RAG] RAG knowledge L%d skipped: %s", layer, e)

        if rag_entries:
            rag_path = output_dir / "rag_knowledge.json"
            rag_path.write_text(
                json.dumps(rag_entries, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("[RAG] RAG knowledge: %s", rag_path)

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
            text_result = await self.metrics.evaluate_text_quality(
                content, kb_context, dim_key,
            )

            # Citation quality
            citation = self.metrics.evaluate_citation_quality(content, dim_key)

            # Extract values from dataclass objects
            faithfulness_score = (
                text_result.faithfulness.faithfulness_score
                if hasattr(text_result, 'faithfulness')
                else 0
            )
            depth_score = (
                text_result.content_depth_score
                if hasattr(text_result, 'content_depth_score')
                else 0
            )

            dim_metrics = {
                "text_length": len(content),
                "faithfulness": faithfulness_score,
                "depth_score": depth_score,
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