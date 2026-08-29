"""Failure scope and no-progress primitives for the L3 claim compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any

from app.contracts.l3.l3_contracts import PlanningProgram, ProgramIssue


class FailureScope(str, Enum):
    FIELD = "field"
    RELATION = "relation"
    CLAIM = "claim"
    PROJECT_PACKAGE = "project_package"
    PROGRAM = "program"


_RELATION_CODES = frozenset({
    "relation_subject_type_mismatch",
    "relation_object_type_mismatch",
    "relation_object_ref_kind_mismatch",
    "relation_unknown_subject",
    "relation_unknown_object",
    "relation_parameters_invalid",
    "relation_parameters_missing",
    "relation_parameter_type_mismatch",
    "relation_deferred",
    "relation_missing_object",
    "unsupported_relation_template",
})
_CLAIM_CODES = frozenset({
    "claim_contract_invalid",
    "draft_contract_invalid",
    "claim_admission_incomplete",
    "claim_lineage_missing",
    "claim_not_executable",
    "spatial_claim_unknown_fact",
    "missing_asset_kind",
    "claim_contract_invalid",
})
_PROGRAM_CODES = frozenset({
    "artifact_corrupt",
    "artifact_dependency_incomplete",
    "duplicate_intervention_id",
    "global_dependency_graph_invalid",
    "empty_program",
})


@dataclass(frozen=True)
class FailureDecision:
    scope: FailureScope
    blocking: bool
    root_issue_id: str
    dependency_scope: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ClaimDependencyGraph:
    claim_to_targets: dict[str, frozenset[str]] = field(default_factory=dict)
    target_edges: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_program(cls, program: PlanningProgram) -> "ClaimDependencyGraph":
        claim_to_targets: dict[str, set[str]] = {}
        target_edges: dict[str, set[str]] = {}
        for intervention in program.interventions:
            target_id = str(intervention.target_id or intervention.intervention_id)
            for claim_id in intervention.claim_refs:
                claim_to_targets.setdefault(str(claim_id), set()).add(target_id)
            target_edges.setdefault(target_id, set())
            requirements = intervention.spatial_requirements
            if isinstance(requirements, dict):
                for relation in requirements.get("relations", []) or []:
                    if not isinstance(relation, dict):
                        continue
                    subject = str(relation.get("subject_ref") or target_id)
                    object_ref = str(relation.get("object_ref") or "")
                    if object_ref and object_ref in target_edges:
                        target_edges.setdefault(subject, set()).add(object_ref)
        for dependency in program.dependencies:
            source = str(dependency.from_intervention_id)
            target = str(dependency.to_intervention_id)
            target_edges.setdefault(source, set()).add(target)
            target_edges.setdefault(target, set())
        return cls(
            claim_to_targets={key: frozenset(value) for key, value in claim_to_targets.items()},
            target_edges={key: frozenset(value) for key, value in target_edges.items()},
        )

    def target_closure(self, targets: set[str] | frozenset[str]) -> frozenset[str]:
        pending = list(targets)
        closure = set(targets)
        while pending:
            current = pending.pop()
            for target in self.target_edges.get(current, frozenset()):
                if target not in closure:
                    closure.add(target)
                    pending.append(target)
        return frozenset(closure)

    def scope_for_issue(self, issue: ProgramIssue) -> frozenset[str]:
        claim_ids = {
            str(value).strip()
            for value in [issue.claim_id, *issue.claim_ids]
            if str(value).strip()
        }
        targets = {
            target
            for claim_id in claim_ids
            for target in self.claim_to_targets.get(claim_id, frozenset())
        }
        return self.target_closure(targets)


@dataclass(frozen=True)
class CompileSnapshot:
    accepted_claim_ids: frozenset[str]
    failure_fingerprints: frozenset[str]
    failed_dependency_scope: frozenset[str]


@dataclass(frozen=True)
class NoProgressDecision:
    stop: bool
    reason: str = ""


def _text_code(issue: object) -> str:
    if isinstance(issue, ProgramIssue):
        return str(issue.code or "").strip()
    text = str(issue or "")
    match = re.search(r"(?:ERROR|WARNING|INFO)\[([^\]]+)\]", text)
    if match:
        return match.group(1).strip()
    return text.split(":", 1)[0].strip()


def error_fingerprint(issue: object) -> str:
    """Collapse repeated wrappers while retaining stable semantic dimensions."""

    code = _text_code(issue)
    text = issue.message if isinstance(issue, ProgramIssue) else str(issue or "")
    relation = ""
    subject = ""
    component = ""
    relation_match = re.search(r"relation[_ ](?:template=)?([a-z_]+)", text)
    if relation_match:
        relation = relation_match.group(1)
    subject_match = re.search(r"subject(?: kind)?[= ]([a-z_]+)", text)
    if subject_match:
        subject = subject_match.group(1)
    component_match = re.search(r"component[_ ]kind[= ]([a-z_]+)", text)
    if component_match:
        component = component_match.group(1)
    return "|".join(item for item in (code, component, relation, subject) if item) or "unknown"


def classify_failure_scope(
    issue: ProgramIssue,
    dependency_graph: ClaimDependencyGraph,
) -> FailureDecision:
    code = str(issue.code or "").strip()
    if code == "semantic_compile_exhausted":
        return FailureDecision(
            scope=FailureScope.CLAIM,
            blocking=False,
            root_issue_id=issue.root_issue_id or error_fingerprint(issue),
        )
    if code in _RELATION_CODES:
        scope = FailureScope.RELATION
    elif code in _CLAIM_CODES or issue.claim_id or issue.claim_ids:
        scope = FailureScope.CLAIM
    elif code in _PROGRAM_CODES:
        scope = FailureScope.PROGRAM
    elif code.endswith("package") or code.startswith("project_package"):
        scope = FailureScope.PROJECT_PACKAGE
    else:
        scope = FailureScope.PROGRAM
    dependency_scope = dependency_graph.scope_for_issue(issue)
    blocking = issue.severity == "error" and (
        scope in {FailureScope.PROGRAM, FailureScope.PROJECT_PACKAGE}
        or bool(dependency_scope)
    )
    return FailureDecision(
        scope=scope,
        blocking=blocking,
        root_issue_id=issue.root_issue_id or error_fingerprint(issue),
        dependency_scope=dependency_scope,
    )


def infer_failure_scope(code: str, *, has_claim_identity: bool = False) -> FailureScope:
    """Classify a diagnostic before a full program dependency graph exists."""

    value = str(code or "").strip()
    if value in _RELATION_CODES:
        return FailureScope.RELATION
    if value in _CLAIM_CODES or has_claim_identity:
        return FailureScope.CLAIM
    if value in _PROGRAM_CODES:
        return FailureScope.PROGRAM
    if value.endswith("package") or value.startswith("project_package"):
        return FailureScope.PROJECT_PACKAGE
    return FailureScope.PROGRAM


def detect_no_progress(
    previous: CompileSnapshot | None,
    current: CompileSnapshot,
) -> NoProgressDecision:
    if previous is None:
        return NoProgressDecision(False)
    repeated = bool(previous.failure_fingerprints & current.failure_fingerprints)
    accepted_unchanged = previous.accepted_claim_ids == current.accepted_claim_ids
    scope_unchanged = current.failed_dependency_scope >= previous.failed_dependency_scope
    if repeated and accepted_unchanged and scope_unchanged:
        return NoProgressDecision(
            True,
            "same semantic failure fingerprint repeated without accepted-claim or dependency-closure progress",
        )
    return NoProgressDecision(False)


__all__ = [
    "ClaimDependencyGraph",
    "CompileSnapshot",
    "FailureDecision",
    "FailureScope",
    "NoProgressDecision",
    "classify_failure_scope",
    "detect_no_progress",
    "error_fingerprint",
    "infer_failure_scope",
]
