"""Deterministic typed views of one authoritative SpatialChangeSet."""

from __future__ import annotations

import hashlib
from typing import Any

from app.contracts.execute.spatial_change_contracts import (
    ExecutionTrace,
    PlannedEntity,
    PlannedEntitySet,
    PlannedRepresentation,
    PlannedRepresentationSet,
    SpatialChangeSet,
)


def _short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def project_spatial_outputs(
    changeset: SpatialChangeSet,
) -> tuple[PlannedEntitySet, PlannedRepresentationSet, ExecutionTrace]:
    """Project entity, representation and replay views without new geometry."""

    typed = SpatialChangeSet.model_validate(changeset.model_dump(mode="python"))
    operation_by_feature = {
        item.feature_id: item for item in typed.operations
    }
    representation_rows: list[PlannedRepresentation] = []
    entity_representations: dict[tuple[str, str, str, str], list[str]] = {}
    entity_refs: dict[tuple[str, str, str, str], str] = {}
    for feature in typed.features:
        source_entities = sorted({
            str(item) for item in feature.entity_refs if str(item).strip()
        })
        if len(source_entities) != 1:
            raise ValueError(
                "planned feature requires one resolved source entity: "
                f"{feature.feature_id}"
            )
        operation = operation_by_feature[feature.feature_id]
        identity = (
            feature.target_id,
            feature.candidate_id,
            source_entities[0],
            feature.part_ref,
        )
        planned_entity_ref = entity_refs.setdefault(
            identity,
            "planned-entity:" + _short("|".join((typed.scenario_id, *identity))),
        )
        planned_representation_ref = (
            "planned-representation:" + _short(feature.feature_id)
        )
        entity_representations.setdefault(identity, []).append(
            planned_representation_ref
        )
        representation_rows.append(PlannedRepresentation(
            planned_representation_ref=planned_representation_ref,
            planned_entity_ref=planned_entity_ref,
            feature_id=feature.feature_id,
            change_ref=feature.change_ref,
            target_ref=feature.target_id,
            candidate_ref=feature.candidate_id,
            part_ref=feature.part_ref,
            geometry_kind=feature.geometry_kind,
            geometry_wkt=feature.geometry_wkt,
            input_crs=feature.input_crs,
            output_crs=feature.output_crs,
            geometry_digest=feature.geometry_digest,
            operation=operation.operation,
            operation_parameters=dict(operation.operation_parameters),
            input_resource_refs=list(operation.input_resource_refs),
            input_representation_refs=list(operation.input_representation_refs),
            input_geometry_refs=list(operation.input_geometry_refs),
            source_snapshot_refs=list(operation.source_snapshot_refs),
            resource_digests=list(operation.resource_digests),
            capability_refs=list(operation.capability_refs),
            selection_refs=list(operation.selection_refs),
            approval_ref=operation.approval_ref,
            world_model_digest=operation.world_model_digest,
        ))
    entities = [
        PlannedEntity(
            planned_entity_ref=entity_refs[identity],
            scenario_id=typed.scenario_id,
            target_ref=identity[0],
            candidate_ref=identity[1],
            source_entity_ref=identity[2],
            part_ref=identity[3],
            representation_refs=refs,
        )
        for identity, refs in entity_representations.items()
    ]
    entity_set = PlannedEntitySet(
        scenario_id=typed.scenario_id,
        entities=entities,
    )
    representation_set = PlannedRepresentationSet(
        scenario_id=typed.scenario_id,
        representations=representation_rows,
    )
    trace = ExecutionTrace(
        trace_ref="execution-trace:" + _short(
            "|".join(item.change_ref for item in typed.operations)
        ),
        scenario_id=typed.scenario_id,
        operations=list(typed.operations),
        planned_entity_refs=[item.planned_entity_ref for item in entities],
        planned_representation_refs=[
            item.planned_representation_ref for item in representation_rows
        ],
    )
    return entity_set, representation_set, trace


__all__ = ["project_spatial_outputs"]
