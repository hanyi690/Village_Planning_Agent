"""L1 Observation profile - compile one L1 dimension report into a fragment.

Enforces the roadmap constraint: 现状地类只提供分类代码与名称（ClassificationRef）；
禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间. Uses ONLY same-system
code->name; never imports advisory_crosswalks.
"""
from __future__ import annotations

import re
from typing import Any

from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.l1_contracts import (
    EvidenceGap,
    L1DimensionFragment,
    L1LocationFact,
)
from app.modules.schema.contracts.parsing_contracts import CompilationProfile, CompilerTrace

from ..diagnostics import collect_diagnostics
from ..instruction_parser import parse_instruction_tables, split_content_instruction
from ..provenance import build_fragment_provenance

_CHAPTER_RE = re.compile(r"^#{1,3}\s+(\S.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)


def _extract_location_facts(
    instruction: str,
    *,
    dimension_key: str,
    report_id: str,
) -> list[L1LocationFact]:
    """Extract L1 place facts from the structured ``【INSTRUCTION】`` table.

    The public report prose is intentionally not a location source here.  The
    prompt contract requires the model to repeat only explicit objects and
    locations in this private table, which keeps the PARSE/GROUND boundary
    deterministic and auditable.
    """
    facts: list[L1LocationFact] = []
    seen: set[str] = set()
    tables = parse_instruction_tables(instruction or "")
    for row in tables.get("l1_rows", []):
        name = str(row.get("名称", "") or "").strip()
        location = str(row.get("位置", "") or "").strip()
        kind = str(row.get("类型", "") or "").strip()
        description = str(row.get("描述", "") or "").strip()
        if not name and not location:
            continue
        candidate_text = f"{name} {location} {description}"
        role = "village" if name.endswith("村") or location.endswith("村") else "unknown"
        if "道路" in kind or "道路" in candidate_text or re.search(r"[YX]\d{3}乡道", candidate_text):
            role = "road"
        elif "河" in candidate_text or "水" in kind:
            role = "water"
        elif "分区" in kind:
            role = "area"
        normalized = location or name
        aliases = list(dict.fromkeys(x for x in (name, location) if x))
        key = f"{normalized}|{role}|{dimension_key}|{report_id}"
        if key in seen:
            continue
        seen.add(key)
        facts.append(L1LocationFact(
            mention=name or location,
            normalized_name=normalized,
            role=role,
            aliases=aliases,
            spatial_hint=location or description,
            source_report_ref=report_id,
            dimension_key=dimension_key,
            source_span=" | ".join(x for x in (kind, name, location, description) if x),
            confidence=0.95 if location else 0.8,
        ))
    return facts


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
        rows.append(
            {
                "name": cells[0],
                "area": cells[1] if len(cells) > 1 else "",
                "ratio": cells[2] if len(cells) > 2 else "",
            }
        )
    return rows


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
    display, instr_from_content = split_content_instruction(content or "")
    instr = instruction or instr_from_content

    facts: list[str] = []
    constraints: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    classification_refs: list[ClassificationRef] = []
    spatial_facts: list[str] = []
    location_facts = _extract_location_facts(
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
                if not name or name in ("地类",) or any(x in name for x in ("未分类", "未利用")):
                    continue
                # 现状分类仅为事实：无规划用途/分区推导，无跨体系映射。
                classification_refs.append(
                    ClassificationRef(
                        system="gbt21010",
                        code=name,
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
            facts.append(f"[{dimension_key}] 模型观察: {line[:240]}")
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
                    marked_facts.append(f"[{dimension_key}] 事实: {value[:240]}")
        facts = list(dict.fromkeys([*facts, *marked_facts]))

    tables = parse_instruction_tables(instr)
    for row in tables.get("facility_rows", []):
        loc = row.get("位置", "")
        name = row.get("设施类型", "")
        qty = row.get("数量", "")
        spatial_facts.append(f"设施 {name} {qty} 处，位置 {loc}".strip())

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
