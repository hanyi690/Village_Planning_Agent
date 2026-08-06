"""Per-node diagnostic for the post-L3 main-graph chain (Wave M).

Loads the REAL PlanningProgram artifact produced by the last fake-LLM run,
then invokes each post_l3_main_nodes node function directly with a minimal
AgentState, printing every gate decision. Bypasses the graph/astream/logging
so we can see exactly which node breaks and why.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("AMAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("BAIDU_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TECENT_MAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TIANDITU_WFS_ANCHOR_ENABLED", "false")

from scripts.mvp_verify_graph_chain import _FakeLLM, _build_uploads, _load_report_md, _load_session_config  # noqa: E402


def _route_of(gate) -> str:
    if gate is None:
        return "None"
    if isinstance(gate, dict):
        return str(gate.get("feedback_route"))
    return str(getattr(gate, "feedback_route", None))


async def main() -> int:
    import shutil
    import app.database.models  # noqa: F401
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    cfg = _load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "diag-graph.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    eng.async_engine = engine
    eng.AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    import app.modules.data.connections.base as conn_base
    import app.modules.kg.manager as kg_man
    import app.services.bundle_store as bs
    import app.services.session_bundle as sb

    sb._bundle_cache.clear()
    kg_man.KGManager._instance = None
    bs.BundleStore._instance = None
    conn_base.ConnectionRegistry._connections.clear()

    import app.agent.l1_observe.analysis_node as l1_node
    import app.agent.l2_strategize.worker as l2_worker
    import app.agent.l3_plan.worker as l3_worker
    import app.core.llm as llm_factory
    import app.modules.rag.service as rag_service_mod

    l1_node._get_llm = lambda: _FakeLLM()
    l2_worker._get_llm = lambda: _FakeLLM()
    l3_worker._get_llm = lambda: _FakeLLM()
    llm_factory.create_llm = lambda *a, **k: _FakeLLM()
    llm_factory.create_flash_llm = lambda *a, **k: _FakeLLM()

    import app.agent.parse.aggregate as parse_agg
    parse_agg.route_compilation = lambda result, diags: "merge"

    async def _fake_generate_queries(self, *a, **k):
        return ["测试查询"]

    async def _fake_search(self, *a, **k):
        return []

    rag_service_mod.RagService.generate_queries = _fake_generate_queries
    rag_service_mod.RagService.search = _fake_search

    session_id = "mvp-jintiancun"
    from tests.fixtures.db import make_session_with_uploads
    await make_session_with_uploads(session_id=session_id, village_name=cfg["village_name"], uploads=_build_uploads())

    from app.services.context.planning_context import build_planning_context
    ctx = await build_planning_context(session_id, refresh=True)
    _parcels = list((ctx.bundle.polygons.get("landuse_current") or [])) if ctx.bundle else []
    print(f"[diag] context: bundle={ctx.bundle is not None} gazetteer={ctx.gazetteer is not None} "
          f"gaz_entries={len(ctx.gazetteer.entries) if ctx.gazetteer else 0} "
          f"kg={ctx.kg is not None} parcels={len(_parcels)} "
          f"anchors={len(ctx.village_anchors or [])}")

    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    program = PlanningProgram.model_validate_json(
        Path(_BACKEND_DIR / ".run-tmp/mvp-jintiancun/artifacts/l3_plan/l3-mvp-jintiancun-v1/v1/payload.json").read_text(encoding="utf-8")
    )
    print(f"[diag] program interventions={len(program.interventions)}")

    from app.agent.bootstrap import post_l3_main_nodes as n
    from app.agent.bootstrap.graph import create_unified_planning_graph
    from app.services.artifact_store import FilesystemArtifactStore
    from app.services.runtime import PlanningRuntimeService

    await PlanningRuntimeService.ensure_initialized()
    FilesystemArtifactStore._instance = None

    base_state = {
        "session_id": session_id,
        "run_id": session_id,
        "context_version": "",
        "config": {"village_name": cfg["village_name"]},
        "planning_program": program,
        "retry_counts": {},
        "error_feedback": {},
        "upstream_gates": [],
        "layout_configs": [],
        "messages": [],
    }
    state = dict(base_state)

    # 1. PARSE
    print("\n===== 1. PARSE =====")
    try:
        out = await n.parse_node(state)
        specs = out.get("specs") or []
        print(f"  specs={len(specs)} parse_gate={_route_of(out.get('parse_gate'))}")
        for s in specs[:6]:
            print(f"    spec type={s.get('type')} dir={s.get('direction')} topo={s.get('topo')} attr={s.get('attr_filter')}")
        state.update(out)
        state["specs"] = specs
    except Exception as e:
        import traceback
        print(f"  PARSE EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    # 2. GROUND
    print("\n===== 2. GROUND =====")
    try:
        out = await n.ground_node(state)
        gr = out.get("grounding_result") or {}
        cands = gr.get("candidates") or []
        unrs = gr.get("unresolved") or []
        print(f"  candidates={len(cands)} unresolved={len(unrs)} ground_gate={_route_of(out.get('ground_gate'))}")
        for c in cands[:6]:
            print(f"    site={c.get('site_id')} parcels={len(c.get('source_parcels') or [])} conf={c.get('metrics', {}).get('confidence')}")
        state.update(out)
    except Exception as e:
        import traceback
        print(f"  GROUND EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    # 3. SELECT
    print("\n===== 3. SELECT =====")
    try:
        from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
        _intent_typed = n._to_typed(state.get("intent"), IntentCompilationResult)
        _ti = getattr(_intent_typed, "typed_intent", None) or {}
        _ti = _ti if isinstance(_ti, dict) else _ti.model_dump(mode="json")
        print(f"  intent: project={len(_ti.get('project_targets') or [])} "
              f"facility={len(_ti.get('facilities') or [])} "
              f"road={len(_ti.get('road_targets') or [])} "
              f"zone={len(_ti.get('zone_targets') or [])}")
        out = await n.select_node(state)
        sel = out.get("site_selection") or {}
        print(f"  selections={len(sel.get('selections') or [])} select_gate={_route_of(out.get('select_gate'))}")
        _df = sel.get("decision_factors") or {}
        print(f"  decision_factors={json.dumps(_df, ensure_ascii=False)[:400]}")
        _elim = sel.get("eliminated") or []
        _reasons = {}
        for e in _elim[:40]:
            r = (e.get("elimination_reason") or "?") + "|" + (e.get("eliminated_by_constraint") or "")[:40]
            _reasons[r] = _reasons.get(r, 0) + 1
        print(f"  eliminated_top={dict(list(sorted(_reasons.items(), key=lambda x: -x[1]))[:6])}")
        state.update(out)
    except Exception as e:
        import traceback
        print(f"  SELECT EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    # 4. EXECUTE
    print("\n===== 4. EXECUTE =====")
    try:
        _ldb = state.get("land_design_briefs") or []
        print(f"  land_design_briefs={len(_ldb)} refs={[b.get('project_ref') for b in _ldb[:5]]}")
        _ssel = state.get("site_selection") or {}
        print(f"  selected_combination={len(_ssel.get('selected_combination') or [])} first={(_ssel.get('selected_combination') or [])[:3]}")
        _ctx4 = await n._resolve_context(state)
        _b4 = getattr(_ctx4, "bundle", None)
        _gd4 = _b4.to_geojson_dict() if _b4 is not None and hasattr(_b4, "to_geojson_dict") else {}
        _lu4 = _gd4.get("landuse_current_geojson") or {}
        _feats4 = _lu4.get("features") or []
        print(f"  gis_data landuse features={len(_feats4)}")
        from shapely.geometry import shape as _shp2
        for _tgt in ("820", "840"):
            for _f in _feats4:
                _pr = _f.get("properties") or {}
                _bsm = str(_pr.get("bsm") or _pr.get("BSM") or "")
                if _tgt in _bsm:
                    _g = _f.get("geometry") or {}
                    try:
                        _s = _shp2(_g)
                        print(f"    SOURCE bsm={_bsm} geom={_s.geom_type} valid={_s.is_valid} "
                              f"parts={len(_s.geoms) if _s.geom_type=='MultiPolygon' else 1} area_ha={round(_s.area/10000,4)}")
                        if _s.geom_type == "MultiPolygon":
                            for _pi, _p in enumerate(_s.geoms):
                                print(f"      part[{_pi}] area_ha={round(_p.area/10000,6)} bounds={[round(x,6) for x in _p.bounds]}")
                    except Exception as _e:
                        print(f"    SOURCE bsm={_bsm} parse_err={_e}")
                    break
        if _feats4:
            print(f"    first props keys={list((_feats4[0].get('properties') or {}).keys())[:12]}")
            print(f"    first bsm value={(_feats4[0].get('properties') or {}).get('bsm')}")
            _bsms4 = set(str((f.get('properties') or {}).get('bsm') or (f.get('properties') or {}).get('BSM') or "") for f in _feats4)
            _sel4 = set(_ssel.get('selected_combination') or [])
        print(f"    landuse bsm sample={list(_bsms4)[:3]}")
        print(f"    selected in landuse bsm: {len(_sel4 & _bsms4)}/{len(_sel4)}")
        try:
            from app.agent.execute.execute_agent import _build_parcel_by_bsm
            from app.agent.execute.execute_state import ExecuteAgentState
            from app.agent.execute.land_design_worker import design_project_footprint
            from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
            _ti4 = state.get("intent")
            _ti4 = _ti4.get("typed_intent") if isinstance(_ti4, dict) else getattr(_ti4, "typed_intent", None)
            _plan4 = n._to_typed(_ti4, SpatialPlanningIntent)
            _es4 = ExecuteAgentState(gis_data=_gd4, gis_bundle=_b4, intent=_plan4)
            _pb4 = _build_parcel_by_bsm(_es4)
            _prj0 = _plan4.project_targets[0]
            _ldb4 = state.get("land_design_briefs") or []
            from app.modules.schema.contracts.selection_contracts import LandDesignBrief
            _brief0 = n._to_typed(_ldb4[0], LandDesignBrief) if _ldb4 else None
            _sel_comb = _ssel.get("selected_combination") or []
            _selbsm = str(_sel_comb[0]) if _sel_comb else ""
            print(f"    repro project0={_prj0.project_id} brief0={getattr(_brief0,'project_ref','')} bsm={_selbsm} "
                  f"parcel_found={_pb4.get(_selbsm) is not None}")
            _ch0 = design_project_footprint(_prj0, _brief0, _selbsm, _pb4)
            print(f"    repro design_project_footprint -> {len(_ch0)} changes")
        except Exception as e:
            import traceback
            print(f"    repro EXCEPTION: {e}")
            traceback.print_exc()
        try:
            from app.agent.execute.execute_agent import _project_worker
            from app.agent.execute.execute_state import ExecuteAgentState
            from app.modules.schema.contracts.selection_contracts import LandDesignBrief, SiteSelectionDecision
            _es_full = ExecuteAgentState(
                session_id=state.get("session_id", ""),
                gis_data=_gd4,
                gis_bundle=_b4,
                intent=_plan4,
                site_selection=n._to_typed(state.get("site_selection"), SiteSelectionDecision),
                land_design_briefs=[n._to_typed(b, LandDesignBrief) for b in (state.get("land_design_briefs") or [])],
            )
            _wr = _project_worker(_es_full)
            print(f"  _project_worker changes={len(_wr.parcel_changes)} "
                  f"diagnostics={[d.get('code') for d in _wr.diagnostics]}")
            _t = getattr(_es_full, "tasks_to_run", None)
            print(f"  tasks_to_run={_t}")
        except Exception as e:
            import traceback
            print(f"  _project_worker EXCEPTION: {e}")
            traceback.print_exc()
        try:
            from app.agent.execute.execute_agent import build_execute_agent_graph
            _eg = build_execute_agent_graph()
            _ed = _es_full.model_dump()
            _ed["gis_bundle"] = _b4
            _ed["intent"] = _plan4
            _ed["site_selection"] = n._to_typed(state.get("site_selection"), SiteSelectionDecision)
            _r = await _eg.ainvoke(_ed, config={"configurable": {"__pregel_checkpointer": None}})
            _wr_all = _r.get("worker_results") or []
            print(f"  execute_agent worker_results={[getattr(w,'worker_type',None) for w in _wr_all]}")
            print(f"  execute_agent tasks_to_run={_r.get('tasks_to_run')}")
            print(f"  execute_agent changes={len(_r.get('parcel_changes') or [])} errors={len(_r.get('execution_errors') or [])}")
            _pb_r = _r.get("parcel_by_bsm") or {}
            print(f"  execute_agent parcel_by_bsm keys={len(_pb_r)} sample={list(_pb_r.keys())[:3]}")
            _ss_r = _r.get("site_selection")
            _ss_comb = getattr(_ss_r, "selected_combination", None) if _ss_r is not None else None
            if _ss_comb is None and isinstance(_ss_r, dict):
                _ss_comb = _ss_r.get("selected_combination")
            print(f"  execute_agent site_selection={_ss_r is not None} selected_combination={len(_ss_comb or [])}")
            _int_r = _r.get("intent")
            print(f"  execute_agent intent type={type(_int_r).__name__} "
                  f"projects={len(getattr(_int_r, 'project_targets', []) or []) if _int_r else 0}")
            _ldb_r = _r.get("land_design_briefs") or []
            print(f"  execute_agent land_design_briefs={len(_ldb_r)}")
            for w in _wr_all:
                print(f"    {getattr(w,'worker_type',None)}: changes={len(getattr(w,'parcel_changes',[]) or [])} "
                      f"diags={[d.get('code') for d in (getattr(w,'diagnostics',[]) or [])][:3]}")
        except Exception as e:
            import traceback
            print(f"  execute_agent EXCEPTION: {e}")
            traceback.print_exc()
        out = await n.execute_node(state)
        print(f"  planned_state={out.get('planned_state') is not None} changeset={out.get('parcel_changeset') is not None} "
              f"layout_configs={len(out.get('layout_configs') or [])} errors={len(out.get('execution_errors') or [])}")

        from types import SimpleNamespace

        def _scan(o, path=""):
            hits = []
            if isinstance(o, SimpleNamespace):
                hits.append(path)
            if isinstance(o, dict):
                for k, v in o.items():
                    hits += _scan(v, f"{path}.{k}")
            elif isinstance(o, (list, tuple)):
                for i, v in enumerate(o):
                    hits += _scan(v, f"{path}[{i}]")
            return hits

        for key in ("planned_state", "parcel_changeset", "layout_configs", "allocated_geojson", "execution_errors"):
            hits = _scan(out.get(key))
            print(f"    scan {key}: {'CLEAN' if not hits else 'SimpleNamespace at ' + str(hits[:5])}")
        print(f"    execution_errors detail: {json.dumps(out.get('execution_errors'), ensure_ascii=False, indent=1)}")
        _cs = out.get("parcel_changeset") or {}
        _chgs = _cs.get("changes") or []
        print(f"    changeset changes={len(_chgs)} conservation={_cs.get('area_conservation_verified')} validity={_cs.get('geometry_validity_verified')}")
        _stat = {}
        for c in _chgs:
            k = str(c.get("action") or "?")
            g = str(c.get("after_geometry_wkt") or "")
            _stat[k] = _stat.get(k, [0, 0])
            _stat[k][0] += 1
            if not g:
                _stat[k][1] += 1
        print(f"    changes_by_action(empty_geom)={_stat}")
        state.update(out)
        from shapely.geometry import shape as _shp
        for _lc in (out.get("layout_configs") or []):
            _lt = _lc.get("layerType", "")
            _feats = ((_lc.get("data") or {}).get("features") or [])
            for _ft in _feats:
                _g = _ft.get("geometry") or {}
                _pr = _ft.get("properties") or {}
                _bsm = _pr.get("bsm") or _pr.get("source_bsm") or "?"
                try:
                    _s = _shp(_g)
                    _union = None
                    if _s.geom_type == "MultiPolygon" and len(_s.geoms) > 1:
                        from shapely.ops import unary_union as _uu
                        _union = _uu(_s)
                    print(f"    LAYER[{_lt}] bsm={_bsm} geom={_s.geom_type} parts={len(_s.geoms) if _s.geom_type=='MultiPolygon' else 1} "
                          f"valid={_s.is_valid} union_type={_union.geom_type if _union is not None else '-'} "
                          f"union_parts={len(_union.geoms) if _union is not None and _union.geom_type=='MultiPolygon' else '-'}")
                except Exception:
                    pass
    except Exception as e:
        import traceback
        print(f"  EXECUTE EXCEPTION: {e}")
        traceback.print_exc()
        import os as _os
        _os._exit(1)
        return 1

    # 5. VALIDATE
    print("\n===== 5. VALIDATE =====")
    try:
        out = await n.validate_node(state)
        rep = out.get("validation_report") or {}
        print(f"  validation_report={out.get('validation_report') is not None} "
              f"overall_passed={rep.get('overall_passed')} validate_gate={_route_of(out.get('validate_gate'))}")
        _fc = [c for c in (rep.get("checks") or []) if not c.get("passed")]
        print(f"  failed_checks={len(_fc)}")
        for c in _fc[:5]:
            print(f"    - {c.get('check_id')}|{c.get('check_name')}|stage={c.get('responsible_stage')}: "
                  f"{str(c.get('actual_value'))[:60]} passed={c.get('passed')}")
        _ib = rep.get("issues_by_stage") or {}
        print(f"  issues_by_stage={ {k: len(v) for k, v in _ib.items()} }")
        print(f"  validate_gate_dict_keys={list(out.get('validate_gate').keys()) if isinstance(out.get('validate_gate'), dict) else 'obj'}")
        state.update(out)
    except Exception as e:
        import traceback
        print(f"  VALIDATE EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    # 6. RECONCILE
    print("\n===== 6. RECONCILE =====")
    try:
        out = await n.reconcile_node(state)
        rep = out.get("reconciliation_report") or {}
        print(f"  reconciliation_report={out.get('reconciliation_report') is not None} reconcile_gate={_route_of(out.get('reconcile_gate'))}")
        state.update(out)
    except Exception as e:
        import traceback
        print(f"  RECONCILE EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    # 7. DELIVER
    print("\n===== 7. DELIVER =====")
    try:
        out = await n.deliver_node(state)
        man = out.get("delivery_manifest") or {}
        print(f"  delivery_manifest={out.get('delivery_manifest') is not None} "
              f"manifest_keys={list(man.keys())[:8] if man else None} deliver_gate={_route_of(out.get('deliver_gate'))}")
        state.update(out)
    except Exception as e:
        import traceback
        print(f"  DELIVER EXCEPTION: {e}")
        traceback.print_exc()
        return 1

    print("\n[diag] ALL 7 NODES COMPLETED")
    print(f"[diag] final upstream_gates routes: {[_route_of(g) for g in state.get('upstream_gates') or []]}")
    print(f"[diag] delivery_manifest present={state.get('delivery_manifest') is not None}")
    await engine.dispose()
    import os as _os
    _os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
