"""Experiment runner base class — shared planning graph execution + baseline saving."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .cache import ExperimentCache
from .config import ExperimentConfig
from .data_accessor import ExperimentDataAccessor

logger = logging.getLogger(__name__)


class ExperimentRunner(ABC):
    """Abstract base for all experiment runners.

    Provides:
    - run_planning_graph(): execute full L1→L2→L3 planning via LangGraph
    - generate_planning_text(): produce MD/JSON output from reports
    - save_baseline(): persist reports + planning text for reuse
    - Subclass implements run() with experiment-specific logic.
    """

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.cache = ExperimentCache(config.cache_dir)
        self.data_accessor = ExperimentDataAccessor(self.cache)

    # ---- planning graph execution ----

    async def run_planning_graph(
        self,
        session_id: str,
        project_name: str,
        rag_config: Optional[Dict[int, bool]] = None,
        village_data: Optional[str] = None,
    ) -> Dict[str, str]:
        """Run full L1→L2→L3 planning graph, return {dim_key: content}.

        Uses in-process SSE listener to wait for each layer completion.
        """
        from app.services.runtime import PlanningRuntimeService
        from app.services.sse import sse_manager
        from app.utils.sse_publisher import SSEPublisher
        from app.agent.state import get_layer_dimensions, get_layer_name
        from scripts.experiments.sse_listener import InProcessEventListener

        await PlanningRuntimeService.ensure_initialized()

        initial_state = PlanningRuntimeService.build_initial_state(
            project_name=project_name,
            village_data=village_data or self.config.village.status_report,
            village_name=self.config.village.village_name,
            task_description=self.config.village.task_description,
            constraints=self.config.village.constraints,
            session_id=session_id,
            stream_mode=True,
            step_mode=False,
            rag_enabled=rag_config is not None,
            rag_layer_config=rag_config or {},
        )

        sse_manager.init_session(session_id, {
            "session_id": session_id,
            "project_name": project_name,
        })
        sse_manager.set_execution_active(session_id, True)

        listener = InProcessEventListener(session_id)
        await listener.connect()

        SSEPublisher.send_layer_start(
            session_id=session_id,
            layer=1,
            layer_name=get_layer_name(1),
            dimension_count=len(get_layer_dimensions(1)),
        )

        task = asyncio.create_task(
            PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
        )

        logger.info("[Runner] Planning execution started: %s", session_id)

        for layer in [1, 2, 3]:
            event = await listener.wait_for_any_event(
                event_types=[listener.EVENT_LAYER_COMPLETED, listener.EVENT_ERROR],
                timeout=900,
                filter_func=lambda e, l=layer: (
                    e.get("type") == "error"
                    or e.get("data", {}).get("layer") == l
                ),
            )
            if event.get("type") == "error":
                raise RuntimeError(
                    f"Layer {layer} failed: {event.get('data', {}).get('message', 'unknown')}"
                )
            logger.info("[Runner] Layer %d completed", layer)

        await task
        await listener.disconnect()

        reports = await self.data_accessor.get_reports(session_id)
        logger.info("[Runner] Retrieved %d reports for %s", len(reports), session_id)
        return reports

    # ---- planning text generation ----

    async def generate_planning_text(
        self,
        session_id: str,
        output_dir: Path,
        project_name: str,
        **kwargs: Any,
    ) -> Any:
        """Generate planning text (MD + JSON) from reports."""
        from app.services.modules.planning_text import PlanningTextConfig, PlanningTextGenerator

        config = PlanningTextConfig(
            session_id=session_id,
            project_name=project_name,
            output_dir=str(output_dir),
            output_formats=("md", "json"),
            append_rag=True,
            **kwargs,
        )
        generator = PlanningTextGenerator(config)
        result = await generator.generate()
        logger.info("[Runner] Planning text: %s | %s", result.md_path, result.json_path)
        return result

    # ---- baseline saving ----

    async def save_baseline(
        self,
        session_id: str,
        reports: Dict[str, str],
        output_dir: Path,
        project_name: str,
        checkpoint_id: str = "",
    ) -> Path:
        """Save baseline: JSON reports + planning text."""
        output_dir.mkdir(parents=True, exist_ok=True)

        baseline = {
            "session_id": session_id,
            "checkpoint_id": checkpoint_id,
            "generated_at": datetime.now().isoformat(),
            "dimension_count": len(reports),
            "reports": reports,
        }
        baseline_path = output_dir / "baseline_reports.json"
        baseline_path.write_text(
            __import__("json").dumps(baseline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[Runner] Baseline saved: %s", baseline_path)

        try:
            await self.generate_planning_text(session_id, output_dir, project_name)
        except Exception as e:
            logger.warning("[Runner] Planning text generation skipped: %s", e)

        return baseline_path

    # ---- checkpoint helpers ----

    async def get_checkpoint_id(self, session_id: str) -> str:
        """Get latest checkpoint_id for a session."""
        from app.services.runtime import PlanningRuntimeService

        snapshot = await PlanningRuntimeService.aget_state(session_id)
        if snapshot and snapshot.config:
            return snapshot.config.get("configurable", {}).get("checkpoint_id", "")
        return ""

    # ---- abstract ----

    @abstractmethod
    async def run(self) -> Any:
        """Subclass implements experiment-specific logic."""
        ...

    # ---- session ID generation ----

    @staticmethod
    def new_session_id(tag: str = "") -> str:
        prefix = f"{tag}_" if tag else ""
        return f"{prefix}{uuid.uuid4().hex[:8]}"