def test_compare_intent_to_layout_detects_missing_project():
    from app.agent.explore.verification import compare_intent_to_layout
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_contracts import ProjectTarget, ZoneTarget

    intent = SpatialPlanningIntent(
        project_targets=[ProjectTarget(project_id="PRJ-1", name="古驿道修复")],
        zone_targets=[ZoneTarget(land_use="生态保护区", area_ha=330.0)],
    )
    layout_configs = [
        {"layerType": "custom_planning_zone", "data": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"zone_name": "生态保护区", "area_ha": 400.0}, "geometry": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}},
        ]}},
    ]
    result = compare_intent_to_layout(intent, layout_configs)
    assert any(d["check"] == "project_placement" for d in result["differences"])
    assert any(d["check"] == "zone_area" for d in result["differences"])
    assert result["revision_suggestions"]
