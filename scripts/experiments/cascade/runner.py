"""Cascade revision runner — fork baseline + inject feedback + check consistency."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..framework.cache import ExperimentCache
from ..framework.config import CascadeScenario, ExperimentConfig
from ..framework.data_accessor import ExperimentDataAccessor
from ..framework.metrics import MetricsSuite
from ..framework.runner import ExperimentRunner

logger = logging.getLogger(__name__)


class CascadeRunner(ExperimentRunner):
    """Runs cascade revision experiments.

    Flow:
    1. Load or generate baseline reports
    2. For each scenario: fork checkpoint → inject feedback → re-run affected layers
    3. Check consistency between baseline and revised reports
    4. Export results
    """

    def __init__(
        self,
        config: ExperimentConfig,
        scenario: CascadeScenario,
        run_index: int = 0,
    ):
        super().__init__(config)
        self.scenario = scenario
        self.run_index = run_index
        self.metrics = MetricsSuite()

    async def run(self) -> Dict[str, Any]:
        """Execute cascade experiment for the configured scenario."""
        scenario = self.scenario
        tag = f"cascade_{scenario.name}_run{self.run_index}"
        session_id = self.new_session_id(tag)

        logger.info(
            "[Cascade] Starting %s: target=%s L%d",
            scenario.name, scenario.target_dimension, scenario.target_layer,
        )

        # 1. Load or generate baseline
        baseline_reports = await self._ensure_baseline()
        if not baseline_reports:
            return {"error": "Failed to generate baseline", "scenario": scenario.name}

        # 2. Run cascade revision
        revised_reports = await self._run_cascade_revision(
            session_id=session_id,
            baseline_reports=baseline_reports,
            scenario=scenario,
        )

        # 3. Check consistency
        consistency_results = self._check_all_consistency(
            baseline_reports, revised_reports, scenario,
        )

        # 4. Save results
        output_dir = self.config.output_dir / scenario.name / f"run{self.run_index}"
        output_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "scenario": scenario.name,
            "session_id": session_id,
            "target_dimension": scenario.target_dimension,
            "target_layer": scenario.target_layer,
            "consistency": consistency_results,
            "overall_consistency": sum(
                v.get("score", 0) for v in consistency_results.values()
            ) / max(len(consistency_results), 1),
        }

        result_path = output_dir / "cascade_result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # Save revised reports
        revised_path = output_dir / "revised_reports.json"
        revised_path.write_text(
            json.dumps(
                {"session_id": session_id, "reports": revised_reports},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

        logger.info(
            "[Cascade] %s done: overall=%.3f",
            scenario.name, result["overall_consistency"],
        )
        return result

    # ---- baseline ----

    async def _ensure_baseline(self) -> Dict[str, str]:
        """Load baseline from cache/file or generate fresh."""
        baseline_dir = self.config.output_dir / "baseline"
        baseline_file = baseline_dir / "baseline_reports.json"

        # Try file cache
        if baseline_file.exists():
            return self.data_accessor.load_baseline_from_file(baseline_file)

        # Try ExperimentCache
        cached = self.cache.load_reports("baseline", "jintian")
        if cached:
            return cached

        # Generate fresh baseline
        logger.info("[Cascade] Generating fresh baseline...")
        session_id = self.new_session_id("baseline")
        # Use g3 config: L1+L3 RAG enabled (actual app config)
        rag_config = {1: True, 2: False, 3: True}
        reports = await self.run_planning_graph(
            session_id=session_id,
            project_name="金田村村庄规划",
            rag_config=rag_config,
        )

        await self.save_baseline(
            session_id=session_id,
            reports=reports,
            output_dir=baseline_dir,
            project_name="金田村村庄规划",
        )
        self.cache.save_reports("baseline", "jintian", reports)
        return reports

    # ---- cascade revision ----

    async def _run_cascade_revision(
        self,
        session_id: str,
        baseline_reports: Dict[str, str],
        scenario: CascadeScenario,
    ) -> Dict[str, str]:
        """Run cascade revision by forking from baseline checkpoint and injecting feedback.

        Uses fork checkpoint mechanism from old run_experiment.py:
        1. Get baseline session_id and checkpoint_id from baseline_reports.json
        2. Fork from baseline checkpoint using graph.aupdate_state()
        3. Inject revision triggers (need_revision, revision_target_dimensions, feedback)
        4. Inject synthetic AIMessage to trigger after_conversation routing
        5. Execute from fork point and collect revised reports
        """
        from app.services.runtime import PlanningRuntimeService
        from app.services.sse import sse_manager
        from app.services.report_store import ReportStore
        from app.agent.state import get_layer_dimensions, get_layer_name
        from scripts.experiments.sse_listener import InProcessEventListener
        from langchain_core.messages import AIMessage

        await PlanningRuntimeService.ensure_initialized()

        # 1. Get baseline session_id and checkpoint_id
        baseline_dir = self.config.output_dir / "baseline"
        baseline_file = baseline_dir / "baseline_reports.json"
        if not baseline_file.exists():
            logger.error("[Cascade] Baseline file not found: %s", baseline_file)
            return {}

        baseline_data = json.loads(baseline_file.read_text(encoding="utf-8"))
        baseline_session_id = baseline_data.get("session_id", "")
        baseline_checkpoint_id = baseline_data.get("checkpoint_id", "")

        if not baseline_session_id:
            logger.error("[Cascade] No session_id in baseline file")
            return {}

        # 2. Get baseline checkpoint state
        if baseline_checkpoint_id:
            config = PlanningRuntimeService.get_thread_config(baseline_session_id, baseline_checkpoint_id)
            graph = PlanningRuntimeService.get_graph()
            baseline_state = await graph.aget_state(config)
        else:
            baseline_state = await PlanningRuntimeService.aget_state(baseline_session_id)

        if not baseline_state or not baseline_state.values:
            logger.error("[Cascade] Baseline checkpoint state not found")
            return {}

        fork_cfg = baseline_state.config
        fork_cfg.setdefault("configurable", {})["checkpoint_ns"] = ""
        logger.info(
            "[Cascade] Forking from baseline: session=%s, checkpoint=%s",
            baseline_session_id,
            fork_cfg.get("configurable", {}).get("checkpoint_id", "?"),
        )

        # 3. Fork: inject revision triggers
        graph = PlanningRuntimeService.get_graph()
        fork_cfg = await graph.aupdate_state(fork_cfg, {
            "need_revision": True,
            "revision_target_dimensions": [scenario.target_dimension],
            "human_feedback": scenario.feedback,
            "revision_feedback": scenario.feedback,
            "is_revision": True,
        }, as_node="conversation")

        # 4. Inject synthetic AIMessage to trigger after_conversation routing
        msg = AIMessage(content="", tool_calls=[{
            "name": "AdvancePlanningIntent",
            "id": f"call_{baseline_session_id[:8]}",
            "args": {},
        }])
        fork_cfg = await graph.aupdate_state(
            fork_cfg, {"messages": [msg]}, as_node="conversation"
        )

        # 5. SSE listener (reuse baseline session_id)
        sse_manager.init_session(baseline_session_id, {
            "session_id": baseline_session_id,
            "project_name": f"金田村级联实验_{scenario.name}",
        })
        sse_manager.set_execution_active(baseline_session_id, True)

        listener = InProcessEventListener(baseline_session_id)
        await listener.connect()

        # 6. Execute from fork point
        task = asyncio.create_task(self._consume_fork_stream(
            baseline_session_id, fork_cfg, listener
        ))

        try:
            # Wait for revision completion - checkpoint_saved event with is_revision=True
            await listener.wait_for_any_event(
                event_types=["checkpoint_saved", "error"],
                timeout=900,
                filter_func=lambda e: (
                    e.get("type") == "error"
                    or e.get("data", {}).get("is_revision") == True
                ),
            )
            logger.info("[Cascade] Revision checkpoint_saved received")
        except asyncio.TimeoutError as e:
            logger.error("[Cascade] Timeout waiting for revision: %s", e)
        except Exception as e:
            logger.error("[Cascade] Error: %s", e)

        await task
        await listener.disconnect()

        # 7. Get revised reports from ReportStore
        store = ReportStore.get_instance()
        reports = {}
        for layer in [1, 2, 3]:
            layer_reports = await store.get_layer_reports(baseline_session_id, layer)
            reports.update(layer_reports)

        logger.info("[Cascade] Retrieved %d revised reports", len(reports))
        return reports

    async def _consume_fork_stream(self, session_id: str, fork_cfg: dict, listener):
        """Consume fork execution stream, push SSE events to listener."""
        from app.services.runtime import PlanningRuntimeService
        from app.services.sse import sse_manager as sse_mgr
        from app.utils.event_factory import create_checkpoint_saved_event

        graph = PlanningRuntimeService.get_graph()
        try:
            async for event in graph.astream(
                None, fork_cfg, stream_mode=['values', 'checkpoints']
            ):
                if isinstance(event, tuple) and len(event) == 2:
                    mode, data = event
                    if mode == 'checkpoints':
                        checkpoint_id = None
                        if hasattr(data, 'config'):
                            checkpoint_id = data.config.get('configurable', {}).get('checkpoint_id', '')
                        elif isinstance(data, dict):
                            checkpoint_id = data.get('config', {}).get('configurable', {}).get('checkpoint_id', '')

                        if checkpoint_id:
                            checkpoint_event = create_checkpoint_saved_event(
                                checkpoint_id=checkpoint_id,
                                layer=0,
                                phase="",
                                session_id=session_id,
                                is_revision=True,
                            )
                            sse_mgr.append_event(session_id, checkpoint_event)
                            sse_mgr.publish_sync(session_id, checkpoint_event)
        except Exception as e:
            logger.error("[Cascade] Fork stream error: %s", e)
            from app.services.sse import sse_manager as sse_mgr
            sse_mgr.append_event(session_id, {"type": "error", "data": {"message": str(e)}})

    # ---- consistency checking ----

    def _check_all_consistency(
        self,
        baseline: Dict[str, str],
        revised: Dict[str, str],
        scenario: CascadeScenario,
    ) -> Dict[str, Any]:
        """Check consistency for target dimension and downstream dimensions.

        Keywords format: {"positive": [...], "negative": [...]}
        - Target dimension: check feedback response (positive coverage + negative removal)
        - Downstream dimensions: check semantic alignment with target
        """
        from app.config.dependency import get_impact_tree_compat

        results = {}
        target_dim = scenario.target_dimension

        # 1. Check target dimension feedback response
        old_target = baseline.get(target_dim, "")
        new_target = revised.get(target_dim, "")
        if new_target:
            # Keywords are {"positive": [...], "negative": [...]}
            keywords = scenario.keywords
            if isinstance(keywords, dict) and "positive" in keywords:
                # New format
                score = self.metrics.check_feedback_response(
                    old_target, new_target, scenario.feedback, keywords
                )
                results[target_dim] = {
                    "score": score,
                    "is_target": True,
                    "positive_coverage": sum(1 for kw in keywords.get("positive", []) if kw in new_target) / max(len(keywords.get("positive", [])), 1),
                    "negative_residual": sum(1 for kw in keywords.get("negative", []) if kw in new_target) / max(len(keywords.get("negative", [])), 1),
                }
            else:
                # Fallback for old format
                results[target_dim] = {"score": 0.5, "is_target": True}
        else:
            results[target_dim] = {"score": 0.0, "is_target": True, "missing": True}

        # 2. Check downstream dimensions (semantic alignment)
        impact_tree = get_impact_tree_compat(target_dim)
        for wave, dims in impact_tree.items():
            for dim_key in dims:
                if dim_key == target_dim:
                    continue
                new_downstream = revised.get(dim_key, "")
                if not new_downstream:
                    results[dim_key] = {"score": 0.0, "skipped": True, "reason": "missing"}
                    continue

                # Check semantic alignment between target revision and downstream
                alignment = self.metrics.check_semantic_alignment(
                    new_target, new_downstream, dim_key
                )
                results[dim_key] = {
                    "score": alignment,
                    "is_target": False,
                    "wave": wave,
                }

        return results