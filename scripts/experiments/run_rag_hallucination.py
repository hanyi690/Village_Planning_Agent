"""
RAG Hallucination Rate Experiment
RAG开启/关闭条件下的法规引用幻觉率对比实验

目的：量化垂直领域知识检索增强对大模型法规引用幻觉的抑制效果

实验对象：Layer 3 中 5 个启用 RAG 的关键维度
- land_use_planning（土地利用规划）
- infrastructure_planning（基础设施规划）
- ecological（生态绿地规划）
- disaster_prevention（防震减灾规划）
- heritage（历史文保规划）

操作步骤：
1. 完成正常运行，保存 Layer1/2 输出作为固定上下文
2. 实验组：RAG开启，生成5个维度
3. 对照组：RAG关闭，生成5个维度
4. 人工核查标注法规引用
5. 统计幻觉率

使用方法:
    python scripts/experiments/run_rag_hallucination.py --step all
    python scripts/experiments/run_rag_hallucination.py --step generate-fixed-context
    python scripts/experiments/run_rag_hallucination.py --step generate-rag-on


    


    python scripts/experiments/run_rag_hallucination.py --step generate-rag-off
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from copy import deepcopy

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    RAG_ENABLED_DIMENSIONS,
    RAG_HALLUCINATION_DIR,
    RAG_ON_DIR,
    RAG_OFF_DIR,
    FIXED_CONTEXT_DIR,
    ANNOTATION_DIR,
    JINTIAN_VILLAGE_DATA,
    ensure_rag_experiment_dirs,
    BASELINE_DIR,
    load_status_report,
)
from scripts.experiments.layer_checkpoint_utils import (
    wait_for_layer_completion,
    save_layer_checkpoint,
    compute_state_fingerprint,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Step 1: Generate Fixed Context
# ============================================

async def run_full_planning_flow(project_name: str, village_data: Dict, timeout: int = 1800) -> Dict[str, Any]:
    """
    Run complete planning flow to get Layer 1/2 outputs.

    Args:
        project_name: Project name
        village_data: Village configuration data
        timeout: Maximum wait time in seconds

    Returns:
        Session state with complete reports
    """
    from backend.services.planning_runtime_service import PlanningRuntimeService

    logger.info(f"[FixedContext] Starting full planning: {project_name}")

    # Start session with step_mode=True to capture intermediate states
    # Pass full status report content, not just village name
    session_id = await PlanningRuntimeService.start_session(
        project_name=project_name,
        village_data=village_data.get("status_report", ""),
        village_name=village_data.get("village_name", "金田村"),
        step_mode=True,  # Manual approval needed to capture states
    )

    logger.info(f"[FixedContext] Session started: {session_id}")

    # Wait for Layer 2 completion (then we have all Layer 1 and 2 outputs)
    state = await wait_for_layer2_completion(session_id, timeout)

    return {
        "session_id": session_id,
        "project_name": project_name,
        **state,
    }


async def wait_for_layer2_completion(session_id: str, timeout: int = 1800) -> Dict[str, Any]:
    """
    Wait for Layer 2 completion using shared layer checkpoint utilities.

    Args:
        session_id: Session identifier
        timeout: Maximum wait time in seconds

    Returns:
        State at Layer 2 completion with checkpoint_id
    """
    logger.info(f"[FixedContext] Waiting for Layer 2 (timeout={timeout}s)")

    # Use shared utility with layer=2
    snapshot = await wait_for_layer_completion(
        session_id=session_id,
        layer=2,
        timeout=timeout,
    )

    if snapshot.get("success"):
        logger.info(f"[FixedContext] Layer 2 completed! checkpoint_id={snapshot.get('checkpoint_id', 'N/A')}")
        return {
            "session_id": session_id,
            "checkpoint_id": snapshot.get("checkpoint_id", ""),
            "state_fingerprint": snapshot.get("state_fingerprint", ""),
            "reports": snapshot.get("reports", {}),
            "completed_dimensions": snapshot.get("completed_dimensions", {}),
            "phase": snapshot.get("phase", ""),
            "pause_after_step": True,
            "previous_layer": 2,
        }
    else:
        logger.warning(f"[FixedContext] Layer 2 wait failed: {snapshot.get('error', 'Unknown error')}")
        # Fallback: return last known state
        from backend.services.checkpoint_service import checkpoint_service
        state = await checkpoint_service.get_state(session_id) or {}
        return state


def save_fixed_context(state: Dict[str, Any]):
    """
    Save Layer 1 and 2 outputs as fixed context.

    Args:
        state: Session state at Layer 2 completion (with checkpoint_id)
    """
    session_id = state.get("session_id", "unknown")
    checkpoint_id = state.get("checkpoint_id", "")
    state_fingerprint = state.get("state_fingerprint", "")
    reports = state.get("reports", {})
    completed_dimensions = state.get("completed_dimensions", {})

    # Save session metadata with checkpoint info
    session_meta = {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "state_fingerprint": state_fingerprint,
        "project_name": state.get("project_name", ""),
        "phase": state.get("phase", ""),
        "created_at": datetime.now().isoformat(),
        "dimensions_with_rag": RAG_ENABLED_DIMENSIONS,
    }
    with open(FIXED_CONTEXT_DIR / "session_id.json", "w", encoding="utf-8") as f:
        json.dump(session_meta, f, indent=2, ensure_ascii=False)
    logger.info(f"[FixedContext] Saved session_id.json (checkpoint_id={checkpoint_id})")

    # Build snapshot for save_layer_checkpoint utility
    # Layer 1 snapshot
    layer1_snapshot = {
        "layer": 1,
        "checkpoint_id": checkpoint_id,  # Same checkpoint for both layers
        "phase": state.get("phase", ""),
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "timestamp": datetime.now().isoformat(),
        "state_fingerprint": state_fingerprint,
        "success": True,
    }
    save_layer_checkpoint(layer1_snapshot, FIXED_CONTEXT_DIR, 1)

    # Layer 2 snapshot
    layer2_snapshot = {
        "layer": 2,
        "checkpoint_id": checkpoint_id,
        "phase": state.get("phase", ""),
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "timestamp": datetime.now().isoformat(),
        "state_fingerprint": state_fingerprint,
        "success": True,
    }
    save_layer_checkpoint(layer2_snapshot, FIXED_CONTEXT_DIR, 2)

    # Save raw_data and other inputs
    raw_data = state.get("raw_data", "")
    with open(FIXED_CONTEXT_DIR / "raw_data.json", "w", encoding="utf-8") as f:
        json.dump({"raw_data": raw_data[:50000] if raw_data else "", "truncated": len(raw_data) > 50000}, f, indent=2)
    logger.info(f"[FixedContext] Saved raw_data.json")


def load_fixed_context_from_baseline() -> Dict[str, Any]:
    """
    Load fixed context from baseline checkpoint directory.

    This allows using existing baseline Layer 1/2 reports without
    running the full planning flow again.

    Returns:
        Fixed context data from baseline
    """
    context = {}

    # Load session metadata
    session_file = BASELINE_DIR / "session_id.json"
    if session_file.exists():
        with open(session_file, "r", encoding="utf-8") as f:
            context["session_meta"] = json.load(f)
        logger.info(f"[Baseline] Loaded session_id.json")
    else:
        logger.warning(f"[Baseline] session_id.json not found")

    # Load layer1 reports
    layer1_file = BASELINE_DIR / "layer1_reports.json"
    if layer1_file.exists():
        with open(layer1_file, "r", encoding="utf-8") as f:
            context["layer1"] = json.load(f)
        logger.info(f"[Baseline] Loaded layer1_reports.json")
    else:
        logger.warning(f"[Baseline] layer1_reports.json not found")

    # Load layer2 reports
    layer2_file = BASELINE_DIR / "layer2_reports.json"
    if layer2_file.exists():
        with open(layer2_file, "r", encoding="utf-8") as f:
            context["layer2"] = json.load(f)
        logger.info(f"[Baseline] Loaded layer2_reports.json")
    else:
        logger.warning(f"[Baseline] layer2_reports.json not found")

    # Load raw_data from status report
    context["raw_data"] = load_status_report()
    logger.info(f"[Baseline] Loaded raw_data: {len(context['raw_data'])} chars")

    return context


def load_fixed_context(from_baseline: bool = False) -> Dict[str, Any]:
    """
    Load fixed context from saved files.

    Args:
        from_baseline: If True, load from baseline checkpoint directory
                       instead of rag_hallucination/fixed_context/

    Returns:
        Fixed context data
    """
    if from_baseline:
        return load_fixed_context_from_baseline()

    context = {}

    session_file = FIXED_CONTEXT_DIR / "session_id.json"
    if session_file.exists():
        with open(session_file, "r", encoding="utf-8") as f:
            context["session_meta"] = json.load(f)

    layer1_file = FIXED_CONTEXT_DIR / "layer1_reports.json"
    if layer1_file.exists():
        with open(layer1_file, "r", encoding="utf-8") as f:
            context["layer1"] = json.load(f)

    layer2_file = FIXED_CONTEXT_DIR / "layer2_reports.json"
    if layer2_file.exists():
        with open(layer2_file, "r", encoding="utf-8") as f:
            context["layer2"] = json.load(f)

    raw_data_file = FIXED_CONTEXT_DIR / "raw_data.json"
    if raw_data_file.exists():
        with open(raw_data_file, "r", encoding="utf-8") as f:
            context["raw_data"] = json.load(f).get("raw_data", "")

    return context


# ============================================
# Step 2/3: Generate Dimension Reports (Full System Flow)
# ============================================

async def start_session_from_fixed_context(
    fixed_context: Dict[str, Any],
    rag_enabled: bool,
) -> str:
    """
    Start session from fixed Layer1/2 context and continue to Layer 3.

    Uses _trigger_planning_execution to restore execution from checkpoint,
    ensuring complete system flow (not simplified planner execution).

    Args:
        fixed_context: Fixed Layer 1/2 context from load_fixed_context()
        rag_enabled: Whether to enable RAG for target dimensions

    Returns:
        Session ID of the restored session
    """
    from backend.services.planning_runtime_service import PlanningRuntimeService
    from backend.services.sse_manager import sse_manager
    from src.config.dimension_metadata import DIMENSIONS_METADATA

    # 1. Generate session_id
    session_id = f"rag_{('on' if rag_enabled else 'off')}_{uuid.uuid4().hex[:8]}"
    await PlanningRuntimeService.ensure_initialized()

    # 2. Temporarily modify RAG config for target dimensions
    original_configs = {}
    for dim in RAG_ENABLED_DIMENSIONS:
        original_configs[dim] = DIMENSIONS_METADATA[dim].get("rag_enabled", False)
        DIMENSIONS_METADATA[dim]["rag_enabled"] = rag_enabled

    try:
        # 3. Initialize SSE manager (required for resume_execution)
        sse_manager.init_session(session_id, {"session_id": session_id})

        # 4. Write initial state via aupdate_state (public API)
        # Build initial_state (fixed Layer1/2 + empty Layer3)
        initial_state = {
            "session_id": session_id,
            "project_name": f"RAG实验_{('ON' if rag_enabled else 'OFF')}",
            "config": {
                "village_data": JINTIAN_VILLAGE_DATA.get("administrative", ""),
                "village_name": JINTIAN_VILLAGE_DATA.get("village_name", "金田村"),
            },
            "phase": "layer3",  # Direct to Layer 3
            "reports": {
                "layer1": fixed_context.get("layer1", {}).get("reports", {}),
                "layer2": fixed_context.get("layer2", {}).get("reports", {}),
                "layer3": {},
            },
            "completed_dimensions": {
                "layer1": fixed_context.get("layer1", {}).get("completed_dimensions", []),
                "layer2": fixed_context.get("layer2", {}).get("completed_dimensions", []),
                "layer3": [],
            },
            "pause_after_step": False,
        }

        # Write state to checkpoint (public API)
        await PlanningRuntimeService.aupdate_state(session_id, initial_state)
        logger.info(f"[FullFlow] Initial checkpoint created for {session_id}")

        # 5. Resume execution (public API)
        # This triggers _trigger_planning_execution internally with synthetic message
        await PlanningRuntimeService.resume_execution(session_id)

        logger.info(f"[FullFlow] Session started: {session_id}, RAG={rag_enabled}")
        return session_id

    finally:
        # 6. Restore original RAG configs
        for dim, original in original_configs.items():
            DIMENSIONS_METADATA[dim]["rag_enabled"] = original


async def wait_for_layer3_completion(session_id: str, timeout: int = 600) -> Dict[str, Any]:
    """
    Wait for Layer 3 completion in a restored session.

    Args:
        session_id: Session identifier
        timeout: Maximum wait time in seconds

    Returns:
        Final state with Layer 3 reports
    """
    from backend.services.checkpoint_service import checkpoint_service

    logger.info(f"[FullFlow] Waiting for Layer 3 completion (session={session_id})")

    start_time = datetime.now()
    check_interval = 10

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            logger.warning(f"[FullFlow] Timeout after {elapsed}s")
            break

        state = await checkpoint_service.get_state(session_id)
        if state:
            phase = state.get("phase", "")
            layer3_completed = state.get("completed_dimensions", {}).get("layer3", [])

            logger.info(f"[FullFlow] Phase: {phase}, Layer3 dims: {len(layer3_completed)}")

            # Check if all RAG dimensions completed
            if set(RAG_ENABLED_DIMENSIONS).issubset(set(layer3_completed)):
                logger.info("[FullFlow] All RAG dimensions completed!")
                return state

            # Or if phase is completed
            if phase == "completed":
                logger.info("[FullFlow] Session completed!")
                return state

        await asyncio.sleep(check_interval)

    return await checkpoint_service.get_state(session_id) or {}


async def generate_all_dimensions_full_flow(
    rag_enabled: bool,
    output_dir: Path,
    timeout: int = 600,
    from_baseline: bool = False,
) -> Dict[str, Any]:
    """
    Generate all RAG dimensions using full system flow.

    This method uses _trigger_planning_execution to restore from fixed context,
    ensuring complete LangGraph execution (not simplified planner).

    Args:
        rag_enabled: RAG setting
        output_dir: Output directory
        timeout: Maximum wait time for Layer 3 completion
        from_baseline: If True, load context from baseline checkpoint

    Returns:
        Generation results with Layer 3 reports
    """
    ensure_rag_experiment_dirs()

    # Load fixed context
    context = load_fixed_context(from_baseline=from_baseline)
    if not context:
        logger.error("[FullFlow] Fixed context not found!")
        return {"error": "Fixed context not found"}

    # Start session from fixed context
    session_id = await start_session_from_fixed_context(context, rag_enabled)

    # Wait for Layer 3 completion
    state = await wait_for_layer3_completion(session_id, timeout)

    # Extract results
    layer3_reports = state.get("reports", {}).get("layer3", {})
    layer3_completed = state.get("completed_dimensions", {}).get("layer3", [])

    results = {
        "session_id": session_id,
        "rag_enabled": rag_enabled,
        "dimensions": RAG_ENABLED_DIMENSIONS,
        "generated_at": datetime.now().isoformat(),
        "reports": {},
        "completed_dimensions": layer3_completed,
    }

    # Save each dimension report
    for dimension_key in RAG_ENABLED_DIMENSIONS:
        content = layer3_reports.get(dimension_key, "")
        result = {
            "dimension_key": dimension_key,
            "rag_enabled": rag_enabled,
            "content": content,
            "success": bool(content),
            "generated_at": datetime.now().isoformat(),
        }
        results["reports"][dimension_key] = result

        with open(output_dir / f"{dimension_key}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"[FullFlow] Saved {dimension_key}.json")

    # Save summary
    with open(output_dir / "experiment_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"[FullFlow] Completed: {len(results['reports'])} dimensions")
    return results


# ============================================
# Step 2/3: Generate Dimension Reports (Simplified Flow)
# ============================================

async def generate_dimension_with_rag(
    dimension_key: str,
    context: Dict[str, Any],
    rag_enabled: bool,
    session_id: str,
) -> Dict[str, Any]:
    """
    Generate single dimension report with RAG on/off.

    Args:
        dimension_key: Dimension to generate
        context: Fixed Layer 1/2 context
        rag_enabled: RAG setting
        session_id: Session ID for SSE events

    Returns:
        Generated dimension result
    """
    from src.config.dimension_metadata import get_dimension_config, DIMENSIONS_METADATA
    from src.planners.generic_planner import GenericPlannerFactory
    from src.rag.core.tools import search_knowledge

    logger.info(f"[Generate] {dimension_key} with RAG={rag_enabled}")

    # Temporarily modify dimension config
    original_config = DIMENSIONS_METADATA.get(dimension_key)
    if original_config:
        original_rag_enabled = original_config.get("rag_enabled", False)
        # Modify in-place (will restore later)
        DIMENSIONS_METADATA[dimension_key]["rag_enabled"] = rag_enabled

    # Execute RAG retrieval if enabled (use real flow, not mock)
    knowledge_cache = {}
    knowledge_injected = ""

    if rag_enabled:
        try:
            # Build query from dimension context
            dim_name = get_dimension_config(dimension_key).get("name", dimension_key)
            task_desc = context.get("layer2", {}).get("reports", {}).get("planning_positioning", "")[:100]
            query = f"{dim_name} 规划标准 技术指标 法规"
            if task_desc:
                query = f"{query} {task_desc}"

            # Call real RAG search (same as knowledge_preload_node)
            knowledge_injected = search_knowledge(
                query=query,
                top_k=3,
                context_mode="standard",
                dimension=dimension_key,
            )

            # Fill knowledge_cache (in both locations for compatibility)
            knowledge_cache[dimension_key] = knowledge_injected if knowledge_injected and not knowledge_injected.startswith("❌") else ""

            logger.info(f"[Generate] RAG检索完成: {len(knowledge_injected)} chars for {dimension_key}")
            logger.info(f"[Generate] knowledge_cache: {len(knowledge_cache.get(dimension_key, ''))} chars")

        except Exception as e:
            logger.warning(f"[Generate] RAG检索失败: {e}, 使用空缓存")
            knowledge_cache = {}
            knowledge_injected = ""

    # Build planner state from fixed context (with real knowledge_cache)
    planner_state = {
        "project_name": context.get("session_meta", {}).get("project_name", "金田村"),
        "session_id": session_id,
        "raw_data": context.get("raw_data", ""),
        "reports": {
            "layer1": context.get("layer1", {}).get("reports", {}),
            "layer2": context.get("layer2", {}).get("reports", {}),
        },
        "completed_dimensions": {
            "layer1": context.get("layer1", {}).get("completed_dimensions", []),
            "layer2": context.get("layer2", {}).get("completed_dimensions", []),
        },
        "knowledge_cache": knowledge_cache,  # Real knowledge from RAG (not empty mock)
        "config": {
            "knowledge_cache": knowledge_cache,  # Also in config for compatibility
            "task_description": context.get("layer2", {}).get("reports", {}).get("planning_positioning", ""),
        },
    }

    # Filter state for this dimension
    from src.config.dimension_metadata import filter_reports_by_dependency, get_full_dependency_chain_func
    from src.config.dimension_metadata import get_analysis_dimension_names, get_concept_dimension_names

    chain = get_full_dependency_chain_func(dimension_key)
    analysis_reports = planner_state["reports"]["layer1"]
    concept_reports = planner_state["reports"]["layer2"]

    planner_state["filtered_analysis"] = filter_reports_by_dependency(
        required_keys=chain.get("layer1_analyses", []),
        reports=analysis_reports,
        name_mapping=get_analysis_dimension_names()
    )
    planner_state["filtered_concept"] = filter_reports_by_dependency(
        required_keys=chain.get("layer2_concepts", []),
        reports=concept_reports,
        name_mapping=get_concept_dimension_names()
    )

    try:
        # Create planner
        planner = GenericPlannerFactory.create_planner(dimension_key)

        # Execute planner
        result = planner.execute(
            state=planner_state,
            streaming=False,
        )

        logger.info(f"[Generate] {dimension_key} completed: {len(result.get('detailed_plan', ''))} chars, knowledge_used={len(knowledge_injected)} chars")

        return {
            "dimension_key": dimension_key,
            "dimension_name": result.get("dimension_name", dimension_key),
            "rag_enabled": rag_enabled,
            "content": result.get("detailed_plan", ""),
            "knowledge_injected": knowledge_injected,  # Track what RAG retrieved
            "knowledge_cache_size": len(knowledge_cache.get(dimension_key, "")),
            "success": result.get("success", False),
            "error": result.get("error", None),
            "generated_at": datetime.now().isoformat(),
        }

    except Exception as e:
        logger.error(f"[Generate] {dimension_key} failed: {e}")
        return {
            "dimension_key": dimension_key,
            "rag_enabled": rag_enabled,
            "content": "",
            "knowledge_injected": knowledge_injected,
            "knowledge_cache_size": 0,
            "success": False,
            "error": str(e),
            "generated_at": datetime.now().isoformat(),
        }

    finally:
        # Restore original config
        if original_config:
            DIMENSIONS_METADATA[dimension_key]["rag_enabled"] = original_rag_enabled


async def generate_all_dimensions(rag_enabled: bool, output_dir: Path, from_baseline: bool = False) -> Dict[str, Any]:
    """
    Generate all 5 RAG dimensions with specified RAG setting.

    Args:
        rag_enabled: RAG setting
        output_dir: Output directory
        from_baseline: If True, load context from baseline checkpoint

    Returns:
        Generation results
    """
    ensure_rag_experiment_dirs()

    # Load fixed context
    context = load_fixed_context(from_baseline=from_baseline)
    if not context:
        logger.error("[Generate] Fixed context not found! Run --step generate-fixed-context first.")
        return {"error": "Fixed context not found"}

    # Generate session ID for this experiment run
    exp_session_id = f"rag_{('on' if rag_enabled else 'off')}_{uuid.uuid4().hex[:8]}"

    results = {
        "session_id": exp_session_id,
        "rag_enabled": rag_enabled,
        "dimensions": RAG_ENABLED_DIMENSIONS,
        "generated_at": datetime.now().isoformat(),
        "reports": {},
    }

    # Generate each dimension
    for dimension_key in RAG_ENABLED_DIMENSIONS:
        result = await generate_dimension_with_rag(
            dimension_key=dimension_key,
            context=context,
            rag_enabled=rag_enabled,
            session_id=exp_session_id,
        )
        results["reports"][dimension_key] = result

        # Save individual dimension report
        with open(output_dir / f"{dimension_key}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"[Generate] Saved {dimension_key}.json")

    # Save summary
    with open(output_dir / "experiment_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    logger.info(f"[Generate] Completed {len(results['reports'])} dimensions")
    return results


# ============================================
# Step 4: Annotation Template
# ============================================

def create_annotation_template():
    """
    Create annotation template for human review.

    Generates Excel template for annotating regulation references.
    """
    from scripts.experiments.config import REGULATION_ANNOTATION_FIELDS

    ensure_rag_experiment_dirs()

    # Check if we have generated reports
    rag_on_reports = {}
    rag_off_reports = {}

    for dimension_key in RAG_ENABLED_DIMENSIONS:
        on_file = RAG_ON_DIR / f"{dimension_key}.json"
        off_file = RAG_OFF_DIR / f"{dimension_key}.json"

        if on_file.exists():
            with open(on_file, "r", encoding="utf-8") as f:
                rag_on_reports[dimension_key] = json.load(f)

        if off_file.exists():
            with open(off_file, "r", encoding="utf-8") as f:
                rag_off_reports[dimension_key] = json.load(f)

    if not rag_on_reports and not rag_off_reports:
        logger.warning("[Annotation] No generated reports found!")
        return

    # Create annotation data structure
    annotation_data = []

    for dimension_key in RAG_ENABLED_DIMENSIONS:
        # RAG ON
        if dimension_key in rag_on_reports:
            annotation_data.append({
                "dimension_key": dimension_key,
                "condition": "RAG_ON",
                "content": rag_on_reports[dimension_key].get("content", ""),
                "content_length": len(rag_on_reports[dimension_key].get("content", "")),
            })

        # RAG OFF
        if dimension_key in rag_off_reports:
            annotation_data.append({
                "dimension_key": dimension_key,
                "condition": "RAG_OFF",
                "content": rag_off_reports[dimension_key].get("content", ""),
                "content_length": len(rag_off_reports[dimension_key].get("content", "")),
            })

    # Save annotation template
    template = {
        "annotation_fields": REGULATION_ANNOTATION_FIELDS,
        "dimensions": annotation_data,
        "instructions": """
