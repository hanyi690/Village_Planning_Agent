"""Typed, deterministic work graph between planning intent and GROUND.

The graph records *what must be established* before a candidate can be
selected.  It deliberately contains no geometry, candidate choice, or
evidence result: those remain the responsibilities of GROUND and SELECT.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.ref import ArtifactRef


PlanningTaskKind = Literal[
    "evidence",
    "candidate_producer",
    "solver_subproblem",
    "validation",
]
PlanningTaskStatus = Literal[
    "planned",
    "ready",
    "running",
    "resolved",
    "blocked",
    "deferred",
    "failed",
]
PlanningTaskSolverKind = Literal[
    "auto",
    "single_choice",
    "coverage",
    "parcel_assignment",
    "network_path",
    "topology_layout",
    "bounded_multiobjective",
]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


class PlanningTaskTransition(BaseModel):
    """One deterministic lifecycle event emitted by the GROUND executor."""

    from_status: PlanningTaskStatus
    to_status: PlanningTaskStatus
    reason: str = Field(min_length=1)
    input_artifact_refs: list[str] = Field(default_factory=list)
    output_artifact_refs: list[str] = Field(default_factory=list)
    lineage_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_collections(self) -> "PlanningTaskTransition":
        self.reason = self.reason.strip()
        self.input_artifact_refs = _sorted_strings(self.input_artifact_refs)
        self.output_artifact_refs = _sorted_strings(self.output_artifact_refs)
        self.lineage_refs = _sorted_strings(self.lineage_refs)
        return self


class PlanningTaskBinding(BaseModel):
    """One typed task label bound to a replayable source artifact fragment."""

    binding_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    binding_kind: Literal[
        "entity",
        "evidence",
        "candidate_domain",
        "geometry",
        "network",
        "parcel_resource_pool",
        "relation",
        "derived_evidence",
    ]
    artifact_ref: ArtifactRef
    json_pointer: str = ""
    source_artifact_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_collections(self) -> "PlanningTaskBinding":
        self.binding_id = self.binding_id.strip()
        self.label = self.label.strip()
        self.json_pointer = self.json_pointer.strip()
        self.source_artifact_refs = _sorted_strings(self.source_artifact_refs)
        return self


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"ready", "blocked", "deferred", "failed"}),
    "ready": frozenset({"running", "blocked", "deferred", "failed"}),
    "running": frozenset({"resolved", "blocked", "deferred", "failed"}),
    "blocked": frozenset(),
    "deferred": frozenset(),
    "resolved": frozenset(),
    "failed": frozenset(),
}


class PlanningTask(BaseModel):
    """One planned prerequisite or evaluation unit.

    Input and artifact references are symbolic, stable labels.  They are not
    claims that a KG entity, evidence record, or geometry already exists.
    """

    task_id: str = Field(min_length=1)
    task_kind: PlanningTaskKind
    target_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    capability: str = ""
    required_inputs: list[str] = Field(default_factory=list)
    produced_artifact_refs: list[str] = Field(default_factory=list)
    dependency_task_ids: list[str] = Field(default_factory=list)
    solver_kind: PlanningTaskSolverKind | None = None
    status: PlanningTaskStatus = "planned"
    diagnostics: list[str] = Field(default_factory=list)
    input_artifact_refs: list[str] = Field(default_factory=list)
    output_artifact_refs: list[str] = Field(default_factory=list)
    lineage_refs: list[str] = Field(default_factory=list)
    transitions: list[PlanningTaskTransition] = Field(default_factory=list)
    input_binding_ids: list[str] = Field(default_factory=list)
    output_binding_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_collections(self) -> "PlanningTask":
        self.task_id = self.task_id.strip()
        self.target_refs = _sorted_strings(self.target_refs)
        self.relation_refs = _sorted_strings(self.relation_refs)
        self.required_inputs = _sorted_strings(self.required_inputs)
        self.produced_artifact_refs = _sorted_strings(self.produced_artifact_refs)
        self.dependency_task_ids = _sorted_strings(self.dependency_task_ids)
        self.diagnostics = _sorted_strings(self.diagnostics)
        self.input_artifact_refs = _sorted_strings(self.input_artifact_refs)
        self.output_artifact_refs = _sorted_strings(self.output_artifact_refs)
        self.lineage_refs = _sorted_strings(self.lineage_refs)
        self.input_binding_ids = _sorted_strings(self.input_binding_ids)
        self.output_binding_ids = _sorted_strings(self.output_binding_ids)
        self.capability = self.capability.strip()
        return self

    def transition_to(
        self,
        status: PlanningTaskStatus,
        *,
        reason: str,
        input_artifact_refs: list[str] | None = None,
        output_artifact_refs: list[str] | None = None,
        lineage_refs: list[str] | None = None,
        input_binding_ids: list[str] | None = None,
        output_binding_ids: list[str] | None = None,
    ) -> "PlanningTask":
        """Return a new task with one valid, auditable state transition."""

        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(
                f"invalid planning task transition {self.status!r} -> {status!r}"
            )
        transition = PlanningTaskTransition(
            from_status=self.status,
            to_status=status,
            reason=reason,
            input_artifact_refs=list(input_artifact_refs or ()),
            output_artifact_refs=list(output_artifact_refs or ()),
            lineage_refs=list(lineage_refs or ()),
        )
        return self.model_copy(
            update={
                "status": status,
                "input_artifact_refs": [
                    *self.input_artifact_refs,
                    *transition.input_artifact_refs,
                ],
                "output_artifact_refs": [
                    *self.output_artifact_refs,
                    *transition.output_artifact_refs,
                ],
                "lineage_refs": [*self.lineage_refs, *transition.lineage_refs],
                "transitions": [*self.transitions, transition],
                "input_binding_ids": [*self.input_binding_ids, *(input_binding_ids or ())],
                "output_binding_ids": [*self.output_binding_ids, *(output_binding_ids or ())],
            }
        )


def _task_payload(task: PlanningTask) -> dict[str, object]:
    return task.model_dump(mode="json")


class PlanningTaskGraph(ContractMeta):
    """Canonical task graph compiled exclusively from ``PlanningIntentGraph``."""

    schema_version: Literal["1.0"] = "1.0"
    tasks: list[PlanningTask] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    source_intent_fingerprint: str = ""
    bindings: list[PlanningTaskBinding] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_and_canonicalize(self) -> "PlanningTaskGraph":
        self.tasks = sorted(self.tasks, key=lambda item: item.task_id)
        self.diagnostics = _sorted_strings(self.diagnostics)
        self.bindings = sorted(self.bindings, key=lambda item: item.binding_id)
        binding_ids = [item.binding_id for item in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("planning task graph contains duplicate binding_id values")
        known_binding_ids = set(binding_ids)
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("planning task graph contains duplicate task_id values")

        known_ids = set(task_ids)
        for task in self.tasks:
            missing = sorted(set(task.dependency_task_ids) - known_ids)
            if missing:
                raise ValueError(
                    f"planning task {task.task_id!r} has unknown dependencies: "
                    + ", ".join(missing)
                )
            missing_bindings = sorted(
                (set(task.input_binding_ids) | set(task.output_binding_ids))
                - known_binding_ids
            )
            if missing_bindings:
                raise ValueError(
                    f"planning task {task.task_id!r} has unknown bindings: "
                    + ", ".join(missing_bindings)
                )

        dependency_map = {
            task.task_id: list(task.dependency_task_ids) for task in self.tasks
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError(f"planning task graph dependency cycle at {task_id!r}")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency_id in dependency_map[task_id]:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_ids:
            visit(task_id)

        payload = {
            "schema_version": self.schema_version,
            "tasks": [_task_payload(task) for task in self.tasks],
            "diagnostics": self.diagnostics,
            "source_intent_fingerprint": self.source_intent_fingerprint,
            "bindings": [item.model_dump(mode="json") for item in self.bindings],
        }
        canonical_fingerprint = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        if self.fingerprint and self.fingerprint != canonical_fingerprint:
            raise ValueError("planning task graph fingerprint does not match canonical payload")
        self.fingerprint = canonical_fingerprint
        return self


__all__ = [
    "PlanningTaskKind",
    "PlanningTaskStatus",
    "PlanningTaskSolverKind",
    "PlanningTaskTransition",
    "PlanningTaskBinding",
    "PlanningTask",
    "PlanningTaskGraph",
]
