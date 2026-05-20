"""Unified result exporter — replaces old export_baseline.py."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cache import ExperimentCache
from .data_accessor import ExperimentDataAccessor

logger = logging.getLogger(__name__)


class ResultExporter:
    """Export session data: layer reports JSON + RAG knowledge + planning text."""

    def __init__(self, cache: ExperimentCache):
        self.data_accessor = ExperimentDataAccessor(cache)

    async def export_session(
        self,
        session_id: str,
        output_dir: Path,
        project_name: str = "village_planning",
        layers: Optional[List[int]] = None,
        include_rag: bool = True,
        include_planning_text: bool = True,
    ) -> Path:
        """Full export: layer reports + RAG knowledge + planning text."""
        output_dir.mkdir(parents=True, exist_ok=True)
        target_layers = layers or [1, 2, 3]

        for layer in target_layers:
            reports = await self.data_accessor.get_reports(session_id, [layer])
            layer_path = output_dir / f"layer{layer}_reports.json"
            layer_path.write_text(
                json.dumps(
                    {"session_id": session_id, "layer": layer, "reports": reports},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.info("[Exporter] Layer %d: %d reports → %s", layer, len(reports), layer_path)

        if include_rag:
            await self._export_rag_knowledge(session_id, output_dir)

        if include_planning_text:
            try:
                from .runner import ExperimentRunner
                from .config import ExperimentConfig

                config = ExperimentConfig.default()
                runner = ExperimentRunner.__new__(ExperimentRunner)
                runner.config = config
                runner.cache = ExperimentCache(config.cache_dir)
                runner.data_accessor = self.data_accessor
                await runner.generate_planning_text(session_id, output_dir, project_name)
            except Exception as e:
                logger.warning("[Exporter] Planning text skipped: %s", e)

        summary = {
            "session_id": session_id,
            "exported_at": datetime.now().isoformat(),
            "layers": target_layers,
            "output_dir": str(output_dir),
        }
        summary_path = output_dir / "export_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("[Exporter] Session %s exported to %s", session_id, output_dir)
        return output_dir

    async def _export_rag_knowledge(self, session_id: str, output_dir: Path) -> None:
        """Export RAG knowledge sources per layer."""
        rag_entries: Dict[str, Any] = {}
        for layer in [1, 2, 3]:
            try:
                with_sources = await self.data_accessor.get_reports_with_sources(session_id, layer)
                if with_sources:
                    rag_entries[f"layer{layer}"] = with_sources
            except Exception as e:
                logger.warning("[Exporter] RAG L%d skipped: %s", layer, e)

        if rag_entries:
            rag_path = output_dir / "rag_knowledge.json"
            rag_path.write_text(
                json.dumps(rag_entries, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("[Exporter] RAG knowledge → %s", rag_path)

    def export_experiment_result(
        self,
        result: Any,
        output_dir: Path,
        filename: str = "experiment_result.json",
    ) -> Path:
        """Export experiment result as JSON + Markdown summary."""
        output_dir.mkdir(parents=True, exist_ok=True)

        result_path = output_dir / filename
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

        md_path = output_dir / "experiment_summary.md"
        lines = ["# Experiment Summary\n"]
        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, dict):
                    lines.append(f"## {key}\n")
                    for k, v in value.items():
                        lines.append(f"- **{k}**: {v}")
                    lines.append("")
                else:
                    lines.append(f"- **{key}**: {value}")
        md_path.write_text("\n".join(lines), encoding="utf-8")

        logger.info("[Exporter] Result → %s", result_path)
        return result_path