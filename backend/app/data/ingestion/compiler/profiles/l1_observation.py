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
from app.domain.assessment.l1_fact_projection import (
    location_fact_to_l1_fact,
    make_l1_fact,
)

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
    """Compile dual-response observations JSON into typed L1LocationFacts.

    The structured observations JSON is the single location-fact source since
    the dual-response migration; invalid/empty JSON yields zero facts (never a
    markdown-table fallback).
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
        if isinstance(item, dict):
            obs = item
        elif hasattr(item, "model_dump"):
            obs = item.model_dump(mode="json")
        else:
            continue
        name = str(obs.get("name") or "").strip()
        location = str(obs.get("location") or "").strip()
        relation = str(obs.get("relation") or "").strip()
        entity_type = str(obs.get("entity_type") or "").strip()
        description = str(obs.get("description") or "").strip()
        if not name and not location:
            continue
        role = _observation_role(entity_type, name, location, description)
        source_span = " | ".join(
            x for x in (entity_type, name, location, relation, description) if x
        )
        # 主事实 = 观察对象的 name（L1 已产出干净地名；编译器信任 name）。
        parts_to_emit: list[tuple[str, str, str]] = []
        if name:
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
                confidence=0.95 if normalized in location_parts else 0.8,
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
        if not isinstance(item, dict):
            continue
        entity_type = str(item.get("entity_type") or "").strip()
        name = str(item.get("name") or "").strip()
        location = str(item.get("location") or "").strip()
        if "设施" in entity_type and name:
            out.append(f"设施 {name}，位置 {location}".strip())
    return out


def _build_fact_records(
    *,
    dimension_key: str,
    report_id: str,
    facts: list[str],
    location_facts: list[L1LocationFact],
    constraints: list[str],
    classification_refs: list[ClassificationRef],
) -> list[Any]:
    """Create the authoritative typed L1 record set for one report."""
    if not report_id:
        # An unidentifiable report may still produce a display snapshot, but
        # its claims cannot become authoritative evidence records.
        return []
    # L1Fact is the spatial-evidence boundary.  Report prose, constraints and
    # current land-use classifications remain in their report/display fields;
    # they are not promoted into a generic machine fact that later grounding
    # could mistake for a place identity.
    records: list[Any] = []
    for fact in location_facts:
        record = location_fact_to_l1_fact(fact)
        if record is not None:
            records.append(record)
    seen: set[str] = set()
    unique_records: list[Any] = []
    for record in records:
        if record.fact_id in seen:
            continue
        seen.add(record.fact_id)
        unique_records.append(record)
    return unique_records


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
    # L1 dual-response: ``content`` is the report body (no 【INSTRUCTION】
    # marker); ``instruction`` is the structured observations JSON - the only
    # location-fact source.  No markdown-table fallback is kept.
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
    fact_records = _build_fact_records(
        dimension_key=dimension_key,
        report_id=report_id,
        facts=facts,
        location_facts=location_facts,
        constraints=constraints,
        classification_refs=classification_refs,
    )

    diagnostics = collect_diagnostics(dimension_key, display, instr)
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
