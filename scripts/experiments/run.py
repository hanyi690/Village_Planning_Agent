"""Unified experiment CLI entry point.

Usage:
    python scripts/experiments/run.py baseline [--output-dir DIR]
    python scripts/experiments/run.py cascade --scenario scenario1 [--runs N] [--baseline-session-id SID]
    python scripts/experiments/run.py rag --groups g1,g2,g3 [--iterations N] [--parallel N] [--g3-reuse-baseline]
    python scripts/experiments/run.py export --session-id SID --output-dir DIR
    python scripts/experiments/run.py clear --keep baseline_e0f06d60
    python scripts/experiments/run.py orchestrate --baseline baseline_e0f06d60 --cascade-runs 3 --rag-iterations 5
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

def setup_logging(output_dir: Path) -> None:
    """Configure logging with both console and file handlers."""
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "experiment.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # File handler
    file_fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)


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

    # Setup file logging
    setup_logging(config.output_dir)

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
        runner = CascadeRunner(
            config, scenario,
            run_index=run_idx,
            baseline_session_id=args.baseline_session_id,
        )
        result = await runner.run()
        results.append(result)

    logger.info("[Cascade] %d runs completed", len(results))


async def cmd_rag(args: argparse.Namespace) -> None:
    """Run RAG quality experiment."""
    config = ExperimentConfig.default("rag")
    config.use_cache = not args.no_cache

    groups = args.groups.split(",")
    for g in groups:
        if g not in RAG_GROUPS:
            logger.error("Unknown group: %s (available: %s)", g, list(RAG_GROUPS.keys()))
            return

    from scripts.experiments.rag.runner import RAGQualityRunner

    # Determine which iteration uses baseline for g3
    g3_baseline_iteration = args.g3_baseline_iteration if args.g3_reuse_baseline else -1

    if args.parallel > 1:
        scheduler = ParallelExperimentScheduler(config, max_parallel=args.parallel)
        all_results = {}
        for iteration in range(args.iterations):
            runners = []
            for g in groups:
                reuse_baseline = (
                    g == "g3"
                    and args.g3_reuse_baseline
                    and iteration == g3_baseline_iteration
                )
                runner = RAGQualityRunner(
                    config,
                    group_name=g,
                    iteration=iteration,
                    reuse_baseline=reuse_baseline,
                    baseline_session_id=args.baseline_session_id if reuse_baseline else None,
                )
                runners.append(runner)
            results = await scheduler.run_experiments_parallel(runners)
            for i, g in enumerate(groups):
                all_results.setdefault(g, []).append(results[i])

        logger.info("[RAG] Parallel run complete: %d groups × %d iterations", len(groups), args.iterations)
    else:
        for iteration in range(args.iterations):
            for g in groups:
                reuse_baseline = (
                    g == "g3"
                    and args.g3_reuse_baseline
                    and iteration == g3_baseline_iteration
                )
                runner = RAGQualityRunner(
                    config,
                    group_name=g,
                    iteration=iteration,
                    reuse_baseline=reuse_baseline,
                    baseline_session_id=args.baseline_session_id if reuse_baseline else None,
                )
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


async def cmd_clear(args: argparse.Namespace) -> None:
    """Clear database except specified sessions."""
    from scripts.experiments.clear_database import clear_all_except, list_all_sessions

    if args.list:
        sessions = await list_all_sessions()
        print(f"\nFound {len(sessions)} sessions:")
        for s in sessions:
            print(f"  - {s['session_id']}: {s['project_name']} ({s['village_name']})")
        return

    keep_ids = [s.strip() for s in args.keep.split(",")]

    if args.dry_run:
        sessions = await list_all_sessions()
        to_delete = [s for s in sessions if s["session_id"] not in keep_ids]
        print(f"\nWould delete {len(to_delete)} sessions:")
        for s in to_delete:
            print(f"  - {s['session_id']}: {s['project_name']}")
        print(f"\nWould keep {len(keep_ids)} sessions: {keep_ids}")
        return

    print(f"Clearing database, keeping: {keep_ids}")
    result = await clear_all_except(keep_ids)
    print(f"\nDeletion summary:")
    for table, count in result.items():
        print(f"  - {table}: {count}")


async def cmd_orchestrate(args: argparse.Namespace) -> None:
    """Run complete experiment suite with orchestrator."""
    from scripts.experiments.orchestrator import ExperimentOrchestrator

    config = ExperimentConfig.default("orchestrator")
    setup_logging(config.output_dir)

    orchestrator = ExperimentOrchestrator(
        config=config,
        baseline_session_id=args.baseline,
        max_parallel=args.parallel,
    )

    cascade_scenarios = args.cascade_scenarios.split(",") if args.cascade_scenarios else []
    rag_groups = args.rag_groups.split(",") if args.rag_groups else []

    result = await orchestrator.run_all(
        cascade_scenarios=cascade_scenarios,
        cascade_runs=args.cascade_runs,
        rag_groups=rag_groups,
        rag_iterations=args.rag_iterations,
    )

    logger.info("[Orchestrate] Complete: %s", result.get("summary", {}))


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
    cascade_parser.add_argument("--baseline-session-id", default=None, help="Use existing baseline session")

    # rag
    rag_parser = subparsers.add_parser("rag", help="Run RAG quality experiment")
    rag_parser.add_argument("--groups", default="g1,g2,g3", help="Comma-separated group names")
    rag_parser.add_argument("--iterations", type=int, default=2, help="Iterations per group")
    rag_parser.add_argument("--parallel", type=int, default=1, help="Max parallel sessions")
    rag_parser.add_argument("--no-cache", action="store_true", help="Disable caching")
    rag_parser.add_argument("--g3-reuse-baseline", action="store_true", help="g3 group reuses baseline for one iteration")
    rag_parser.add_argument("--g3-baseline-iteration", type=int, default=0, help="Which iteration (0-indexed) uses baseline for g3")
    rag_parser.add_argument("--baseline-session-id", default=None, help="Baseline session ID for g3 reuse")

    # export
    export_parser = subparsers.add_parser("export", help="Export session data")
    export_parser.add_argument("--session-id", required=True)
    export_parser.add_argument("--output-dir", required=True)
    export_parser.add_argument("--project-name", default=None)

    # clear
    clear_parser = subparsers.add_parser("clear", help="Clear database except specified sessions")
    clear_parser.add_argument("--keep", default="baseline_e0f06d60", help="Comma-separated session_ids to keep")
    clear_parser.add_argument("--list", action="store_true", help="List all sessions without deleting")
    clear_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    # orchestrate
    orchestrate_parser = subparsers.add_parser("orchestrate", help="Run complete experiment suite")
    orchestrate_parser.add_argument("--baseline", default="baseline_e0f06d60", help="Baseline session ID")
    orchestrate_parser.add_argument("--cascade-scenarios", default="scenario1,scenario2", help="Comma-separated scenario names")
    orchestrate_parser.add_argument("--cascade-runs", type=int, default=3, help="Runs per scenario")
    orchestrate_parser.add_argument("--rag-groups", default="g1,g2,g3", help="Comma-separated group names")
    orchestrate_parser.add_argument("--rag-iterations", type=int, default=5, help="Iterations per group")
    orchestrate_parser.add_argument("--parallel", type=int, default=5, help="Max parallel sessions")

    args = parser.parse_args()

    commands = {
        "baseline": cmd_baseline,
        "cascade": cmd_cascade,
        "rag": cmd_rag,
        "export": cmd_export,
        "clear": cmd_clear,
        "orchestrate": cmd_orchestrate,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()