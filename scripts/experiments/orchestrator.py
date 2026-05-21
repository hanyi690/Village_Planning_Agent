"""Unified experiment orchestrator — single entry point for all experiments.

Usage:
    python scripts/experiments/run.py orchestrate \
        --baseline baseline_e0f06d60 \
        --cascade-scenarios scenario1,scenario2 \
        --cascade-runs 3 \
        --rag-groups g1,g2,g3 \
        --rag-iterations 5 \
        --parallel 5
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .framework.config import ExperimentConfig, CASCADE_SCENARIOS, RAG_GROUPS
from .framework.cache import ExperimentCache
from .framework.parallel import ParallelExperimentScheduler

logger = logging.getLogger(__name__)


class ExperimentOrchestrator:
    """Orchestrates cascade + RAG experiments with parallel execution.

    Features:
    - Single entry point for all experiments
    - Parallel scheduling with max_parallel control
    - Baseline session reuse for cascade and g3 RAG
    - Independent folder export for each experiment
    - Project name generation (village name consistent)
    """

    def __init__(
        self,
        config: ExperimentConfig,
        baseline_session_id: str = "baseline_e0f06d60",
        max_parallel: int = 5,
    ):
        self.config = config
        self.baseline_session_id = baseline_session_id
        self.scheduler = ParallelExperimentScheduler(config, max_parallel)
        self.cache = ExperimentCache(config.cache_dir)
        self.results: Dict[str, Any] = {}

    def _generate_project_name(self, experiment_type: str, identifier: str) -> str:
        """Generate unique project name while keeping village name consistent.

        Example: "金田村_cascade_s1_run0", "金田村_rag_g1_iter2"
        """
        return f"金田村_{experiment_type}_{identifier}"

    async def run_cascade_experiments(
        self,
        scenarios: List[str] = ["scenario1", "scenario2"],
        runs_per_scenario: int = 3,
    ) -> Dict[str, List[Any]]:
        """Run cascade revision experiments in parallel.

        Args:
            scenarios: List of scenario names (scenario1, scenario2)
            runs_per_scenario: Number of runs per scenario

        Returns:
            Dict mapping scenario_name -> list of results
        """
        from .cascade.runner import CascadeRunner

        results = {}

        for scenario_name in scenarios:
            scenario = CASCADE_SCENARIOS.get(scenario_name)
            if not scenario:
                logger.error("[Orchestrator] Unknown scenario: %s", scenario_name)
                continue

            # Create runners for each run
            runners = []
            for run_idx in range(runs_per_scenario):
                runner = CascadeRunner(
                    config=self.config,
                    scenario=scenario,
                    run_index=run_idx,
                    baseline_session_id=self.baseline_session_id,
                )
                runners.append(runner)

            # Run in parallel
            logger.info(
                "[Orchestrator] Running cascade %s: %d runs with max_parallel=%d",
                scenario_name, runs_per_scenario, self.scheduler.max_parallel,
            )

            scenario_results = await self.scheduler.run_experiments_parallel(runners)
            results[scenario_name] = scenario_results

            # Log summary
            successful = sum(1 for r in scenario_results if not isinstance(r, Exception))
            logger.info(
                "[Orchestrator] Cascade %s complete: %d/%d successful",
                scenario_name, successful, runs_per_scenario,
            )

        self.results["cascade"] = results
        return results

    async def run_rag_experiments(
        self,
        groups: List[str] = ["g1", "g2", "g3"],
        iterations_per_group: int = 5,
        g3_reuse_baseline: bool = True,
        g3_baseline_iteration: int = 0,  # Which iteration uses baseline
    ) -> Dict[str, List[Any]]:
        """Run RAG quality experiments with g3 baseline reuse.

        Args:
            groups: List of group names (g1, g2, g3)
            iterations_per_group: Number of iterations per group
            g3_reuse_baseline: Whether g3 should reuse baseline for one iteration
            g3_baseline_iteration: Which iteration (0-4) uses baseline data

        Returns:
            Dict mapping group_name -> list of results
        """
        from .rag.runner import RAGQualityRunner

        results = {}

        for group_name in groups:
            rag_config = RAG_GROUPS.get(group_name)
            if not rag_config:
                logger.error("[Orchestrator] Unknown group: %s", group_name)
                continue

            runners = []
            for iter_idx in range(iterations_per_group):
                # Check if this iteration should reuse baseline
                reuse_baseline = (
                    group_name == "g3"
                    and g3_reuse_baseline
                    and iter_idx == g3_baseline_iteration
                )

                runner = RAGQualityRunner(
                    config=self.config,
                    group_name=group_name,
                    iteration=iter_idx,
                    reuse_baseline=reuse_baseline,
                    baseline_session_id=self.baseline_session_id if reuse_baseline else None,
                )
                runners.append(runner)

            # Run in parallel
            logger.info(
                "[Orchestrator] Running RAG %s: %d iterations with max_parallel=%d",
                group_name, iterations_per_group, self.scheduler.max_parallel,
            )

            group_results = await self.scheduler.run_experiments_parallel(runners)
            results[group_name] = group_results

            # Log summary
            successful = sum(1 for r in group_results if not isinstance(r, Exception))
            logger.info(
                "[Orchestrator] RAG %s complete: %d/%d successful",
                group_name, successful, iterations_per_group,
            )

        self.results["rag"] = results
        return results

    async def run_all(
        self,
        cascade_scenarios: List[str] = ["scenario1", "scenario2"],
        cascade_runs: int = 3,
        rag_groups: List[str] = ["g1", "g2", "g3"],
        rag_iterations: int = 5,
    ) -> Dict[str, Any]:
        """Run complete experiment suite.

        Order:
        1. Cascade experiments (parallel per scenario)
        2. RAG experiments (parallel per group)

        Returns:
            Dict with cascade and rag results
        """
        start_time = datetime.now()
        logger.info("[Orchestrator] Starting full experiment suite at %s", start_time)

        # Run cascade experiments
        cascade_results = await self.run_cascade_experiments(
            scenarios=cascade_scenarios,
            runs_per_scenario=cascade_runs,
        )

        # Run RAG experiments
        rag_results = await self.run_rag_experiments(
            groups=rag_groups,
            iterations_per_group=rag_iterations,
            g3_reuse_baseline=True,
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Save overall summary
        summary = {
            "baseline_session_id": self.baseline_session_id,
            "cascade_scenarios": cascade_scenarios,
            "cascade_runs": cascade_runs,
            "rag_groups": rag_groups,
            "rag_iterations": rag_iterations,
            "max_parallel": self.scheduler.max_parallel,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "cascade_summary": {
                name: {
                    "total": len(results),
                    "successful": sum(1 for r in results if not isinstance(r, Exception)),
                }
                for name, results in cascade_results.items()
            },
            "rag_summary": {
                name: {
                    "total": len(results),
                    "successful": sum(1 for r in results if not isinstance(r, Exception)),
                }
                for name, results in rag_results.items()
            },
        }

        summary_path = self.config.output_dir / "experiment_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "[Orchestrator] Complete: duration=%.1fs, summary saved to %s",
            duration, summary_path,
        )

        return {
            "cascade": cascade_results,
            "rag": rag_results,
            "summary": summary,
        }


async def run_orchestrator(
    baseline_session_id: str = "baseline_e0f06d60",
    cascade_scenarios: List[str] = ["scenario1", "scenario2"],
    cascade_runs: int = 3,
    rag_groups: List[str] = ["g1", "g2", "g3"],
    rag_iterations: int = 5,
    max_parallel: int = 5,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Convenience function to run orchestrator with parameters."""
    config = ExperimentConfig.default("orchestrator")
    if output_dir:
        config.output_dir = output_dir

    orchestrator = ExperimentOrchestrator(
        config=config,
        baseline_session_id=baseline_session_id,
        max_parallel=max_parallel,
    )

    return await orchestrator.run_all(
        cascade_scenarios=cascade_scenarios,
        cascade_runs=cascade_runs,
        rag_groups=rag_groups,
        rag_iterations=rag_iterations,
    )