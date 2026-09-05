from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shapely.geometry import GeometryCollection, LineString, Polygon, mapping

from app.contracts.data.source_contracts import SourceAdmissionDecision
from app.data.boundary_scope import build_boundary_scope_artifact
from app.data.resource_catalog import DataResourceCatalog
from app.infrastructure.evidence_runtime.source_semantic_runtime import (
    collect_authoritative_source_features,
)


def test_jintian_landuse_repair_keeps_surface_family_and_audits_feature_343():
    payload = json.loads(
        Path("data/gis/jintian/current/landuse.geojson").read_text(
            encoding="utf-8-sig"
        )
    )
    raw = payload["features"][343]
    catalog = DataResourceCatalog.from_records(
        [{"geometry": raw["geometry"], "properties": raw.get("properties") or {}}],
        dataset_ref="jintian:current:landuse",
        crs="EPSG:4326",
    )
    feature = catalog.snapshot.features[0]
    audit = feature.topology_repair_audit
    assert audit["policy"] == "surface_family_compatible"
    assert audit["source_geometry_type"] == audit["repaired_geometry_type"]
    assert audit["source_part_count"] != audit["repaired_part_count"]
    assert audit["review_required"] is True
    assert feature.normalized_geometry is not None


def test_lower_dimensional_make_valid_result_stays_unresolved():
    catalog = DataResourceCatalog.from_records(
        [{
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [0.0, 0.0],
                    [1.0, 1.0],
                    [1.0, 2.0],
                    [1.0, 1.0],
                    [0.0, 0.0],
                ]],
            },
        }],
        dataset_ref="test:mixed-dimension",
        crs="EPSG:4326",
    )
    feature = catalog.snapshot.features[0]
    audit = feature.topology_repair_audit
    assert audit["repaired_geometry_type"] == "MultiLineString"
    assert audit["repaired_geometry_family"] == "line"
    assert feature.normalized_geometry is None
    assert feature.crs_transform[-1] == "invalid_geometry"


