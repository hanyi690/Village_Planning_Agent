"""
维度级 Prompt 优化 — 单维度重新生成

修改系统 prompt 模板后，运行此脚本加载与基线完全相同的上下文，
用当前 prompt 调用 LLM，生成对比文档。

Usage:
    python scripts/experiments/dimension_prompt_optimization/run.py <dimension_key>

Example:
    python scripts/experiments/dimension_prompt_optimization/run.py natural_environment
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# ---- 配置 ----
CASCADE_BASELINE = (
    project_root / "output" / "experiments" / "cascade_consistency"
    / "baseline" / "baseline_reports.json"
)
OUTPUT_DIR = project_root / "output" / "experiments" / "dimension_prompt_optimization"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def main(dim_key: str):
    from app.config.loader import get_dimension_config, get_dimension_layer, list_dimensions
    from app.agent.nodes.analysis import _build_prompt
    from app.core.llm import create_llm
    from app.core.settings import LLM_MODEL, MAX_TOKENS, LLM_STREAM_TIMEOUT
    from app.services.runtime import PlanningRuntimeService
    from app.services.report_store import ReportStore
    from app.services import GisService, RagService

    # 验证维度
    valid = [d.key for d in list_dimensions()]
    if dim_key not in valid:
        print(f"无效维度 '{dim_key}'，可选: {valid}")
        return 1

    # 加载基线
    if not CASCADE_BASELINE.exists():
        print(f"基线文件不存在: {CASCADE_BASELINE}")
        print("请先运行: python scripts/experiments/cascade_consistency/run_baseline.py")
        return 1

    with open(CASCADE_BASELINE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    baseline_content = baseline["reports"].get(dim_key, "")
    session_id = baseline["session_id"]
    checkpoint_id = baseline.get("checkpoint_id", "")
    print(f"[1/5] 基线已加载: {len(baseline_content)} chars, {dim_key}")

    # 初始化
    await PlanningRuntimeService.ensure_initialized()

    # 只读加载检查点状态（不修改，不污染）
    config = PlanningRuntimeService.get_thread_config(session_id, checkpoint_id)
    graph = PlanningRuntimeService.get_graph()
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        print("检查点状态不可用")
        return 1
    state = snapshot.values
    print(f"[2/5] 检查点已加载 (phase={state.get('phase')})")

    # 维度配置
    cfg = get_dimension_config(dim_key)
    dim_layer = getattr(cfg, 'layer', get_dimension_layer(dim_key) or 3)

    # RAG 缓存
    knowledge_cache = state.get("config", {}).get("knowledge_cache", {})
    rag_context = ""
    if dim_key in knowledge_cache:
        rag_context = knowledge_cache[dim_key].get("context", "")
        print(f"[3/5] RAG 缓存命中 ({len(rag_context)} chars)")
    elif getattr(cfg, 'rag_query', ''):
        print(f"[3/5] RAG 缓存未命中，运行检索...")
        queries = await RagService.get_instance().generate_queries(cfg, state)
        results = []
        for q in queries:
            results.extend(await RagService.get_instance().search(q, top_k=5))
        from app.services.modules.rag.service import RagService as RS
        rag_context = RS.format_for_prompt(results) if results else ""

    # GIS 工具
    tool_results = []
    tools = getattr(cfg, 'tools', [])
    if tools:
        from app.tools.protocol import IMPL_STATUS, ImplStatus
        safe = [t for t in tools if IMPL_STATUS.get(t) == ImplStatus.IMPLEMENTED]
        if safe:
            ctx = {
                "session_id": session_id,
                "project_name": state.get("project_name", ""),
                "village_data": state.get("config", {}).get("village_data", ""),
            }
            tool_results = await GisService.run_parallel(safe, ctx)

    # 依赖报告（从 DB 直接读取）
    store = ReportStore.get_instance()
    deps = ""
    same_layer_contexts = ""

    same_layer_deps = getattr(cfg, 'depends_on', [])
    if same_layer_deps:
        dep_reports = await store.get_dependencies(session_id, same_layer_deps)
        parts = [f"【{k}】分析结果：\n{dep_reports[k]}"
                 for k in same_layer_deps if k in dep_reports]
        same_layer_contexts = "\n\n".join(parts)

    if dim_layer == 2:
        l1 = await store.get_layer_reports(session_id, 1)
        l1_deps = getattr(cfg, 'layer_depends_on', [])
        keys = l1_deps if l1_deps else list(l1.keys())
        parts = [f"【{k}】{l1[k]}" for k in keys if l1.get(k)]
        deps = "\n".join(parts)
    elif dim_layer == 3:
        l1 = await store.get_layer_reports(session_id, 1)
        l2 = await store.get_layer_reports(session_id, 2)
        l1_deps = getattr(cfg, 'layer_depends_on', [])
        l2_deps = getattr(cfg, 'phase_depends_on', [])
        parts = []
        for k in l1_deps:
            if l1.get(k):
                parts.append(f"【{k}】{l1[k]}")
        for k in l2_deps:
            if l2.get(k):
                parts.append(f"【{k}】{l2[k]}")
        deps = "\n".join(parts)

    print(f"[4/5] 上下文已组装 (deps={len(deps)} chars, rag={len(rag_context)} chars)")

    # 构建 prompt（使用当前模板 — 用户刚修改的）
    rec_state = {
        "dimension_key": dim_key,
        "project_name": state.get("project_name", ""),
        "config": state.get("config", {}),
        "image_ids": state.get("image_ids", []),
        "is_revision": False,
    }
    prompt = _build_prompt(cfg, rec_state, tool_results, rag_context, deps, same_layer_contexts)

    # LLM 调用
    print(f"[5/5] 调用 LLM (prompt={len(prompt)} chars)...")
    llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS, streaming=True)

    new_content = ""
    try:
        async with asyncio.timeout(LLM_STREAM_TIMEOUT):
            async for chunk in llm.astream(prompt):
                if hasattr(chunk, 'content') and chunk.content:
                    new_content += chunk.content
    except asyncio.TimeoutError:
        print(f"LLM 超时 ({LLM_STREAM_TIMEOUT}s)")
        return 1

    # 生成对比文档
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{dim_key}_{ts}.txt"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write(f"维度: {dim_key} ({getattr(cfg, 'name', dim_key)})\n")
        f.write(f"生成时间: {datetime.now().isoformat()}\n")
        f.write("=" * 70 + "\n\n")
        f.write("=" * 70 + "\n")
        f.write(f"基线内容 ({len(baseline_content)} chars)\n")
        f.write("=" * 70 + "\n\n")
        f.write(baseline_content + "\n\n")
        f.write("=" * 70 + "\n")
        f.write(f"修改后内容 ({len(new_content)} chars)\n")
        f.write("=" * 70 + "\n\n")
        f.write(new_content + "\n\n")
        f.write("=" * 70 + "\n")
        diff = len(new_content) - len(baseline_content)
        f.write(f"字符数: {len(baseline_content)} → {len(new_content)} "
                f"({'增加' if diff > 0 else '减少'} {abs(diff)})\n")

    print(f"\n完成! 输出: {output_path}")
    print(f"字符数: {len(baseline_content)} → {len(new_content)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
