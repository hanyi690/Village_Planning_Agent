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

# 添加项目根目录和backend到路径（必须在其他导入之前）
# 路径计算：脚本位于 scripts/experiments/rag_hallucination/run_rag_experiment.py
# 需要向上 4 级到达项目根目录
script_dir = Path(__file__).parent.resolve()  # rag_hallucination
project_root = script_dir.parent.parent.parent.resolve()  # Village_Planning_Agent
backend_root = (project_root / "backend").resolve()

# 确保路径在列表开头
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# 使用相对导入（从项目根目录）
from scripts.experiments.config import (
    RAG_ENABLED_DIMENSIONS,
    RAG_HALLUCINATION_DIR,
    RAG_ON_DIR,
    RAG_OFF_DIR,
    FIXED_CONTEXT_DIR,
    FIXED_CONTEXT_RAG_ON,
    FIXED_CONTEXT_RAG_OFF,
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


async def generate_fixed_context(rag_enabled_for_l1l2: bool = True, timeout: int = 1800) -> Dict[str, Any]:
    """Run Layer 1-2 with specified RAG setting to generate fixed context.

    Args:
        rag_enabled_for_l1l2: Whether RAG is enabled for Layer 1-2
        timeout: Timeout in seconds

    Returns:
        Fixed context state
    """
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager

    rag_status = "ON" if rag_enabled_for_l1l2 else "OFF"
    logger.info(f"[FixedContext] Starting Layer 1-2 generation (RAG={rag_status})...")
    await PlanningRuntimeService.ensure_initialized()

    session_id = f"fixed_context_rag_{rag_status.lower()}_{uuid.uuid4().hex[:8]}"
    project_name = f"金田村RAG实验_L1L2_{rag_status}"
    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": project_name})

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=project_name,
        village_data=village_data,
        village_name=JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
        task_description="制定金田村村庄总体规划（2022-2035年）",
        constraints="符合广东省村庄规划编制导则技术要求",
        session_id=session_id,
        step_mode=False,  # 自动完成 Layer 1-2，不暂停
        rag_layer_config={1: rag_enabled_for_l1l2, 2: rag_enabled_for_l1l2, 3: True},
    )

    sse_manager.set_execution_active(session_id, True)
    asyncio.create_task(PlanningRuntimeService._trigger_planning_execution(session_id, initial_state))
    logger.info(f"[FixedContext] Session started: {session_id}")

    state = await wait_for_layer_completion(session_id, target_layer=2, timeout=timeout)
    save_fixed_context(session_id, state, rag_enabled_for_l1l2)
    return state


async def wait_for_layer_completion(session_id: str, target_layer: int, timeout: int = 600) -> Dict[str, Any]:
    """Wait for a specific layer to complete.

    当 step_mode=False 时，检查 previous_layer 是否达到目标层。
    """
    from app.services.runtime import PlanningRuntimeService

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
            previous_layer = state.get("previous_layer", 0)
            phase = state.get("phase", "")

            # 检查是否完成目标层（step_mode=False 时）
            if previous_layer >= target_layer:
                logger.info(f"[Wait] Layer {target_layer} completed! (previous_layer={previous_layer})")
                return state

            # 检查是否进入下一阶段
            if target_layer == 2 and phase in ["layer3", "completed"]:
                logger.info(f"[Wait] Layer 2 completed! (phase={phase})")
                return state

        await asyncio.sleep(check_interval)

    checkpoint_state = await PlanningRuntimeService.aget_state(session_id)
    return dict(checkpoint_state.values) if checkpoint_state and checkpoint_state.values else {}


async def save_fixed_context_async(session_id: str, state: Dict[str, Any], rag_enabled_for_l1l2: bool = True):
    """Save fixed context with injected knowledge to disk (async version).

    Args:
        session_id: Session ID
        state: State dictionary
        rag_enabled_for_l1l2: Whether RAG was enabled for Layer 1-2
    """
    from app.services.report_store import ReportStore

    ensure_rag_experiment_dirs()

    # Load reports from database (reports are not stored in state)
    store = ReportStore.get_instance()
    layer1_reports = await store.get_layer_reports(session_id, 1)
    layer2_reports = await store.get_layer_reports(session_id, 2)

    reports = {
        "layer1": layer1_reports,
        "layer2": layer2_reports,
    }

    # Extract injected knowledge from reports
    injected_knowledge = extract_injected_knowledge({"reports": reports})

    context = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(),
        "rag_enabled_for_l1l2": rag_enabled_for_l1l2,
        "phase": state.get("phase", ""),
        "reports": reports,
        "completed_dimensions": state.get("completed_dimensions", {}),
        "injected_knowledge": injected_knowledge,
    }

    # Select file path based on RAG status
    context_file = FIXED_CONTEXT_RAG_ON if rag_enabled_for_l1l2 else FIXED_CONTEXT_RAG_OFF
    with open(context_file, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2, ensure_ascii=False)
    logger.info(f"[FixedContext] Saved to {context_file}")
    logger.info(f"[FixedContext] Layer 1 reports: {len(layer1_reports)}, Layer 2 reports: {len(layer2_reports)}")


