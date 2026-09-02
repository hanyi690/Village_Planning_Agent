from __future__ import annotations

from types import SimpleNamespace

from rdflib import RDF, URIRef
import pytest

from app.contracts.cognition import SourceRecord
from app.data.resource_catalog import DataResourceCatalog
from app.infrastructure.cognition_runtime.world_model_store import (
    WorldModelKGStore,
)
from app.infrastructure.kg.ontology import PLN


def _catalog() -> DataResourceCatalog:
    records = [{
        "type": "Feature",
        "id": "parcel-1",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[116.0, 24.0], [116.001, 24.0], [116.0, 24.001], [116.0, 24.0]]],
        },
        "properties": {
            "name": "示例地块",
            "__data_logical_entity_ref": "parcel-entity",
            "__data_logical_part_ref": "parcel-part",
        },
    }]
    draft = DataResourceCatalog.from_records(
        records,
        dataset_ref="dataset:wm-v0",
        name="wm-v0",
        crs="EPSG:4326",
    )
    feature = draft.snapshot.features[0]
    return DataResourceCatalog.from_records(
        records,
        dataset_ref="dataset:wm-v0",
        name="wm-v0",
        crs="EPSG:4326",
        admission_decisions=[{
            "decision_ref": "admission:wm-v0:parcel-1",
            "source_ref": (
                f"resource:{feature.dataset_ref}:{feature.source_feature_ref}"
            ),
            "source_digest": feature.source_feature_digest,
            "input_role": "current_evidence",
            "status": "admitted",
            "resource_kind": "gis",
            "reason": "wm_v0_exit_gate",
        }],
    )


def test_wm_v0_bootstrap_reload_and_current_view_are_deterministic(tmp_path):
    catalog = _catalog()
    first = WorldModelKGStore(
        "wm-v0-session",
        "示例村",
        catalog,
        artifact_root=str(tmp_path),
    )
    first_snapshot = first.snapshot_contract()
    first_port = first.current_world

    source_rows = first_port.find_source_records(limit=10)
    entity_rows = first_port.find_entities(limit=10)
    assert len(source_rows) == 1
    assert len(entity_rows) == 1
    assert source_rows[0]["source_snapshot_ref"] == catalog.snapshot.snapshot_id
    assert entity_rows[0]["parts"][0]["source_feature_ref"]
    entity_ref = entity_rows[0]["entity_ref"]
    representation_rows = first_port.representations_for(entity_ref, limit=10)
    assert len(representation_rows) == 1
    assert representation_rows[0]["source_feature_ref"] == (
        entity_rows[0]["parts"][0]["source_feature_ref"]
    )
    for row in (
        source_rows[0],
        entity_rows[0],
        entity_rows[0]["parts"][0],
        representation_rows[0],
    ):
        assert row["snapshot_ref"] == first_snapshot.snapshot_ref
        assert row["snapshot_digest"] == first_snapshot.graph_digest
        assert row["current_world_digest"] == first_snapshot.current_world_digest
    assert not hasattr(first_port, "planned_graph")
    assert not hasattr(first_port, "intent_graph")
    assert not hasattr(first_port, "assertion_graph")
    assert not hasattr(first_port, "g")

    # Planned data exists physically in the Dataset but is outside this port.
    planned_entity = URIRef("urn:planning:test:planned-only")
    current_digest_before_planned = first.current_world_digest
    first.planned_graph.add((planned_entity, RDF.type, PLN.WorldEntity))
    assert first_port.find_entities(entity_ref=str(planned_entity)) == []
    assert first.current_world_digest == current_digest_before_planned

    planned_result = first.commit_planned_state(
        SimpleNamespace(features=[{"feature_id": "planned-only"}])
    )
    assert planned_result["status"] == "committed"
    planned_snapshot = first.snapshot_contract()
    assert planned_snapshot.snapshot_ref != first_snapshot.snapshot_ref
    assert planned_snapshot.graph_digest != first_snapshot.graph_digest
    assert planned_snapshot.current_world_digest == current_digest_before_planned
    assert first_port.find_entities(entity_ref=str(planned_entity)) == []

    post_commit_source_rows = first_port.find_source_records(limit=10)
    post_commit_entity_rows = first_port.find_entities(limit=10)
    post_commit_representation_rows = first_port.representations_for(
        entity_ref,
        limit=10,
    )

    second = WorldModelKGStore(
        "wm-v0-session",
        "示例村",
        catalog,
        artifact_root=str(tmp_path),
    )
    second_snapshot = second.snapshot_contract()

    assert planned_snapshot.snapshot_ref == second_snapshot.snapshot_ref
    assert planned_snapshot.graph_digest == second_snapshot.graph_digest
    assert planned_snapshot.current_world_digest == second_snapshot.current_world_digest
    assert planned_snapshot.source_record_refs == second_snapshot.source_record_refs
    assert planned_snapshot.entity_refs == second_snapshot.entity_refs
    assert planned_snapshot.representation_refs == second_snapshot.representation_refs
    assert first_snapshot.assertion_refs == ()
    assert planned_snapshot.assertion_refs == ()
    assert list(first.source_graph.subjects(RDF.type, PLN.NormalizedSourceClaim))
    assert list(second.source_graph.subjects(RDF.type, PLN.NormalizedSourceClaim))
    assert post_commit_source_rows == second.current_world.find_source_records(limit=10)
    assert post_commit_entity_rows == second.current_world.find_entities(limit=10)
    assert post_commit_representation_rows == second.current_world.representations_for(
        entity_ref,
        limit=10,
    )


