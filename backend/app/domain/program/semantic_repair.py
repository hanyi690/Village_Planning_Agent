"""Verified, evidence-bound semantic repair for the authoritative L3 program.

The provider may propose only three operation kinds: duplicate merge,
dependency edge, or explicit abstention.  It cannot patch an intervention or
rewrite diagnostics.  Target IDs and evidence references are generated from
the current program for every invocation; an old cache entry or an unknown
reference is not adapted into the new contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.contracts.llm.decision_contracts import (
    ClosedSetRef,
    DecisionContext,
    PendingDecision,
    SemanticIssue,
    SemanticValidationOutcome,
    StrictDecisionModel,
    stable_digest,
)
from app.infrastructure.llm.verified_structured import run_verified_structured_decision
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PROMPT_VERSION = "l3-semantic-repair-verified-v2"


class DuplicateMerge(StrictDecisionModel):
    """Evidence-backed duplicate target merge proposal."""

    operation: Literal["duplicate_merge"] = "duplicate_merge"
    canonical_target_id: str = Field(min_length=1)
    duplicate_target_ids: list[str] = Field(min_length=1)
    evidence_refs: list[ClosedSetRef] = Field(min_length=1)
    rationale: str = ""


class DependencyEdge(StrictDecisionModel):
    """Evidence-backed dependency edge proposal."""

    operation: Literal["dependency_edge"] = "dependency_edge"
    from_intervention_id: str = Field(min_length=1)
    to_intervention_id: str = Field(min_length=1)
    dependency_type: str = Field(min_length=1)
    evidence_refs: list[ClosedSetRef] = Field(min_length=1)
    rationale: str = ""


class Abstain(StrictDecisionModel):
    """Explicitly decline to make a semantic repair decision."""

    operation: Literal["abstain"] = "abstain"
    decision_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    rationale: str = ""


ProgramSemanticRepairOperation = Annotated[
    DuplicateMerge | DependencyEdge | Abstain,
    Field(discriminator="operation"),
]


class ProgramSemanticRepairCandidate(StrictDecisionModel):
    """Provider-facing operation union with no hidden semantic patch fields."""

    operations: list[ProgramSemanticRepairOperation] = Field(
        default_factory=list,
        max_length=240,
    )

    @model_validator(mode="after")
    def validate_non_empty(self) -> "ProgramSemanticRepairCandidate":
        if not self.operations:
            raise ValueError("semantic repair must contain an operation or abstain")
        return self


class ProgramSemanticRepairResult(BaseModel):
    program: PlanningProgram
    applied: bool = False
    attempts: int = 0
    cache_hits: int = 0
    validation_errors: list[str] = Field(default_factory=list)
    pending: list[PendingDecision] = Field(default_factory=list)
    candidate_set_digest: str = ""


class SemanticRepairCache:
    """Atomic JSON cache keyed by prompt, input, and dynamic candidates."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        if path is not None and path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
            except Exception as exc:  # noqa: BLE001
                logger.warning("[l3-semantic-repair] cache load failed: %s", exc)

    def get(self, key: str) -> ProgramSemanticRepairCandidate | None:
        raw = self._data.get(key)
        if raw is None:
            return None
        try:
            return ProgramSemanticRepairCandidate.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[l3-semantic-repair] invalid cached candidate: %s", exc)
            return None

    def put(self, key: str, candidate: ProgramSemanticRepairCandidate) -> None:
        self._data[key] = candidate.model_dump(mode="json")
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                json.dumps(self._data, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[l3-semantic-repair] cache flush failed: %s", exc)


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if str(value or "").strip()))


def _duplicate_candidate_pairs(program: PlanningProgram) -> list[list[str]]:
    """Generate an input-bound comparison set; the provider does not invent IDs."""
    pairs: list[list[str]] = []
    items = list(program.interventions)
    for left_position, left in enumerate(items):
        for right in items[left_position + 1 :]:
            if (
                left.category != right.category
                or left.expected_output_kind != right.expected_output_kind
            ):
                continue
            similarity = SequenceMatcher(None, left.name, right.name).ratio()
            if similarity >= 0.58:
                pairs.append([left.target_id, right.target_id])
            if len(pairs) >= 120:
                return pairs
    return pairs


