from types import SimpleNamespace

from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.workflow.parse_contracts import SpatialPlanningIntent, ZoneTarget
from app.domain.allocation.global_zone_select import (
    allocate_zones_for_select,
    build_global_zone_problem,
)
from app.domain.suitability.model import SuitabilityCandidate, SuitabilitySurface


def _target(target_id: str) -> ZoneTarget:
    return ZoneTarget(
        target_id=target_id,
        zone_id=f"zone-{target_id}",
        land_use="农村道路",
        area_ha=1.0,
        candidate_bsms=["P1", "P2"],
        classification_decision=ClassificationDecision(
            target_id=target_id,
            code_system=ClassificationSystem.GBT21010,
            candidate_codes=["1006"],
            selected_code="1006",
            evidence_refs=[f"claim:{target_id}"],
            status="resolved",
        ),
    )


def _context():
    parcels = [
        SimpleNamespace(
            bsm="P1", area_sqm=10000.0, geometry={"type": "Polygon", "coordinates": []},
            mapping_provenance={"source": "fixture"},
        ),
        SimpleNamespace(
            bsm="P2", area_sqm=10000.0, geometry={"type": "Polygon", "coordinates": []},
            mapping_provenance={"source": "fixture"},
        ),
    ]
    workspace = SimpleNamespace(polygons={"landuse_current": parcels})
    return SimpleNamespace(workspace=workspace, constraint_index=None)


def test_select_adapter_builds_only_target_bound_parcel_facts():
    intent = SpatialPlanningIntent(zone_targets=[_target("A")])
    suitability = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="site-A",
                target_id="A",
                source_parcels=["P1"],
                score=0.8,
                hard_feasible=True,
                evidence_refs=["ground:A"],
            ),
            SuitabilityCandidate(
                candidate_id="site-other",
                target_id="other",
                source_parcels=["P2"],
                score=1.0,
                hard_feasible=True,
                evidence_refs=["ground:other"],
            ),
        ]
    )

    problem = build_global_zone_problem(intent, suitability, _context())

    assert [item.bsm for item in problem.parcels] == ["P1"]
    assert [item.bsm for item in problem.candidate_sets[0].candidates] == ["P1"]
    assert problem.parcels[0].geometry_ref == "bundle:landuse_current:P1"


def test_select_adapter_resolves_zone_conflict_globally():
    intent = SpatialPlanningIntent(zone_targets=[_target("A"), _target("B")])
    suitability = SuitabilitySurface(
        candidates=[
            SuitabilityCandidate(
                candidate_id="site-A",
                target_id="A",
                source_parcels=["P1", "P2"],
                score=0.9,
                hard_feasible=True,
                evidence_refs=["ground:A"],
            ),
            SuitabilityCandidate(
                candidate_id="site-B",
                target_id="B",
                source_parcels=["P1", "P2"],
                score=0.8,
                hard_feasible=True,
                evidence_refs=["ground:B"],
            ),
        ]
    )

    result = allocate_zones_for_select(intent, suitability, _context())

    assert result.status == "OPTIMAL"
    assert len(result.assignments) == 2
    assert len({item.bsm for item in result.assignments}) == 2


def test_select_adapter_keeps_missing_candidate_fail_closed():
    intent = SpatialPlanningIntent(zone_targets=[_target("A")])
    result = allocate_zones_for_select(intent, SuitabilitySurface(), _context())

    assert result.status in {"MODEL_INVALID", "INFEASIBLE"}
    assert result.assignments == []
    assert any(item.code == "ZONE_NO_FEASIBLE_CANDIDATE" for item in result.diagnostics)
