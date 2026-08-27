"""L1 Observation profile - normalize one L1 dimension into a snapshot.

Enforces the roadmap constraint: 现状地类只提供分类代码与名称（ClassificationRef）；
禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间. Uses ONLY same-system
code->name; never imports advisory_crosswalks.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.domain.l1_contracts import (
    EvidenceGap,
    LocationMention,
    LocationScopeMention,
    L1SpatialProvenance,
    L1Snapshot,
)
from app.contracts.workflow.parsing_contracts import CompilationProfile, CompilerTrace
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.domain.assessment.l1_fact_projection import make_l1_fact
from app.domain.assessment.observation_draft import observation_to_compiler_payload

from ..diagnostics import collect_diagnostics
from ..provenance import build_fragment_provenance

_CHAPTER_RE = re.compile(r"^#{1,3}\s+(\S.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)


def _split_explicit_places(value: str) -> list[str]:
    """Split a report location cell, preserving only explicit place tokens."""
    value = re.sub(r"（.*?）|\(.*?\)", "", value or "")
    value = value.replace("以及", "、").replace("和", "、").replace("及", "、")
    parts = re.split(r"[、,，;；/]+", value)
    result: list[str] = []
    for part in parts:
        part = re.sub(r"^\s*(?:经过|位于|沿线|覆盖|全村)\s*", "", part).strip()
        part = re.sub(r"^\d+[、.．)]?\s*", "", part).strip()
        if not part or part in {"全村", "/", "-", "—"}:
            continue
        # A route such as “肩丰-炉池” is a relation, not a single village.
        if "-" in part or "—" in part:
            result.extend(x.strip() for x in re.split(r"[-—]", part) if x.strip())
        else:
            result.append(part)
    return list(dict.fromkeys(result))


def _clean_model_text(text: str) -> str:
    """Remove reasoning/protocol chatter before compiling human facts."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.I | re.S)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"^\[[^\]]+\]\s*模型观察:\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*模型观察:\s*", "", cleaned, flags=re.MULTILINE)
    lines: list[str] = []
    meta_patterns = (
        "用户要求我", "按照要求的格式", "输出一个固定格式", "让我先仔细阅读",
        "我需要分析", "需要我作为", "以下是我", "下面我将",
    )
    for line in cleaned.splitlines():
        if any(pattern in line for pattern in meta_patterns):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _dedup_location_mentions_local(
    mentions: list[LocationMention],
) -> list[LocationMention]:
    result: list[LocationMention] = []
    seen: set[
        tuple[str, str, str, tuple[str, ...], str, tuple[str, ...]]
    ] = set()
    for fact in mentions:
        key = (
            fact.normalized_name.strip(),
            fact.role.strip(),
            fact.dimension_key.strip(),
            tuple(sorted({
                f"{scope.role}:{scope.normalized_name or scope.name}:"
                f"{scope.relation_to_target}"
                for scope in fact.scopes
                if (scope.normalized_name or scope.name).strip()
            })),
            str(getattr(fact, "instance_label", "") or "").strip(),
            tuple(sorted({
                str(value).strip()
                for value in (
                    getattr(fact, "source_feature_ids", None) or []
                )
                if str(value).strip()
            })),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(fact)
    return result


def _dedup_location_facts_local(
    facts: list[LocationMention],
) -> list[LocationMention]:
    """Compatibility wrapper for callers still using the retired helper name."""

    return _dedup_location_mentions_local(facts)


def _iter_chapters(content: str) -> list[tuple[str, str]]:
    """Yield (chapter_title, chapter_body) from markdown content."""
    matches = list(_CHAPTER_RE.finditer(content or ""))
    chapters: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content or "")
        chapters.append((m.group(1).strip(), content[m.end():end]))
    return chapters


def _first_sentence(text: str) -> str:
    body = re.sub(r"^\s*[-*]\s+", "", text.strip(), flags=re.MULTILINE)
    body = body.replace("\n", " ")
    body = re.sub(r"\s+", " ", body).strip()
    return body[:120]


