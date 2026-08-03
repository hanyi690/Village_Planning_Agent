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
