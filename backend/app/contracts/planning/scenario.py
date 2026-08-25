"""Immutable, auditable planning-scenario contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.planning.constraint_factor import RelationSatisfaction


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _strip_runtime_timestamps(value: object) -> object:
    """Remove ContractMeta timestamps from nested replay fingerprints."""
    if isinstance(value, dict):
        return {
            key: _strip_runtime_timestamps(child)
            for key, child in value.items()
            if key != "created_at"
        }
    if isinstance(value, list):
        return [_strip_runtime_timestamps(child) for child in value]
    return value


def _sorted_strings(values: list[str]) -> list[str]:
    return sorted({item for item in values if item})


def _scenario_lineage_refs(value: object, *, key: str = "") -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            refs.update(_scenario_lineage_refs(child, key=str(child_key)))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.update(_scenario_lineage_refs(child, key=key))
    elif isinstance(value, str) and value and ("ref" in key or key.endswith("_ids")):
        refs.add(value)
    return refs


class ScenarioFeature(BaseModel):
    feature_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    geometry_kind: Literal["point", "line", "polygon", "multipatch"]
    geometry_wkt: str = Field(min_length=1)
    crs: str = Field(min_length=1)
    generation_operation: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    source_bsms: list[str] = Field(default_factory=list)
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_fact_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""
    source_binding_ref: str = ""
    subgeometry_operation: str = "bundle_extent"
    subgeometry_diagnostics: list[str] = Field(default_factory=list)
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(min_length=1)

    @field_validator("source_refs")
    @classmethod
    def require_non_empty_source_refs(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("source_refs must contain non-empty references")
        return _sorted_strings(value)

    @field_validator("relation_ids")
    @classmethod
    def require_non_empty_relation_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("relation_ids must contain non-empty references")
        return _sorted_strings(value)

    @field_validator(
        "source_bsms",
        "feature_bsms",
        "source_feature_ids",
        "entity_refs",
        "evidence_refs",
        "l1_fact_refs",
        "adjacent_parcel_bsms",
        "adjacency_evidence_refs",
    )
    @classmethod
    def normalize_lineage_refs(cls, value: list[str]) -> list[str]:
        return _sorted_strings(value)

    @field_validator("subgeometry_diagnostics")
    @classmethod
    def normalize_subgeometry_diagnostics(cls, value: list[str]) -> list[str]:
        return _sorted_strings(value)


class ScenarioFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str
    relation_id: str = ""
    target_id: str = ""


class ScenarioTargetSelection(BaseModel):
    """Authoritative selected members for one planning target."""

    target_id: str = Field(min_length=1)
    selection_mode: Literal["all_members", "choose_one", "choose_subset"]
    candidate_ids: list[str] = Field(min_length=1)
    binding_ref: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "ScenarioTargetSelection":
        self.candidate_ids = sorted(set(item for item in self.candidate_ids if item))
        if not self.candidate_ids:
            raise ValueError("candidate_ids must contain at least one member")
        if self.selection_mode == "choose_one" and len(self.candidate_ids) != 1:
            raise ValueError("choose_one selection must contain exactly one candidate")
        return self


class PlanningScenario(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str
    parent_scenario_id: str = ""
    baseline_ref: str
    problem_fingerprint: str
    target_selections: list[ScenarioTargetSelection] = Field(default_factory=list)
    feature_intents: list[ScenarioFeature] = Field(default_factory=list)
    relation_satisfactions: list[RelationSatisfaction] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    objective_vector: dict[str, float] = Field(default_factory=dict)
    findings: list[ScenarioFinding] = Field(default_factory=list)
    status: Literal["draft", "partial", "complete", "failed"] = "draft"
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_and_fingerprint(self) -> "PlanningScenario":
        if self.status == "complete":
            blocking = [
                item.relation_id
                for item in self.relation_satisfactions
                if item.criticality == "hard" and item.status != "satisfied"
            ]
            if blocking:
                raise ValueError(
                    "complete scenario has unsatisfied hard relations: "
                    + ", ".join(sorted(blocking))
                )
        invalid_features = [
            item.feature_id
            for item in self.feature_intents
            if item.scenario_id != self.scenario_id
        ]
        if invalid_features:
            raise ValueError(
                "scenario feature belongs to a different scenario: "
                + ", ".join(sorted(invalid_features))
            )
        self.target_selections = sorted(
            self.target_selections,
            key=lambda item: item.target_id,
        )
        selection_targets = [item.target_id for item in self.target_selections]
        if len(selection_targets) != len(set(selection_targets)):
            raise ValueError("target_selections must contain one row per target")
        self.feature_intents = sorted(self.feature_intents, key=lambda item: item.feature_id)
        self.relation_satisfactions = sorted(
            self.relation_satisfactions,
            key=lambda item: item.relation_id,
        )
        self.metrics = {
            str(key): float(value)
            for key, value in sorted(self.metrics.items(), key=lambda item: str(item[0]))
        }
        self.objective_vector = {
            str(key): float(value)
            for key, value in sorted(self.objective_vector.items(), key=lambda item: str(item[0]))
        }
        self.findings = sorted(
            self.findings,
            key=lambda item: (
                item.severity,
                item.code,
                item.relation_id,
                item.target_id,
                item.message,
            ),
        )
        payload = _strip_runtime_timestamps(
            self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
        )
        raw = _canonical_json(payload).encode("utf-8")
        derived_fingerprint = hashlib.sha256(raw).hexdigest()
        if self.fingerprint and self.fingerprint != derived_fingerprint:
            raise ValueError("scenario fingerprint does not match canonical content")
        self.fingerprint = derived_fingerprint
        return self


class ObjectiveDefinition(BaseModel):
    """One measurable objective compiled from L2/L3 semantics."""

    objective_id: str = Field(min_length=1)
    direction: Literal["maximize", "minimize"] = "maximize"
    source_refs: list[str] = Field(default_factory=list)
    evaluator_key: str = ""
    description: str = ""

    @model_validator(mode="after")
    def canonicalize(self) -> "ObjectiveDefinition":
        self.source_refs = _sorted_strings(self.source_refs)
        return self


class SolverConflictGroup(BaseModel):
    """One interpretable group of assumptions that explains a proven conflict."""

    group_id: str = Field(min_length=1)
    assumption_refs: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize(self) -> "SolverConflictGroup":
        self.assumption_refs = _sorted_strings(self.assumption_refs)
        return self


class MasterCertificatePayload(BaseModel):
    """Typed global coordination proof bound to a solver certificate."""

    status: Literal["feasible", "bounded_infeasible", "deferred"]
    selected_candidate_ids: dict[str, str] = Field(default_factory=dict)
    project_refs: list[str] = Field(default_factory=list)
    parcel_refs: list[str] = Field(default_factory=list)
    network_refs: list[str] = Field(default_factory=list)
    demand_refs: list[str] = Field(default_factory=list)
    conflict_refs: list[str] = Field(default_factory=list)
    blocker_refs: list[str] = Field(default_factory=list)
    combinations_inspected: int = Field(default=0, ge=0)
    search_limit: int = Field(default=0, ge=0)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "MasterCertificatePayload":
        self.selected_candidate_ids = {
            str(target_id): str(candidate_id)
            for target_id, candidate_id in sorted(self.selected_candidate_ids.items())
        }
        for field in (
            "project_refs",
            "parcel_refs",
            "network_refs",
            "demand_refs",
            "conflict_refs",
            "blocker_refs",
        ):
            setattr(self, field, _sorted_strings(getattr(self, field)))
        payload = self.model_dump(mode="json", exclude={"fingerprint"})
        derived = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        if self.fingerprint and self.fingerprint != derived:
            raise ValueError("master certificate fingerprint does not match canonical content")
        self.fingerprint = derived
        return self


class BackendCertificatePayload(BaseModel):
    """Typed, replayable proof contributed by one solver backend."""

    backend_id: str = Field(min_length=1)
    backend_version: str = Field(min_length=1)
    problem_kind: Literal[
        "single_choice",
        "coverage",
        "parcel_assignment",
        "network_path",
        "topology_layout",
        "bounded_multiobjective",
        "unknown",
    ]
    problem_fingerprint: str = Field(min_length=1)
    input_digest: str = Field(min_length=1)
    required_input_refs: list[str] = Field(default_factory=list)
    deterministic_settings: dict[str, str | int | float | bool] = Field(default_factory=dict)
    solver_config: dict[str, object] = Field(default_factory=dict)
    selected_candidate_ids: dict[str, list[str]] = Field(default_factory=dict)
    route_refs: list[str] = Field(default_factory=list)
    selection_digest: str = Field(min_length=1)
    status: Literal["feasible", "infeasible", "bounded", "timeout", "unknown"]
    termination_reason: str = ""
    proof_kind: Literal[
        "feasible_witness",
        "bounded_search",
        "infeasibility_core",
        "unknown",
    ] = "unknown"
    solver_invoked: bool = False
    input_closed: bool = False
    enumeration_complete: bool = False
    assumption_refs: list[str] = Field(default_factory=list)
    infeasibility_core_refs: list[str] = Field(default_factory=list)
    conflict_groups: list[SolverConflictGroup] = Field(default_factory=list)
    master_certificate: MasterCertificatePayload | None = None

    @model_validator(mode="after")
    def canonicalize(self) -> "BackendCertificatePayload":
        self.required_input_refs = _sorted_strings(self.required_input_refs)
        self.deterministic_settings = {
            str(key): value
            for key, value in sorted(self.deterministic_settings.items(), key=lambda item: str(item[0]))
        }
        self.solver_config = {
            str(key): value
            for key, value in sorted(self.solver_config.items(), key=lambda item: str(item[0]))
        }
        required_config_fields = {
            "deterministic_seed",
            "search_limit",
            "time_limit_seconds",
            "max_scenarios",
            "objective_definitions",
            "backend_version",
            "replay_settings",
        }
        missing_config_fields = required_config_fields.difference(self.solver_config)
        if missing_config_fields:
            raise ValueError(
                "backend certificate solver_config is incomplete: "
                + ", ".join(sorted(missing_config_fields))
            )
        if str(self.solver_config.get("backend_version") or "") != self.backend_version:
            raise ValueError(
                "backend certificate solver_config backend_version does not match backend"
            )
        for key in ("deterministic_seed", "search_limit", "max_scenarios"):
            if key in self.deterministic_settings and (
                self.deterministic_settings[key] != self.solver_config.get(key)
            ):
                raise ValueError(
                    f"backend certificate deterministic setting {key} does not match solver_config"
                )
        self.selected_candidate_ids = {
            str(target_id): _sorted_strings(list(candidate_ids))
            for target_id, candidate_ids in sorted(self.selected_candidate_ids.items())
        }
        self.route_refs = _sorted_strings(self.route_refs)
        self.assumption_refs = _sorted_strings(self.assumption_refs)
        self.infeasibility_core_refs = _sorted_strings(self.infeasibility_core_refs)
        self.conflict_groups = sorted(
            [
                SolverConflictGroup.model_validate(item.model_dump(mode="python"))
                for item in self.conflict_groups
            ],
            key=lambda item: item.group_id,
        )
        assumption_refs = set(self.assumption_refs)
        core_refs = set(self.infeasibility_core_refs)
        grouped_refs = {
            ref
            for group in self.conflict_groups
            for ref in group.assumption_refs
        }
        if not core_refs.issubset(assumption_refs):
            raise ValueError("infeasibility core refs must be declared assumptions")
        if not grouped_refs.issubset(assumption_refs):
            raise ValueError("conflict group refs must be declared assumptions")
        if self.status == "infeasible":
            if not self.solver_invoked or not self.input_closed or not self.enumeration_complete:
                raise ValueError(
                    "infeasible backend certificate requires a closed, exhausted solver run"
                )
            if self.proof_kind != "infeasibility_core":
                raise ValueError("infeasible backend certificate requires an infeasibility core")
            if not core_refs:
                raise ValueError("infeasible backend certificate requires core refs")
            if not self.conflict_groups:
                raise ValueError("infeasible backend certificate requires conflict groups")
        expected_selection_digest = derive_backend_selection_digest(
            self.selected_candidate_ids,
            self.route_refs,
        )
        if self.selection_digest != expected_selection_digest:
            raise ValueError("backend selection_digest does not match selected output")
        return self


def derive_backend_selection_digest(
    selected_candidate_ids: dict[str, list[str]],
    route_refs: list[str],
) -> str:
    """Bind a backend proof to its canonical selected members and routes."""

    payload = {
        "selected_candidate_ids": {
            str(target_id): _sorted_strings(list(candidate_ids))
            for target_id, candidate_ids in sorted(selected_candidate_ids.items())
        },
        "route_refs": _sorted_strings(route_refs),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def derive_solver_model_digest(
    proof: BackendCertificatePayload,
    *,
    deterministic_seed: int,
    search_limit: int,
) -> str:
    """Digest the complete route, typed input and replay configuration."""

    payload = {
        "backend_proof": proof.model_dump(mode="json"),
        "deterministic_seed": deterministic_seed,
        "search_limit": search_limit,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class SolverCertificate(ContractMeta):
    """Evidence about how a closed planning problem was searched."""

    schema_version: Literal["1.0"] = "1.0"
    problem_fingerprint: str
    model_digest: str
    solver_version: str
    deterministic_seed: int = 0
    search_limit: int = Field(default=0, ge=0)
    combinations_inspected: int = Field(default=0, ge=0)
    feasible_scenario_count: int = Field(default=0, ge=0)
    status: Literal["feasible", "infeasible", "bounded", "timeout", "unknown"]
    termination_reason: str = ""
    conflict_explanations: list[str] = Field(default_factory=list)
    # Route trace for the task-specific backend that produced this proof.
    # Kept as primitive fields here to avoid a contract import cycle; the
    # typed BackendCertificatePayload is carried in backend_certificate.
    problem_kind: str = "unknown"
    backend_id: str = ""
    backend_version: str = ""
    required_input_refs: list[str] = Field(default_factory=list)
    backend_certificate: BackendCertificatePayload | None = None
    master_certificate: MasterCertificatePayload | None = None
    solver_invoked: bool = False
    input_closed: bool = False
    enumeration_complete: bool = False
    proof_kind: Literal[
        "feasible_witness",
        "bounded_search",
        "infeasibility_core",
        "unknown",
    ] = "unknown"
    readiness_status: Literal[
        "unverified",
        "ready",
        "pending",
        "blocked",
        "human_required",
        "not_groundable",
    ] = "unverified"
    readiness_fingerprint: str = ""
    readiness_blocker_refs: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def derive_fingerprint(self) -> "SolverCertificate":
        self.conflict_explanations = _sorted_strings(self.conflict_explanations)
        self.required_input_refs = _sorted_strings(self.required_input_refs)
        self.readiness_blocker_refs = _sorted_strings(self.readiness_blocker_refs)
        proof = self.backend_certificate
        if proof is not None:
            for field, top, nested in (
                ("problem_fingerprint", self.problem_fingerprint, proof.problem_fingerprint),
                ("problem_kind", self.problem_kind, proof.problem_kind),
                ("backend_id", self.backend_id, proof.backend_id),
                ("backend_version", self.backend_version, proof.backend_version),
                ("status", self.status, proof.status),
            ):
                if top != nested:
                    raise ValueError(f"backend certificate {field} does not match SolverCertificate")
            if self.required_input_refs != proof.required_input_refs:
                raise ValueError("backend certificate required_input_refs do not match SolverCertificate")
            config_seed = proof.solver_config.get("deterministic_seed")
            config_limit = proof.solver_config.get("search_limit")
            if config_seed != self.deterministic_seed:
                raise ValueError("backend certificate deterministic_seed does not match SolverCertificate")
            if config_limit != self.search_limit:
                raise ValueError("backend certificate search_limit does not match SolverCertificate")
            expected_digest = derive_solver_model_digest(
                proof,
                deterministic_seed=self.deterministic_seed,
                search_limit=self.search_limit,
            )
            if self.model_digest != expected_digest:
                raise ValueError("SolverCertificate model_digest does not match backend proof")
            for field in (
                "solver_invoked",
                "input_closed",
                "enumeration_complete",
                "proof_kind",
            ):
                if getattr(self, field) != getattr(proof, field):
                    raise ValueError(f"backend certificate {field} does not match SolverCertificate")
            if self.master_certificate is not None and proof.master_certificate is None:
                raise ValueError("SolverCertificate master certificate is not bound to backend proof")
            if self.master_certificate is not None and proof.master_certificate is not None:
                if self.master_certificate.model_dump(mode="json") != proof.master_certificate.model_dump(mode="json"):
                    raise ValueError("SolverCertificate master certificate does not match backend proof")
            if self.master_certificate is None and proof.master_certificate is not None:
                self.master_certificate = proof.master_certificate
        if self.status == "infeasible":
            if proof is None:
                raise ValueError("infeasible SolverCertificate requires a typed backend proof")
            if proof.proof_kind != "infeasibility_core":
                raise ValueError("infeasible SolverCertificate requires an infeasibility core")
            if not self.solver_invoked or not self.input_closed or not self.enumeration_complete:
                raise ValueError(
                    "infeasible SolverCertificate requires a closed, exhausted solver run"
                )
        if self.status in {"feasible", "bounded"} and self.readiness_status not in {"unverified", "ready"}:
            raise ValueError(
                "formal SolverCertificate requires ready solver preflight"
            )
        if self.status in {"feasible", "bounded"} and self.readiness_status == "ready" and self.readiness_blocker_refs:
            raise ValueError(
                "ready SolverCertificate cannot carry readiness blockers"
            )
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
            self.fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return self

    def bind_readiness(self, readiness: object) -> "SolverCertificate":
        """Bind SELECT preflight proof to the solver certificate."""

        return self.model_copy(update={
            "readiness_status": str(getattr(readiness, "status", "unverified") or "unverified"),
            "readiness_fingerprint": str(getattr(readiness, "fingerprint", "") or ""),
            "readiness_blocker_refs": list(getattr(readiness, "blocker_refs", None) or []),
            "fingerprint": "",
        })


class ScenarioSet(ContractMeta):
    """Authoritative SELECT product containing alternatives and solver proof."""

    schema_version: Literal["1.0"] = "1.0"
    set_id: str = Field(min_length=1)
    problem_fingerprint: str = Field(min_length=1)
    baseline_ref: str = ""
    scenarios: list[PlanningScenario] = Field(default_factory=list)
    feasible_scenario_ids: list[str] = Field(default_factory=list)
    pareto_scenario_ids: list[str] = Field(default_factory=list)
    recommended_scenario_id: str = ""
    recommendation_policy: str = ""
    objective_definitions: list[ObjectiveDefinition] = Field(default_factory=list)
    objective_vectors: dict[str, dict[str, float]] = Field(default_factory=dict)
    infeasibility_explanations: list[str] = Field(default_factory=list)
    solver_certificate: SolverCertificate
    fingerprint: str = ""

    @model_validator(mode="after")
    def validate_and_fingerprint(self) -> "ScenarioSet":
        # Revalidate nested members because ``model_copy(update=...)`` can
        # otherwise mutate a typed instance without invoking its validators.
        self.scenarios = [
            PlanningScenario.model_validate(item.model_dump(mode="python"))
            for item in self.scenarios
        ]
        self.scenarios = sorted(self.scenarios, key=lambda item: item.scenario_id)
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("ScenarioSet scenario IDs must be unique")
        mismatched = [
            item.scenario_id
            for item in self.scenarios
            if item.problem_fingerprint != self.problem_fingerprint
        ]
        if mismatched:
            raise ValueError(
                "ScenarioSet contains scenarios for another problem: "
                + ", ".join(sorted(mismatched))
            )
        known = set(ids)
        self.feasible_scenario_ids = sorted(set(self.feasible_scenario_ids))
        self.pareto_scenario_ids = sorted(set(self.pareto_scenario_ids))
        if not set(self.feasible_scenario_ids).issubset(known):
            raise ValueError("feasible_scenario_ids reference unknown scenarios")
        scenario_by_id = {item.scenario_id: item for item in self.scenarios}
        incomplete_feasible = [
            scenario_id
            for scenario_id in self.feasible_scenario_ids
            if scenario_by_id[scenario_id].status != "complete"
        ]
        if incomplete_feasible:
            raise ValueError(
                "feasible scenarios must have status complete: "
                + ", ".join(sorted(incomplete_feasible))
            )
        complete_ids = {
            item.scenario_id for item in self.scenarios if item.status == "complete"
        }
        if complete_ids != set(self.feasible_scenario_ids):
            raise ValueError(
                "complete scenarios must be formal feasible scenarios"
            )
        if not set(self.pareto_scenario_ids).issubset(set(self.feasible_scenario_ids)):
            raise ValueError("pareto scenarios must be feasible scenarios")
        if self.recommended_scenario_id and self.recommended_scenario_id not in set(self.feasible_scenario_ids):
            raise ValueError("recommended scenario must be feasible")
        if self.solver_certificate.problem_fingerprint != self.problem_fingerprint:
            raise ValueError(
                "solver certificate problem_fingerprint must match ScenarioSet"
            )
        formal_ids = {
            *self.feasible_scenario_ids,
            *self.pareto_scenario_ids,
            *(
                [self.recommended_scenario_id]
                if self.recommended_scenario_id
                else []
            ),
        }
        certificate_status = self.solver_certificate.status
        if certificate_status == "bounded" and formal_ids:
            raise ValueError("bounded solver certificate cannot carry formal scenarios")
        master = self.solver_certificate.master_certificate
        if master is not None and master.status != "feasible":
            if self.recommended_scenario_id or self.feasible_scenario_ids:
                raise ValueError("non-feasible master certificate cannot carry formal scenarios")
        if formal_ids or certificate_status in {"feasible", "bounded"}:
            certificate = self.solver_certificate
            if not certificate.backend_id or not certificate.backend_version:
                raise ValueError("formal ScenarioSet requires backend id and version")
            if certificate.backend_certificate is None:
                raise ValueError("formal ScenarioSet requires a typed backend certificate")
            if certificate.problem_kind in {"", "unknown"}:
                raise ValueError("formal ScenarioSet requires a resolved problem kind")
            recommended = scenario_by_id.get(self.recommended_scenario_id)
            expected_selected = (
                {
                    item.target_id: list(item.candidate_ids)
                    for item in recommended.target_selections
                }
                if recommended is not None
                else {}
            )
            proof = certificate.backend_certificate
            if proof.selected_candidate_ids != expected_selected:
                raise ValueError(
                    "backend proof selected_candidate_ids must match recommended scenario"
                )
            if master is not None and master.status == "feasible" and recommended is not None:
                expected_master = {
                    item.target_id: item.candidate_ids[0]
                    for item in recommended.target_selections
                    if len(item.candidate_ids) == 1
                }
                if any(
                    target_id not in expected_master
                    or expected_master[target_id] != candidate_id
                    for target_id, candidate_id in master.selected_candidate_ids.items()
                ):
                    raise ValueError("master certificate selected candidates do not match recommendation")
            if proof.route_refs:
                if recommended is None:
                    raise ValueError("backend proof route_refs require a recommended scenario")
                lineage_refs = _scenario_lineage_refs(recommended.model_dump(mode="json"))
                if not set(proof.route_refs).issubset(lineage_refs):
                    raise ValueError("backend proof route_refs must match scenario lineage")
        if certificate_status == "feasible" and not self.feasible_scenario_ids:
            raise ValueError("feasible certificate must reference feasible scenarios")
        if certificate_status in {"infeasible", "unknown", "timeout"} and formal_ids:
            raise ValueError(
                f"{certificate_status} certificate cannot contain formal scenarios"
            )
        if self.feasible_scenario_ids and certificate_status not in {"feasible", "bounded"}:
            raise ValueError(
                "formal feasible scenarios require a feasible or bounded certificate"
            )
        if self.solver_certificate.feasible_scenario_count != len(
            self.feasible_scenario_ids
        ):
            raise ValueError(
                "certificate feasible_scenario_count must equal formal feasible scenarios"
            )
        self.objective_vectors = {
            str(scenario_id): {
                str(key): float(value)
                for key, value in sorted(vector.items(), key=lambda item: str(item[0]))
            }
            for scenario_id, vector in sorted(self.objective_vectors.items(), key=lambda item: str(item[0]))
        }
        objective_ids = [item.objective_id for item in self.objective_definitions]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective definitions must have unique objective IDs")
        declared_objectives = set(objective_ids)
        for scenario_id in self.feasible_scenario_ids:
            scenario = scenario_by_id[scenario_id]
            missing_scenario = declared_objectives.difference(scenario.objective_vector)
            if missing_scenario:
                raise ValueError(
                    "feasible scenario is missing declared objective results: "
                    + ", ".join(sorted(missing_scenario))
                )
            missing_projection = declared_objectives.difference(
                self.objective_vectors.get(scenario_id, {})
            )
            if missing_projection:
                raise ValueError(
                    "feasible objective vector is missing declared results: "
                    + ", ".join(sorted(missing_projection))
                )
        self.infeasibility_explanations = _sorted_strings(self.infeasibility_explanations)
        payload = _strip_runtime_timestamps(
            self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
        )
        derived_fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        if self.fingerprint and self.fingerprint != derived_fingerprint:
            raise ValueError("ScenarioSet fingerprint does not match canonical content")
        self.fingerprint = derived_fingerprint
        return self

    @property
    def recommended(self) -> PlanningScenario | None:
        return next(
            (item for item in self.scenarios if item.scenario_id == self.recommended_scenario_id),
            None,
        )

    @property
    def feasible(self) -> list[PlanningScenario]:
        ids = set(self.feasible_scenario_ids)
        return [item for item in self.scenarios if item.scenario_id in ids]

    def bind_solver_readiness(self, readiness: object) -> "ScenarioSet":
        """Return a revalidated ScenarioSet carrying SELECT readiness proof."""

        payload = self.model_dump(mode="python")
        payload["solver_certificate"] = self.solver_certificate.bind_readiness(readiness).model_dump(mode="python")
        payload["fingerprint"] = ""
        return ScenarioSet.model_validate(payload)


def resolve_formal_scenario_member(
    scenario_set: object,
    scenario: object,
) -> tuple[ScenarioSet, PlanningScenario]:
    """Resolve a scenario to the unique canonical member stored in its set."""

    if not isinstance(scenario_set, ScenarioSet) or not isinstance(
        scenario,
        PlanningScenario,
    ):
        raise ValueError("scenario is not a typed formal ScenarioSet member")
    validated_set = ScenarioSet.model_validate(
        scenario_set.model_dump(mode="python")
    )
    validated_scenario = PlanningScenario.model_validate(
        scenario.model_dump(mode="python")
    )
    matches = [
        member
        for member in validated_set.scenarios
        if member.scenario_id == validated_scenario.scenario_id
    ]
    if len(matches) != 1:
        raise ValueError("scenario does not resolve to one formal ScenarioSet member")
    member = matches[0]
    if member.fingerprint != validated_scenario.fingerprint:
        raise ValueError("scenario fingerprint does not match formal ScenarioSet member")
    if _canonical_json(member.model_dump(mode="json")) != _canonical_json(
        validated_scenario.model_dump(mode="json")
    ):
        raise ValueError("scenario content does not match formal ScenarioSet member")
    return validated_set, member


__all__ = [
    "ScenarioFeature",
    "ScenarioFinding",
    "ScenarioTargetSelection",
    "PlanningScenario",
    "ObjectiveDefinition",
    "SolverConflictGroup",
    "MasterCertificatePayload",
    "BackendCertificatePayload",
    "derive_backend_selection_digest",
    "derive_solver_model_digest",
    "SolverCertificate",
    "ScenarioSet",
    "resolve_formal_scenario_member",
]
