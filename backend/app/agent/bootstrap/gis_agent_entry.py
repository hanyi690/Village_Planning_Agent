"""GIS agent entry. Migrated from agent/graph.py per docs/architecture/agent-graph.md §5."""

from typing import Dict, Any, List, Literal, Optional
from langgraph.graph import END
from langgraph.errors import GraphInterrupt, NodeError
from langgraph.types import Command
from langchain_core.messages import AIMessage

from app.utils.logger import get_logger
logger = get_logger(__name__)


def _gis_error_handler(state: Dict[str, Any], error: NodeError) -> Command:
    """GIS Agent error handler — return error message to conversation instead of crashing."""
    logger.error("[gis_agent] Node %s failed: %s", error.node, error.error)
    return Command(
        update={"messages": [AIMessage(content=f"GIS 分析出错: {error.error}")]},
        goto=END,
    )


async def gis_agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GIS Agent node — post-L3 subgraph chain.

    Step 1: 构建 PlanningContext（bundle/KG/gazetteer/anchors/reports）。
    Step 2: 从 L3 报告编译 PlanningProgram（复用 l3_aggregate 的确定性编译器）。
    Step 3: 运行 post-L3 链（PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE
            -> RECONCILE -> DELIVER）。
    Step 4: SSE + 回写 AgentState（conservative：保留遗留 gis_* 字段并新增
            delivery_manifest）。
    """
    from app.agent.bootstrap.post_l3_chain import build_post_l3_chain
    from app.agent.bootstrap.post_l3_state import PostL3ChainState

    session_id = state.get("session_id", "")
    village_name = state.get("config", {}).get("village_name", "")

    # ── 单一路径：SessionPlanningContext 组装 bundle/KG/gazetteer/anchors/reports ──
    from app.services.context import build_planning_context

    context = await build_planning_context(
        session_id, village_name, include_reports=True
    )
    village_name = context.village_name or village_name
    gis_bundle = context.bundle

    user_uploaded = state.get("user_uploaded_data", {})
    has_uploaded_sources = any(
        source.startswith("upload:")
        for source in gis_bundle.metadata.provider_sources
    )
    if user_uploaded and not has_uploaded_sources:
        from app.modules.data.bundle_assembly_adapter import DataBundleAssemblyAdapter
        from app.modules.schema.types.canonical import VillageBundle

        metadata = gis_bundle.metadata.model_copy(
            update={"provider_sources": []},
            deep=True,
        )
        gis_bundle = VillageBundle(
            village_name=village_name,
            metadata=metadata,
        )
        merger = DataBundleAssemblyAdapter()
        for layer_key, geojson in user_uploaded.items():
            merger.merge_geojson_into_bundle(gis_bundle, layer_key, geojson)

    # ── Step 2: 从 L3 报告编译 PlanningProgram（确定性编译器）──
    planning_program = None
    try:
        from app.modules.ports.artifact_store import ArtifactRef
        from app.modules.schema.contracts.l3_contracts import PlanningProgram
        from app.services.artifact_store import FilesystemArtifactStore

        existing_ref = state.get("l3_program_ref")
        if isinstance(existing_ref, dict) and existing_ref.get("artifact_id"):
            ref = ArtifactRef(**existing_ref)
            payload = FilesystemArtifactStore().retrieve(ref)
            planning_program = PlanningProgram(**payload)
        else:
            from app.agent.l3_plan.aggregate import l3_aggregate

            l3_out = await l3_aggregate(
                {"session_id": session_id, "run_id": session_id, "context_version": ""}
            )
            ref = ArtifactRef(**l3_out["l3_program_ref"])
            payload = FilesystemArtifactStore().retrieve(ref)
            planning_program = PlanningProgram(**payload)
    except Exception as e:
        logger.warning("[gis_agent_node] L3 program compile failed: %s", e)
        planning_program = None

    # ── Step 3: 运行 post-L3 链（HITL: 捕获 interrupt 暂停）──
    chain_state = PostL3ChainState(
        session_id=session_id,
        village_name=village_name,
        run_id=session_id,
        context=context,
        context_version=getattr(context, "context_version", "") or "",
        planning_program=planning_program,
        messages=list(state.get("messages", []) or []),
    )

    from app.database.engine import get_global_checkpointer

    chain = build_post_l3_chain(checkpointer=await get_global_checkpointer())
    config = {"configurable": {"thread_id": session_id}}

    # context 含 KG 闭包/适配器等不可序列化对象，无法写入 checkpoint：
    # 从图输入剥离（checkpoint 存 None），节点经会话 context 缓存恢复。
    chain_input = chain_state.model_dump()
    chain_input["context"] = None

    try:
        chain_result = await chain.ainvoke(chain_input, config)
    except GraphInterrupt as exc:
        interrupt_payloads = _extract_interrupt_payloads(exc)
    else:
        interrupt_payloads = chain_result.get("__interrupt__") or []

    if interrupt_payloads:
        items = _pending_items_from_interrupts(interrupt_payloads)
        logger.info(
            "[gis_agent_node] post-L3 chain paused at human_review: %d items "
            "(thread_id=%s)", len(items), session_id,
        )
        return {
            "post_l3_pending_review": items,
            "post_l3_thread_id": session_id,
            "post_l3_status": "needs_human_review",
        }

    delivery_manifest = chain_result.get("delivery_manifest")
    layout_configs = list(chain_result.get("layout_configs", []) or [])
    validation_report = chain_result.get("validation_report")
    reconciliation_report = chain_result.get("reconciliation_report")
    export_result = chain_result.get("export_result") or {}
    render_result = list(chain_result.get("render_result", []) or [])
    render_artifact = chain_result.get("render_artifact") or {}
    execution_errors = list(chain_result.get("execution_errors", []) or [])

    # ── Step 4: SSE + return ──
    render_layers = render_result

    if render_layers and session_id:
        try:
            from app.utils.sse_publisher import SSEPublisher
            layer_types = [
                c.get("layerType") or c.get("layer_type") or "unknown"
                for c in render_layers
            ]
            SSEPublisher.send_gis_result(
                session_id=session_id,
                dimension_key="spatial_layout",
                dimension_name="空间布局",
                summary=f"生成 {len(render_layers)} 个图层: {', '.join(layer_types)}",
                layers=render_layers,
                pipeline_trace=state.get("pipeline_trace"),
            )
        except Exception as e:
            logger.warning(f"[gis_agent_node] SSE publish failed: %s", e)

    summary_payload = {
        "layout_configs": layout_configs,
        "export_result": export_result,
        "render_result": render_result,
        "validation_result": (
            {"passed": validation_report.overall_passed}
            if validation_report is not None
            else {}
        ),
        "execution_errors": execution_errors,
    }
    return {
        "messages": [AIMessage(content=_format_gis_result(summary_payload, layout_configs))],
        "delivery_manifest": delivery_manifest,
        "reconciliation_report_ref": reconciliation_report,
        "validation_report_ref": validation_report,
    }


async def _get_reports_and_summaries(
    state: Dict[str, Any],
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """从 DB 加载 L3 GIS 输入报告和 L1/L2/L3 冲突检测摘要。

    reports: 嵌套格式 {dk: {"summary": {"metrics": ...}, "content": ...}}
    summaries: 扁平格式 {dk: {dimension_key, layer, metrics, key_points, text_summary}}
    """
    session_id = state.get("session_id", "")
    flat_summaries: Dict[str, Dict[str, Any]] = {}
    l3_summaries: Dict[str, Dict[str, Any]] = {}

    if session_id:
        try:
            from app.services.report_store import ReportStore
            store = ReportStore()
            for layer in (1, 2, 3):
                layer_summaries = await store.get_layer_summaries(
                    session_id,
                    layer=layer,
                ) or {}
                flat_summaries.update(layer_summaries)
                if layer == 3:
                    l3_summaries = layer_summaries
        except Exception:
            pass

    if not l3_summaries:
        return _get_reports_fallback(state), {}

    reports = {}
    for dk, parsed in l3_summaries.items():
        reports[dk] = {
            "summary": {
                "metrics": parsed.get("metrics", {}),
                "key_points": parsed.get("key_points", []),
                "text_summary": parsed.get("text_summary", ""),
            },
            "content": parsed.get("text_summary", ""),
        }
    return reports, flat_summaries


def _get_reports_fallback(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Fallback: 从 completed_dimensions 构造最小格式。"""
    completed = state.get("completed_dimensions", {})
    result = {}
    for layer_key, dims in completed.items():
        for dim_key in dims:
            result[dim_key] = {"status": "completed", "layer": layer_key}
    return result


