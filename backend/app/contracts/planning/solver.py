"""Typed contracts shared by the ScenarioOptimizer solver portfolio.

The contracts in this module describe the closed input and the auditable
contribution of one deterministic backend.  They deliberately do not expose
free-form prompt text or an execution/materialization operation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .scenario import (
    BackendCertificatePayload,
    ObjectiveDefinition,
    PlanningScenario,
    ScenarioFinding,
    ScenarioSet,
)


SolverProblemKind = Literal[
    "single_choice",
    "coverage",
    "parcel_assignment",
    "network_path",
    "topology_layout",
    "bounded_multiobjective",
    "unknown",
]

SolverStatus = Literal["feasible", "infeasible", "bounded", "timeout", "unknown"]
SolverSubproblemStatus = Literal["ready", "blocked", "deferred"]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sorted_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})


def _lineage_refs(value: object, *, key: str = "") -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            refs.update(_lineage_refs(child, key=str(child_key)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.update(_lineage_refs(child, key=key))
    elif isinstance(value, str) and value and ("ref" in key or key.endswith("_ids")):
        refs.add(value)
    return refs


class SolverConfig(BaseModel):
    """Deterministic settings passed to a backend for replay."""

    deterministic_seed: int = 0
    search_limit: int = Field(default=20_000, ge=1)
    time_limit_seconds: float | None = Field(default=None, gt=0)
    max_scenarios: int = Field(default=8, ge=1)
    objective_definitions: list[ObjectiveDefinition] = Field(default_factory=list)
    backend_version: str = ""
    replay_settings: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def canonicalize(self) -> "SolverConfig":
        self.replay_settings = {
            str(key): value
            for key, value in sorted(self.replay_settings.items(), key=lambda item: str(item[0]))
        }
        return self


class SolverProblemView(BaseModel):
    """Read-only typed projection of a grounded problem for routing."""

    problem_fingerprint: str = Field(min_length=1)
    problem_kind: SolverProblemKind
    target_ids: tuple[str, ...] = Field(default_factory=tuple)
    candidate_ids_by_target: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    selection_modes_by_target: dict[str, str] = Field(default_factory=dict)
    required_input_refs: list[str] = Field(default_factory=list)
    snapshot_refs: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    explicit_solver_kind: str = ""
    routing_reason_codes: list[str] = Field(default_factory=list)
    input_complete: bool = True
    missing_input_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize(self) -> "SolverProblemView":
        self.target_ids = tuple(sorted(set(self.target_ids)))
        self.candidate_ids_by_target = {
            str(target_id): tuple(sorted(set(candidate_ids)))
            for target_id, candidate_ids in sorted(self.candidate_ids_by_target.items())
        }
        self.selection_modes_by_target = {
            str(target_id): str(mode)
            for target_id, mode in sorted(self.selection_modes_by_target.items())
        }
        self.required_input_refs = _sorted_strings(self.required_input_refs)
        self.snapshot_refs = _sorted_strings(self.snapshot_refs)
        self.resource_refs = _sorted_strings(self.resource_refs)
        self.routing_reason_codes = _sorted_strings(self.routing_reason_codes)
        self.missing_input_refs = _sorted_strings(self.missing_input_refs)
        return self


class SolverSubproblem(BaseModel):
    """One target/relation-scoped solver unit compiled from GROUND facts.

    A subproblem is a routing and completeness boundary.  It does not contain
    a selected candidate and cannot by itself authorize execution.
    """

    schema_version: Literal["1.0"] = "1.0"
    subproblem_id: str = Field(min_length=1)
    target_refs: tuple[str, ...] = Field(default_factory=tuple)
    relation_refs: tuple[str, ...] = Field(default_factory=tuple)
    problem_kind: SolverProblemKind
    candidate_ids_by_target: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    required_input_refs: list[str] = Field(default_factory=list)
    dependency_subproblem_ids: list[str] = Field(default_factory=list)
    status: SolverSubproblemStatus = "ready"
    diagnostics: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "SolverSubproblem":
        self.target_refs = tuple(sorted(set(item for item in self.target_refs if item)))
        self.relation_refs = tuple(sorted(set(item for item in self.relation_refs if item)))
        self.candidate_ids_by_target = {
            str(target_id): tuple(sorted(set(candidate_ids)))
            for target_id, candidate_ids in sorted(self.candidate_ids_by_target.items())
        }
        self.required_input_refs = _sorted_strings(self.required_input_refs)
        self.dependency_subproblem_ids = _sorted_strings(self.dependency_subproblem_ids)
        self.diagnostics = _sorted_strings(self.diagnostics)
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        raw = _canonical_json(payload).encode("utf-8")
        derived = hashlib.sha256(raw).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("solver subproblem fingerprint does not match canonical content")
        self.fingerprint = derived
        return self


class SolverSubproblemPlan(BaseModel):
    """Deterministic decomposition of one grounded planning problem."""

    schema_version: Literal["1.0"] = "1.0"
    problem_fingerprint: str = Field(min_length=1)
    subproblems: list[SolverSubproblem] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_graph_and_fingerprint(self) -> "SolverSubproblemPlan":
        self.subproblems = sorted(self.subproblems, key=lambda item: item.subproblem_id)
        self.diagnostics = _sorted_strings(self.diagnostics)
        ids = [item.subproblem_id for item in self.subproblems]
        if len(ids) != len(set(ids)):
            raise ValueError("solver subproblem IDs must be unique")
        known = set(ids)
        for item in self.subproblems:
            missing = sorted(set(item.dependency_subproblem_ids) - known)
            if missing:
                raise ValueError(
                    f"solver subproblem {item.subproblem_id!r} has unknown dependencies: "
                    + ", ".join(missing)
                )
        dependencies = {
            item.subproblem_id: list(item.dependency_subproblem_ids)
            for item in self.subproblems
        }
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(item_id: str) -> None:
            if item_id in visiting:
                raise ValueError(f"solver subproblem dependency cycle at {item_id!r}")
            if item_id in visited:
                return
            visiting.add(item_id)
            for dependency_id in dependencies[item_id]:
                visit(dependency_id)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in ids:
            visit(item_id)
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        raw = _canonical_json(payload).encode("utf-8")
        derived = hashlib.sha256(raw).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("solver subproblem plan fingerprint does not match canonical content")
        self.fingerprint = derived
        return self


class BackendSupport(BaseModel):
    """Explicit support decision; unsupported is never an implicit fallback."""

    supported: bool
    reason_codes: list[str] = Field(default_factory=list)
    required_input_refs: list[str] = Field(default_factory=list)
    input_complete: bool = True

    @model_validator(mode="after")
    def canonicalize(self) -> "BackendSupport":
        self.reason_codes = _sorted_strings(self.reason_codes)
        self.required_input_refs = _sorted_strings(self.required_input_refs)
        return self


class BackendResult(BaseModel):
    """Typed result returned by one backend before ScenarioSet projection."""

    problem_kind: SolverProblemKind
    selected_candidate_ids: dict[str, list[str]] = Field(default_factory=dict)
    route_refs: list[str] = Field(default_factory=list)
    objective_vectors: dict[str, dict[str, float]] = Field(default_factory=dict)
    scenarios: list[PlanningScenario] = Field(default_factory=list)
    findings: list[ScenarioFinding] = Field(default_factory=list)
    infeasibility_explanations: list[str] = Field(default_factory=list)
    certificate: BackendCertificatePayload
    scenario_set: ScenarioSet

    @model_validator(mode="after")
    def canonicalize(self) -> "BackendResult":
        self.selected_candidate_ids = {
            str(target_id): sorted(set(candidate_ids))
            for target_id, candidate_ids in sorted(self.selected_candidate_ids.items())
        }
        self.route_refs = _sorted_strings(self.route_refs)
        self.objective_vectors = {
            str(scenario_id): {
                str(key): float(value)
                for key, value in sorted(vector.items(), key=lambda item: str(item[0]))
            }
            for scenario_id, vector in sorted(self.objective_vectors.items())
        }
        self.scenarios = sorted(self.scenarios, key=lambda item: item.scenario_id)
        self.findings = sorted(
            self.findings,
            key=lambda item: json.dumps(
                item.model_dump(mode="json"),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
        self.infeasibility_explanations = _sorted_strings(self.infeasibility_explanations)
        if self.problem_kind != self.certificate.problem_kind:
            raise ValueError("BackendResult problem_kind does not match backend certificate")
        if self.selected_candidate_ids != self.certificate.selected_candidate_ids:
            raise ValueError("BackendResult selected_candidate_ids do not match backend certificate")
        if self.route_refs != self.certificate.route_refs:
            raise ValueError("BackendResult route_refs do not match backend certificate")
        if self.scenario_set is not None:
            solver_certificate = self.scenario_set.solver_certificate
            nested = solver_certificate.backend_certificate
            if nested is None:
                raise ValueError("BackendResult ScenarioSet has no backend certificate")
            if self.certificate.model_dump(mode="json") != nested.model_dump(mode="json"):
                raise ValueError(
                    "BackendResult backend certificate does not match ScenarioSet backend certificate"
                )
            if solver_certificate.status != self.certificate.status:
                raise ValueError("BackendResult status does not match SolverCertificate")
            if [
                item.model_dump(mode="json") for item in self.scenarios
            ] != [
                item.model_dump(mode="json")
                for item in self.scenario_set.scenarios
            ]:
                raise ValueError("BackendResult scenarios do not match ScenarioSet")
            expected_findings = sorted(
                [
                    finding
                    for scenario in self.scenario_set.scenarios
                    for finding in scenario.findings
                ],
                key=lambda item: json.dumps(
                    item.model_dump(mode="json"),
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            if [
                item.model_dump(mode="json") for item in self.findings
            ] != [
                item.model_dump(mode="json") for item in expected_findings
            ]:
                raise ValueError("BackendResult findings do not match ScenarioSet")
            if (
                self.infeasibility_explanations
                != self.scenario_set.infeasibility_explanations
            ):
                raise ValueError(
                    "BackendResult infeasibility_explanations do not match ScenarioSet"
                )
            if self.objective_vectors != self.scenario_set.objective_vectors:
                raise ValueError("BackendResult objective_vectors do not match ScenarioSet")
            recommended = self.scenario_set.recommended
            expected_selected = (
                {
                    item.target_id: list(item.candidate_ids)
                    for item in recommended.target_selections
                }
                if recommended is not None
                else {}
            )
            if self.selected_candidate_ids != expected_selected:
                raise ValueError(
                    "BackendResult selected_candidate_ids do not match recommended scenario"
                )
            if recommended is None and self.route_refs:
                raise ValueError("BackendResult route_refs require a recommended scenario")
            if recommended is not None:
                lineage_refs = _lineage_refs(recommended.model_dump(mode="json"))
                if not set(self.route_refs).issubset(lineage_refs):
                    raise ValueError("BackendResult route_refs do not match scenario lineage")
        return self


def backend_input_digest(view: SolverProblemView, config: SolverConfig) -> str:
    """Return a stable digest for the exact typed backend input/settings."""

    payload = {
        "view": view.model_dump(mode="json"),
        "config": config.model_dump(mode="json"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "BackendCertificatePayload",
    "BackendResult",
    "BackendSupport",
    "SolverConfig",
    "SolverProblemKind",
    "SolverProblemView",
    "SolverSubproblem",
    "SolverSubproblemPlan",
    "SolverSubproblemStatus",
    "SolverStatus",
    "backend_input_digest",
]
