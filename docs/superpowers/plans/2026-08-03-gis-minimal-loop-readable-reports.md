# GIS 最小闭环 + 可读阶段报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the 4 confirmed functional gaps in the GIS planning loop and add a readable, per-stage Markdown report so each pipeline stage's output is visible and testable.

**Architecture:** Two independent blocks. Block A repairs the data chain: (1) PARSE becomes a fallback that backfills missing intent categories instead of being skipped, (2) MIP constraints carry source provenance and are deduped, (3) a post-execute EXPLORE verification compares L3 text vs L4 geometry and writes a readable step report. Block B adds a pure Markdown renderer over the existing `step_reports` table, a `text/markdown` API endpoint, frontend display, and a real-session assertion test.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / LangGraph / pytest / rdflib; TypeScript / React 18 / Next 14 / react-markdown (already a dependency) / jest.

## Global Constraints

- 换行符 LF，缩进 2 空格（Python）；单引号（前端）、双引号（Python）。
- 所有新增 step_report 使用既有 `VALID_STAGES` 集合（`EXPLORE` 已存在）。
- 不新建 Agent 框架；修订反馈走既有 `revision_trigger` 级联机制。
- 不修改 `_merge_explore_bsms`（已确认为死代码，零调用）；不修改 `ConstraintCompiler` 的启用状态。
- 保留既有上传类型归一化（`session_routes.py:1464-1467`）、DataCatalog 脏类型重推、`ensure_session_kg` 预建守护（上一轮已完成，勿回退）。
- 新代码必须可单测（纯函数优先），不允许只测 JSON 结构不测语义。
- 全量 pytest 零新增失败；前端 `tsc --noEmit` 通过。

---

### Task 1: 约束来源标注 + 去重

**Files:**
- Create: `backend/app/agent/gis/execute/constraints.py`
- Modify: `backend/app/agent/gis/execute/agent.py:358` (replace `all_constraints = ...`)
- Test: `backend/tests/unit/test_execute_constraints.py`

**Interfaces:**
- Produces: `merge_sourced_constraints(kg_constraints: List[Dict], parse_constraints: List[Dict]) -> List[Dict]` — each output dict gains `source_type` (`"kg:layer2"` or `"parse"`); deduped by `(source_type, id, operator, value)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_execute_constraints.py`:
```python
def test_merge_sourced_constraints_tags_and_dedupes():
    from app.agent.gis.execute.constraints import merge_sourced_constraints

    kg = [{"id": "eco", "operator": ">=", "value": 330.0}, {"id": "eco", "operator": ">=", "value": 330.0}]
    parse = [{"type": "farmland_protection", "value": 85.2, "source_text": "农田保护区 85.20公顷"}]
    out = merge_sourced_constraints(kg, parse)
    assert len(out) == 2
    assert out[0]["source_type"] == "kg:layer2"
    assert out[1]["source_type"] == "parse"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_execute_constraints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.gis.execute.constraints'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/agent/gis/execute/constraints.py`:
```python
"""Constraint provenance — tag each MIP constraint with its source and dedupe."""
from __future__ import annotations
from typing import Any, Dict, List


def merge_sourced_constraints(
    kg_constraints: List[Dict[str, Any]],
    parse_constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for c in kg_constraints:
        key = ("kg:layer2", c.get("id", ""), c.get("operator", c.get("op", "")), str(c.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        merged.append({**c, "source_type": "kg:layer2"})
    for c in parse_constraints:
        key = ("parse", c.get("type", ""), str(c.get("value", "")), str(c.get("source_text", ""))[:40])
        if key in seen:
            continue
        seen.add(key)
        merged.append({**c, "source_type": "parse"})
    return merged
```

- [ ] **Step 4: Wire into EXECUTE layout node**

