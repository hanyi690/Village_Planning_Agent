"""Bounded LLM semantic repair for the authoritative L3 program.

The model may interpret planning prose, but it never creates geometry, BSMs,
classification codes, or executable changes.  Every proposed patch is checked
against the existing program contract before it is applied.  Invalid feedback
is sent back to the model for a bounded retry, and every prompt/result is
content-addressed so graph resume does not repeat an identical LLM call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
    RoadPlanningParameters,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_PROMPT_VERSION = "l3-semantic-repair-v1"


class InterventionSemanticPatch(BaseModel):
    target_id: str
    intervention_action: Literal[
        "preserve",
        "new",
        "expand",
        "relocate",
        "upgrade",
        "widen",
        "harden",
        "repair",
        "demolish",
    ] = "new"
    materialization_role: Literal[
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    ] | None = None
    area_min_ha: float | None = None
    area_max_ha: float | None = None
    road_parameters: RoadPlanningParameters | None = None
    rationale: str = ""


class DuplicateMerge(BaseModel):
    canonical_target_id: str
    duplicate_target_ids: list[str] = Field(default_factory=list)
    rationale: str = ""


class DiagnosticDisposition(BaseModel):
    issue_index: int
    resolution: Literal["unresolved", "normalized", "audit_only"] = "unresolved"
    rationale: str = ""


class ProgramSemanticRepairCandidate(BaseModel):
    patches: list[InterventionSemanticPatch] = Field(default_factory=list)
    duplicate_merges: list[DuplicateMerge] = Field(default_factory=list)
    dependencies: list[InterventionDependency] = Field(default_factory=list)
    diagnostic_dispositions: list[DiagnosticDisposition] = Field(default_factory=list)

    @field_validator(
        "patches",
        "duplicate_merges",
        "dependencies",
        "diagnostic_dispositions",
        mode="before",
    )
    @classmethod
    def decode_provider_arrays(cls, value: Any) -> Any:
        """Normalize MiniMax nested tool arguments at the provider boundary."""
        if isinstance(value, str):
            decoded = json.loads(value)
            if not isinstance(decoded, list):
                raise TypeError("structured repair field must decode to a list")
            return decoded
        return value


class ProgramSemanticRepairResult(BaseModel):
    program: PlanningProgram
    applied: bool = False
    attempts: int = 0
    cache_hits: int = 0
    validation_errors: list[str] = Field(default_factory=list)


class SemanticRepairCache:
    """Atomic JSON cache keyed by the complete prompt fingerprint."""

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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if str(value or "").strip()))


def _duplicate_candidate_pairs(program: PlanningProgram) -> list[list[str]]:
    """Generate a small comparison set; the LLM makes the semantic decision."""
    pairs: list[list[str]] = []
    items = list(program.interventions)
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
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


def _repair_payload(program: PlanningProgram) -> dict[str, Any]:
    catalogue = [
        {
            "target_id": item.target_id,
            "name": item.name,
            "category": item.category,
            "output": item.expected_output_kind,
            "phase": item.implementation_phase,
            "location": (item.spatial_requirements or {}).get("location", ""),
        }
        for item in program.interventions
    ]
    return {
        "catalogue": catalogue,
        "duplicate_candidate_pairs": _duplicate_candidate_pairs(program),
    }


def _build_prompt(program: PlanningProgram, feedback: list[str]) -> str:
    payload = _repair_payload(program)
    return (
        "你是村庄规划项目库的跨专题 Program Critic。每个项目的类型、尺度和动作已由"
        "所属 L3 专题完成结构化编译；你不得重新解释或修改这些对象字段。"
        "不得创建坐标、BSM、地块、几何或规划用地编码。\n"
        "规则：\n"
        "1. patches 和 diagnostic_dispositions 必须为空；源头字段错误只能返回所属 L3 专题。\n"
        "2. duplicate_merges 只可从 duplicate_candidate_pairs 选择；专题总目标与其子工程不是重复，"
        "名称相似但范围、里程、阶段或功能不同也不是重复。\n"
        "3. dependency 的 from 表示前置项目，to 表示依赖它的后续项目；只输出有充分规划逻辑依据的依赖。\n"
        f"上轮确定性校验反馈：{json.dumps(feedback, ensure_ascii=False)}\n"
        f"输入：{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def _duplicate_map(candidate: ProgramSemanticRepairCandidate) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for merge in candidate.duplicate_merges:
        for duplicate in merge.duplicate_target_ids:
            mapping[duplicate] = merge.canonical_target_id
    return mapping


def _has_cycle(dependencies: list[InterventionDependency]) -> bool:
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


def validate_semantic_repair_candidate(
    program: PlanningProgram,
    candidate: ProgramSemanticRepairCandidate,
) -> list[str]:
    """Check all LLM suggestions without mutating the program."""
    errors: list[str] = []
    by_id = {item.target_id: item for item in program.interventions}
    duplicate_pairs = {frozenset(pair) for pair in _duplicate_candidate_pairs(program)}
    duplicate_ids: set[str] = set()
    canonical_ids: set[str] = set()

    for merge in candidate.duplicate_merges:
        canonical = by_id.get(merge.canonical_target_id)
        if canonical is None:
            errors.append(f"unknown canonical target: {merge.canonical_target_id}")
            continue
        canonical_ids.add(merge.canonical_target_id)
        if not merge.duplicate_target_ids:
            errors.append(f"empty duplicate merge: {merge.canonical_target_id}")
        for duplicate_id in merge.duplicate_target_ids:
            duplicate = by_id.get(duplicate_id)
            if duplicate is None:
                errors.append(f"unknown duplicate target: {duplicate_id}")
                continue
            if duplicate_id == merge.canonical_target_id or duplicate_id in duplicate_ids:
                errors.append(f"duplicate target reused: {duplicate_id}")
                continue
            duplicate_ids.add(duplicate_id)
            if frozenset((merge.canonical_target_id, duplicate_id)) not in duplicate_pairs:
                errors.append(f"merge was not in candidate pairs: {duplicate_id}")
            if (
                duplicate.category != canonical.category
                or duplicate.expected_output_kind != canonical.expected_output_kind
            ):
                errors.append(f"incompatible duplicate merge: {duplicate_id}")

    if candidate.patches:
        errors.append("program critic cannot patch object semantics; return the source L3 dimension")
    if candidate.diagnostic_dispositions:
        errors.append("program critic cannot hide or downgrade source diagnostics")

    final_ids = set(by_id).difference(duplicate_ids)
    dependencies: list[InterventionDependency] = []
    mapping = _duplicate_map(candidate)
    for dependency in [*program.dependencies, *candidate.dependencies]:
        source = mapping.get(dependency.from_intervention_id, dependency.from_intervention_id)
        target = mapping.get(dependency.to_intervention_id, dependency.to_intervention_id)
        if source not in final_ids or target not in final_ids:
            errors.append(f"dependency references unknown target: {source}->{target}")
            continue
        if source == target:
            errors.append(f"self dependency: {source}")
            continue
        dependencies.append(
            dependency.model_copy(
                update={"from_intervention_id": source, "to_intervention_id": target}
            )
        )
    if _has_cycle(dependencies):
        errors.append("dependency graph contains a cycle")
    return _unique(errors)


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
    """Apply an already validated candidate and preserve an audit trail."""
    errors = validate_semantic_repair_candidate(program, candidate)
    if errors:
        raise ValueError("invalid semantic repair candidate: " + "; ".join(errors))
    by_id = {item.target_id: item.model_copy(deep=True) for item in program.interventions}
    mapping = _duplicate_map(candidate)
    for duplicate_id, canonical_id in mapping.items():
        by_id[canonical_id] = _merge_interventions(by_id[canonical_id], by_id[duplicate_id])
        del by_id[duplicate_id]

    for patch in candidate.patches:
        target_id = mapping.get(patch.target_id, patch.target_id)
        item = by_id[target_id]
        update: dict[str, Any] = {"intervention_action": patch.intervention_action}
        if patch.materialization_role is not None:
            update["materialization_role"] = patch.materialization_role
        if patch.area_min_ha is not None and patch.area_max_ha is not None:
            update["area_range_ha"] = (patch.area_min_ha, patch.area_max_ha)
        if patch.road_parameters is not None:
            update["road_parameters"] = patch.road_parameters
        by_id[target_id] = item.model_copy(update=update)

    for target_id, item in list(by_id.items()):
        if item.category == "protection" and item.materialization_role is None:
            by_id[target_id] = item.model_copy(
                update={"materialization_role": "protection_overlay"}
            )
        elif item.category == "restoration" and item.materialization_role is None:
            by_id[target_id] = item.model_copy(
                update={"materialization_role": "restoration_overlay"}
            )

    disposition_by_index = {
        disposition.issue_index: disposition
        for disposition in candidate.diagnostic_dispositions
    }
    issues: list[ProgramIssue] = []
    for index, issue in enumerate(program.program_issues):
        disposition = disposition_by_index.get(index)
        if disposition is None or disposition.resolution == "unresolved":
            issues.append(issue.model_copy(deep=True))
            continue
        issues.append(
            issue.model_copy(
                update={
                    "severity": "warning" if disposition.resolution == "normalized" else "info",
                    "code": (
                        "claim_set_diagnostic_resolved"
                        if disposition.resolution == "normalized"
                        else "claim_set_diagnostic_audit"
                    ),
                    "detail": disposition.rationale,
                }
            )
        )
    issues.append(
        ProgramIssue(
            severity="info",
            code="semantic_repair_applied",
            message=(
                f"bounded LLM repair applied: patches={len(candidate.patches)}, "
                f"merges={len(candidate.duplicate_merges)}, "
                f"dependencies={len(candidate.dependencies)}"
            ),
            detail=f"attempts={attempts}; cache_hits={cache_hits}; prompt={_PROMPT_VERSION}",
        )
    )

    dependency_keys: set[tuple[str, str, str]] = set()
    dependencies: list[InterventionDependency] = []
    for dependency in [*program.dependencies, *candidate.dependencies]:
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


def _coerce_candidate(value: Any) -> ProgramSemanticRepairCandidate:
    if isinstance(value, ProgramSemanticRepairCandidate):
        return value
    if hasattr(value, "content"):
        value = value.content
    if isinstance(value, str):
        stripped = value.strip().strip("`")
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
        return ProgramSemanticRepairCandidate.model_validate_json(stripped)
    return ProgramSemanticRepairCandidate.model_validate(value)


def _is_nonrecoverable_provider_quota(exc: BaseException) -> bool:
    """Return true for provider quota states that cannot improve by retrying."""
    text = str(exc or "").lower()
    return any(
        marker in text
        for marker in (
            "gousagelimiterror",
            "weekly usage limit",
            "quota exceeded",
            "insufficient balance",
        )
    )


async def repair_planning_program(
    program: PlanningProgram,
    *,
    llm: Any = None,
    cache_path: Path | None = None,
    max_rounds: int = 3,
    timeout_seconds: float = 180.0,
) -> ProgramSemanticRepairResult:
    """Run validation-guided LLM repair with bounded retries and resume cache."""
    if max_rounds < 1:
        raise ValueError("max_rounds must be positive")
    source_errors = [
        issue
        for issue in program.program_issues
        if issue.severity == "error"
        and issue.code != "classification_decision_required"
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
        )
    from app.infrastructure.llm.structured import run_structured_output

    cache = SemanticRepairCache(cache_path)
    feedback: list[str] = []
    cache_hits = 0
    attempts = 0
    quota_exhausted = False
    for round_index in range(max_rounds):
        prompt = _build_prompt(program, feedback)
        cache_key = hashlib.sha256(
            f"{_PROMPT_VERSION}\n{prompt}".encode("utf-8")
        ).hexdigest()
        candidate = cache.get(cache_key)
        if candidate is not None:
            cache_hits += 1
        else:
            attempts += 1
            try:
                raw = await run_structured_output(
                    ProgramSemanticRepairCandidate,
                    [
                            {
                                "role": "system",
                                "content": "Return only the requested structured repair candidate.",
                            },
                            {"role": "user", "content": prompt},
                    ],
                    max_retries=1,
                    timeout=timeout_seconds,
                    temperature=0.1,
                    max_tokens=8192,
                    llm=llm,
                )
                candidate = _coerce_candidate(raw)
                cache.put(cache_key, candidate)
            except Exception as exc:  # noqa: BLE001
                feedback = [f"round {round_index + 1} provider/schema failure: {exc}"]
                quota_exhausted = _is_nonrecoverable_provider_quota(exc)
                logger.warning(
                    "[l3-semantic-repair] %s%s",
                    feedback[0],
                    "; stopping because provider quota is exhausted"
                    if quota_exhausted
                    else "",
                )
                if quota_exhausted:
                    break
                continue

        feedback = validate_semantic_repair_candidate(program, candidate)
        if feedback:
            logger.warning(
                "[l3-semantic-repair] round %d rejected with %d deterministic errors",
                round_index + 1,
                len(feedback),
            )
            continue
        repaired = apply_semantic_repair_candidate(
            program,
            candidate,
            attempts=attempts,
            cache_hits=cache_hits,
        )
        logger.info(
            "[l3-semantic-repair] applied after round=%d calls=%d cache_hits=%d interventions=%d->%d",
            round_index + 1,
            attempts,
            cache_hits,
            len(program.interventions),
            len(repaired.interventions),
        )
        return ProgramSemanticRepairResult(
            program=repaired,
            applied=True,
            attempts=attempts,
            cache_hits=cache_hits,
        )

    failure = ProgramIssue(
        severity="error",
        code=(
            "llm_provider_quota_exhausted"
            if quota_exhausted
            else "llm_semantic_repair_failed"
        ),
        message=(
            "L3 semantic repair stopped because the provider quota is exhausted"
            if quota_exhausted
            else "L3 semantic repair exhausted its bounded retry budget"
        ),
        detail="; ".join(feedback)[:2000],
    )
    return ProgramSemanticRepairResult(
        program=program.model_copy(
            update={"program_issues": [*program.program_issues, failure]}, deep=True
        ),
        applied=False,
        attempts=attempts,
        cache_hits=cache_hits,
        validation_errors=feedback,
    )


__all__ = [
    "DiagnosticDisposition",
    "DuplicateMerge",
    "InterventionSemanticPatch",
    "ProgramSemanticRepairCandidate",
    "ProgramSemanticRepairResult",
    "SemanticRepairCache",
    "apply_semantic_repair_candidate",
    "repair_planning_program",
    "validate_semantic_repair_candidate",
]