def _parse_land_use_table(chapter_body: str) -> list[dict[str, str]]:
    """Parse 地类|面积|占比 rows from a chapter body. Returns row dicts."""
    rows: list[dict[str, str]] = []
    for line in chapter_body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2 or all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        if any("地类" in c or "名称" in c for c in cells):
            continue  # header row
        has_code = bool(re.fullmatch(r"[A-Za-z0-9._-]+", cells[0]))
        rows.append(
            {
                "code": cells[0] if has_code else "",
                "name": cells[1] if has_code and len(cells) > 1 else cells[0],
                "area": cells[2] if has_code and len(cells) > 2 else (cells[1] if len(cells) > 1 else ""),
                "ratio": cells[3] if has_code and len(cells) > 3 else (cells[2] if len(cells) > 2 else ""),
            }
        )
    return rows


_OBSERVATION_TYPE_ROLES = {
    "现状设施": "facility",
    "设施": "facility",
    "现状项目": "project",
    "项目": "project",
    "现状分区": "area",
    "分区": "area",
    "自然村": "natural_village",
    "村庄": "natural_village",
    "道路": "road",
    "水系": "water",
    "水体": "water",
    "地物": "landmark",
}


def _observation_role(entity_type: str, name: str, location: str, description: str) -> str:
    et = (entity_type or "").strip()
    if et:
        mapped = _OBSERVATION_TYPE_ROLES.get(et)
        if mapped:
            return mapped
    text = f"{name} {location} {description}"
    for key, role in _OBSERVATION_TYPE_ROLES.items():
        if key in text:
            return role
    return "unknown"


_SCOPE_ROLE_ALIASES = {
    "natural_village": "natural_village",
    "village": "natural_village",
    "natural village": "natural_village",
    "自然村": "natural_village",
    "村庄": "natural_village",
    "administrative_village": "administrative_village",
    "行政村": "administrative_village",
    "place": "place",
    "地点": "place",
    "area": "area",
    "区域": "area",
}


def _scope_role(value: Any, *, default: str = "unknown") -> str:
    raw = str(value or "").strip().casefold().replace("-", "_")
    return _SCOPE_ROLE_ALIASES.get(raw, raw or default)


_DESCRIPTIVE_MARKERS = (
    "至", "贯穿", "沿线", "两岸", "附近", "周边", "一带", "一段", "位于",
    "汇入", "通往", "经过", "沿", "东北", "东南", "西北", "西南", "北部",
    "南部", "东部", "西部", "中部", "村界", "全村", "境内",
)


def _is_place_like(token: str) -> bool:
    """地点 token 判定（启发式，尽量保守）：短、无方位/描述/动词标记。

    只有这类 token 才被编译为独立 location_fact；其余仅作 hint。
    """
    token = (token or "").strip()
    if not token or len(token) > 6:
        return False
    if any(marker in token for marker in _DESCRIPTIVE_MARKERS):
        return False
    return True