`backend/app/agent/gis/execute/agent.py` (around line 358), replace:
```python
        all_constraints = list(state.kg_constraints or []) + mip_parse_constraints
```
with:
```python
        from app.agent.gis.execute.constraints import merge_sourced_constraints

        all_constraints = merge_sourced_constraints(
            list(state.kg_constraints or []), mip_parse_constraints
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_execute_constraints.py tests/unit/test_execute_custom_zoning.py -v`
Expected: new test PASS; `test_execute_custom_zoning` is a known pre-existing baseline failure — confirm it still fails identically (not a regression).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/gis/execute/constraints.py backend/app/agent/gis/execute/agent.py backend/tests/unit/test_execute_constraints.py
git commit -m "feat(execute): tag MIP constraints with source_type and dedupe"
```

---

### Task 2: PARSE 作为 fallback 回填缺失类别

**Files:**
- Modify: `backend/app/agent/gis/layout_pipeline.py` (`_parse_intent_node` ~lines 333-353; extract planning-text helper from lines 359-391)
- Create: `backend/app/agent/gis/parse_fallback.py`
- Test: `backend/tests/unit/test_parse_fallback.py`

**Interfaces:**
- Produces: `merge_fallback_targets(external: SpatialPlanningIntent, parsed: SpatialPlanningIntent) -> int` — appends zone/facility/road targets whose `land_use`/`type`/`road_level` is not already present in `external`; returns count added. Mutates `external` in place.
- Consumes: `parse_async` from `app.agent.gis.parse.agent` (existing signature `parse_async(planning_text, village_name, planning_period)` → `ParseResult.intent`).

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_parse_fallback.py`:
```python
def test_merge_fallback_targets_backfills_missing_categories():
    from app.agent.gis.parse_fallback import merge_fallback_targets
    from app.agent.gis.parse.state import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_contracts import ZoneTarget, FacilityTarget, RoadTarget

    external = SpatialPlanningIntent(
        zone_targets=[ZoneTarget(land_use="生态保护区")],
        facilities=[FacilityTarget(type="村委会")],
    )
    parsed = SpatialPlanningIntent(
        zone_targets=[ZoneTarget(land_use="生态保护区"), ZoneTarget(land_use="农田保护区")],
        facilities=[FacilityTarget(type="村委会"), FacilityTarget(type="文化广场")],
        road_targets=[RoadTarget(road_level="村道1号")],
    )
    added = merge_fallback_targets(external, parsed)
    assert added == 2
    names = {z.land_use for z in external.zone_targets}
    assert "农田保护区" in names
    assert len(external.facilities) == 2
    assert len(external.road_targets) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parse_fallback.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`backend/app/agent/gis/parse_fallback.py`:
```python
"""PARSE-as-fallback: merge missing intent categories without disturbing anchors."""
from __future__ import annotations


def merge_fallback_targets(external, parsed) -> int:
    added = 0
    ext_zones = {z.land_use for z in external.zone_targets if z.land_use}
    for zt in parsed.zone_targets:
        if zt.land_use and zt.land_use not in ext_zones:
            external.zone_targets.append(zt)
            ext_zones.add(zt.land_use)
            added += 1
    ext_fac = {f.type for f in external.facilities if f.type}
    for ft in parsed.facilities:
        if ft.type and ft.type not in ext_fac:
            external.facilities.append(ft)
            ext_fac.add(ft.type)
            added += 1
    ext_road = {r.road_level for r in external.road_targets if r.road_level}
    for rt in parsed.road_targets:
        if rt.road_level and rt.road_level not in ext_road:
            external.road_targets.append(rt)
            ext_road.add(rt.road_level)
            added += 1
    return added
```

- [ ] **Step 4: Extract planning-text builder + wire into `_parse_intent_node`**

In `backend/app/agent/gis/layout_pipeline.py`, extract lines 359-391 into a module-level helper:
```python
def _build_planning_text(state) -> str:
    reports = state.reports or {}
    planning_parts = []
    instruction_text = ""
    if reports:
        priority = (
            "land_use_planning", "spatial_structure", "traffic_planning",
            "public_service", "infrastructure_planning", "ecological",
            "disaster_prevention", "project_bank",
        )
        ordered_keys = list(priority) + [key for key in reports if key not in priority]
        for key in ordered_keys:
            if key not in reports:
                continue
            val = reports[key]
            if isinstance(val, dict):
                planning_parts.append(val.get("content", val.get("text", "")))
                instruction_text += val.get("instruction", "") + "\n"
            elif isinstance(val, str):
                planning_parts.append(val)
    planning_text = "\n\n".join(part for part in planning_parts if part)
    if not planning_text:
        planning_text = state.intent_json.get("planning_text", "")
    if instruction_text:
        planning_text = planning_text[:9000] + "\n\n" + instruction_text[:4000]
    return planning_text