def save_fixed_context(session_id: str, state: Dict[str, Any], rag_enabled_for_l1l2: bool = True):
    """Save fixed context (sync wrapper for backward compatibility)."""
    import asyncio
    asyncio.run(save_fixed_context_async(session_id, state, rag_enabled_for_l1l2))


def extract_injected_knowledge(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract injected knowledge from state.

    Knowledge sources:
    1. rag_context: RAG retrieved raw content
    2. dimension_knowledge: Knowledge slices injected for each dimension
    3. retrieved_sources: Retrieved document sources

    Args:
        state: State dictionary

    Returns:
        Injected knowledge dictionary
    """
    injected = {
        "rag_context": {},
        "dimension_knowledge": {},
        "retrieved_sources": [],
    }

    # Extract references from reports
    reports = state.get("reports", {})
    for layer_key, layer_reports in reports.items():
        if isinstance(layer_reports, dict):
            for dim_key, report_content in layer_reports.items():
                if isinstance(report_content, str) and report_content:
                    refs = ReferenceExtractor().extract(report_content)
                    injected["dimension_knowledge"][dim_key] = {
                        "references": [r.text for r in refs],
                        "content_snippets": [],
                    }

    # Extract RAG records if available
    rag_records = state.get("rag_records", [])
    for record in rag_records:
        source = record.get("source", "")
        content = record.get("content", "")
        if source:
            injected["retrieved_sources"].append(source)
            injected["rag_context"][source] = content[:500] if content else ""

    # Extract from rag_context if available
    rag_context = state.get("rag_context", {})
    if isinstance(rag_context, dict):
        for source, content in rag_context.items():
            if source not in injected["rag_context"]:
                injected["rag_context"][source] = content[:500] if content else ""
            if source not in injected["retrieved_sources"]:
                injected["retrieved_sources"].append(source)

    return injected


def load_fixed_context(rag_enabled_for_l1l2: bool = True) -> Optional[Dict[str, Any]]:
    """Load fixed context from disk.

    Args:
        rag_enabled_for_l1l2: Whether to load RAG ON or RAG OFF context

    Returns:
        Fixed context dictionary or None if not found
    """
    context_file = FIXED_CONTEXT_RAG_ON if rag_enabled_for_l1l2 else FIXED_CONTEXT_RAG_OFF
    if not context_file.exists():
        return None
    with open(context_file, "r", encoding="utf-8") as f:
        return json.load(f)


async def generate_layer3_reports(rag_enabled: bool, output_dir: Path, timeout: int = 600) -> Dict[str, Any]:
    """Generate Layer 3 reports with specified RAG setting.

    Uses matching fixed context:
    - RAG ON group: Uses fixed_context_rag_on.json (Layer 1-2 with RAG ON)
    - RAG OFF group: Uses fixed_context_rag_off.json (Layer 1-2 with RAG OFF)

    Args:
        rag_enabled: Whether RAG is enabled for Layer 3
        output_dir: Output directory
        timeout: Timeout in seconds

    Returns:
        Experiment results
    """
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager

    logger.info(f"[Layer3] Generating with RAG={rag_enabled}")

    # Load matching fixed context
    # RAG ON group uses fixed context generated with RAG ON for L1-L2
    # RAG OFF group uses fixed context generated with RAG OFF for L1-L2
    fixed_context = load_fixed_context(rag_enabled_for_l1l2=rag_enabled)
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

    # Load Layer 3 reports from database (reports are not stored in state)
    from app.services.report_store import ReportStore
    store = ReportStore.get_instance()
    layer3_reports = await store.get_layer_reports(session_id, 3)

    results = {
        "session_id": session_id,
        "rag_enabled": rag_enabled,
        "rag_layer_config": rag_layer_config,
        "fixed_context_source": "rag_on" if rag_enabled else "rag_off",
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


def validate_and_analyze() -> Dict[str, Any]:
    """Step: Extract references and validate using injected knowledge.

    For RAG ON group: Uses injected_knowledge from fixed_context_rag_on.json
    For RAG OFF group: Uses KB global validation (no injected knowledge)

    Returns:
        Validation statistics
    """
    logger.info("[Validate] Extracting references and validating...")

    from scripts.experiments.rag_hallucination.reference_extractor import ReferenceExtractor
    from scripts.experiments.rag_hallucination.hallucination_validator import HallucinationValidator

    extractor = ReferenceExtractor()
    validator = HallucinationValidator()

    results = {"rag_on": {}, "rag_off": {}}

    # Load fixed contexts to get injected knowledge
    rag_on_context = load_fixed_context(rag_enabled_for_l1l2=True)
    rag_off_context = load_fixed_context(rag_enabled_for_l1l2=False)

    for group, group_dir, context in [
        ("rag_on", RAG_ON_DIR, rag_on_context),
        ("rag_off", RAG_OFF_DIR, rag_off_context),
    ]:
        injected_knowledge = context.get("injected_knowledge", {}) if context else {}
        all_validations = []

        for dim_key in RAG_ENABLED_DIMENSIONS:
            report_file = group_dir / f"{dim_key}.json"
            if not report_file.exists():
                logger.warning(f"[Validate] {group}/{dim_key}.json not found")
                continue

            with open(report_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)

            content = report_data.get("content", "")
            if not content:
                continue

            # Extract references
            references = extractor.extract(content)
            logger.info(f"[{group}] {dim_key}: Extracted {len(references)} references")

            # Validate references using injected knowledge if available
            validations = []
            for ref in references:
                if injected_knowledge:
                    # Use injected knowledge validation
                    result = validator.validate_with_injected_knowledge(ref, injected_knowledge)
                else:
                    # Use KB global validation
                    result = validator.validate_reference(ref)
                validations.append(result)

            # Statistics
            stats = validator.get_validation_statistics(validations)
            all_validations.extend(validations)

            results[group][dim_key] = {
                "reference_count": len(references),
                "validations": [v.to_dict() for v in validations],
                "statistics": stats,
                "injected_knowledge_used": bool(injected_knowledge),
            }

        # Calculate overall hallucination rate
        if all_validations:
            overall_stats = validator.get_validation_statistics(all_validations)
            results[group]["overall"] = overall_stats

    # Save validation results
    validation_file = RAG_HALLUCINATION_DIR / "validation_results.json"
    with open(validation_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"[Validate] Results saved to {validation_file}")
    return results


async def check_service_health() -> bool:
    """检查规划服务是否可用

    Returns:
        服务是否健康
    """
    try:
        from app.services.runtime import PlanningRuntimeService
        await PlanningRuntimeService.ensure_initialized()
        logger.info("[Health] Planning service is available")
        return True
    except Exception as e:
        logger.error(f"[Health] Planning service unavailable: {e}")
        return False


def calculate_iteration_statistics(results: list) -> Dict[str, Any]:
    """计算多次迭代的统计量

    Args:
        results: 多次迭代的实验结果列表

    Returns:
        统计信息（均值、标准差、最小值、最大值）
    """
    import numpy as np

    if not results:
        return {"iterations": 0}

    rag_on_rates = []
    rag_off_rates = []

    for r in results:
        rag_on_overall = r.get("rag_on", {}).get("overall", {})
        rag_off_overall = r.get("rag_off", {}).get("overall", {})

        rates_on = rag_on_overall.get("hallucination_rates", {})
        rates_off = rag_off_overall.get("hallucination_rates", {})

        rag_on_rates.append(rates_on.get("strict", 0))
        rag_off_rates.append(rates_off.get("strict", 0))

    stats = {
        "iterations": len(results),
        "rag_on": {
            "mean": float(np.mean(rag_on_rates)) if rag_on_rates else 0,
            "std": float(np.std(rag_on_rates)) if rag_on_rates else 0,
            "min": float(np.min(rag_on_rates)) if rag_on_rates else 0,
            "max": float(np.max(rag_on_rates)) if rag_on_rates else 0,
            "values": rag_on_rates,
        },
        "rag_off": {
            "mean": float(np.mean(rag_off_rates)) if rag_off_rates else 0,
            "std": float(np.std(rag_off_rates)) if rag_off_rates else 0,
            "min": float(np.min(rag_off_rates)) if rag_off_rates else 0,
            "max": float(np.max(rag_off_rates)) if rag_off_rates else 0,
            "values": rag_off_rates,
        },
    }

    # 计算幻觉率降低百分比
    if stats["rag_off"]["mean"] > 0:
        reduction = (stats["rag_off"]["mean"] - stats["rag_on"]["mean"]) / stats["rag_off"]["mean"]
        stats["reduction_percentage"] = float(reduction * 100)

    return stats


def cleanup_experiment_data(keep_latest: int = 3):
    """清理历史实验数据

    Args:
        keep_latest: 保留最近N次实验数据
    """
    import shutil

    # 清理session文件
    session_dirs = list(Path("output/sessions").glob("rag_*"))
    if len(session_dirs) > keep_latest:
        session_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for old_dir in session_dirs[keep_latest:]:
            shutil.rmtree(old_dir)
            logger.info(f"[Cleanup] Removed old session: {old_dir}")

    # 清理中间输出
    for pattern in ["*.tmp", "*.log"]:
        for f in RAG_HALLUCINATION_DIR.glob(pattern):
            f.unlink()
            logger.info(f"[Cleanup] Removed temp file: {f}")


async def run_experiment(step: str = "all", iterations: int = 1):
    """Run RAG hallucination experiment.

    Steps:
    1. generate-fixed-context-on: Generate fixed context with RAG ON for L1-L2
    2. generate-fixed-context-off: Generate fixed context with RAG OFF for L1-L2
    3. generate-rag-on: Generate Layer 3 reports with RAG ON
    4. generate-rag-off: Generate Layer 3 reports with RAG OFF
    5. validate: Extract and validate references
    6. generate-outputs: Generate output documents

    Args:
        step: Experiment step to run
        iterations: Number of iterations (for variance calculation)
    """
    # 服务健康检查
    if step not in ["validate", "validate-only", "generate-outputs"]:
        if not await check_service_health():
            logger.error("[Experiment] Aborted: service health check failed")
            return {"error": "Service unavailable"}

    ensure_rag_experiment_dirs()
    logger.info("=" * 60)
    logger.info(f"[RAG Experiment] Starting - Step: {step}, Iterations: {iterations}")
    logger.info("=" * 60)

    all_results = []

    for i in range(iterations):
        logger.info(f"[Experiment] Iteration {i+1}/{iterations}")

        # 设置随机种子（确保可复现）
        import random
        random.seed(42 + i)

        iteration_result = await _run_single_iteration(step)
        all_results.append(iteration_result)

    # 计算多次迭代统计量
    if iterations > 1:
        stats = calculate_iteration_statistics(all_results)
        stats_file = RAG_HALLUCINATION_DIR / "iteration_statistics.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        logger.info(f"[Experiment] Iteration statistics saved to {stats_file}")

    # 清理历史数据
    cleanup_experiment_data(keep_latest=3)

    logger.info("=" * 60)
    logger.info("[RAG Experiment] Completed")
    logger.info("=" * 60)

    return all_results


async def _run_single_iteration(step: str) -> Dict[str, Any]:
    """运行单次实验迭代

    Args:
        step: 实验步骤

    Returns:
        单次迭代结果
    """
    result = {"step": step, "timestamp": datetime.now().isoformat()}

    # Generate both fixed contexts
    if step == "all" or step == "generate-fixed-context":
        # Generate fixed context with RAG ON for Layer 1-2
        await generate_fixed_context(rag_enabled_for_l1l2=True, timeout=1800)
        # Generate fixed context with RAG OFF for Layer 1-2
        await generate_fixed_context(rag_enabled_for_l1l2=False, timeout=1800)

    if step == "all" or step == "generate-fixed-context-on":
        await generate_fixed_context(rag_enabled_for_l1l2=True, timeout=1800)

    if step == "all" or step == "generate-fixed-context-off":
        await generate_fixed_context(rag_enabled_for_l1l2=False, timeout=1800)

    if step == "all" or step == "generate-rag-on":
        rag_on_result = await generate_layer3_reports(rag_enabled=True, output_dir=RAG_ON_DIR, timeout=600)
        result["rag_on_generation"] = rag_on_result

    if step == "all" or step == "generate-rag-off":
        rag_off_result = await generate_layer3_reports(rag_enabled=False, output_dir=RAG_OFF_DIR, timeout=600)
        result["rag_off_generation"] = rag_off_result

    if step == "all" or step == "validate" or step == "validate-only":
        validation_result = validate_and_analyze()
        result["validation"] = validation_result

    if step == "all" or step == "generate-outputs":
        generate_output_documents()

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RAG Hallucination Experiment")
    parser.add_argument(
        "--step",
        default="all",
        choices=[
            "all",
            "generate-fixed-context",
            "generate-fixed-context-on",
            "generate-fixed-context-off",
            "generate-rag-on",
            "generate-rag-off",
            "validate",
            "validate-only",
            "generate-outputs",
        ],
        help="Experiment step to run",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations for variance calculation (default: 1)",
    )
    args = parser.parse_args()
    asyncio.run(run_experiment(step=args.step, iterations=args.iterations))


if __name__ == "__main__":
    main()