_EVIDENCE_NAMESPACES = {
    "l1_fact": "l1_fact",
    "source_fact": "l1_fact",
    "source_segment": "source_segment",
    "segment": "source_segment",
    "source_feature": "source_feature",
    "feature": "source_feature",
    "claim": "claim",
    "target": "target",
    "constraint": "constraint",
    "demand": "demand",
}


def _closed_ref(value: str, default_namespace: str) -> ClosedSetRef:
    text = str(value).strip()
    prefix, separator, ref_id = text.partition(":")
    namespace = _EVIDENCE_NAMESPACES.get(prefix, default_namespace)
    if separator and prefix in _EVIDENCE_NAMESPACES:
        ref_id = ref_id.strip()
    else:
        ref_id = text
    return ClosedSetRef(namespace=namespace, ref_id=ref_id)


def _available_evidence_refs(program: PlanningProgram) -> list[ClosedSetRef]:
    refs: dict[str, ClosedSetRef] = {}

    def add(values: Iterable[str], namespace: str) -> None:
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            ref = _closed_ref(value, namespace)
            refs[ref.key] = ref

    for item in program.interventions:
        add(item.claim_refs, "claim")
        add(item.evidence_refs, "source_segment")
        add(item.source_fact_refs, "l1_fact")
        add(item.source_refs, "source_segment")
    for claim in program.claims:
        add([claim.claim_id], "claim")
        add(claim.evidence_refs, "source_segment")
        add(claim.source_fact_refs, "l1_fact")
        add(claim.source_refs, "source_segment")
    return [refs[key] for key in sorted(refs)]


def _repair_payload_base(program: PlanningProgram) -> dict[str, Any]:
    catalogue = [
        {
            "target_id": item.target_id,
            "name": item.name,
            "category": item.category,
            "output": item.expected_output_kind,
            "phase": item.implementation_phase,
            "claim_refs": list(item.claim_refs),
            "evidence_refs": list(item.evidence_refs),
        }
        for item in program.interventions
    ]
    evidence_catalog = [
        ref.model_dump(mode="json") for ref in _available_evidence_refs(program)
    ]
    return {
        "target_catalogue": catalogue,
        "duplicate_candidate_pairs": _duplicate_candidate_pairs(program),
        "evidence_catalog": evidence_catalog,
    }


def _candidate_set_digest(program: PlanningProgram) -> str:
    return stable_digest(_repair_payload_base(program))


def _repair_payload(program: PlanningProgram) -> dict[str, Any]:
    payload = _repair_payload_base(program)
    payload["candidate_set_digest"] = _candidate_set_digest(program)
    return payload


def _build_prompt(program: PlanningProgram, feedback: Sequence[str]) -> str:
    payload = _repair_payload(program)
    return (
        "你是村庄规划项目库的 typed semantic critic。只返回一个 typed "
        "ProgramSemanticRepairCandidate，operations 只能选择 duplicate_merge、"
        "dependency_edge 或 abstain。target_id、dependency endpoint 和 evidence_ref "
        "必须来自本次输入的候选目录；不能创建几何、BSM、坐标、规划用地编码或任何对象字段。"
        "duplicate_merge 与 dependency_edge 都必须提供输入目录中的 evidence_refs；无法证明时返回 abstain。"
        "duplicate merge 不得把不同范围、阶段、功能或尺度的项目合并；dependency edge 必须保持有向图闭合。\n"
        f"candidate_set_digest={payload['candidate_set_digest']}\n"
        f"input={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
        f"previous_validation_feedback={json.dumps(list(feedback), ensure_ascii=False)}"
    )


def _dynamic_repair_model(program: PlanningProgram) -> type[BaseModel]:
    """Return the stable operation union; runtime closure stays local.

    The current program's target and evidence IDs are still rendered in the
    prompt and checked by ``_validation_errors``.  They are not expanded into
    ``Literal`` fields because that would make the provider schema vary with
    every program and can produce an oversized nested union.
    """
    if not isinstance(program, PlanningProgram):
        raise TypeError("semantic repair requires a PlanningProgram")
    return ProgramSemanticRepairCandidate


def _duplicate_map(candidate: ProgramSemanticRepairCandidate) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for operation in candidate.operations:
        if isinstance(operation, DuplicateMerge):
            for duplicate in operation.duplicate_target_ids:
                mapping[duplicate] = operation.canonical_target_id
    return mapping


