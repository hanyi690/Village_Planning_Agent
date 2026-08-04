"""Spec mapper tests - PlanningIntervention -> SpatialReferenceSpec (deterministic)."""
from __future__ import annotations

from app.modules.parsing.compiler.spec_mapper import (
    map_intervention_to_spec,
    map_interventions_to_specs,
)
from app.modules.schema.contracts.l3_contracts import PlanningIntervention


def _intervention(**kwargs) -> PlanningIntervention:
    defaults = {
        "intervention_id": "itv-1",
        "name": "test intervention",
        "spatial_requirements": {},
    }
    defaults.update(kwargs)
    return PlanningIntervention(**defaults)


def test_directional_mapping():
    spec = map_intervention_to_spec(
        _intervention(spatial_requirements={"location": "村东北侧"})
    )
    assert spec is not None
    assert spec.type == "directional"
    assert spec.direction == "NE"
    assert spec.reference is not None
    assert spec.reference.kind == "village"


def test_attributive_mapping():
    spec = map_intervention_to_spec(
        _intervention(spatial_requirements={"dlbm_in": ["0301", "0302"]})
    )
    assert spec is not None
    assert spec.type == "attributive"
    assert spec.attr_filter == {"dlbm_in": ["0301", "0302"]}


def test_topological_mapping():
    spec = map_intervention_to_spec(
        _intervention(spatial_requirements={"adjacent_to": "文化广场"})
    )
    assert spec is not None
    assert spec.type == "topological"
    assert spec.topo == "sfTouches"
    assert spec.reference is not None
    assert spec.reference.kind == "entity_type"
    assert spec.reference.filter == {"label_contains": "文化广场"}


def test_composed_mapping():
    spec = map_intervention_to_spec(
        _intervention(spatial_requirements={"location": "村北", "dlbm_in": ["0101"]})
    )
    assert spec is not None
    assert spec.type == "composed"
    assert spec.op == "and"
    assert len(spec.children) == 2


def test_unmappable_single_returns_none():
    spec = map_intervention_to_spec(
        _intervention(spatial_requirements={})
    )
    assert spec is None


def test_unmappable_batch_emits_diagnostic():
    specs, diagnostics = map_interventions_to_specs(
        [_intervention(spatial_requirements={})]
    )
    assert specs == []
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "AMBIGUOUS_REFERENCE"


def test_batch_mixed_mappable_and_unmappable():
    specs, diagnostics = map_interventions_to_specs(
        [
            _intervention(
                intervention_id="itv-ok",
                spatial_requirements={"dlbm_in": ["0101"]},
            ),
            _intervention(
                intervention_id="itv-bad",
                spatial_requirements={},
            ),
        ]
    )
    assert len(specs) == 1
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "AMBIGUOUS_REFERENCE"