def _extract_interrupt_payloads(exc: GraphInterrupt) -> list[Any]:
    """Extract the list of langgraph Interrupt objects from a GraphInterrupt.

    LangGraph 1.x stores the interrupt sequence on the exception; prefer the
    public ``interrupts`` attribute when present, else fall back to ``args[0]``.
    """
    if getattr(exc, "interrupts", None):
        return list(exc.interrupts)
    if exc.args and isinstance(exc.args[0], (list, tuple)):
        return list(exc.args[0])
    return []


def _pending_items_from_interrupts(interrupts: list[Any]) -> list[Dict[str, Any]]:
    """Pull human_review_items out of the interrupt payload(s)."""
    for intr in interrupts:
        value = getattr(intr, "value", None)
        if isinstance(value, dict):
            items = value.get("human_review_items") or []
            if items:
                return list(items)
    return []


def _format_gis_result(result: Dict[str, Any], layout_configs: List[Dict[str, Any]]) -> str:
    """格式化 GIS Agent 结果为对话消息"""
    validation = result.get("validation_result", {}) or {}
    if not validation.get("passed", False):
        reasons = result.get("execution_errors", []) or validation.get("violations", [])
        return (
            f"GIS 布局生成失败：校验未通过，正式成果未导出。"
            f"已生成 {len(layout_configs)} 个诊断图层；原因：{reasons}"
        )
    layer_types = [
        c.get("layerType") or c.get("layer_type") or "unknown"
        for c in layout_configs
    ]
    return f"GIS 布局生成完成：{len(layout_configs)} 个图层 ({', '.join(layer_types)})"


__all__ = ["gis_agent_node"]
