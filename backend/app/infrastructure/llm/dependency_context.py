"""Bounded, typed dependency context for analysis prompts."""

from dataclasses import dataclass
from collections.abc import Collection
import json
from typing import Any

from app.infrastructure.llm.context_manager import render_dependency_table
from app.infrastructure.reports.report_store import ReportStore


@dataclass(frozen=True)
class DependencyArtifact:
    dimension_key: str
    layer: int
    version: int
    report_id: str
    summary: str
    instruction: Any
    instruction_status: str = "resolved"


@dataclass(frozen=True)
class DependencyContext:
    dimension_key: str
    layer: int
    keys: tuple[str, ...]
    artifacts: tuple[DependencyArtifact, ...]
    missing_keys: tuple[str, ...] = ()

    def render_for_prompt(
        self,
        include_keys: Collection[str] | None = None,
        *,
        include_summary: bool = True,
        include_instruction: bool = True,
        instruction_projection: str = "full",
    ) -> str:
        selected = set(str(key) for key in include_keys) if include_keys is not None else set(self.keys)
        selected_artifacts = [
            item for item in self.artifacts if item.dimension_key in selected
        ]
        if instruction_projection == "decision":
            lines = [
                "【跨依赖去重后的 L2 abstract decisions】",
                render_table(
                    (
                        "source_dimensions",
                        "decision_type",
                        "decision_id",
                        "statement_or_name",
                        "scope_or_value",
                        "refs",
                        "requirements",
                    ),
                    _decision_rows(selected_artifacts),
                ),
            ]
            missing = [key for key in self.missing_keys if key in selected]
            if missing:
                lines.append("缺失的直接依赖：" + "、".join(missing))
            return "\n".join(lines)
        if instruction_projection == "claim":
            lines = [
                "【跨依赖去重后的 L3 rough claims】",
                render_table(
                    (
                        "source_dimensions",
                        "claim_id",
                        "claim_family",
                        "planning_role",
                        "statement",
                        "location_hints",
                        "refs",
                        "grounding_requirements",
                        "uncertainty",
                    ),
                    _claim_rows(selected_artifacts),
                ),
            ]
            missing = [key for key in self.missing_keys if key in selected]
            if missing:
                lines.append("缺失的直接依赖：" + "、".join(missing))
            return "\n".join(lines)
        allowed_dependencies: list[dict[str, Any]] = []
        for item in self.artifacts:
            if item.dimension_key not in selected:
                continue
            dependency: dict[str, Any] = {
                "dimension_key": item.dimension_key,
                "layer": item.layer,
                "version": item.version,
                "report_id": item.report_id,
                "instruction_status": item.instruction_status,
            }
            if include_summary:
                dependency["summary"] = item.summary
            if include_instruction:
                dependency["instruction"] = (
                    _decision_projection(item.instruction)
                    if instruction_projection == "decision"
                    else item.instruction
                )
            allowed_dependencies.append(dependency)
        missing = [
            key for key in self.missing_keys if key in selected
        ]
        lines = [
            f"消费维度：{self.dimension_key}（L{self.layer}）",
            render_dependency_table(allowed_dependencies),
        ]
        if missing:
            lines.append("\n缺失的直接依赖：" + "、".join(missing))
        return "\n".join(lines)


_DECISION_DROP_KEYS = frozenset({
    "source_documents", "source_digest", "pass_cursor", "diagnostics",
    "retrieval_trace", "query_trace", "content", "report_body", "raw",
    "raw_content", "sources", "knowledge_sources",
    # These are useful for human reporting but do not carry dependency edges
    # or executable semantics into L3.  Keeping them in every transitive L2
    # projection is the main source of avoidable context growth.
    "rationale", "confidence", "description", "resolution",
})