def _has_cycle(dependencies: Sequence[InterventionDependency]) -> bool:
    graph: dict[str, list[str]] = {}
    for dependency in dependencies:
        graph.setdefault(dependency.from_intervention_id, []).append(
            dependency.to_intervention_id
        )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _validation_errors(
    program: PlanningProgram,
    candidate: ProgramSemanticRepairCandidate,
) -> list[str]:
    errors: list[str] = []
    operations = list(candidate.operations)
    if not operations:
        return ["semantic repair must contain an operation or abstain"]

    by_id = {item.target_id: item for item in program.interventions}
    known_evidence = {ref.key for ref in _available_evidence_refs(program)}
    duplicate_pairs = {frozenset(pair) for pair in _duplicate_candidate_pairs(program)}
    duplicate_ids: set[str] = set()
    canonical_ids: set[str] = set()
    dependency_operations: list[DependencyEdge] = []
    abstains = [operation for operation in operations if isinstance(operation, Abstain)]
    if abstains and len(operations) != 1:
        errors.append("abstain cannot be combined with another semantic operation")

    for operation in operations:
        if isinstance(operation, Abstain):
            if operation.decision_ref != "program" and operation.decision_ref not in by_id:
                errors.append(f"unknown abstain decision_ref: {operation.decision_ref}")
            continue

        operation_evidence = {ref.key for ref in operation.evidence_refs}
        if not operation_evidence:
            errors.append(f"{operation.operation} requires evidence_refs")
        unknown_evidence = sorted(operation_evidence - known_evidence)
        if unknown_evidence:
            errors.append(
                f"{operation.operation} references unknown evidence: "
                + ", ".join(unknown_evidence)
            )

        if isinstance(operation, DuplicateMerge):
            canonical = by_id.get(operation.canonical_target_id)
            if canonical is None:
                errors.append(f"unknown canonical target: {operation.canonical_target_id}")
                continue
            if operation.canonical_target_id in duplicate_ids:
                errors.append(f"canonical target is already merged: {operation.canonical_target_id}")
            canonical_ids.add(operation.canonical_target_id)
            for duplicate_id in operation.duplicate_target_ids:
                duplicate = by_id.get(duplicate_id)
                if duplicate is None:
                    errors.append(f"unknown duplicate target: {duplicate_id}")
                    continue
                if (
                    duplicate_id == operation.canonical_target_id
                    or duplicate_id in duplicate_ids
                    or duplicate_id in canonical_ids
                ):
                    errors.append(f"duplicate target reused: {duplicate_id}")
                    continue
                duplicate_ids.add(duplicate_id)
                if frozenset((operation.canonical_target_id, duplicate_id)) not in duplicate_pairs:
                    errors.append(f"merge was not in input candidate pairs: {duplicate_id}")
                if (
                    duplicate.category != canonical.category
                    or duplicate.expected_output_kind != canonical.expected_output_kind
                ):
                    errors.append(f"incompatible duplicate merge: {duplicate_id}")
        elif isinstance(operation, DependencyEdge):
            dependency_operations.append(operation)

    final_ids = set(by_id).difference(duplicate_ids)
    mapping = _duplicate_map(candidate)
    dependencies: list[InterventionDependency] = []
    existing_dependency_keys: set[tuple[str, str, str]] = set()
    for dependency in program.dependencies:
        source = mapping.get(dependency.from_intervention_id, dependency.from_intervention_id)
        target = mapping.get(dependency.to_intervention_id, dependency.to_intervention_id)
        if source not in final_ids or target not in final_ids:
            errors.append(f"dependency references unknown target: {source}->{target}")
            continue
        if source == target:
            errors.append(f"self dependency: {source}")
            continue
        key = (source, target, dependency.dependency_type)
        existing_dependency_keys.add(key)
        dependencies.append(
            dependency.model_copy(
                update={
                    "from_intervention_id": source,
                    "to_intervention_id": target,
                }
            )
        )

    for operation in dependency_operations:
        source = mapping.get(operation.from_intervention_id, operation.from_intervention_id)
        target = mapping.get(operation.to_intervention_id, operation.to_intervention_id)
        if source not in final_ids or target not in final_ids:
            errors.append(f"dependency edge references unknown target: {source}->{target}")
            continue
        if source == target:
            errors.append(f"self dependency: {source}")
            continue
        key = (source, target, operation.dependency_type)
        if key in existing_dependency_keys:
            errors.append(f"dependency edge already exists: {source}->{target}")
            continue
        existing_dependency_keys.add(key)
        dependencies.append(
            InterventionDependency(
                from_intervention_id=source,
                to_intervention_id=target,
                dependency_type=operation.dependency_type,
            )
        )

    if _has_cycle(dependencies):
        errors.append("dependency graph contains a cycle")
    return _unique(errors)


