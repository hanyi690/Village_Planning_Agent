"""Temporary: inspect 820/840 bsm geometries to decide continuity handling."""
import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    import scripts._diag_postl3 as d

    state = await d._build_state()

    from app.agent.bootstrap.post_l3_main_nodes import _to_typed, _resolve_context
    from app.agent.execute.execute_agent import _build_parcel_by_bsm
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.land_design_worker import design_project_footprint
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import (
        LandDesignBrief,
        SiteSelectionDecision,
    )

    intent = _to_typed(state.get("intent"), IntentCompilationResult)
    plan_intent = _to_typed(getattr(intent, "typed_intent", None) or intent, SpatialPlanningIntent)
    site_selection = _to_typed(state.get("site_selection"), SiteSelectionDecision)
    context = await _resolve_context(state)
    bundle = getattr(context, "bundle", None)
    gis_data = bundle.to_geojson_dict() if bundle is not None else {}

    es = ExecuteAgentState(
        gis_data=gis_data,
        gis_bundle=bundle,
        intent=plan_intent,
        site_selection=site_selection,
        land_design_briefs=[
            _to_typed(b, LandDesignBrief) for b in (state.get("land_design_briefs") or [])
        ],
        execution_plan=_to_typed(state.get("execution_plan"), ExecutionPlan),
    )
    pb = _build_parcel_by_bsm(es)
    sel = list(site_selection.selected_combination or [])
    briefs = es.land_design_briefs
    projects_by_id = {p.project_id: p for p in plan_intent.project_targets}

    from shapely.geometry import shape

    for i, bsm in enumerate(sel):
        brief = briefs[i] if i < len(briefs) else None
        project = projects_by_id.get(brief.project_ref) if brief else None
        if not project:
            continue
        chs = design_project_footprint(project, brief, str(bsm), pb)
        for c in chs:
            if str(c.bsm).endswith("820") or str(c.bsm).endswith("840") or True:
                pass
        # only print the target bsms
        if "820" in str(bsm) or "840" in str(bsm):
            print("bsm:", bsm, "project:", project.project_id)
            for c in chs:
                aw = c.after_geometry_wkt or ""
                if not aw:
                    print("   EMPTY WKT, action=", c.action)
                    continue
                from shapely import wkt

                g = wkt.loads(aw)
                print("   action=%s geom_type=%s valid=%s empty=%s" % (c.action, g.geom_type, g.is_valid, g.is_empty))
                if g.geom_type == "MultiPolygon":
                    print("     parts=%d areas=%s" % (len(g.geoms), [round(float(p.area) / 10000, 4) for p in g.geoms]))
                    # check if parts touch/near each other
                    if len(g.geoms) == 2:
                        d_ = g.geoms[0].distance(g.geoms[1])
                        print("     part distance (deg):", round(d_, 8))
                elif g.geom_type == "Polygon":
                    print("     area_ha=", round(float(g.area) / 10000, 4))


asyncio.run(main())