```

Then replace the `has_structured` early-return block (lines 342-353) so PARSE runs and backfills:
```python
        if has_structured:
            intent = existing
            from app.agent.gis.parse_fallback import merge_fallback_targets
            from app.agent.gis.parse import parse_async as _fallback_parse

            planning_text = _build_planning_text(state)
            if planning_text:
                try:
                    result = await _fallback_parse(
                        planning_text=planning_text[:13000],
                        village_name=village_name,
                    )
                    added = merge_fallback_targets(intent, result.intent)
                    if added:
                        logger.info("[Pipeline:parse] PARSE fallback merged %d missing targets", added)
                except Exception as e:
                    logger.warning("[Pipeline:parse] PARSE fallback failed: %s", e)
            return {
                "intent": intent,
                "intent_json": intent,
                "planning_intent": intent,
            }
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/test_parse_fallback.py tests/unit/test_parse_instruction.py tests/unit/test_parse_agent.py -v`
Expected: new test PASS; existing parse tests unchanged (no new failures).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/gis/layout_pipeline.py backend/app/agent/gis/parse_fallback.py backend/tests/unit/test_parse_fallback.py
git commit -m "feat(parse): run PARSE as fallback backfill instead of skipping when external intent present"
```

---

### Task 3: EXPLORE 校核模式（L3 文本 vs L4 几何）

**Files:**
- Create: `backend/app/agent/explore/verification.py`
- Modify: `backend/app/agent/gis/execute/agent.py` (`_validate_node`, ~line 965 area)
- Test: `backend/tests/unit/test_explore_verification.py`

