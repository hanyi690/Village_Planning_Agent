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
    L1LocationFact,
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


def _dedup_location_facts_local(facts: list[L1LocationFact]) -> list[L1LocationFact]:
    result: list[L1LocationFact] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        key = (
            fact.normalized_name.strip(),
            fact.role.strip(),
            fact.dimension_key.strip(),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(fact)
    return result


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
    "自然村": "village",
    "村庄": "village",
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
    if name.endswith("村"):
        return "village"
    return "unknown"


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


def _extract_location_facts_from_observations(
    instruction: str,
    *,
    dimension_key: str,
    report_id: str,
) -> list[L1LocationFact]:
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
    facts: list[L1LocationFact] = []
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
        if str(obs.get("status") or "confirmed").strip() != "confirmed":
            continue
        spatial_observation = kind in {"spatial_entity", "spatial_relation"} or bool(
            location or relation or obs.get("source_feature_ids")
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
        if not name and not location:
            continue
        role = _observation_role(entity_type, name, location, description)
        source_span = source_quote or " | ".join(
            x for x in (entity_type, name, location, relation, description) if x
        )
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
            part_role = (
                "village"
                if location_part.endswith(("村", "自然村"))
                else role
            )
            parts_to_emit.append((location_part, part_role, location_part))
        for normalized, part_role, spatial_hint in parts_to_emit:
            aliases = list(dict.fromkeys(x for x in (name, normalized) if x))
            key = f"{normalized}|{part_role}|{dimension_key}|{report_id}"
            if key in seen:
                continue
            seen.add(key)
            facts.append(L1LocationFact(
                mention=name or normalized,
                normalized_name=normalized,
                role=part_role,
                aliases=aliases,
                spatial_hint=spatial_hint,
                source_report_ref=report_id,
                dimension_key=dimension_key,
                source_span=source_span,
                evidence_refs=evidence_refs,
                confidence=(
                    float(obs.get("confidence"))
                    if isinstance(obs.get("confidence"), (int, float))
                    else (0.95 if normalized in location_parts else 0.8)
                ),
            ))
    return facts


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
        if str(raw.get("status") or "confirmed").strip() != "confirmed":
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
            location or relation or raw.get("source_feature_ids")
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
            "metric": str(raw.get("metric") or "").strip(),
            "location": location,
            "relation": relation,
            "description": description,
            "scale": str(raw.get("scale") or "").strip(),
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
        if str(raw.get("status") or "confirmed") != "confirmed":
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
    location_facts = _extract_location_facts_from_observations(
        instr,
        dimension_key=dimension_key,
        report_id=report_id,
    )
    # Location facts cross the PARSE boundary only through the model's
    # structured observations JSON; a malformed L1 response yields zero facts
    # and GROUND never consumes facts the model did not actually produce.
    location_facts = _dedup_location_facts_local(location_facts)
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
        location_facts=location_facts,
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