def test_mixed_dimension_make_valid_result_is_preserved_as_read_only_collection():
    invalid_polygon = Polygon(
        [(0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]
    )
    repaired = GeometryCollection([
        Polygon([(0.0, 0.0), (0.5, 0.5), (0.0, 1.0), (0.0, 0.0)]),
        LineString([(0.5, 0.5), (1.0, 1.0)]),
    ])
    with patch("shapely.make_valid", return_value=repaired):
        catalog = DataResourceCatalog.from_records(
            [{"geometry": mapping(invalid_polygon)}],
            dataset_ref="test:collection-adaptation",
            crs="EPSG:4326",
        )

    feature = catalog.snapshot.features[0]
    representation = catalog.snapshot.representations[0]
    operations = {item.operation for item in catalog.snapshot.capabilities}
    assert feature.geometry_kind == "polygon"
    assert feature.normalized_geometry_kind == "collection"
    assert feature.normalized_geometry["type"] == "GeometryCollection"
    assert feature.topology_repair_audit["representation_adaptation"] == (
        "complete_geometry_collection_read_only"
    )
    assert representation.geometry_kind == "collection"
    assert operations == {"read"}
    assert {item.geometry_kind for item in catalog.snapshot.capabilities} == {"collection"}


def test_unknown_native_geometry_is_lossless_read_only_and_wm_safe():
    from rdflib import Graph, RDF

    from app.contracts.data.source_contracts import SourceAdmissionDecision
    from app.data.admission import assert_cognition_ready_catalog
    from app.infrastructure.kg.adapters.source_catalog_adapter import (
        project_source_catalog,
    )
    from app.infrastructure.kg.ontology import PLN

    native_geometry = {
        "type": "CircularString",
        "coordinates": [[0.0, 0.0], [0.5, 0.8], [1.0, 0.0]],
        "vendor_payload": {"radius_unit": "m"},
    }
    draft = DataResourceCatalog.from_records(
        [{"geometry": native_geometry, "properties": {"label": "unknown curve"}}],
        dataset_ref="test:opaque-geometry",
        crs="EPSG:4326",
    )
    feature = draft.snapshot.features[0]
    representation = draft.snapshot.representations[0]
    capabilities = draft.snapshot.capabilities
    decision = SourceAdmissionDecision(
        decision_ref="data.admission:opaque-geometry",
        source_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
        source_digest=feature.source_feature_digest,
        input_role="current_evidence",
        status="admitted",
        resource_kind="opaque",
    )
    catalog = DataResourceCatalog(draft.snapshot.model_copy(update={
        "admission_decisions": (decision,),
    }))

    assert feature.geometry_kind == "opaque"
    assert feature.normalized_geometry is None
    assert feature.geometry == native_geometry
    assert feature.diagnostics[0] == "opaque_geometry_read_only"
    assert representation.geometry_kind == "opaque"
    assert representation.status == "read_only"
    assert {item.operation for item in capabilities} == {"read"}
    assert_cognition_ready_catalog(catalog.snapshot)
    assert catalog.resolve_geometry(
        resource_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
        normalized=False,
    ) == native_geometry
    assert catalog.resolve_geometry(
        resource_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
    ) is None

    source_graph = Graph()
    world_graph = Graph()
    project_source_catalog(source_graph, catalog, world_graph=world_graph)
    assert len(list(source_graph.subjects(RDF.type, PLN.SourceRecord))) == 1
    assert len(list(world_graph.subjects(RDF.type, PLN.WorldEntity))) == 0


def test_collection_normalized_kind_cannot_receive_source_polygon_semantic_role():
    invalid_polygon = Polygon(
        [(0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]
    )
    repaired = GeometryCollection([
        Polygon([(0.0, 0.0), (0.5, 0.5), (0.0, 1.0), (0.0, 0.0)]),
        LineString([(0.5, 0.5), (1.0, 1.0)]),
    ])
    with patch("shapely.make_valid", return_value=repaired):
        catalog = DataResourceCatalog.from_records(
            [{"geometry": mapping(invalid_polygon)}],
            dataset_ref="test:collection-role",
            layer_ref="landuse",
            crs="EPSG:4326",
        )

    from rdflib import Graph, RDF

    from app.infrastructure.kg.adapters.source_catalog_adapter import (
        project_source_catalog,
    )
    from app.infrastructure.kg.ontology import PLN

    feature = catalog.snapshot.features[0]
    admitted = SourceAdmissionDecision(
        decision_ref="data.admission:collection-role",
        source_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
        source_digest=feature.source_feature_digest,
        input_role="current_evidence",
        status="admitted",
        resource_kind="collection",
    )
    catalog = DataResourceCatalog(catalog.snapshot.model_copy(update={
        "admission_decisions": (admitted,),
    }))
    graph = Graph()
    project_source_catalog(
        graph,
        catalog,
        schema_mapping_snapshot=type(
            "Snapshot",
            (),
            {
                "collection_profiles": (
                    type(
                        "Profile",
                        (),
                        {"collection_ref": "c", "dataset_ref": feature.dataset_ref, "layer_ref": feature.layer_ref},
                    )(),
                ),
                "decisions": (
                    type(
                        "Decision",
                        (),
                        {
                            "collection_ref": "c",
                            "field_name": "geometry:polygon",
                            "status": "accepted",
                            "decision_ref": "decision:polygon",
                            "candidate_concept_ref": "landuse",
                            "representation_role_ref": "polygon_surface",
                            "candidate_property_ref": "",
                        },
                    )(),
                ),
            },
        )(),
    )
    representation = next(
        subject
        for subject in graph.subjects(RDF.type, PLN.SpatialRepresentation)
        if str(graph.value(subject, PLN.geometryKind) or "") == "collection"
    )
    assert list(graph.objects(representation, PLN.representationPurpose)) == []


def test_geometry_collection_cannot_become_boundary_scope():
    geometry = mapping(GeometryCollection([
        Polygon([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]),
        LineString([(0.0, 0.0), (1.0, 1.0)]),
    ]))
    catalog = DataResourceCatalog.from_records(
        [{
            "geometry": geometry,
            "properties": {"layer_ref": "boundary"},
        }],
        dataset_ref="test:collection-boundary",
        layer_ref="boundary",
        crs="EPSG:4326",
    )
    feature = catalog.snapshot.features[0]
    admitted = SourceAdmissionDecision(
        decision_ref="data.admission:collection-boundary",
        source_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
        source_digest=feature.source_feature_digest,
        input_role="current_evidence",
        status="admitted",
        resource_kind="collection",
    )
    snapshot = catalog.snapshot.model_copy(update={
        "admission_decisions": (admitted,),
    })
    assert build_boundary_scope_artifact(
        snapshot,
        mode="admitted_boundary",
        source_dataset_ref=feature.dataset_ref,
        source_layer_ref="boundary",
    ) is None


def test_geometry_collection_is_not_recalled_as_semantic_spatial_source():
    geometry = mapping(GeometryCollection([
        Polygon([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)]),
        LineString([(0.0, 0.0), (1.0, 1.0)]),
    ]))
    catalog = DataResourceCatalog.from_records(
        [{
            "geometry": geometry,
            "properties": {"layer_ref": "water_bodies", "name": "mixed"},
        }],
        dataset_ref="test:collection-semantic",
        layer_ref="water_bodies",
        crs="EPSG:4326",
    )
    feature = catalog.snapshot.features[0]
    admitted = SourceAdmissionDecision(
        decision_ref="data.admission:collection-semantic",
        source_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
        source_digest=feature.source_feature_digest,
        input_role="current_evidence",
        status="admitted",
        resource_kind="collection",
    )
    current = catalog.snapshot.model_copy(update={
        "admission_decisions": (admitted,),
    })
    grouped = collect_authoritative_source_features(
        SimpleNamespace(data_resource_catalog=DataResourceCatalog(current))
    )
    assert grouped == {"facility": [], "road": [], "water": []}