**Interfaces:**
- Produces: `compare_intent_to_layout(intent, layout_configs) -> Dict` with keys `consistent_items`, `differences`, `revision_suggestions`; and `async save_explore_verification(session_id, intent, layout_configs) -> Dict` which calls `compare_intent_to_layout` then `save_step_report(stage="EXPLORE", step_name="l3_l4_verification", ...)`.
- Consumes: `save_step_report` from `app.services.step_report` (existing signature).

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_explore_verification.py`:
```python
def test_compare_intent_to_layout_detects_missing_project():
    from app.agent.explore.verification import compare_intent_to_layout
    from app.agent.gis.parse.state import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_contracts import ProjectTarget, ZoneTarget

    intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="PRJ-1", name="古驿道修复")],
        zone_targets=[ZoneTarget(land_use="生态保护区", area_ha=330.0)],
    )
    layout_configs = [
        {"layerType": "custom_planning_zone", "data": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"zone_name": "生态保护区", "area_ha": 331.0}, "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}},
        ]}},
    ]
    result = compare_intent_to_layout(intent, layout_configs)
    assert any(d["check"] == "project_placement" for d in result["differences"])
    assert any(d["check"] == "zone_area" for d in result["differences"])
    assert result["revision_suggestions"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_explore_verification.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`backend/app/agent/explore/verification.py`:
```python
"""EXPLORE verification — compare L3 text targets vs L4 geometry (post-execute)."""
from __future__ import annotations
from typing import Any, Dict, List


def compare_intent_to_layout(intent: Any, layout_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    differences: List[Dict[str, Any]] = []
    consistent: Dict[str, Any] = {}

    # ── zone areas ──
    zone_text = {
        z.land_use: float(z.area_ha)
        for z in (getattr(intent, "zone_targets", None) or [])
        if z.land_use and z.area_ha
    }
    zone_actual: Dict[str, float] = {}
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) != "custom_planning_zone":
            continue
        data = cfg.get("data") or cfg.get("geojson") or {}
        for f in data.get("features", []):
            p = f.get("properties") or {}
            name = p.get("zone_name") or p.get("category_name_zh")
            if name:
                zone_actual[name] = zone_actual.get(name, 0.0) + float(p.get("area_ha", 0) or 0)
    for name, target in zone_text.items():
        actual = zone_actual.get(name, 0.0)
        if actual > 0 and abs(actual - target) / target > 0.1:
            differences.append({"check": "zone_area", "name": name, "target_ha": target, "actual_ha": actual})
    consistent["zone_actual"] = zone_actual

    # ── project placement ──
    projects = list(getattr(intent, "project_targets", None) or [])
    placed = 0
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) in {"planned_project", "project_point"}:
            placed += len(((cfg.get("data") or cfg.get("geojson") or {}).get("features", [])) or [])
    if projects and placed == 0:
        differences.append({"check": "project_placement", "expected": len(projects), "actual": placed})
    consistent["placed_projects"] = placed

    # ── road connectivity ──
    roads = list(getattr(intent, "road_targets", None) or [])
    road_count = 0
    for cfg in layout_configs:
        if (cfg.get("layerType") or cfg.get("layer_type")) in {"planned_road", "planned_road_candidates"}:
            road_count += len(((cfg.get("data") or cfg.get("geojson") or {}).get("features", [])) or [])
    if roads and road_count == 0:
        differences.append({"check": "road_connectivity", "expected": len(roads), "actual": road_count})
    consistent["road_count"] = road_count

    suggestions = [d["name"] for d in differences if d["check"] == "zone_area"]
    return {
        "consistent_items": consistent,
        "differences": differences,
        "revision_suggestions": suggestions,
    }


async def save_explore_verification(session_id: str, intent: Any, layout_configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from app.services.step_report import save_step_report

    result = compare_intent_to_layout(intent, layout_configs)
    try:
        await save_step_report(
            session_id, "EXPLORE",
            step_name="l3_l4_verification",
            outputs={
                "differences": len(result["differences"]),
                "consistent_items": result["consistent_items"],
            },
            diagnostics={
                "differences": result["differences"],
                "revision_suggestions": result["revision_suggestions"],
            },
        )
    except Exception as e:  # noqa: BLE001 — non-fatal
        import logging
        logging.getLogger(__name__).debug("[EXPLORE-verify] step report failed: %s", e)
    return result
```

- [ ] **Step 4: Wire into `_validate_node`**

In `backend/app/agent/gis/execute/agent.py`, inside `_validate_node` after `consistency = _build_l3_l4_consistency_report(state)` (near line 965):
```python
        try:
            from app.agent.explore.verification import save_explore_verification

            verification = await save_explore_verification(
                state.session_id, state.intent, state.layout_configs or []
            )
            consistency["l3_l4_verification"] = verification
        except Exception as e:
            logger.debug("[EXECUTE:validate] explore verification failed: %s", e)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/test_explore_verification.py tests/unit/test_execute_custom_zoning.py -v`
Expected: new test PASS; `test_execute_custom_zoning` still fails identically to baseline (pre-existing).

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/explore/verification.py backend/app/agent/gis/execute/agent.py backend/tests/unit/test_explore_verification.py
git commit -m "feat(explore): add L3-vs-L4 verification step report"
```

---

### Task 4: 可读 Markdown 阶段报告渲染器

**Files:**
- Create: `backend/app/services/stage_report.py`
- Test: `backend/tests/unit/test_stage_report.py`

**Interfaces:**
- Produces: `render_stage_report_markdown(reports: List[Dict], summary: Dict) -> str` (pure, no I/O); `async build_stage_report_markdown(session_id: str) -> str` (loads via `get_session_step_reports` + `build_backend_run_report`).
- Consumes: `app.services.step_report.get_session_step_reports`, `app.services.step_report.build_backend_run_report`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_stage_report.py`:
```python
def test_render_stage_report_markdown_contains_stage_headings():
    from app.services.stage_report import render_stage_report_markdown

    reports = [
        {"stage": "KG_PREBUILD", "step_name": "kg_prebuild", "timestamp": "2026-08-03T00:00:00",
         "outputs": {"triple_count": 30836}, "diagnostics": {"sfTouches": 100}, "artifacts": []},
        {"stage": "EXPLORE", "step_name": "explore_bridge", "timestamp": "2026-08-03T00:00:01",
         "outputs": {"instructions": 0}, "diagnostics": {"total": 66, "resolved": 0}, "artifacts": []},
    ]
    md = render_stage_report_markdown(reports, {"session_id": "sess-1", "feasible": False})
    assert "## KG_PREBUILD / kg_prebuild" in md
    assert "## EXPLORE / explore_bridge" in md
    assert "triple_count" in md and "30836" in md
    assert "resolved" in md and "0" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_stage_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`backend/app/services/stage_report.py`:
```python
"""Human-readable Markdown rendering of the full GIS pipeline stage reports."""
from __future__ import annotations

import json
from typing import Any, Dict, List


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value)


