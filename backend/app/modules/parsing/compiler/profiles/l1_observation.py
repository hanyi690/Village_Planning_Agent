"""L1 Observation profile - compile one L1 dimension report into a fragment.

Enforces the roadmap constraint: 现状地类只提供分类代码与名称（ClassificationRef）；
禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间. Uses ONLY same-system
code->name; never imports advisory_crosswalks.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
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
_VILLAGE_LIST_RE = re.compile(
    r"(?:下辖|下属|包括|分别为|分别是)[^。\n]{0,80}?([\u4e00-\u9fff、,，]{2,120})(?:。|其中|$)"
)
_VILLAGE_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,8}(?:自然村|村)")


class _ReportTableParser(HTMLParser):
    """Small dependency-free HTML table reader for uploaded markdown reports."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _iter_html_tables(content: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return header/data rows from HTML tables without interpreting domains."""
    result: list[tuple[list[str], list[list[str]]]] = []
    for block in re.findall(r"<table\b[^>]*>.*?</table>", content or "", flags=re.I | re.S):
        parser = _ReportTableParser()
        parser.feed(block)
        if len(parser.rows) < 2:
            continue
        header = parser.rows[0]
        rows = [row for row in parser.rows[1:] if any(cell.strip() for cell in row)]
        if header and rows:
            result.append((header, rows))
    return result


_DIMENSION_TABLE_TERMS: dict[str, tuple[str, ...]] = {
    "traffic": ("道路", "停车", "公交", "路灯", "交通"),
    "infrastructure": ("供水", "变压器", "水电站", "污水", "燃气", "机耕", "污水管", "供水设施", "道路硬化"),
    "public_services": ("学校", "文化", "广场", "篮球", "养老", "厕所", "服务中心", "卫生", "市场"),
    "public_service": ("学校", "文化", "广场", "篮球", "养老", "厕所", "服务中心", "卫生", "市场"),
    "ecological_green": ("生态", "河道", "绿化", "古树", "护栏", "水边"),
    "historical_culture": ("古驿道", "祠堂", "历史", "文化"),
    "land_use": ("农田", "复垦", "水田", "用地", "生态修复"),
}


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
        from app.modules.parsing.natural_villages import _KNOWN_NATURAL_VILLAGES
        return tuple(sorted((str(x).removesuffix("村") for x in _KNOWN_NATURAL_VILLAGES), key=len, reverse=True))
    except Exception:
        return ()


def _extract_places_from_cell(value: str) -> list[str]:
    """Extract only named places from a table cell; discard service prose."""
    known = _known_village_names()
    if known:
        found: list[str] = []
        for name in known:
            if name and name in (value or "") and name not in found:
                found.append(name)
        if found:
            return found
    return [
        part for part in _split_explicit_places(value)
        if part not in {"服务本村", "服务全村", "覆盖全村", "本村", "全村"}
        and not any(token in part for token in ("经过", "路段", "服务", "覆盖"))
    ]


def _extract_report_location_facts(
    display: str,
    *,
    dimension_key: str,
    report_id: str,
) -> list[L1LocationFact]:
    """Extract explicit source-report places when the LLM omitted INSTRUCTION.

    This is not a guessed GIS binding: it only records names and the exact
    source span.  Geometry remains the responsibility of GROUND/gazetteer.
    """
    facts: list[L1LocationFact] = []
    seen: set[tuple[str, str]] = set()

    # The socioeconomic report is the authoritative source for the village
    # list.  Keep this extraction dimension-scoped instead of copying it into
    # every L1 dimension.
    if dimension_key in {"location", "socio_economic", "architecture"}:
        for match in _VILLAGE_LIST_RE.finditer(display or ""):
            sentence = match.group(0)
            known = _known_village_names()
            names = [name for name in known if name and name in sentence]
            # The report writes bare names in the list; do not treat arbitrary
            # two-character words in an administrative sentence as places.
            for name in names:
                name = name.removesuffix("自然村").removesuffix("村").strip()
                if not name or name in {"分别为", "分别是"}:
                    continue
                key = (name, "village")
                if key in seen:
                    continue
                seen.add(key)
                facts.append(L1LocationFact(
                    mention=name,
                    normalized_name=name,
                    role="village",
                    aliases=[name, f"{name}村"],
                    spatial_hint=name,
                    source_report_ref=report_id,
                    dimension_key=dimension_key,
                    source_span=sentence[:300],
                    confidence=1.0,
                ))

    terms = _DIMENSION_TABLE_TERMS.get(dimension_key, ())
    for header, rows in _iter_html_tables(display):
        name_idx = next((i for i, h in enumerate(header) if "设施名称" in h or "项目名称" in h), None)
        location_idx = next((i for i, h in enumerate(header) if "空间位置" in h or "所在位置" in h or h == "位置"), None)
        if name_idx is None or location_idx is None:
            continue
        for row in rows:
            if name_idx >= len(row) or location_idx >= len(row):
                continue
            name = row[name_idx].strip()
            location = row[location_idx].strip()
            if not name or not location or name in {"设施名称", "项目名称"}:
                continue
            row_text = " | ".join(row)
            if terms and not any(term in row_text for term in terms):
                continue
            for place in _extract_places_from_cell(location):
                role = "village" if place.endswith("村") or len(place) <= 4 else "unknown"
                key = (place, role)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(L1LocationFact(
                    mention=place,
                    normalized_name=place,
                    role=role,
                    aliases=[place],
                    spatial_hint=place,
                    source_report_ref=report_id,
                    dimension_key=dimension_key,
                    source_span=row_text[:400],
                    confidence=0.95,
                ))
    return facts


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
        role = "village" if name.endswith("村") else "unknown"
        if "道路" in kind or "道路" in candidate_text or re.search(r"[YX]\d{3}乡道", candidate_text):
            role = "road"
        elif "河" in candidate_text or "水" in kind:
            role = "water"
        elif "分区" in kind:
            role = "area"
        elif "设施" in kind or "设施" in candidate_text or "点" in kind:
            role = "facility"
        location_parts = _split_explicit_places(location) if location else []
        if not location_parts:
            location_parts = [location] if location else [""]
        source_span = " | ".join(x for x in (kind, name, location, description) if x)
        parts_to_emit: list[tuple[str, str, str]] = []
        # Preserve the named object itself (facility/road/water/area) and its
        # explicit location as separate typed facts.  Previously the location
        # value replaced the object name, so facilities disappeared before KG.
        if name and role != "village":
            parts_to_emit.append((name, role, name))
        for location_part in location_parts:
            part_role = "village" if location_part.endswith(("村", "自然村")) or location_part in _known_village_names() else role
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
    # Keep the original report for source-span extraction, but never promote
    # model reasoning/protocol chatter into the human fact inventory.
    source_display = display
    display = _clean_model_text(display)
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
    # The uploaded report is raw input, not an L1 intermediate artifact.  It
    # may be retained as an audit/source reference, but it must never be
    # promoted directly into ``location_facts``.  Location facts cross the
    # PARSE boundary only through the model's structured INSTRUCTION table;
    # otherwise a malformed L1 response would appear valid and GROUND would
    # consume facts the model never actually produced.
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