标注指南：
1. 对每个维度的生成文本，逐一标注所有涉及法规的表述
2. 标注粒度为"单条法规引用"
3. 每条引用需判定：是否正确、错误分类、核查依据
4. "部分错误"指法规名称真实但条款编号或内容不符
5. 在统计幻觉率时，"部分错误"与"虚构"均计入错误数
""",
        "created_at": datetime.now().isoformat(),
    }

    with open(ANNOTATION_DIR / "annotation_template.json", "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    logger.info(f"[Annotation] Created template for {len(annotation_data)} dimension reports")


# ============================================
# Mock Functions (for testing)
# ============================================

async def mock_generate_fixed_context() -> Dict[str, Any]:
    """Mock function for testing without full runtime."""
    logger.info("[Mock] Generating mock fixed context")

    # Try to load existing jintian reports
    reports_dir = Path(__file__).parent.parent.parent / "docs"

    reports = {"layer1": {}, "layer2": {}}
    completed_dimensions = {"layer1": [], "layer2": []}

    for layer in [1, 2]:
        report_path = reports_dir / f"layer{layer}_完整报告.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            reports[f"layer{layer}"]["full_report"] = content
            completed_dimensions[f"layer{layer}"] = ["full_report"]
            logger.info(f"[Mock] Loaded layer{layer} report: {len(content)} chars")

    session_id = f"mock_fixed_{uuid.uuid4().hex[:8]}"

    state = {
        "session_id": session_id,
        "project_name": "金田村",
        "phase": "layer2",
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "pause_after_step": True,
        "previous_layer": 2,
    }

    save_fixed_context(state)
    return state


async def mock_generate_dimension(dimension_key: str, rag_enabled: bool) -> Dict[str, Any]:
    """Mock function for testing."""
    logger.info(f"[Mock] Generating mock {dimension_key} with RAG={rag_enabled}")

    return {
        "dimension_key": dimension_key,
        "dimension_name": dimension_key,
        "rag_enabled": rag_enabled,
        "content": f"Mock content for {dimension_key} with RAG={rag_enabled}",
        "success": True,
        "error": None,
        "generated_at": datetime.now().isoformat(),
    }


# ============================================
# Main Entry Point
# ============================================

async def run_experiment(step: str = "all", use_mock: bool = False, use_full_flow: bool = True, from_baseline: bool = False):
    """
    Run RAG hallucination experiment.

    Args:
        step: Experiment step to run
            - all: Run all steps
            - generate-fixed-context: Step 1
            - generate-rag-on: Step 2
            - generate-rag-off: Step 3
            - create-template: Step 4
        use_mock: Use mock data for testing
        use_full_flow: Use complete LangGraph flow (via _trigger_planning_execution)
                       If False, use simplified planner.execute() flow
        from_baseline: Load context from baseline checkpoint instead of fixed_context directory
    """
    ensure_rag_experiment_dirs()

    logger.info("=" * 60)
    logger.info("[RAG Hallucination] Starting experiment")
    logger.info(f"[RAG Hallucination] Step: {step}")
    logger.info(f"[RAG Hallucination] Full flow: {use_full_flow}")
    logger.info(f"[RAG Hallucination] From baseline: {from_baseline}")
    logger.info("=" * 60)

    try:
        if step == "all" or step == "generate-fixed-context":
            logger.info("\n--- Step 1: Generate Fixed Context ---")
            if use_mock:
                await mock_generate_fixed_context()
            else:
                state = await run_full_planning_flow(
                    project_name="金田村RAG实验",
                    village_data=JINTIAN_VILLAGE_DATA,
                    timeout=1800,
                )
                save_fixed_context(state)

        if step == "all" or step == "generate-rag-on":
            logger.info("\n--- Step 2: Generate with RAG ON ---")
            if use_mock:
                for dim in RAG_ENABLED_DIMENSIONS:
                    result = await mock_generate_dimension(dim, True)
                    with open(RAG_ON_DIR / f"{dim}.json", "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
            elif use_full_flow:
                await generate_all_dimensions_full_flow(rag_enabled=True, output_dir=RAG_ON_DIR, from_baseline=from_baseline)
            else:
                await generate_all_dimensions(rag_enabled=True, output_dir=RAG_ON_DIR, from_baseline=from_baseline)

        if step == "all" or step == "generate-rag-off":
            logger.info("\n--- Step 3: Generate with RAG OFF ---")
            if use_mock:
                for dim in RAG_ENABLED_DIMENSIONS:
                    result = await mock_generate_dimension(dim, False)
                    with open(RAG_OFF_DIR / f"{dim}.json", "w", encoding="utf-8") as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
            elif use_full_flow:
                await generate_all_dimensions_full_flow(rag_enabled=False, output_dir=RAG_OFF_DIR, from_baseline=from_baseline)
            else:
                await generate_all_dimensions(rag_enabled=False, output_dir=RAG_OFF_DIR, from_baseline=from_baseline)

        if step == "all" or step == "create-template":
            logger.info("\n--- Step 4: Create Annotation Template ---")
            create_annotation_template()

        logger.info("=" * 60)
        logger.info("[RAG Hallucination] Experiment completed")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"[RAG Hallucination] Failed: {e}", exc_info=True)
        raise


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run RAG hallucination experiment")
    parser.add_argument("--step", type=str, default="all",
                        choices=["all", "generate-fixed-context", "generate-rag-on", "generate-rag-off", "create-template"],
                        help="Experiment step to run")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")
    parser.add_argument("--simplified", action="store_true",
                        help="Use simplified planner.execute() flow instead of full LangGraph")
    parser.add_argument("--from-baseline", action="store_true",
                        help="Load fixed context from baseline checkpoint instead of fixed_context directory")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    args = parser.parse_args()

    asyncio.run(run_experiment(step=args.step, use_mock=args.mock, use_full_flow=not args.simplified, from_baseline=args.from_baseline))


if __name__ == "__main__":
    main()