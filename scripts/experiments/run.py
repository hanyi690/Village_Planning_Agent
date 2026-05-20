"""Unified experiment CLI entry point.

Usage:
    python scripts/experiments/run.py baseline [--output-dir DIR]
    python scripts/experiments/run.py cascade --scenario scenario1 [--runs N] [--no-cache]
    python scripts/experiments/run.py rag --groups g1,g2,g3 [--iterations N] [--parallel N] [--no-cache]
    python scripts/experiments/run.py export --session-id SID --output-dir DIR
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project roots on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.experiments.framework.config import ExperimentConfig, CASCADE_SCENARIOS, RAG_GROUPS
from scripts.experiments.framework.cache import ExperimentCache
from scripts.experiments.framework.exporter import ResultExporter
from scripts.experiments.framework.parallel import ParallelExperimentScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---- commands ----

async def cmd_baseline(args: argparse.Namespace) -> None:
    """Generate baseline reports for jintian village."""
    config = ExperimentConfig.default("baseline")
    if args.output_dir:
        config.output_dir = Path(args.output_dir)

    from scripts.experiments.framework.runner import ExperimentRunner

    # Use a concrete subclass — CascadeRunner works for baseline generation
    from scripts.experiments.cascade.runner import CascadeRunner
    from scripts.experiments.framework.config import CascadeScenario

    dummy_scenario = CascadeScenario(
        name="baseline",
        target_dimension="development_goals",
        target_layer=1,
        feedback="",
        keywords={},
    )
    runner = CascadeRunner(config, dummy_scenario)
    reports = await runner._ensure_baseline()
    logger.info("[Baseline] %d reports ready", len(reports))


async def cmd_cascade(args: argparse.Namespace) -> None:
    """Run cascade revision experiment."""
    config = ExperimentConfig.default(f"cascade_{args.scenario}")
    config.use_cache = not args.no_cache

    scenario = CASCADE_SCENARIOS.get(args.scenario)
    if not scenario:
        logger.error("Unknown scenario: %s (available: %s)", args.scenario, list(CASCADE_SCENARIOS.keys()))
        return

    from scripts.experiments.cascade.runner import CascadeRunner

    results = []
    for run_idx in range(args.runs):
        runner = CascadeRunner(config, scenario, run_index=run_idx)
        result = await runner.run()
        results.append(result)

    logger.info("[Cascade] %d runs completed", len(results))


async def cmd_rag(args: argparse.Namespace) -> None:
    """Run RAG quality experiment."""
    config = ExperimentConfig.default("rag_quality")
    config.use_cache = not args.no_cache

    groups = args.groups.split(",")
    for g in groups:
        if g not in RAG_GROUPS:
            logger.error("Unknown group: %s (available: %s)", g, list(RAG_GROUPS.keys()))
            return

    from scripts.experiments.rag_quality.runner import RAGQualityRunner

    if args.parallel > 1:
        scheduler = ParallelExperimentScheduler(config, max_parallel=args.parallel)
        all_results = {}
        for iteration in range(args.iterations):
            runners = [
                RAGQualityRunner(config, group_name=g, iteration=iteration)
                for g in groups
            ]
            results = await scheduler.run_experiments_parallel(runners)
            for i, g in enumerate(groups):
                all_results.setdefault(g, []).append(results[i])

        logger.info("[RAG] Parallel run complete: %d groups × %d iterations", len(groups), args.iterations)
    else:
        for iteration in range(args.iterations):
            for g in groups:
                runner = RAGQualityRunner(config, group_name=g, iteration=iteration)
                result = await runner.run()
                logger.info("[RAG] %s iter%d: %.3f", g, iteration, result.get("overall_consistency", 0))


async def cmd_export(args: argparse.Namespace) -> None:
    """Export session data."""
    config = ExperimentConfig.default("export")
    cache = ExperimentCache(config.cache_dir)
    exporter = ResultExporter(cache)

    output_dir = Path(args.output_dir)
    await exporter.export_session(
        session_id=args.session_id,
        output_dir=output_dir,
        project_name=args.project_name or "village_planning",
    )
    logger.info("[Export] Session %s → %s", args.session_id, output_dir)


# ---- main ----

def main() -> None:
    parser = argparse.ArgumentParser(description="Village Planning Experiment Runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # baseline
    baseline_parser = subparsers.add_parser("baseline", help="Generate baseline reports")
    baseline_parser.add_argument("--output-dir", default=None)

    # cascade
    cascade_parser = subparsers.add_parser("cascade", help="Run cascade revision experiment")
    cascade_parser.add_argument("--scenario", required=True, help="Scenario name (scenario1/2/3)")
    cascade_parser.add_argument("--runs", type=int, default=1, help="Number of runs")
    cascade_parser.add_argument("--no-cache", action="store_true", help="Disable caching")

    # rag
    rag_parser = subparsers.add_parser("rag", help="Run RAG quality experiment")
    rag_parser.add_argument("--groups", default="g1,g2,g3", help="Comma-separated group names")
    rag_parser.add_argument("--iterations", type=int, default=2, help="Iterations per group")
    rag_parser.add_argument("--parallel", type=int, default=1, help="Max parallel sessions")
    rag_parser.add_argument("--no-cache", action="store_true", help="Disable caching")

    # export
    export_parser = subparsers.add_parser("export", help="Export session data")
    export_parser.add_argument("--session-id", required=True)
    export_parser.add_argument("--output-dir", required=True)
    export_parser.add_argument("--project-name", default=None)

    args = parser.parse_args()

    commands = {
        "baseline": cmd_baseline,
        "cascade": cmd_cascade,
        "rag": cmd_rag,
        "export": cmd_export,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()