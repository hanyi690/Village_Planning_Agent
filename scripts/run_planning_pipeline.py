"""金田村"产业空间布局规划图"端到端 CLI（v4）。

链路（全系统内闭环）：
  1. DB 28 份报告（已有则复用；缺失则跑完整 L1/L2/L3 分析）
  2. PARSE：L3 结构化表格 → intent（分区/项目）
  3. LLM 词汇表提取：L3 报告【功能分区表】→ session Vocabulary（自由色）
  4. EXPLORE(project 域) → Binder（KG 语义）→ format_bound_intent → custom_zone_targets
  5. layout_pipeline → EXECUTE：CustomZoningGenerator（三线拦截）→ custom_functional_zone 层
  6. 落盘 custom_functional_zone.geojson → render_integrated_map.py → PNG

进程自结束：run_with_exit_guard 保证任何路径（正常/崩溃/挂住）进程都能自行退出。

Usage:
    python scripts/run_planning_pipeline.py [--session-id SID] [--skip-render]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.resolve()
backend_root = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from scripts.experiments.framework.config import (
    DEFAULT_CONSTRAINTS,
    DEFAULT_TASK_DESCRIPTION,
    JINTIAN_VILLAGE_DATA,
    ensure_cascade_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

OUT_DIR = project_root / "docs" / "gis" / "output"
RUN_STATE_PATH = project_root / "output" / "run_state.json"
PIPELINE_TIMEOUT_S = 900  # L3b: pipeline.ainvoke 外层硬超时
EXIT_GRACE_S = 10         # L2: 主协程完成后给 shutdown 的正常退出宽限


def run_with_exit_guard(coro_factory) -> int:
    """Guarantee the process exits on its own under every path.

    L2 mechanism:
      - normal / exception path: shutdown_database() in finally
      - daemon watchdog: after the main coroutine finishes, if the process
        is still alive EXIT_GRACE_S later (unclosed non-daemon threads),
        force os._exit() — no process can hang forever.
    Returns the exit code.
    """
    import os
    import threading

    done = threading.Event()
    result = {"code": 1}

    def _watchdog():
        done.wait()  # 等主协程完成（含 shutdown_database）
        time.sleep(EXIT_GRACE_S)  # 正常退出窗口：仅当进程仍被非 daemon 线程挂住时才触发
        os._exit(result["code"])  # main done but process hung -> hard exit

    threading.Thread(target=_watchdog, daemon=True).start()

    try:
        asyncio.run(coro_factory())
        result["code"] = 0
    except SystemExit as e:
        result["code"] = int(e.code or 0)
    except Exception as e:
        logger.error("[ExitGuard] fatal: %s", e, exc_info=True)
        result["code"] = 1
    finally:
        # done.set() 必须先于 shutdown_database：watchdog 兜底不依赖 shutdown
        # 是否成功（若 shutdown 自身挂死，进程仍能由 watchdog os._exit）。
        done.set()
        try:
            from app.database.engine import shutdown_database

            asyncio.run(shutdown_database())
        except Exception:
            pass

    return result["code"]


def _write_run_state(phase: str, session_id: str) -> None:
    RUN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_PATH.write_text(
        json.dumps({"phase": phase, "session_id": session_id, "ts": time.time()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_run_state() -> Dict[str, Any]:
    if RUN_STATE_PATH.exists():
        try:
            return json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


async def _ensure_reports(session_id: str) -> Dict[str, Any]:
    """Reuse existing L3 reports from DB, or run the full planning graph."""
    from app.services.report_store import ReportStore

    store = ReportStore.get_instance()
    l3 = await store.get_layer_reports(session_id, 3)
    if l3 and len(l3) >= 12:
        logger.info("[Pipeline] Reusing %d existing L3 reports for %s", len(l3), session_id)
        return l3
    logger.info("[Pipeline] Missing L3 reports — running full planning graph")
    await _run_full_graph(session_id)
    return await store.get_layer_reports(session_id, 3)


async def _run_full_graph(session_id: str) -> None:
    """Port of scripts/experiments/cascade/baseline.py:_run_graph (L1->L2->L3)."""
    from app.agent.state import get_layer_dimensions, get_layer_name
    from app.database.operations import create_planning_session_async
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager
    from app.utils.sse_publisher import SSEPublisher
    from app.utils.stats_collector import StatsCollector
    from scripts.experiments.framework.sse_listener import InProcessEventListener

    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")
    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")

    stats = StatsCollector.get_instance()
    stats.start_session(session_id, "金田村规划")

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name="金田村规划",
        village_data=village_data,
        village_name=village_name,
        task_description=DEFAULT_TASK_DESCRIPTION,
        constraints=DEFAULT_CONSTRAINTS,
        session_id=session_id,
        stream_mode=True,
        step_mode=False,
    )

    await create_planning_session_async({
        "session_id": session_id,
        "project_name": "金田村规划",
        "village_data": village_data,
        "village_name": village_name,
        "task_description": DEFAULT_TASK_DESCRIPTION,
        "constraints": DEFAULT_CONSTRAINTS,
        "config": {"village_name": village_name},
    })

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": "金田村规划"})
    sse_manager.set_execution_active(session_id, True)
    listener = InProcessEventListener(session_id)
    await listener.connect()

    SSEPublisher.send_layer_start(
        session_id=session_id, layer=1,
        layer_name=get_layer_name(1),
        dimension_count=len(get_layer_dimensions(1)),
    )

    task = asyncio.create_task(
        PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
    )

    for layer in [1, 2, 3]:
        event = await listener.wait_for_any_event(
            event_types=["layer_completed", "error"],
            timeout=1200,
            filter_func=lambda e, l=layer: (
                e.get("type") == "error"
                or e.get("data", {}).get("layer") == l
            ),
        )
        if event.get("type") == "error":
            raise RuntimeError(f"Layer {layer} failed: {event.get('data', {}).get('message', 'unknown')}")
        logger.info("[Pipeline] Layer %d completed", layer)

    await task
    await listener.disconnect()


async def _prepare_intent(reports: Dict[str, Any], village_name: str) -> Any:
    """PARSE 表格 → intent；LLM 词汇表提取 → session vocabulary。"""
    from app.agent.gis.parse import parse
    from app.agent.gis.vocab_extractor import extract_vocabulary_from_reports, register_session_vocabulary

    planning_text = "\n".join(
        v.get("content", "") if isinstance(v, dict) else str(v)
        for v in (reports or {}).values()
    )
    result = parse(planning_text, village_name=village_name)
    intent = result.intent

    vocab = await extract_vocabulary_from_reports(reports)
    if vocab.categories:
        intent.vocabulary_name = register_session_vocabulary("pipeline", vocab)
        logger.info("[Pipeline] session vocabulary: %d categories %s",
                    len(vocab.categories), [c.name_zh for c in vocab.categories])
    else:
        # 词汇表 100% 来自报告动态提取（LLM → 确定性表格提取），无固定 YAML 兜底
        logger.warning("[Pipeline] no functional zone categories extracted from reports")
    return intent


async def _run_gis(session_id: str, reports: Dict[str, Any], bundle: Any = None) -> Dict[str, Any]:
    """EXPLORE(project) → Binder → format → layout_pipeline → EXECUTE。"""
    from app.agent.explore import ExploreFlashAgent
    from app.agent.gis import build_layout_pipeline
    from app.agent.gis.format_bound_intent import format_bound_spatial_intent
    from app.agent.gis.spatial_entity_binder import DeterministicBundleBinder
    from app.modules.data.catalog import DataCatalog
    from app.modules.kg import open_kg_session

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    if bundle is None:
        bundle = await DataCatalog().load_village_bundle_async(village_name)
    open_kg_session(session_id=session_id, village_name=bundle.village_name or village_name, bundle=bundle)

    planning_text = "\n".join(
        v.get("content", "") if isinstance(v, dict) else str(v)
        for v in (reports or {}).values()
    )

    # 1. EXPLORE（project 域 + KG 探索）
    agent = ExploreFlashAgent(session_id=session_id, village_name=village_name)
    instructions = agent.explore(planning_text)

    # 2. Binder（BSM 匹配 + candidate 标记）
    binder = DeterministicBundleBinder(bundle)
    bound_entities = binder.bind(instructions)

    # 3. format → SpatialPlanningIntent（含 custom_zone_targets）
    intent = await _prepare_intent(reports, village_name)
    intent = format_bound_spatial_intent(
        village_name=village_name,
        bound_entities=bound_entities,
        fallback_intent=intent,
        vocabulary_name=intent.vocabulary_name,
    )
    logger.info("[Pipeline] intent: %d zones, %d custom_zone_targets, %d projects",
                len(intent.zone_targets), len(intent.custom_zone_targets), len(intent.facilities))

    # 4. layout_pipeline（EXECUTE 双图层）
    pipeline = build_layout_pipeline()
    try:
        result = await asyncio.wait_for(
            pipeline.ainvoke({
                "session_id": session_id,
                "village_name": village_name,
                "reports": {},
                "intent_json": {},
                "gis_data": bundle.to_geojson_dict(),
                "gis_bundle": bundle,
                "intent": intent,
                "kg_turtle": "",
                "kg_constraints": [],
                "layout_configs": [],
                "allocated_geojson": {},
                "allocation_summary": {},
                "validation_result": {},
                "validation_round": 0,
                "export_result": {},
                "render_result": [],
                "messages": [],
            }),
            timeout=PIPELINE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.error("[Pipeline] layout pipeline timed out after %ds", PIPELINE_TIMEOUT_S)
        return {"layout_configs": [], "validation_result": {"passed": False, "reason": "timeout"}}
    return result


def _build_structure_overlay(reports: Dict[str, Any]) -> Dict[str, Any]:
    """解析 L3 spatial_structure 报告 → structure_overlay.geojson（核/轴/区标注）。

    数据全部来自系统内报告：空间结构模式（一轴两核三区）+ 功能节点表。
    核 = 节点表名称含"核"的行；轴/区 = 模式文本提取；位置优先 gazetteer 质心，
    无命中则用村域 bbox 分布点（明确标注 kind=label，非真实几何）。
    """
    import json as _json
    from app.modules.kg.gazetteer import load_gazetteer

    content = ""
    for key, val in (reports or {}).items():
        if key == "spatial_structure":
            content = val.get("content", "") if isinstance(val, dict) else str(val)
            break
    if not content:
        return {"type": "FeatureCollection", "features": []}

    gazetteer = load_gazetteer("jintian")
    features = []

    # 节点表（节点名称|核心功能|服务范围|主要布局）→ 核
    import re

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("|") and "核" in line and "节点名称" not in line and not re.match(r"^\|[\s:|-]+\|$", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            name = cells[0]
            if not name or "节点" in name or "合计" in name:
                continue
            entry = None
            for ge in gazetteer.entries:
                if ge.name and ge.name in name:
                    entry = ge
                    break
            if entry and entry.centroid:
                features.append({
                    "type": "Feature",
                    "properties": {"kind": "center", "label": name, "color": "#B22222"},
                    "geometry": {"type": "Point", "coordinates": entry["centroid"]},
                })
            else:
                features.append({
                    "type": "Feature",
                    "properties": {"kind": "label", "label": name, "color": "#B22222",
                                   "note": "no-gazetteer-anchor"},
                    "geometry": None,
                })

    # 空间结构模式（"一轴两核三区"）→ 轴/区文字标注
    for line in content.splitlines():
        line = line.strip()
        if "规划构建" not in line and "空间结构" not in line:
            continue
        m = re.findall(r"[“\"]([^”\"]{4,40})[”\"]", line)
        for phrase in m:
            kind = "axis" if "轴" in phrase else "zone"
            features.append({
                "type": "Feature",
                "properties": {"kind": kind, "label": phrase, "color": "#1a5f9e"
                               if kind == "axis" else "#2E8B57"},
                "geometry": None,
            })

    return {"type": "FeatureCollection", "features": features}


async def main(session_id: str, skip_render: bool) -> None:
    from app.services.runtime import PlanningRuntimeService

    ensure_cascade_dirs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    await PlanningRuntimeService.ensure_initialized()

    session_id = session_id or f"plan_{uuid.uuid4().hex[:8]}"
    logger.info("[Pipeline] session_id=%s", session_id)

    # KG session 必须早于探索（_ensure_reports 触发 L1/L2/L3 wave 钩子时 KG 已就绪）
    from app.modules.data.catalog import DataCatalog
    from app.modules.kg import open_kg_session

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    bundle = await DataCatalog().load_village_bundle_async(village_name)
    open_kg_session(
        session_id=session_id,
        village_name=bundle.village_name or village_name,
        bundle=bundle,
    )

    _write_run_state("reports", session_id)
    reports = await _ensure_reports(session_id)

    _write_run_state("gis", session_id)
    result = await _run_gis(session_id, reports, bundle)

    layers = result.get("layout_configs", [])
    print("\n" + "=" * 60)
    print(f"[Pipeline] layout layers: {[c.get('layerType') for c in layers]}")

    def _layer_score(data: Dict[str, Any]) -> Tuple[int, int]:
        """同 layerType 多候选时选最优：含地块(bsm)数优先，其次 feature 数。"""
        feats = data.get("features", []) or []
        bsms = sum(
            len(f.get("properties", {}).get("source_bsms", []) or [])
            + len(f.get("properties", {}).get("target_bsms", []) or [])
            for f in feats
        )
        return (bsms, len(feats))

    best_by_type: Dict[str, Dict[str, Any]] = {}
    for c in layers:
        lt = c.get("layerType")
        data = c.get("data")
        if not lt or not data or not data.get("features"):
            continue
        prev = best_by_type.get(lt)
        if prev is None or _layer_score(data) > _layer_score(prev["data"]):
            best_by_type[lt] = c

    custom = best_by_type.get("custom_functional_zone")
    if custom:
        out = OUT_DIR / "custom_functional_zone.geojson"
        out.write_text(json.dumps(custom["data"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Pipeline] custom_functional_zone: {len(custom['data']['features'])} features -> {out}")
    else:
        print("[Pipeline] WARNING: no custom_functional_zone layer produced")

    # 落盘全部图层（每层独立 geojson，供渲染分开图层使用）
    saved_layers = []
    for lt, c in best_by_type.items():
        data = c["data"]
        path = OUT_DIR / f"{lt}.geojson"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_layers.append(f"{lt}:{len(data['features'])}")
    print(f"[Pipeline] saved layers: {saved_layers}")

    # A5: 结构标注（L3 spatial_structure 报告 → structure_overlay）
    overlay = _build_structure_overlay(reports)
    if overlay.get("features"):
        path = OUT_DIR / "structure_overlay.geojson"
        path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Pipeline] structure_overlay: {len(overlay['features'])} annotations -> {path}")

    print(f"[Pipeline] validation: {result.get('validation_result', {})}")
    print("=" * 60)

    _write_run_state("render", session_id)
    if not skip_render:
        try:
            subprocess.run(
                [sys.executable, str(script_dir / "render_integrated_map.py")],
                check=False,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            logger.error("[Pipeline] render subprocess timed out after 180s")
        except Exception as e:
            logger.error("[Pipeline] render subprocess failed: %s", e)
    _write_run_state("done", session_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()

    async def _entry():
        await main(args.session_id or None, args.skip_render)

    sys.exit(run_with_exit_guard(_entry))