def validate_semantic_repair_candidate(
    program: PlanningProgram,
    candidate: ProgramSemanticRepairCandidate,
) -> list[str]:
    """Return deterministic semantic findings without changing the program."""
    return _validation_errors(program, candidate)


def _merge_interventions(
    canonical: PlanningIntervention,
    duplicate: PlanningIntervention,
) -> PlanningIntervention:
    requirements = dict(canonical.spatial_requirements or {})
    duplicate_requirements = dict(duplicate.spatial_requirements or {})
    for key, value in duplicate_requirements.items():
        if key == "location_hints":
            requirements[key] = _unique(
                list(requirements.get(key) or []) + list(value or [])
            )
        elif not requirements.get(key) and value:
            requirements[key] = value
    return canonical.model_copy(
        update={
            "problem_addressed": max(
                (canonical.problem_addressed, duplicate.problem_addressed), key=len
            ),
            "scale": canonical.scale or duplicate.scale,
            "functions": _unique(canonical.functions + duplicate.functions),
            "constraints": _unique(canonical.constraints + duplicate.constraints),
            "claim_refs": _unique(canonical.claim_refs + duplicate.claim_refs),
            "evidence_refs": _unique(canonical.evidence_refs + duplicate.evidence_refs),
            "spatial_requirements": requirements,
        }
    )


def apply_semantic_repair_candidate(
    program: PlanningProgram,
    candidate: ProgramSemanticRepairCandidate,
    *,
    attempts: int = 1,
    cache_hits: int = 0,
) -> PlanningProgram:
    """Apply only an already verified, evidence-backed operation set."""
    errors = validate_semantic_repair_candidate(program, candidate)
    if errors:
        raise ValueError("invalid semantic repair candidate: " + "; ".join(errors))
    if any(isinstance(operation, Abstain) for operation in candidate.operations):
        return program.model_copy(deep=True)

    by_id = {item.target_id: item.model_copy(deep=True) for item in program.interventions}
    mapping = _duplicate_map(candidate)
    for duplicate_id, canonical_id in mapping.items():
        by_id[canonical_id] = _merge_interventions(by_id[canonical_id], by_id[duplicate_id])
        del by_id[duplicate_id]

    dependency_keys: set[tuple[str, str, str]] = set()
    dependencies: list[InterventionDependency] = []
    for dependency in program.dependencies:
        revised = dependency.model_copy(
            update={
                "from_intervention_id": mapping.get(
                    dependency.from_intervention_id, dependency.from_intervention_id
                ),
                "to_intervention_id": mapping.get(
                    dependency.to_intervention_id, dependency.to_intervention_id
                ),
            }
        )
        key = (
            revised.from_intervention_id,
            revised.to_intervention_id,
            revised.dependency_type,
        )
        if revised.from_intervention_id != revised.to_intervention_id and key not in dependency_keys:
            dependency_keys.add(key)
            dependencies.append(revised)

    operation_names: list[str] = []
    evidence_keys: list[str] = []
    for operation in candidate.operations:
        operation_names.append(operation.operation)
        if isinstance(operation, DependencyEdge):
            revised = InterventionDependency(
                from_intervention_id=mapping.get(
                    operation.from_intervention_id, operation.from_intervention_id
                ),
                to_intervention_id=mapping.get(
                    operation.to_intervention_id, operation.to_intervention_id
                ),
                dependency_type=operation.dependency_type,
            )
            key = (
                revised.from_intervention_id,
                revised.to_intervention_id,
                revised.dependency_type,
            )
            if key not in dependency_keys:
                dependency_keys.add(key)
                dependencies.append(revised)
            evidence_keys.extend(ref.key for ref in operation.evidence_refs)
        elif isinstance(operation, DuplicateMerge):
            evidence_keys.extend(ref.key for ref in operation.evidence_refs)

    issues = [issue.model_copy(deep=True) for issue in program.program_issues]
    issues.append(
        ProgramIssue(
            severity="info",
            code="semantic_repair_applied",
            message="verified semantic repair operations applied",
            detail=(
                f"operations={','.join(operation_names)}; "
                f"evidence_refs={','.join(sorted(set(evidence_keys)))}; "
                f"attempts={attempts}; cache_hits={cache_hits}; prompt={_PROMPT_VERSION}"
            ),
        )
    )
    return program.model_copy(
        update={
            "interventions": [
                by_id[item.target_id]
                for item in program.interventions
                if item.target_id in by_id
            ],
            "dependencies": dependencies,
            "program_issues": issues,
        },
        deep=True,
    )