_DECISION_COLLECTION_FIELDS = {
    "objectives": {"objective_id", "statement", "kind", "status", "scope", "target_year", "source_fact_refs", "constraint_refs"},
    "metrics": {"metric_id", "name", "value", "unit", "direction", "status", "baseline_ref", "objective_refs", "source_fact_refs", "target_year"},
    "strategies": {"strategy_id", "statement", "action", "objective_refs", "target_refs", "strength", "scope", "phase", "prerequisite_refs", "source_fact_refs"},
    "priorities": {"priority_id", "rank", "strategy_refs", "statement"},
    "spatial_structures": {"structure_id", "statement", "scope", "relation_kind", "objective_refs", "source_fact_refs", "grounding_requirements"},
    "conflicts": {"conflict_id", "objective_refs", "strategy_refs", "severity"},
    "evidence_gaps": {"gap_id", "dimension", "required_fact", "severity", "description"},
}
_DECISION_ROOT_FIELDS = frozenset({
    "schema_version", "dimension_key", "objectives", "metrics", "strategies",
    "priorities", "spatial_structures", "conflicts", "evidence_gaps", "source_refs",
})

_DECISION_ID_FIELDS = {
    "objectives": "objective_id",
    "metrics": "metric_id",
    "strategies": "strategy_id",
    "priorities": "priority_id",
    "spatial_structures": "structure_id",
    "conflicts": "conflict_id",
    "evidence_gaps": "gap_id",
}

_CLAIM_FIELDS = frozenset({
    "claim_id",
    "dimension_key",
    "statement",
    "planning_role",
    "suggested_category",
    "suggested_output_kind",
    "location_hints",
    "constraint_refs",
    "objective_refs",
    "evidence_refs",
    "source_fact_refs",
    "uncertainty",
})


