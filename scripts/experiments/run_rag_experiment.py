"""
RAG Hallucination Experiment - Simplified Version
Uses Layer-level RAG switch for hallucination comparison.

Experiment Flow:
1. Run Layer 1-2 (RAG enabled), save fixed context
2. Run Layer 3 (RAG ON) for experiment group
3. Run Layer 3 (RAG OFF) for control group
4. Manual annotation of hallucination references
5. Calculate hallucination rates, generate output docs

Usage:
    python scripts/experiments/run_rag_experiment.py --step all
    python scripts/experiments/run_rag_experiment.py --step generate-rag-on
    python scripts/experiments/run_rag_experiment.py --step generate-rag-off
    python scripts/experiments/run_rag_experiment.py --step generate-outputs
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from scripts.experiments.config import (
    RAG_ENABLED_DIMENSIONS,
    RAG_HALLUCINATION_DIR,
    RAG_ON_DIR,
    RAG_OFF_DIR,
    FIXED_CONTEXT_DIR,
    JINTIAN_VILLAGE_DATA,
    ensure_rag_experiment_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


DIMENSION_NAMES = {
    "land_use_planning": "土地利用规划",
    "infrastructure_planning": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
}


async def generate_fixed_context(timeout: int = 1800) -> Dict[str, Any]:
    """Run Layer 1-2 with RAG enabled to generate fixed context."""
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager

    logger.info("[FixedContext] Starting Layer 1-2 generation...")
    await PlanningRuntimeService.ensure_initialized()

    session_id = f"fixed_context_{uuid.uuid4().hex[:8]}"
    project_name = "金田村RAG实验"
    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": project_name})

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=project_name,
        village_data=village_data,
        village_name=JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
        task_description="制定金田村村庄总体规划（2022-2035年）",
        constraints="符合广东省村庄规划编制导则技术要求",
        session_id=session_id,
        step_mode=True,
        rag_layer_config={1: True, 2: True, 3: True},
    )

    sse_manager.set_execution_active(session_id, True)
    asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id, initial_state))
    logger.info(f"[FixedContext] Session started: {session_id}")

    state = await wait_for_layer_completion(session_id, target_layer=2, timeout=timeout)
    save_fixed_context(session_id, state)
    return state


async def wait_for_layer_completion(session_id: str, target_layer: int, timeout: int = 600) -> Dict[str, Any]:
    """Wait for a specific layer to complete."""
    from app.services.runtime import PlanningRuntimeService
    from app.agent.state import _phase_to_layer

    start_time = datetime.now()
    check_interval = 5

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            logger.warning(f"[Wait] Timeout after {elapsed}s")
            break

        checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
        if checkpoint_state and checkpoint_state.values:
            state = dict(checkpoint_state.values)
            execution_paused = state.get("execution_paused", False)

            if execution_paused and state.get("previous_layer") == target_layer:
                logger.info(f"[Wait] Layer {target_layer} completed!")
                return state

        await asyncio.sleep(check_interval)

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    return dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}


def save_fixed_context(session_id: str, state: Dict[str, Any]):
    """Save fixed context to disk."""
    ensure_rag_experiment_dirs()
    context = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(),
        "phase": state.get("phase", ""),
        "reports": state.get("reports", {}),
        "completed_dimensions": state.get("completed_dimensions", {}),
    }
    with open(FIXED_CONTEXT_DIR / "fixed_context.json", "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False)
    logger.info(f"[FixedContext] Saved to {FIXED_CONTEXT_DIR / 'fixed_context.json'}")


def load_fixed_context() -> Optional[Dict[str, Any]]:
    """Load fixed context from disk."""
    context_file = FIXED_CONTEXT_DIR / "fixed_context.json"
    if not context_file.exists():
        return None
    with open(context_file, "r", encoding="utf-8") as f:
        return json.load(f)


async def generate_layer3_reports(rag_enabled: bool, output_dir: Path, timeout: int = 600) -> Dict[str, Any]:
    """Generate Layer 3 reports with specified RAG setting."""
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager

    logger.info(f"[Layer3] Generating with RAG={rag_enabled}")

    fixed_context = load_fixed_context()
    if not fixed_context:
        logger.error("[Layer3] Fixed context not found!")
        return {"error": "Fixed context not found"}

    await PlanningRuntimeService.ensure_initialized()

    session_id = f"rag_{'on' if rag_enabled else 'off'}_{uuid.uuid4().hex[:8]}"
    project_name = f"RAG实验_{'ON' if rag_enabled else 'OFF'}"

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": project_name})

    # Layer-level RAG config: Layer 3 based on rag_enabled
    rag_layer_config = {1: True, 2: True, 3: rag_enabled}

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=project_name,
        village_data=JINTIAN_VILLAGE_DATA.get("status_report", ""),
        village_name=JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
        task_description="制定金田村村庄总体规划（2022-2035年）",
        constraints="符合广东省村庄规划编制导则技术要求",
        session_id=session_id,
        step_mode=False,
        rag_layer_config=rag_layer_config,
    )

    # Inject fixed context
    initial_state["reports"] = fixed_context.get("reports", {})
    initial_state["completed_dimensions"] = fixed_context.get("completed_dimensions", {})
    initial_state["phase"] = "layer3"

    sse_manager.set_execution_active(session_id, True)
    asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id, initial_state))
    logger.info(f"[Layer3] Session: {session_id}, RAG config: {rag_layer_config}")

    state = await wait_for_completion(session_id, timeout=timeout)
    layer3_reports = state.get("reports", {}).get("layer3", {})

    results = {
        "session_id": session_id,
        "rag_enabled": rag_enabled,
        "rag_layer_config": rag_layer_config,
        "dimensions": RAG_ENABLED_DIMENSIONS,
        "generated_at": datetime.now().isoformat(),
        "reports": {},
    }

    for dim_key in RAG_ENABLED_DIMENSIONS:
        content = layer3_reports.get(dim_key, "")
        results["reports"][dim_key] = {
            "dimension_key": dim_key,
            "dimension_name": DIMENSION_NAMES.get(dim_key, dim_key),
            "rag_enabled": rag_enabled,
            "content": content,
            "content_length": len(content),
            "success": bool(content),
        }
        with open(output_dir / f"{dim_key}.json", "w", encoding="utf-8") as f:
            json.dump(results["reports"][dim_key], f, indent=2, ensure_ascii=False)
        logger.info(f"[Layer3] Saved {dim_key}.json")

    with open(output_dir / "experiment_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    return results


async def wait_for_completion(session_id: str, timeout: int = 600) -> Dict[str, Any]:
    """Wait for session completion."""
    from app.services.runtime import PlanningRuntimeService

    start_time = datetime.now()
    check_interval = 5

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            break
        checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
        if checkpoint_state and checkpoint_state.values:
            state = dict(checkpoint_state.values)
            if state.get("phase") == "completed":
                return state
        await asyncio.sleep(check_interval)

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    return dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}


def generate_output_documents():
    """Generate Excel, Word, and KB summary documents."""
    from scripts.experiments.generate_experiment_outputs import main as generate_outputs
    generate_outputs(use_mock=False)


async def run_experiment(step: str = "all"):
    """Run RAG hallucination experiment."""
    ensure_rag_experiment_dirs()
    logger.info("=" * 60)
    logger.info(f"[RAG Experiment] Starting - Step: {step}")
    logger.info("=" * 60)

    if step == "all" or step == "generate-fixed-context":
        await generate_fixed_context(timeout=1800)

    if step == "all" or step == "generate-rag-on":
        await generate_layer3_reports(rag_enabled=True, output_dir=RAG_ON_DIR, timeout=600)

    if step == "all" or step == "generate-rag-off":
        await generate_layer3_reports(rag_enabled=False, output_dir=RAG_OFF_DIR, timeout=600)

    if step == "all" or step == "generate-outputs":
        generate_output_documents()

    logger.info("=" * 60)
    logger.info("[RAG Experiment] Completed")
    logger.info("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", default="all",
                        choices=["all", "generate-fixed-context", "generate-rag-on", "generate-rag-off", "generate-outputs"])
    args = parser.parse_args()
    asyncio.run(run_experiment(step=args.step))


if __name__ == "__main__":
    main()