def _validation_outcome(
    context: DecisionContext,
    program: PlanningProgram,
    candidate: ProgramSemanticRepairCandidate,
) -> SemanticValidationOutcome[Any]:
    errors = validate_semantic_repair_candidate(program, candidate)
    if errors:
        issue = SemanticIssue(
            stage=context.stage,
            code="semantic_repair_invalid",
            severity="error",
            fatal_scope="stage",
            object_ref=context.object_type,
            field_path="operations",
            dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
            retryable=True,
            repair_kind="semantic_validation",
            message="; ".join(errors)[:2000],
        )
        return SemanticValidationOutcome(
            pending=[
                PendingDecision(
                    decision_ref=context.object_type,
                    reason_code="semantic_repair_pending",
                    issue_fingerprints=[issue.fingerprint],
                    dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
                    requires_human_review=True,
                )
            ],
            issues=[issue],
        )

    abstain = next(
        (operation for operation in candidate.operations if isinstance(operation, Abstain)),
        None,
    )
    if abstain is not None:
        issue = SemanticIssue(
            stage=context.stage,
            code="semantic_repair_abstain",
            severity="warning",
            fatal_scope="stage",
            object_ref=abstain.decision_ref,
            field_path="operations",
            dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
            retryable=False,
            repair_kind="abstain",
            message=abstain.reason_code,
        )
        return SemanticValidationOutcome(
            pending=[
                PendingDecision(
                    decision_ref=abstain.decision_ref,
                    reason_code=abstain.reason_code,
                    issue_fingerprints=[issue.fingerprint],
                    dependency_refs=[f"candidate_set:{context.candidate_set_digest}"],
                    requires_human_review=True,
                )
            ],
            issues=[issue],
        )
    return SemanticValidationOutcome(accepted=[candidate])