def _decision_projection(value: Any, *, _root: bool = True) -> Any:
    """Keep semantic decision content without recursively copying raw payloads."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name in _DECISION_DROP_KEYS:
                continue
            if _root and name not in _DECISION_ROOT_FIELDS:
                continue
            allowed = _DECISION_COLLECTION_FIELDS.get(name)
            if allowed is not None and isinstance(item, list):
                item = [
                    {
                        str(child_key): _decision_projection(child_value, _root=False)
                        for child_key, child_value in child.items()
                        if str(child_key) in allowed
                    }
                    if isinstance(child, dict) else _decision_projection(child, _root=False)
                    for child in item
                ]
            result[name] = _decision_projection(item, _root=False)
        return result
    if isinstance(value, list):
        return [_decision_projection(item, _root=False) for item in value]
    return value


def _merge_list_values(first: Any, second: Any) -> list[Any]:
    values = list(first) if isinstance(first, list) else ([] if first is None else [first])
    values.extend(second if isinstance(second, list) else ([] if second is None else [second]))
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _decision_rows(artifacts: list[DependencyArtifact]) -> list[dict[str, Any]]:
    """Flatten and merge L2 decisions into one consumer-specific table."""

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for artifact in artifacts:
        projected = _decision_projection(artifact.instruction)
        if not isinstance(projected, dict):
            continue
        for collection, id_field in _DECISION_ID_FIELDS.items():
            items = projected.get(collection)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get(id_field) or "").strip()
                marker = item_id or json.dumps(
                    item,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                key = (collection, marker)
                refs = {
                    str(value).strip()
                    for field, values in item.items()
                    if str(field).endswith("_refs")
                    for value in (values if isinstance(values, list) else [values])
                    if str(value).strip()
                }
                requirements = {
                    str(value).strip()
                    for value in (item.get("grounding_requirements") or [])
                    if str(value).strip()
                }
                if key not in merged:
                    merged[key] = {
                        "source_dimensions": [artifact.dimension_key],
                        "decision_type": collection.removesuffix("s"),
                        "decision_id": item_id,
                        "statement_or_name": (
                            item.get("statement")
                            or item.get("name")
                            or item.get("required_fact")
                            or item.get("action")
                            or ""
                        ),
                        "scope_or_value": (
                            item.get("scope")
                            or item.get("value")
                            or item.get("phase")
                            or item.get("strength")
                            or item.get("rank")
                            or ""
                        ),
                        "refs": sorted(refs),
                        "requirements": sorted(requirements),
                    }
                    order.append(key)
                    continue
                row = merged[key]
                if artifact.dimension_key not in row["source_dimensions"]:
                    row["source_dimensions"].append(artifact.dimension_key)
                row["refs"] = sorted(set(row["refs"]) | refs)
                row["requirements"] = sorted(set(row["requirements"]) | requirements)
    return [merged[key] for key in order]


def _claim_projection(value: Any) -> list[dict[str, Any]]:
    """Keep only rough claim semantics from same-layer L3 artifacts."""

    if not isinstance(value, dict):
        return []
    raw_claims = value.get("claims")
    if not isinstance(raw_claims, list):
        return []
    return [
        {
            str(key): item
            for key, item in claim.items()
            if str(key) in _CLAIM_FIELDS
        }
        for claim in raw_claims
        if isinstance(claim, dict)
    ]


def _claim_rows(artifacts: list[DependencyArtifact]) -> list[dict[str, Any]]:
    """Flatten same-layer rough claims and merge duplicate claim IDs."""

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for artifact in artifacts:
        for claim in _claim_projection(artifact.instruction):
            claim_id = str(claim.get("claim_id") or "").strip()
            marker = claim_id or json.dumps(
                claim,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if marker not in merged:
                merged[marker] = {
                    "source_dimensions": [artifact.dimension_key],
                    "claim_id": claim_id,
                    "claim_family": claim.get("suggested_category") or "",
                    "planning_role": claim.get("planning_role") or "",
                    "statement": claim.get("statement") or "",
                    "location_hints": claim.get("location_hints") or [],
                    "refs": _merge_list_values(
                        claim.get("objective_refs"),
                        _merge_list_values(
                            claim.get("source_fact_refs"),
                            claim.get("evidence_refs"),
                        ),
                    ),
                    "grounding_requirements": [],
                    "uncertainty": claim.get("uncertainty") or "",
                }
                order.append(marker)
            else:
                row = merged[marker]
                if artifact.dimension_key not in row["source_dimensions"]:
                    row["source_dimensions"].append(artifact.dimension_key)
                row["refs"] = _merge_list_values(row["refs"], claim.get("source_fact_refs"))
                row["refs"] = _merge_list_values(row["refs"], claim.get("objective_refs"))
                row["refs"] = _merge_list_values(row["refs"], claim.get("evidence_refs"))
    return [merged[key] for key in order]


def direct_dependency_keys(dimension_config: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    keys: list[str] = []
    for name in ("depends_on", "layer_depends_on", "phase_depends_on"):
        for value in getattr(dimension_config, name, ()) or ():
            key = str(value).strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return tuple(keys)


def _instruction(value: Any) -> tuple[Any, str]:
    if value is None or value == "":
        return None, "missing"
    if isinstance(value, (dict, list)):
        return _semantic_instruction(value), "resolved"
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None, "unparseable"
    if isinstance(parsed, (dict, list)):
        return _semantic_instruction(parsed), "resolved"
    return None, "unparseable"


_AUDIT_ONLY_INSTRUCTION_KEYS = frozenset({
    "source_documents",
    "source_digest",
    "pass_cursor",
    "diagnostics",
    "retrieval_trace",
    "query_trace",
})
_RAW_INSTRUCTION_KEYS = frozenset({
    "content",
    "report_body",
    "raw",
    "raw_content",
})


def _semantic_instruction(value: dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    """Keep dependency instructions semantic and exclude audit/raw payloads."""

    if isinstance(value, list):
        return value
    return {
        str(key): item
        for key, item in value.items()
        if str(key) not in _AUDIT_ONLY_INSTRUCTION_KEYS
        and str(key) not in _RAW_INSTRUCTION_KEYS
    }


async def load_dependency_context(session_id: str, dimension_key: str, config: Any, layer: int) -> DependencyContext:
    keys = direct_dependency_keys(config)
    records = await ReportStore.get_instance().get_latest_dependency_records(session_id, keys)
    artifacts: list[DependencyArtifact] = []
    missing: list[str] = []
    for key in keys:
        record = records.get(key)
        if not record:
            missing.append(key)
            continue
        instruction, status = _instruction(record.get("instruction"))
        artifacts.append(DependencyArtifact(
            dimension_key=key,
            layer=int(record.get("layer", 0)),
            version=int(record.get("version", 0)),
            report_id=str(record.get("report_id", "")),
            summary=str(record.get("summary") or ""),
            instruction=instruction,
            instruction_status=status,
        ))
    return DependencyContext(dimension_key, layer, keys, tuple(artifacts), tuple(missing))


__all__ = ["DependencyArtifact", "DependencyContext", "direct_dependency_keys", "load_dependency_context"]
