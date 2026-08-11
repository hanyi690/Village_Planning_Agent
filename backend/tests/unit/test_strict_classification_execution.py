from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent.execute.land_design_worker import (
    design_facility_parcel,
    design_project_parcel,
    design_zone_parcel,
)
from app.agent.select.aggregate import _candidate_site_to_parcels
from app.modules.parsing.table_schema_inference import map_table_to_zone_targets
from app.modules.schema.contracts.classification_ref import (
    ClassificationDecision,
    ClassificationRef,
    classification_code_names,
)
from app.modules.schema.contracts.grounding_contracts import CandidateSite
from app.modules.schema.contracts.parse_contracts import (
    FacilityTarget,
    ProjectTarget,
    ZoneTarget,
)
from app.modules.schema.contracts.selection_contracts import LandDesignBrief


def _decision(system: str = "ghytbm", code: str = "1100") -> ClassificationDecision:
    return ClassificationDecision(
        target_id="target-1",
        code_system=system,
        candidate_codes=[code],
        selected_code=code,
        evidence_refs=["test:explicit"],
        status="resolved",
    )


def _parcel() -> dict:
    return {
        "bsm": "p1",
        "dlbm": "1100",
        "dlbm_system": "ghytbm",
        "area_sqm": 10000.0,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]],
        },
    }


def test_classification_refs_reject_cross_system_codes() -> None:
    with pytest.raises(ValidationError):
        ClassificationRef(
            system="ghytbm",
            code="0101",
            canonical_name=classification_code_names("gbt21010")["0101"],
            source="ingested",
        )

    with pytest.raises(ValidationError):
        ClassificationDecision(
            target_id="target-1",
            code_system="ghytbm",
            candidate_codes=["0101"],
            selected_code="0101",
            evidence_refs=["test:cross-system"],
            status="resolved",
        )

    with pytest.raises(ValidationError):
        ClassificationDecision(
            target_id="target-1",
            code_system="custom",
            candidate_codes=["自由文本分类码"],
            selected_code="自由文本分类码",
            evidence_refs=["test:free-text"],
            status="resolved",
        )


def test_table_parse_requires_explicit_classification_namespace() -> None:
    ambiguous = map_table_to_zone_targets(
        [["耕地", "1100", "10%"]],
        ["名称", "DLBM", "比例"],
    )
    assert ambiguous[0].classification_decision is None
    assert ambiguous[0].vne_code is None

    explicit = map_table_to_zone_targets(
        [["耕地", "1100", "10%"]],
        ["名称", "GHYTBM", "比例"],
    )
    decision = explicit[0].classification_decision
    assert decision is not None
    assert decision.code_system.value == "ghytbm"
    assert decision.selected_code == "1100"


def test_select_keeps_parcel_names_in_the_declared_namespace() -> None:
    site = CandidateSite(site_id="site-1", source_parcels=["p1"])
    parcel = SimpleNamespace(
        geometry={},
        dlbm="0101",
        dlbm_system="gbt21010",
        area_sqm=10000.0,
    )
    selected = _candidate_site_to_parcels(site, {"p1": parcel})
    assert selected[0].dlmc == classification_code_names("gbt21010")["0101"]

    parcel.dlbm = "1100"
    parcel.dlbm_system = "ghytbm"
    selected = _candidate_site_to_parcels(site, {"p1": parcel})
    assert selected[0].dlmc == classification_code_names("ghytbm")["1100"]

    parcel.dlbm_system = ""
    selected = _candidate_site_to_parcels(site, {"p1": parcel})
    assert selected[0].dlmc == ""


def test_execute_does_not_classify_from_zone_free_text() -> None:
    target = ZoneTarget(
        zone_id="zone-1",
        land_use="自由文本分类",
        candidate_bsms=["p1"],
    )
    assert design_zone_parcel(target, {"p1": _parcel()}) == []

    target.classification_decision = _decision()
    changes = design_zone_parcel(target, {"p1": _parcel()})
    assert len(changes) == 1
    assert changes[0].after_classification.system.value == "ghytbm"
    assert changes[0].after_classification.code == "1100"


def test_execute_does_not_classify_from_project_brief_text() -> None:
    project = ProjectTarget(project_id="project-1", name="项目", candidate_bsms=["p1"])
    brief = LandDesignBrief(
        project_ref="project-1",
        footprint_conditions=["code:1100"],
    )
    assert design_project_parcel(project, brief, "p1", {"p1": _parcel()}) is None

    project.classification_decision = _decision()
    change = design_project_parcel(project, brief, "p1", {"p1": _parcel()})
    assert change is not None
    assert change.after_classification.code == "1100"


def test_execute_does_not_classify_facility_from_type_text() -> None:
    facility = FacilityTarget(
        type="自由文本设施",
        status="planned_new",
        anchor_point=(0.005, 0.005),
    )
    assert design_facility_parcel(facility, {"p1": _parcel()}, None) is None

    facility.classification_decision = _decision()
    change = design_facility_parcel(facility, {"p1": _parcel()}, None)
    assert change is not None
    assert change.after_classification.code == "1100"


def test_planning_zone_lookup_fails_closed_without_matching_evidence() -> None:
    from app.modules.schema.encodings.classification import get_schema

    assert get_schema().get_planning_zone_for_zone_type("not-a-real-zone") == ""
