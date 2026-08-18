from __future__ import annotations

from app.contracts.migrations.planning_v1_to_v2 import (
    migrate_planning_v1_to_v2,
    migrate_scenario_feature_v1_to_v2,
)


def test_legacy_relation_without_parameters_is_deferred_with_finding() -> None:
    result = migrate_planning_v1_to_v2(
        {
            "schema_version": "1.0",
            "nodes": [],
            "relations": [
                {
                    "relation_id": "near-legacy",
                    "relation_template": "near",
                    "subject_ref": "facility-1",
                    "object_ref": "settlement-1",
                    "criticality": "hard",
                }
            ],
        }
    )

    relation = result.graph.relations[0]
    assert result.graph.schema_version == "2.0"
    assert relation.parameters is None
    assert relation.parameter_status == "missing"
    assert any(
        finding.code == "migration_missing_parameters"
        and finding.status == "deferred"
        for finding in result.findings
    )


def test_migration_preserves_explicit_typed_parameters() -> None:
    result = migrate_planning_v1_to_v2(
        {
            "schema_version": "1.0",
            "nodes": [],
            "relations": [
                {
                    "relation_id": "connect-1",
                    "relation_template": "connect_network",
                    "subject_ref": "road-1",
                    "object_ref": "facility-1",
                    "source_claim_refs": ["claim:2", "claim:1"],
                    "source_binding_refs": ["binding:1"],
                    "geometry_scope": "network",
                    "weight": 3,
                    "parameters": {
                        "parameter_type": "connect",
                        "network_kind": "road",
                        "endpoint_tolerance_m": 15,
                        "network_ref": "network:road:1",
                    },
                }
            ],
        }
    )

    relation = result.graph.relations[0]
    assert relation.parameter_status == "provided"
    assert relation.parameters is not None
    assert relation.parameters.parameter_type == "connect"
    assert relation.source_claim_refs == ["claim:1", "claim:2"]
    assert relation.source_binding_refs == ["binding:1"]
    assert relation.geometry_scope == "network"
    assert relation.weight == 3.0
    assert result.findings == []


def test_migration_maps_legacy_parameter_shape_without_guessing_values() -> None:
    result = migrate_planning_v1_to_v2(
        {
            "relations": [
                {
                    "relation_id": "near-legacy-parameters",
                    "relation_template": "near",
                    "subject_ref": "facility-1",
                    "object_ref": "settlement-1",
                    "parameters": {"max_distance_m": 800, "metric": "euclidean"},
                }
            ]
        }
    )

    relation = result.graph.relations[0]
    assert relation.parameter_status == "provided"
    assert relation.parameters is not None
    assert relation.parameters.parameter_type == "distance"
    assert not result.findings


def test_invalid_legacy_parameters_yield_explicit_invalid_finding() -> None:
    result = migrate_planning_v1_to_v2(
        {
            "relations": [
                {
                    "relation_id": "serve-invalid",
                    "relation_template": "serve",
                    "subject_ref": "facility-1",
                    "object_ref": "settlement-1",
                    "parameters": {
                        "facility_type": "clinic",
                        "max_travel_time_min": 20,
                        "min_coverage_ratio": 0.8,
                        "capacity": 100,
                        "capacity_unit": "person/day",
                        "network_ref": "road-network-1",
                    },
                }
            ]
        }
    )

    relation = result.graph.relations[0]
    assert relation.parameters is None
    assert relation.parameter_status == "missing"
    assert [finding.code for finding in result.findings] == ["migration_invalid_parameters"]


def test_legacy_feature_without_source_refs_stays_deferred() -> None:
    result = migrate_scenario_feature_v1_to_v2(
        {
            "feature_id": "feature-legacy",
            "scenario_id": "scenario-legacy",
            "target_id": "facility-1",
            "candidate_id": "candidate:1",
            "geometry_kind": "point",
            "geometry_wkt": "POINT (116 23)",
            "crs": "EPSG:4326",
            "generation_operation": "legacy_worker",
        }
    )

    assert result.feature is None
    assert result.findings[0].code == "migration_missing_feature_source_refs"
    assert result.findings[0].status == "deferred"


def test_legacy_singular_source_ref_is_explicitly_promoted() -> None:
    result = migrate_scenario_feature_v1_to_v2(
        {
            "feature_id": "feature-legacy",
            "scenario_id": "scenario-legacy",
            "target_id": "facility-1",
            "candidate_id": "candidate:1",
            "geometry_kind": "point",
            "geometry_wkt": "POINT (116 23)",
            "crs": "EPSG:4326",
            "generation_operation": "legacy_worker",
            "source_ref": "artifact:candidate:1",
            "relation_ids": ["serve-1"],
        }
    )

    assert result.feature is not None
    assert result.feature.source_refs == ["artifact:candidate:1"]
