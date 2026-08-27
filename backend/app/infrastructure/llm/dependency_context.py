"""Safe, metadata-only dependency context for analysis prompts."""

from dataclasses import dataclass
import json
from collections.abc import Collection
from typing import Any

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
    ) -> str:
        selected = set(str(key) for key in include_keys) if include_keys is not None else set(self.keys)
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
                dependency["instruction"] = item.instruction
            allowed_dependencies.append(dependency)
        payload = {
            "consumer_dimension": self.dimension_key,
            "consumer_layer": self.layer,
            "allowed_direct_dependencies": allowed_dependencies,
            "missing_direct_dependencies": list(self.missing_keys),
        }
        payload["missing_direct_dependencies"] = [
            key for key in self.missing_keys if key in selected
        ]
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