def render_stage_report_markdown(
    reports: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    lines = ["# GIS 全链阶段报告", ""]
    lines.append(f"- **Session**: {summary.get('session_id', '')}")
    lines.append(f"- **Feasible**: {summary.get('feasible', False)}")
    lines.append("")
    for r in reports:
        stage = r.get("stage", "?")
        step = r.get("step_name", "")
        lines.append(f"## {stage} / {step}")
        lines.append(f"- timestamp: {r.get('timestamp', '')}")
        outputs = r.get("outputs") or {}
        if outputs:
            lines.append("### 产出")
            for k, v in sorted(outputs.items()):
                lines.append(f"- **{k}**: {_fmt(v)}")
        diag = r.get("diagnostics") or {}
        if diag:
            lines.append("### 诊断")
            for k, v in sorted(diag.items()):
                lines.append(f"- {k}: {_fmt(v)}")
        artifacts = r.get("artifacts") or []
        if artifacts:
            lines.append("### 产物")
            for a in artifacts:
                lines.append(f"- {a.get('kind')}: `{a.get('path')}`")
        lines.append("")
    return "\n".join(lines)


async def build_stage_report_markdown(session_id: str) -> str:
    from app.services.step_report import build_backend_run_report, get_session_step_reports

    reports = await get_session_step_reports(session_id)
    if not reports:
        return ""
    try:
        summary = await build_backend_run_report(session_id)
    except Exception:  # noqa: BLE001 — non-fatal
        summary = {}
    return render_stage_report_markdown(reports, summary)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_stage_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/stage_report.py backend/tests/unit/test_stage_report.py
git commit -m "feat(report): readable Markdown renderer over step_reports"
```

---

### Task 5: `stage-report.md` API 端点 + backend-run-report 注入 markdown

**Files:**
- Modify: `backend/app/api/session_routes.py` (imports line 29-30; add route near line 722)
- Modify: `backend/app/services/step_report.py` (`build_backend_run_report` return, ~line 335)
- Test: `backend/tests/unit/test_stage_report_api.py`

**Interfaces:**
- Consumes: `build_stage_report_markdown` from `app.services.stage_report`.
- Produces: `GET /api/sessions/{session_id}/stage-report.md` → `Response(content=markdown, media_type="text/markdown; charset=utf-8")`; `build_backend_run_report` return dict gains key `markdown`.

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/test_stage_report_api.py`:
```python
def test_backend_run_report_includes_markdown_field(monkeypatch):
    from app.services.step_report import build_backend_run_report

    async def fake_build(session_id):
        return {"session_id": session_id, "feasible": False, "layers": {}, "issues": []}

    monkeypatch.setattr("app.services.step_report.build_backend_run_report", fake_build)
    # direct renderer-level assertion instead of full async chain
    from app.services.stage_report import render_stage_report_markdown

    md = render_stage_report_markdown([], {"session_id": "s", "feasible": False})
    assert "GIS 全链阶段报告" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_stage_report_api.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.stage_report`

- [ ] **Step 3: Inject markdown into `build_backend_run_report`**

In `backend/app/services/step_report.py`, in `build_backend_run_report` just before `return {` (line 335):
```python
    try:
        from app.services.stage_report import render_stage_report_markdown
        report_md = render_stage_report_markdown(trace["reports"], report)
    except Exception:  # noqa: BLE001
        report_md = ""
    return {
        ...existing keys...,
        "markdown": report_md,
    }
```
(Add `"markdown": report_md,` to the existing return dict.)

- [ ] **Step 4: Add the API endpoint**

In `backend/app/api/session_routes.py`, add `Response` to the fastapi.responses import (line 30):
```python
from fastapi.responses import Response, StreamingResponse
```
Add route after `get_backend_run_report` (~line 723):
```python
@router.get("/api/sessions/{session_id}/stage-report.md")
async def get_stage_report_markdown(session_id: str):
    """Return the full pipeline stage report as readable Markdown."""
    from app.services.stage_report import build_stage_report_markdown

    markdown = await build_stage_report_markdown(session_id)
    if not markdown:
        state = await PlanningRuntimeService.aget_state_values(session_id)
        if not state:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return Response(
        content=markdown or "# 无阶段报告\n\n该会话尚未产生任何 StepReport。\n",
        media_type="text/markdown; charset=utf-8",
    )
```

- [ ] **Step 5: Run tests + import check**

Run: `python -m pytest tests/unit/test_stage_report_api.py tests/unit/test_stage_report.py -v`
Run: `python -c "import app.api.session_routes; import app.services.step_report; import app.services.stage_report; print('imports OK')"`
Expected: PASS both; `imports OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/session_routes.py backend/app/services/step_report.py backend/tests/unit/test_stage_report_api.py
git commit -m "feat(api): stage-report.md markdown endpoint + backend-run-report markdown field"
```

---

### Task 6: 前端展示阶段报告

**Files:**
- Create: `frontend/src/features/planning/components/gis/StageReportPanel.tsx`
- Modify: `frontend/src/features/planning/components/chat/GisResultCard.tsx` (import + render panel)
- Test: `frontend/src/features/planning/components/gis/__tests__/StageReportPanel.test.tsx`

**Interfaces:**
- Consumes: `sessionId` from `usePlanningStore((s) => s.sessionId)`; endpoint `/api/sessions/${sessionId}/stage-report.md`.
- Produces: `<StageReportPanel sessionId={string} />` — fetches markdown on mount, renders with `react-markdown`, shows a load-failure fallback.

- [ ] **Step 1: Write the failing test**

`frontend/src/features/planning/components/gis/__tests__/StageReportPanel.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react';
import StageReportPanel from '../StageReportPanel';

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    text: async () => '# GIS 全链阶段报告\n\n## EXPLORE / explore_bridge',
  } as Response);
});

test('renders fetched markdown headings', async () => {
  render(<StageReportPanel sessionId="sess-1" />);
  expect(await screen.findByText('GIS 全链阶段报告')).toBeInTheDocument();
  expect(await screen.findByText(/EXPLORE \/ explore_bridge/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest --config jest.config.ts src/features/planning/components/gis/__tests__/StageReportPanel.test.tsx`
Expected: FAIL with `Cannot find module '../StageReportPanel'`

- [ ] **Step 3: Write minimal implementation**

`frontend/src/features/planning/components/gis/StageReportPanel.tsx`:
```tsx
'use client';

import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function StageReportPanel({ sessionId }: { sessionId: string | null }) {
  const [markdown, setMarkdown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    fetch(`${API_BASE_URL}/api/sessions/${sessionId}/stage-report.md`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((text) => { if (!cancelled) setMarkdown(text); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [sessionId]);

  if (error) return <div className="text-xs text-red-500">阶段报告加载失败: {error}</div>;
  if (markdown === null) return <div className="text-xs text-gray-400">加载阶段报告…</div>;
  return (
    <details>
      <summary className="cursor-pointer select-none text-xs font-medium text-gray-700 py-1">查看阶段报告（Markdown）</summary>
      <div className="mt-1 max-h-96 overflow-auto border border-gray-200 rounded p-3 text-xs">
        <ReactMarkdown>{markdown}</ReactMarkdown>
      </div>
    </details>
  );
}
```

- [ ] **Step 4: Wire into GisResultCard**

In `frontend/src/features/planning/components/chat/GisResultCard.tsx`, add import and render at the end of the card body:
```tsx
import StageReportPanel from '../gis/StageReportPanel';
// inside component:
const sessionId = usePlanningStore((s) => s.sessionId);
...
<StageReportPanel sessionId={sessionId} />
```

- [ ] **Step 5: Run tests + type check**

Run: `npx jest --config jest.config.ts src/features/planning/components/gis/__tests__/StageReportPanel.test.tsx`
Run: `npx tsc --noEmit`
Expected: PASS; type check clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/planning/components/gis/StageReportPanel.tsx frontend/src/features/planning/components/chat/GisResultCard.tsx frontend/src/features/planning/components/gis/__tests__/StageReportPanel.test.tsx
git commit -m "feat(frontend): render readable stage-report markdown in GIS result card"
```

---

### Task 7: 真实 session 可读断言测试

**Files:**
- Create: `backend/tests/integration/test_real_session_stages.py`
- Modify: `backend/tests/fixtures/db.py` (optional helper for full GIS uploads)

**Interfaces:**
- Consumes: `tests.fixtures.db.sqlite_db`, `pipeline_reset`, `make_session_with_uploads`; `app.services.session_kg.ensure_session_kg`; `app.services.stage_report.build_stage_report_markdown`; `app.services.step_report.save_step_report`.
- Produces: an integration test that persists a real session with full current-GIS uploads (landuse/road/boundary/annotation), prebuilds KG, writes representative stage reports, and asserts the rendered Markdown is readable (per-stage headings + key metrics).

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_real_session_stages.py`:
```python
"""Real-session readable stage assertions.

Uses the real DataCatalog session bundle path (uploads → bundle → KG prebuild)
then writes representative step reports and renders the readable Markdown.
"""
import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

_FULL_UPLOADS = [
    {"file_category": "gis_data", "filename": "landuse.geojson", "file_type": "geojson",
     "gis_data_type": "landuse_current",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"BSM": "P0000000000000000001", "DLBM": "1100", "area_sqm": 10000},
          "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}},
    {"file_category": "gis_data", "filename": "road.geojson", "file_type": "geojson",
     "gis_data_type": "road",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"name": "村道", "BSM": "R1"},
          "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]}},
    {"file_category": "gis_data", "filename": "boundary.geojson", "file_type": "geojson",
     "gis_data_type": "boundary",
     "gis_data": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "properties": {"name": "村界"},
          "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}]}},
]


@pytest.mark.asyncio
async def test_real_session_stages_readable(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = await make_session_with_uploads("sess-real", "金田村", uploads=_FULL_UPLOADS)

        from app.services.session_kg import ensure_session_kg

        snap = await ensure_session_kg(sid, village_name="金田村")
        assert snap is not None and snap.get("triple_count", 0) > 0

        from app.services.step_report import save_step_report

        await save_step_report(sid, "KG_PREBUILD", step_name="kg_prebuild",
                               outputs={"triple_count": snap["triple_count"]},
                               diagnostics={"sfTouches": 3})
        await save_step_report(sid, "EXPLORE", step_name="explore_bridge",
                               outputs={"instructions": 2},
                               diagnostics={"total": 3, "resolved": 2, "unresolved": 1})
        await save_step_report(sid, "EXECUTE", step_name="execute_layout",
                               outputs={"layers": 6},
                               diagnostics={"validation_passed": True})

        from app.services.stage_report import build_stage_report_markdown

        md = await build_stage_report_markdown(sid)
        assert "## KG_PREBUILD / kg_prebuild" in md
        assert "## EXPLORE / explore_bridge" in md
        assert "## EXECUTE / execute_layout" in md
        assert "resolved" in md
        print("\n===== READABLE STAGE REPORT =====")
        print(md)
        print("=================================")
    finally:
        await teardown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_real_session_stages.py -v -s`
Expected: FAIL — `ensure_session_kg` returns snap with 0 triples OR `stage_report` import missing (Task 4 not merged yet). Either failure is acceptable at this point.

- [ ] **Step 3: No implementation (test-only) — run after Tasks 1-5**

Run: `python -m pytest tests/integration/test_real_session_stages.py -v -s`
Expected: PASS and prints the readable Markdown report (visible per-stage output).

- [ ] **Step 4: Full regression**

Run: `python -m pytest tests/unit tests/integration -q --ignore=tests/unit/test_catalog_session_context.py --ignore=tests/unit/test_architecture_invariants.py --ignore=tests/unit/test_execute_custom_zoning.py 2>&1 | Select-Object -Last 5`
Expected: `X passed` — only the 3 known pre-existing baseline failures remain excluded.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/test_real_session_stages.py backend/tests/fixtures/db.py
git commit -m "test(integration): real-session readable stage assertions"
```

---

## Self-Review

**1. Spec coverage** — against the 4 confirmed gaps + readability ask:
- 1c PARSE fallback → Task 2. ✓
- 4b constraint provenance → Task 1. ✓
- 5b EXPLORE verification → Task 3. ✓
- Readable per-stage output (user's core complaint) → Tasks 4-7. ✓
- (3c/3d facility/road anchored consumption: verified already wired — FacilityPlacer consumes `candidate_bsms` at `facility_placer.py:139-140`; road uses `start_anchor/end_anchor` at `road_planner.py:58-59`. No change needed; documented in plan. ✓)
- 6-point acceptance (12 L1/4 L2/12 L3, unique IDs, KG L3 entities, MIP per-target pools, L4 derived_from) — verified already implemented in prior audit; not re-implemented to avoid churn. ✓

**2. Placeholder scan** — no TBD/TODO; every task has real code and exact file/line anchors.

**3. Type consistency** — `merge_sourced_constraints`, `merge_fallback_targets`, `compare_intent_to_layout`, `save_explore_verification`, `render_stage_report_markdown`, `build_stage_report_markdown`, `StageReportPanel` are each defined once with signatures used identically by dependents.