def test_source_record_contract_uses_design_name_and_fields():
    record = SourceRecord(
        source_record_ref="source-record:dataset:feature",
        dataset_ref="dataset",
        source_feature_ref="feature",
        source_snapshot_ref="data:snapshot",
        source_digest="sha256:source",
    )
    assert record.source_record_ref.startswith("source-record:")
    assert record.input_role == "current_evidence"
    assert record.admission_status == "admitted"


def test_v2_consumers_require_the_current_world_port():
    from app.infrastructure.evidence_runtime.v2_catalog import _current_world_port
    from app.modules.ground.reference_resolution import _current_world_port as ground_current_world_port

    generic = object()
    current = object()
    context = SimpleNamespace(
        world_model_mode="v2_only",
        current_world=current,
        ports=SimpleNamespace(
            current_world=current,
            world_model=generic,
        ),
    )
    assert _current_world_port(context) is current
    assert ground_current_world_port(context) is current

    missing_current = SimpleNamespace(
        world_model_mode="v2_only",
        ports=SimpleNamespace(world_model=generic),
    )
    assert _current_world_port(missing_current) is None
    assert ground_current_world_port(missing_current) is None


def test_spatial_resolver_uses_current_world_in_v2_mode():
    from app.spatial.grounding.resolver import SpatialResolver

    current = object()
    resolver = SpatialResolver(
        SimpleNamespace(
            workspace=object(),
            kg=object(),
            world_model_mode="v2_only",
            ports=SimpleNamespace(current_world=current),
        ),
        ground_llm_budget={},
    )

    assert resolver.kg is current


@pytest.mark.asyncio
async def test_context_runtime_injects_current_world_port(tmp_path):
    from app.infrastructure.context_runtime.manager import build_planning_context

    context = await build_planning_context(
        "wm-v0-context-session",
        village_name="示例村",
        refresh=True,
        include_reports=False,
        data_catalog=_catalog(),
        artifact_root=str(tmp_path),
    )

    assert context.ports.current_world is not None
    assert context.ports.current_world.find_source_records(limit=10)
    assert context.capabilities["current_world"] is True


def test_current_view_consumers_do_not_reintroduce_whole_graph_access():
    module_roots = (
        "backend/app/modules/evidence",
        "backend/app/modules/ground",
        "backend/app/modules/l1",
        "backend/app/modules/l2",
        "backend/app/modules/l3",
    )
    forbidden = (
        "ports.world_model",
        "context.world_model.read_port",
        "context.kg.read_port",
        "KGWorldModelAdapter(",
    )
    from pathlib import Path

    for root in module_roots:
        for path in Path(root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert not any(token in text for token in forbidden), path