async def repair_planning_program(
    program: PlanningProgram,
    *,
    llm: Any = None,
    cache_path: Path | None = None,
    max_rounds: int = 3,
    timeout_seconds: float = 180.0,
) -> ProgramSemanticRepairResult:
    """Run verified semantic repair with bounded retries and dynamic candidates."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")

    candidate_digest = _candidate_set_digest(program)
    source_errors = [
        issue
        for issue in program.program_issues
        if issue.severity == "error" and issue.code != "classification_decision_required"
    ]
    if source_errors:
        feedback = [
            f"{issue.dimension_key or 'program'}:{issue.code}:{issue.message}"
            for issue in source_errors
        ]
        logger.warning(
            "[l3-program-critic] skipped because %d source errors must return to L3",
            len(source_errors),
        )
        return ProgramSemanticRepairResult(
            program=program.model_copy(deep=True),
            applied=False,
            validation_errors=feedback,
            candidate_set_digest=candidate_digest,
        )

    if llm is None:
        from app.core.llm_config import get_llm_settings

        enabled = get_llm_settings().semantic_repair_enabled
        if not enabled:
            disabled_issue = ProgramIssue(
                stage="l3",
                severity="warning",
                code="llm_semantic_repair_disabled",
                message=(
                    "L3 semantic repair provider is disabled; typed program was "
                    "retained without provider interpretation"
                ),
            )
            return ProgramSemanticRepairResult(
                program=program.model_copy(
                    update={"program_issues": [*program.program_issues, disabled_issue]},
                    deep=True,
                ),
                applied=False,
                validation_errors=[disabled_issue.message],
                candidate_set_digest=candidate_digest,
            )

    dynamic_model = _dynamic_repair_model(program)
    cache = SemanticRepairCache(cache_path)
    feedback: list[str] = []
    cache_hits = 0
    attempts = 0
    previous_retry_state = None

    for round_index in range(max_rounds):
        prompt = _build_prompt(program, feedback)
        cache_key = hashlib.sha256(
            f"{_PROMPT_VERSION}\n{candidate_digest}\n{prompt}".encode("utf-8")
        ).hexdigest()
        candidate = cache.get(cache_key)
        if candidate is not None:
            cache_hits += 1
            outcome = _validation_outcome(
                DecisionContext(
                    stage="l3",
                    object_type="program_semantic_repair",
                    input_digest=stable_digest(_repair_payload(program)),
                    candidate_set_digest=candidate_digest,
                    prompt_version=_PROMPT_VERSION,
                    validator_version="semantic-repair-v2",
                ),
                program,
                candidate,
            )
            result_pending = outcome.pending
            result_issues = outcome.issues
            result_accepted = outcome.accepted
            retry_state = None
        else:
            attempts += 1
            context = DecisionContext(
                stage="l3",
                object_type="program_semantic_repair",
                input_digest=stable_digest(_repair_payload(program)),
                candidate_set_digest=candidate_digest,
                prompt_version=_PROMPT_VERSION,
                validator_version="semantic-repair-v2",
            )
            result = await run_verified_structured_decision(
                decision_context=context,
                proposal_model_factory=lambda _context, proposal_model=dynamic_model: proposal_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Return only the typed semantic repair operation union.",
                    },
                    {"role": "user", "content": prompt},
                ],
                contract_key="program.semantic_repair",
                semantic_validator=lambda decision_context, proposal: _validation_outcome(
                    decision_context,
                    program,
                    proposal,
                ),
                previous_retry_state=previous_retry_state,
                llm=llm,
                max_retries=0,
                timeout=timeout_seconds,
                max_tokens=8192,
                allow_content_json=True,
            )
            result_pending = result.pending
            result_issues = result.issues
            result_accepted = result.accepted
            retry_state = result.retry_state
            if result_accepted:
                candidate = result_accepted[0]
                cache.put(cache_key, candidate)

        if result_accepted:
            candidate = result_accepted[0]
            repaired = apply_semantic_repair_candidate(
                program,
                candidate,
                attempts=attempts,
                cache_hits=cache_hits,
            )
            if any(isinstance(operation, Abstain) for operation in candidate.operations):
                return ProgramSemanticRepairResult(
                    program=program.model_copy(deep=True),
                    applied=False,
                    attempts=attempts,
                    cache_hits=cache_hits,
                    validation_errors=[item.reason_code for item in result_pending],
                    pending=result_pending,
                    candidate_set_digest=candidate_digest,
                )
            logger.info(
                "[l3-semantic-repair] applied operations after round=%d calls=%d cache_hits=%d",
                round_index + 1,
                attempts,
                cache_hits,
            )
            return ProgramSemanticRepairResult(
                program=repaired,
                applied=True,
                attempts=attempts,
                cache_hits=cache_hits,
                candidate_set_digest=candidate_digest,
            )

        if any(issue.code == "semantic_repair_abstain" for issue in result_issues):
            return ProgramSemanticRepairResult(
                program=program.model_copy(deep=True),
                applied=False,
                attempts=attempts,
                cache_hits=cache_hits,
                validation_errors=[item.reason_code for item in result_pending],
                pending=result_pending,
                candidate_set_digest=candidate_digest,
            )

        feedback = [
            f"{issue.code}:{issue.message}" for issue in result_issues
        ] or [item.reason_code for item in result_pending]
        feedback = list(dict.fromkeys(feedback))
        if not feedback:
            feedback = ["verified semantic repair proposal was not accepted"]
        if retry_state is not None:
            if retry_state.transport_failure_code or retry_state.should_stop:
                break
            previous_retry_state = retry_state

    failure = ProgramIssue(
        severity="error",
        code="llm_semantic_repair_failed",
        message="L3 semantic repair exhausted its verified retry budget",
        detail="; ".join(feedback)[:2000],
    )
    return ProgramSemanticRepairResult(
        program=program.model_copy(
            update={"program_issues": [*program.program_issues, failure]},
            deep=True,
        ),
        applied=False,
        attempts=attempts,
        cache_hits=cache_hits,
        validation_errors=feedback,
        pending=(result_pending if "result_pending" in locals() else []),
        candidate_set_digest=candidate_digest,
    )


__all__ = [
    "Abstain",
    "DependencyEdge",
    "DuplicateMerge",
    "ProgramSemanticRepairCandidate",
    "ProgramSemanticRepairOperation",
    "ProgramSemanticRepairResult",
    "SemanticRepairCache",
    "apply_semantic_repair_candidate",
    "repair_planning_program",
    "validate_semantic_repair_candidate",
]