def _explicit_spatial_mentions(obs: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only provider-declared spatial work items.

    The compiler intentionally does not mine arbitrary description prose for
    geometry.  A provider must opt into the typed ``spatial_mentions`` field;
    the resulting records remain semantic until EvidenceGraph resolves them.
    """

    mentions: list[dict[str, Any]] = []
    for raw in obs.get("spatial_mentions") or []:
        if not isinstance(raw, dict):
            continue
        target = str(
            raw.get("target_name")
            or raw.get("normalized_name")
            or raw.get("mention")
            or ""
        ).strip()
        if not target:
            continue
        raw_scopes = raw.get("scope_mentions")
        if raw_scopes is None:
            raw_scopes = [
                {"name": value, "role": "natural_village"}
                for value in raw.get("village_scopes") or []
            ]
            raw_scopes.extend(
                {"name": value, "role": "place"}
                for value in raw.get("place_scopes") or []
            )
        scopes: list[dict[str, Any]] = []
        for value in raw_scopes or []:
            if isinstance(value, str):
                value = {"name": value}
            if not isinstance(value, dict):
                continue
            name = str(
                value.get("name") or value.get("normalized_name") or ""
            ).strip()
            if not name:
                continue
            scopes.append({
                "name": name,
                "normalized_name": str(
                    value.get("normalized_name") or name
                ).strip(),
                "role": _scope_role(value.get("role")),
                "relation_to_target": str(
                    value.get("relation_to_target")
                    or value.get("relation")
                    or "located_in"
                ).strip(),
                "aliases": list(dict.fromkeys(
                    str(alias).strip()
                    for alias in (value.get("aliases") or [])
                    if str(alias).strip()
                )),
                "source_quote": str(value.get("source_quote") or "").strip(),
                "source_refs": list(dict.fromkeys(
                    str(ref).strip()
                    for ref in (value.get("source_refs") or [])
                    if str(ref).strip()
                )),
                "source_segment_ids": list(dict.fromkeys(
                    str(ref).strip()
                    for ref in (value.get("source_segment_ids") or [])
                    if str(ref).strip()
                )),
                "confidence": (
                    float(value.get("confidence"))
                    if isinstance(value.get("confidence"), (int, float))
                    else 0.0
                ),
            })
        mentions.append({
            **raw,
            "target_name": target,
            "normalized_name": str(raw.get("normalized_name") or target).strip(),
            "mention": str(raw.get("mention") or target).strip(),
            "scope_mentions": scopes,
        })
    return mentions


def _extract_location_mentions_from_observations(
    instruction: str,
    *,
    dimension_key: str,
    report_id: str,
) -> list[LocationMention]:
    """Compile the validated L1 observation projection into typed facts.

    The structured observations JSON is the single location-fact source;
    invalid or empty JSON yields zero facts.
    """
    if not instruction:
        return []
    try:
        payload = json.loads(instruction)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("observations") or []
    if not isinstance(payload, list):
        return []
    mentions: list[LocationMention] = []
    seen: set[str] = set()
    for item in payload:
        try:
            obs = observation_to_compiler_payload(item)
        except Exception:
            continue
        name = str(obs.get("name") or "").strip()
        location = str(obs.get("location") or "").strip()
        relation = str(obs.get("relation") or "").strip()
        entity_type = str(obs.get("entity_type") or "").strip()
        description = str(obs.get("description") or "").strip()
        kind = str(obs.get("fact_type") or "").strip()
        explicit_mentions = _explicit_spatial_mentions(obs)
        if str(obs.get("status") or "").strip() != "confirmed":
            continue
        spatial_observation = kind in {"spatial_entity", "spatial_relation"} or bool(
            location or relation or obs.get("source_feature_ids") or explicit_mentions
        )
        if not spatial_observation:
            continue
        source_quote = str(obs.get("source_quote") or "").strip()
        source_segment_ids = [
            str(value).strip()
            for value in (obs.get("source_segment_ids") or [])
            if str(value).strip()
        ]
        evidence_refs = list(dict.fromkeys([
            *[
                str(value).strip()
                for value in (obs.get("source_refs") or [])
                if str(value).strip()
            ],
            *source_segment_ids,
        ]))
        if not name and not location and not explicit_mentions:
            continue
        role = _observation_role(entity_type, name, location, description)
        base_role = role
        source_span = source_quote or " | ".join(
            x for x in (entity_type, name, location, relation, description) if x
        )
        if explicit_mentions:
            observation_source_refs = [
                str(value).strip()
                for value in (obs.get("source_refs") or [])
                if str(value).strip()
            ]
            observation_feature_ids = [
                str(value).strip()
                for value in (obs.get("source_feature_ids") or [])
                if str(value).strip()
            ]
            raw_confidence = obs.get("confidence")
            for mention in explicit_mentions:
                target_name = str(mention.get("target_name") or name).strip()
                normalized_name = str(
                    mention.get("normalized_name") or target_name
                ).strip()
                mention_role = _scope_role(
                    mention.get("role"),
                    default=base_role,
                )
                mention_relation = str(mention.get("relation") or relation).strip()
                raw_scope_mentions = list(mention.get("scope_mentions") or [])
                if not raw_scope_mentions:
                    raw_scope_mentions = [
                        {
                            "name": scope,
                            "normalized_name": scope,
                            "role": "unknown",
                            "relation_to_target": mention_relation or "located_in",
                        }
                        for scope in _split_explicit_places(location)
                    ]
                scope_mentions: list[LocationScopeMention] = []
                for raw_scope in raw_scope_mentions:
                    if isinstance(raw_scope, str):
                        raw_scope = {"name": raw_scope}
                    if not isinstance(raw_scope, dict):
                        continue
                    scope_name = str(
                        raw_scope.get("name")
                        or raw_scope.get("normalized_name")
                        or ""
                    ).strip()
                    if not scope_name:
                        continue
                    scope_mentions.append(LocationScopeMention(
                        name=scope_name,
                        normalized_name=str(
                            raw_scope.get("normalized_name") or scope_name
                        ).strip(),
                        role=_scope_role(raw_scope.get("role")),
                        relation_to_target=str(
                            raw_scope.get("relation_to_target")
                            or raw_scope.get("relation")
                            or mention_relation
                            or "located_in"
                        ).strip(),
                        aliases=list(dict.fromkeys(
                            str(value).strip()
                            for value in (raw_scope.get("aliases") or [])
                            if str(value).strip()
                        )),
                        source_quote=str(
                            raw_scope.get("source_quote") or source_quote
                        ).strip(),
                        source_refs=list(dict.fromkeys([
                            *observation_source_refs,
                            *[
                                str(value).strip()
                                for value in (raw_scope.get("source_refs") or [])
                                if str(value).strip()
                            ],
                        ])),
                        source_segment_ids=list(dict.fromkeys([
                            *source_segment_ids,
                            *[
                                str(value).strip()
                                for value in (
                                    raw_scope.get("source_segment_ids") or []
                                )
                                if str(value).strip()
                            ],
                        ])),
                        confidence=(
                            float(raw_scope.get("confidence"))
                            if isinstance(raw_scope.get("confidence"), (int, float))
                            else 0.0
                        ),
                    ))
                aliases = list(dict.fromkeys([
                    *[
                        str(value).strip()
                        for value in (mention.get("aliases") or [])
                        if str(value).strip()
                    ],
                    target_name,
                    normalized_name,
                ]))
                mention_feature_ids = list(dict.fromkeys([
                    *observation_feature_ids,
                    *[
                        str(value).strip()
                        for value in (mention.get("source_feature_ids") or [])
                        if str(value).strip()
                    ],
                ]))
                resolution_state = str(
                    mention.get("resolution_state") or "needs_retrieval"
                ).strip()
                if resolution_state not in {
                    "resolved",
                    "needs_retrieval",
                    "conflict",
                    "source_exhausted",
                    "unknown",
                }:
                    resolution_state = "needs_retrieval"
                provenance = L1SpatialProvenance(
                    source_refs=observation_source_refs,
                    source_segment_ids=source_segment_ids,
                    source_quote=source_quote,
                    observation_id=(
                        str(mention.get("observation_id") or "").strip()
                    ),
                )
                scope_names = [scope.name for scope in scope_mentions]
                scope_hint = " ".join(
                    value for value in (
                        "、".join(scope_names),
                        mention_relation,
                    ) if value
                )
                mentions.append(LocationMention(
                    mention=target_name,
                    normalized_name=normalized_name,
                    target_name=target_name,
                    role=mention_role,
                    aliases=aliases,
                    spatial_hint=scope_hint,
                    related_mentions=scope_names,
                    scopes=scope_mentions,
                    instance_label=str(
                        mention.get("instance_label") or ""
                    ).strip(),
                    instance_count=str(
                        mention.get("instance_count")
                        or obs.get("scale")
                        or ""
                    ).strip(),
                    resolution_state=resolution_state,
                    provenance=provenance,
                    source_report_ref=report_id,
                    dimension_key=dimension_key,
                    source_span=source_span,
                    evidence_refs=evidence_refs,
                    source_feature_ids=mention_feature_ids,
                    confidence=(
                        float(raw_confidence)
                        if isinstance(raw_confidence, (int, float))
                        else 0.8
                    ),
                ))
            # Explicit work items are authoritative for the location index;
            # do not add a second generic target by mining the description.
            continue
        # Only observations with an explicit spatial role/evidence can emit
        # location facts. Non-spatial metric/demand names remain L1Fact rows.
        parts_to_emit: list[tuple[str, str, str]] = []
        if name and kind in {"spatial_entity", "spatial_relation"}:
            parts_to_emit.append((name, role, location or relation or name))
        # location 里只有"短地点 token"（如 社前村）才作为关联地点事实产出，
        # 用于 facility@村 这类锚定；方位/描述串（如 西南至东北贯穿金田村）
        # 一律不当地点，只作为主事实的 spatial_hint。
        location_parts = _split_explicit_places(location) if location else []
        for location_part in location_parts:
            if not location_part or not _is_place_like(location_part):
                continue
            part_role = role
            parts_to_emit.append((location_part, part_role, location_part))
        for normalized, part_role, spatial_hint in parts_to_emit:
            aliases = list(dict.fromkeys(x for x in (name, normalized) if x))
            key = f"{normalized}|{part_role}|{dimension_key}|{report_id}"
            if key in seen:
                continue
            seen.add(key)
            mentions.append(LocationMention(
                mention=name or normalized,
                normalized_name=normalized,
                role=part_role,
                target_name=name or normalized,
                aliases=aliases,
                spatial_hint=spatial_hint,
                scopes=[],
                source_report_ref=report_id,
                dimension_key=dimension_key,
                source_span=source_span,
                evidence_refs=evidence_refs,
                source_feature_ids=[
                    str(value).strip()
                    for value in (obs.get("source_feature_ids") or [])
                    if str(value).strip()
                ],
                provenance=L1SpatialProvenance(
                    source_refs=[
                        str(value).strip()
                        for value in (obs.get("source_refs") or [])
                        if str(value).strip()
                    ],
                    source_segment_ids=source_segment_ids,
                    source_quote=source_quote,
                ),
                confidence=(
                    float(obs.get("confidence"))
                    if isinstance(obs.get("confidence"), (int, float))
                    else (0.95 if normalized in location_parts else 0.8)
                ),
            ))
    return mentions


def _spatial_facts_from_observations(instruction: str) -> list[str]:
    """Derive facility spatial facts from the structured observations JSON."""
    if not instruction:
        return []
    try:
        payload = json.loads(instruction)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("observations") or []
    if not isinstance(payload, list):
        return []
    out: list[str] = []
    for item in payload:
        try:
            item = observation_to_compiler_payload(item)
        except Exception:
            continue
        entity_type = str(item.get("entity_type") or "").strip()
        name = str(item.get("name") or "").strip()
        location = str(item.get("location") or "").strip()
        if "设施" in entity_type and name:
            out.append(f"设施 {name}，位置 {location}".strip())
    return out


def _instruction_payload(instruction: str) -> dict[str, Any]:
    """Decode the object-shaped L1 instruction envelope."""

    if not instruction:
        return {}
    try:
        payload = json.loads(instruction)
    except (json.JSONDecodeError, TypeError):
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"observations": payload}
    return {}


def _instruction_diagnostics(
    instruction: str,
    *,
    dimension_key: str,
) -> list[ParseDiagnostic]:
    payload = _instruction_payload(instruction)
    diagnostics: list[ParseDiagnostic] = []
    for index, raw in enumerate(payload.get("diagnostics") or []):
        message = str(raw or "").strip()
        if not message:
            continue
        severity = "warning"
        if message.startswith("l1_dimension_fact_type_mismatch:"):
            severity = "info"
        diagnostics.append(
            ParseDiagnostic(
                diagnostic_id=f"{dimension_key}-instruction-diagnostic-{index}",
                severity=severity,
                code="INSTRUCTION_DIAGNOSTIC",
                message=message,
                field_path="instruction.diagnostics",
            )
        )
    return diagnostics


def _scope_conflict_diagnostics(
    mentions: list[LocationMention],
    *,
    dimension_key: str,
) -> list[ParseDiagnostic]:
    """Flag near-duplicate scope spellings without choosing a correction."""

    scopes = sorted({
        str(value).strip()
        for mention in mentions
        for scope in mention.scopes
        for value in (scope.normalized_name or scope.name,)
        if str(value).strip()
    })
    diagnostics: list[ParseDiagnostic] = []
    for index, left in enumerate(scopes):
        left_core = re.sub(r"(?:自然村|村)$", "", left)
        for right in scopes[index + 1:]:
            right_core = re.sub(r"(?:自然村|村)$", "", right)
            if (
                len(left_core) < 2
                or len(left_core) != len(right_core)
                or left_core[-1:] != right_core[-1:]
                or sum(a != b for a, b in zip(left_core, right_core)) != 1
            ):
                continue
            diagnostics.append(ParseDiagnostic(
                diagnostic_id=f"{dimension_key}-scope-conflict-{left}-{right}",
                severity="warning",
                code="L1_SCOPE_CONFLICT_CANDIDATE",
                message=(
                    f"空间范围出现近似但不相同的名称：{left} / {right}；"
                    "保留两者并交由证据或 HUMAN 确认，不自动归一化。"
                ),
                field_path="location_mentions.scopes",
                source_text_loc=f"{left}|{right}",
            ))
    return diagnostics


def _compile_typed_observation_facts(
    instruction: str,
    *,
    dimension_key: str,
    report_id: str,
) -> list[Any]:
    """Compile the L1 model's semantic observations into stable ``L1Fact`` records.

    ``report_body`` is intentionally not parsed here.  A fact enters the
    planning evidence surface only through the structured observation envelope
    and its source lineage.  This keeps metrics, demands, constraints and
    spatial objects distinct instead of treating every paragraph as a place.
    """

    payload = _instruction_payload(instruction)
    raw_observations = payload.get("observations") or []
    if not isinstance(raw_observations, list):
        return []
    records: list[Any] = []
    for item in raw_observations:
        try:
            raw = observation_to_compiler_payload(item)
        except Exception:
            continue
        if str(raw.get("status") or "").strip() != "confirmed":
            continue
        name = str(raw.get("name") or "").strip()
        entity_type = str(raw.get("entity_type") or "").strip()
        location = str(raw.get("location") or "").strip()
        relation = str(raw.get("relation") or "").strip()
        description = str(raw.get("description") or "").strip()
        kind = str(raw.get("fact_type") or "").strip()
        semantic_type = str(
            raw.get("semantic_type")
            or raw.get("metric")
            or raw.get("demand_type")
            or raw.get("constraint_type")
            or raw.get("subject")
            or _observation_role(entity_type, name, location, description)
            or kind
        ).strip()
        value = raw.get("value")
        if not any((
            name,
            entity_type,
            location,
            relation,
            description,
            semantic_type,
            value is not None,
        )):
            continue
        statement_parts = [value for value in (name, description, location, relation) if value]
        if value is not None:
            value_label = semantic_type or kind
            unit = str(raw.get("unit") or "").strip()
            statement_parts.append(f"{value_label}={value}{unit}")
        statement = "；".join(dict.fromkeys(statement_parts))
        source_refs = list(dict.fromkeys([
            *[
                str(value).strip()
                for value in (raw.get("source_refs") or [])
                if str(value).strip()
            ],
            *[
                str(value).strip()
                for value in (raw.get("source_segment_ids") or [])
                if str(value).strip()
            ],
            str(report_id or "").strip(),
        ]))
        source_span = str(raw.get("source_quote") or "").strip() or statement
        spatial = kind in {"spatial_entity", "spatial_relation"} or bool(
            location
            or relation
            or raw.get("source_feature_ids")
            or raw.get("spatial_mentions")
        )
        fact_kind = "spatial_observation" if spatial else "document_observation"
        attributes = {
            str(key).strip(): str(value).strip()
            for key, value in (raw.get("attributes") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        standard_attributes = {
            "fact_type": kind,
            "entity_type": entity_type,
            "name": name,
            "target_name": str(raw.get("target_name") or "").strip(),
            "metric": str(raw.get("metric") or "").strip(),
            "location": location,
            "relation": relation,
            "description": description,
            "scale": str(raw.get("scale") or "").strip(),
            "spatial_mention_count": str(
                len(raw.get("spatial_mentions") or [])
            ),
            "related_observation_ids": ",".join(
                str(value).strip()
                for value in (raw.get("related_observation_ids") or [])
                if str(value).strip()
            ),
            "constraint_refs": ",".join(
                str(value).strip()
                for value in (raw.get("constraint_refs") or [])
                if str(value).strip()
            ),
        }
        for key, attribute_value in standard_attributes.items():
            if attribute_value and key not in attributes:
                attributes[key] = attribute_value
        record = make_l1_fact(
            statement=statement,
            fact_kind=fact_kind,
            dimension_key=dimension_key,
            subject_scope=(
                str(raw.get("scope") or raw.get("applies_to_scope") or "").strip()
                or name
                or entity_type
                or location
                or semantic_type
                or dimension_key
            ),
            semantic_type=semantic_type,
            attributes=attributes,
            value=value,
            unit=str(raw.get("unit") or "").strip(),
            counting_basis=str(raw.get("counting_basis") or "").strip(),
            source_refs=source_refs,
            source_span=source_span,
            source_feature_ids=(raw.get("source_feature_ids") or []),
        )
        if record is not None:
            records.append(record)
    unique: dict[str, Any] = {}
    for record in records:
        unique.setdefault(record.fact_id, record)
    return list(unique.values())


def _structured_constraints(instruction: str) -> list[str]:
    payload = _instruction_payload(instruction)
    constraints: list[str] = []
    for item in payload.get("observations") or []:
        try:
            raw = observation_to_compiler_payload(item)
        except Exception:
            continue
        if str(raw.get("status") or "") != "confirmed":
            continue
        kind = str(raw.get("fact_type") or "").strip()
        if kind not in {"constraint", "risk"}:
            continue
        text = str(raw.get("description") or raw.get("name") or "").strip()
        if text:
            constraints.append(text)
    return list(dict.fromkeys(constraints))


def compile_l1_observation(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L1Snapshot:
    steps: list[str] = []
    # L1 split projection: ``content`` is the persisted report body (no
    # 【INSTRUCTION】 marker); ``instruction`` is the validated observation JSON
    # and the only location-fact source.
    display = _clean_model_text(content or "")
    instr = instruction or ""

    facts: list[str] = []
    constraints: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    classification_refs: list[ClassificationRef] = []
    spatial_facts: list[str] = []
    location_mentions = _extract_location_mentions_from_observations(
        instr,
        dimension_key=dimension_key,
        report_id=report_id,
    )
    # Location facts cross the PARSE boundary only through the model's
    # structured observations JSON; a malformed L1 response yields zero facts
    # and GROUND never consumes facts the model did not actually produce.
    location_mentions = _dedup_location_mentions_local(location_mentions)
    typed_observation_facts = _compile_typed_observation_facts(
        instr,
        dimension_key=dimension_key,
        report_id=report_id,
    )
    section_locators: list[str] = []

    chapters = _iter_chapters(display)
    steps.append(f"split chapters: {len(chapters)}")

    for title, body in chapters:
        section_locators.append(f"#{title}")
        if "控制线" in title or "管控" in title:
            for b in _BULLET_RE.findall(body):
                constraints.append(b.strip())
            continue
        if "用地结构" in title or "地类" in title:
            for row in _parse_land_use_table(body):
                name = row["name"]
                if not row.get("code"):
                    continue
                if not name or name in ("地类",) or any(x in name for x in ("未分类", "未利用")):
                    continue
                # 现状分类仅为事实：无规划用途/分区推导，无跨体系映射。
                classification_refs.append(
                    ClassificationRef(
                        system="gbt21010",
                        code=row.get("code", ""),
                        canonical_name=name,
                        source="ingested",
                    )
                )
            steps.append(f"parsed land-use rows: {len(classification_refs)}")
            continue
        if "缺失数据" in title or "数据缺口" in title:
            for idx, b in enumerate(_BULLET_RE.findall(body)):
                evidence_gaps.append(
                    EvidenceGap(
                        gap_id=f"{dimension_key}-{idx}",
                        dimension=dimension_key,
                        description=b.strip(),
                        required_fact=b.strip(),
                        severity="warning",
                    )
                )
            continue
        first = _first_sentence(body)
        if first:
            facts.append(f"[{dimension_key}] {title}: {first}")

    marked_facts = []
    for raw_line in display.splitlines():
        line = raw_line.strip()
        if line.startswith("【事实】"):
            value = line[len("【事实】"):].strip()
            if len(value) >= 4:
                marked_facts.append(f"[{dimension_key}] 现状事实: {value[:240]}")
    facts = list(dict.fromkeys([*facts, *marked_facts]))

    spatial_facts = _spatial_facts_from_observations(instr)
    # Typed observations are the only producer of authoritative L1 records.
    # Location facts are a separate mention index for spatial resolution and
    # never synthesize a planning fact when the typed observation is absent.
    fact_records = typed_observation_facts
    structured_constraints = _structured_constraints(instr)
    if structured_constraints:
        constraints = list(dict.fromkeys([*structured_constraints, *constraints]))

    diagnostics = collect_diagnostics(dimension_key, display, instr)
    diagnostics.extend(
        _instruction_diagnostics(
            instr,
            dimension_key=dimension_key,
        )
    )
    diagnostics.extend(
        _scope_conflict_diagnostics(
            location_mentions,
            dimension_key=dimension_key,
        )
    )
    steps.append(f"diagnostics: {len(diagnostics)}")

    provenance = build_fragment_provenance(
        dimension_key,
        report_id,
        run_id,
        section_locators,
        source_module="l1_observe",
    )
    return L1Snapshot(
        context_version="",
        artifact_id="",
        fact_records=fact_records,
        facts=facts,
        facts_by_dimension={dimension_key: list(facts)},
        location_mentions=location_mentions,
        constraints=constraints,
        evidence_gaps=evidence_gaps,
        classification_refs=classification_refs,
        sources=(
            [EvidenceSource(source_type="report", reference=report_id)]
            if report_id
            else []
        ),
        dimension_provenance=[provenance],
        spatial_facts_by_dimension={dimension_key: spatial_facts},
        diagnostics_by_dimension={dimension_key: diagnostics},
        traces_by_dimension={
            dimension_key: CompilerTrace(
                profile=CompilationProfile.L1_OBSERVATION,
                steps=steps,
            )
        },
        provenance=provenance,
    )


__all__ = ["compile_l1_observation"]
