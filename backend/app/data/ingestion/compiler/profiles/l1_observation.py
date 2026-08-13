"""L1 Observation profile - compile one L1 dimension report into a fragment.

Enforces the roadmap constraint: 现状地类只提供分类代码与名称（ClassificationRef）；
禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间. Uses ONLY same-system
code->name; never imports advisory_crosswalks.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.domain.l1_contracts import (
    EvidenceGap,
    L1DimensionFragment,
    L1LocationFact,
)
from app.contracts.workflow.parsing_contracts import CompilationProfile, CompilerTrace

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


def _known_village_names() -> tuple[str, ...]:
    try:
        from app.data.ingestion.natural_villages import _KNOWN_NATURAL_VILLAGES
        return tuple(sorted((str(x).removesuffix("村") for x in _KNOWN_NATURAL_VILLAGES), key=len, reverse=True))
    except Exception:
        return ()


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
        entity_type = str(obs.get("entity_type") or "").strip()
        description = str(obs.get("description") or "").strip()
        if not name and not location:
            continue
        role = _observation_role(entity_type, name, location, description)
        source_span = " | ".join(x for x in (entity_type, name, location, description) if x)
        parts_to_emit: list[tuple[str, str, str]] = []
        if name and role != "village":
            parts_to_emit.append((name, role, name))
        location_parts = _split_explicit_places(location) if location else []
        if not location_parts:
            location_parts = [location] if location else [""]
        for location_part in location_parts:
            part_role = (
                "village"
                if location_part.endswith(("村", "自然村"))
                or location_part in _known_village_names()
                else role
            )
            parts_to_emit.append((location_part or name, part_role, location_part or description))
        for normalized, part_role, spatial_hint in parts_to_emit:
            aliases = list(dict.fromkeys(x for x in (name, normalized) if x))
            key = f"{normalized}|{part_role}|{dimension_key}|{report_id}"
            if key in seen:
                continue
            seen.add(key)
            facts.append(L1LocationFact(
                mention=name or location_part,
                normalized_name=normalized,
                role=part_role,
                aliases=aliases,
                spatial_hint=spatial_hint,
                source_report_ref=report_id,
                dimension_key=dimension_key,
                source_span=source_span,
                confidence=0.95 if location_part else 0.8,
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


def compile_l1_observation(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L1DimensionFragment:
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

    # Remote LLMs are not required to emit Markdown headings.  The previous
    # compiler silently returned zero facts for valid prose, which made the
    # L1 artifact look empty even though the model had observed the village.
    # Preserve a bounded, human-readable paragraph fallback while keeping the
    # KG promotion in l1_aggregate as the authoritative GIS fact source.
    if not facts and display.strip():
        for raw_line in display.splitlines():
            line = re.sub(r"^\s*[-*\d.)]+\s*", "", raw_line).strip()
            if not line or line.startswith(("#", "|", "```", "【", "---")):
                continue
            if len(line) < 12:
                continue
            facts.append(f"[{dimension_key}] 现状事实: {line[:240]}")
            if len(facts) >= 12:
                break
        steps.append(f"fallback prose facts: {len(facts)}")
    else:
        marked_facts = []
        for raw_line in display.splitlines():
            line = raw_line.strip()
            if line.startswith("【事实】"):
                value = line[len("【事实】"):].strip()
                if len(value) >= 4:
                    marked_facts.append(f"[{dimension_key}] 现状事实: {value[:240]}")
        facts = list(dict.fromkeys([*facts, *marked_facts]))

    spatial_facts = _spatial_facts_from_observations(instr)

    diagnostics = collect_diagnostics(dimension_key, display, instr)
    steps.append(f"diagnostics: {len(diagnostics)}")

    return L1DimensionFragment(
        dimension_key=dimension_key,
        facts=facts,
        constraints=constraints,
        issues=[],
        opportunities=[],
        evidence_gaps=evidence_gaps,
        classification_refs=classification_refs,
        spatial_facts=spatial_facts,
        location_facts=location_facts,
        diagnostics=diagnostics,
        provenance=build_fragment_provenance(
            dimension_key,
            report_id,
            run_id,
            section_locators,
            source_module="l1_observe",
        ),
        trace=CompilerTrace(
            profile=CompilationProfile.L1_OBSERVATION,
            steps=steps,
        ),
    )


__all__ = ["compile_l1_observation"]
