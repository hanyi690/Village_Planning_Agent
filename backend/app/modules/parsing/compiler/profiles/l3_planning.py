"""L3 Planning profile - compile one L3 dimension report into a fragment.

L3 dimension reports are typed project / intent statements, not spatial
geometry. Enforces the roadmap constraint (Wave A.1): 禁止自动推出规划用途/
分区/点位 — the compiled fragment carries interventions, dependencies,
evidence gaps, program issues, and omissions only; it never derives planning
zones, planning uses, or site positions beyond what the report already
states. Delivered in Wave E Task 3.
"""
from __future__ import annotations

import re

from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningIntervention,
    ProgramIssue,
)
from app.modules.schema.contracts.parsing_contracts import CompilationProfile, CompilerTrace

from ..diagnostics import collect_diagnostics
from ..instruction_parser import split_content_instruction
from ..provenance import build_fragment_provenance

_CHAPTER_RE = re.compile(r"^#{1,3}\s+(\S.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)

_LOCATION_HEADER_RE = re.compile(r"(位置|选址|所在位置|方位|位于|布局)")
_NAME_HEADER_RE = re.compile(r"(名称|类型)")

_CATEGORY_MAP = {
    "项目": "project",
    "功能分区": "zone",
    "设施": "facility",
    "轴线": "restoration",
    "道路": "road",
}

_GAP_KEYWORDS = ("缺失", "待定", "需进一步", "尚不明确", "缺乏")
_OMISSION_KEYWORDS = ("未涉及", "未规划", "缺失")
_CONTRADICTION_KEYWORDS = ("冲突", "矛盾", "重叠")
_DEPENDENCY_MARKERS = ("策略逻辑关系", "依赖", "时序", "先后", "前置")
_PROJECT_KEYWORDS = ("项目", "设施", "道路")

# These dimensions feed the spatial grounding chain.  A planning
# intervention may stay coarse (village/zone/direction), but it must carry a
# source-backed spatial reference before it can be handed to PARSE/GROUND.
_SPATIAL_DIMENSIONS = frozenset({
    "industry",
    "traffic",
    "traffic_planning",
    "public_service",
    "infrastructure",
    "infrastructure_planning",
    "ecological",
    "spatial_structure",
    "land_use_planning",
    "settlement_planning",
})


def _iter_chapters(content: str) -> list[tuple[str, str]]:
    """Yield (chapter_title, chapter_body) from markdown content."""
    matches = list(_CHAPTER_RE.finditer(content or ""))
    chapters: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content or "")
        chapters.append((m.group(1).strip(), content[m.end():end]))
    return chapters


def _extract_bullets(section: str) -> list[str]:
    return [b.strip() for b in _BULLET_RE.findall(section)]


def _interventions_from_instruction(
    instr: str,
    dimension_key: str,
) -> list[PlanningIntervention]:
    """P8 INSTRUCTION table -> PlanningIntervention list.

    Header is ``| 类型 | 名称 | 位置 | 描述 | 规模 |`` which does not match
    parse_instruction_tables' classification keys, so we parse raw table
    structures via ``_iter_tables`` directly.
    """
    from app.modules.parsing.tables import _iter_tables

    result: list[PlanningIntervention] = []
    for header, rows in _iter_tables(instr):
        header = [h.strip() for h in header]
        name_idx = next(
            (i for i, h in enumerate(header) if "名称" in h),
            None,
        )
        if name_idx is None:
            continue
        type_idx = next((i for i, h in enumerate(header) if "类型" in h), None)
        loc_idx = next(
            (i for i, h in enumerate(header) if _LOCATION_HEADER_RE.search(h)),
            None,
        )
        desc_idx = next((i for i, h in enumerate(header) if "描述" in h), None)
        scale_idx = next((i for i, h in enumerate(header) if "规模" in h), None)
        for row in rows:
            row = [c.strip() for c in row]
            if name_idx >= len(row):
                continue
            name = row[name_idx]
            if not name or "名称" in name or "合计" in name:
                continue
            type_raw = row[type_idx] if type_idx is not None and type_idx < len(row) else ""
            category = _CATEGORY_MAP.get(type_raw, "project")
            scale = row[scale_idx] if scale_idx is not None and scale_idx < len(row) else ""
            location = row[loc_idx] if loc_idx is not None and loc_idx < len(row) else ""
            description = row[desc_idx] if desc_idx is not None and desc_idx < len(row) else ""
            result.append(
                PlanningIntervention(
                    intervention_id=f"{dimension_key}-int-{len(result)}",
                    name=name,
                    category=category,
                    problem_addressed=description,
                    scale=scale,
                    implementation_phase="short",
                    spatial_requirements={"location": location} if loc_idx is not None else {},
                )
            )
    return result


def _fallback_interventions(display: str, dimension_key: str) -> list[PlanningIntervention]:
    """Bullet fallback when the INSTRUCTION segment has no tables."""
    result: list[PlanningIntervention] = []
    for line in display.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "【", "|")):
            continue
        bullet = line.startswith(("-", "*"))
        keyword_hit = any(k in line for k in _PROJECT_KEYWORDS)
        if not (bullet or keyword_hit):
            continue
        name = line.lstrip("-* ").strip()
        if not name:
            continue
        result.append(
            PlanningIntervention(
                intervention_id=f"{dimension_key}-int-{len(result)}",
                name=name,
                category="project",
                scale="",
                implementation_phase="short",
            )
        )
    return result


def _detect_dependencies(
    display: str,
    interventions: list[PlanningIntervention],
) -> list[InterventionDependency]:
    """Simple dependency detection; empty when unreliable."""
    deps: list[InterventionDependency] = []
    by_name = {iv.name: iv.intervention_id for iv in interventions}
    for line in display.splitlines():
        if not any(m in line for m in _DEPENDENCY_MARKERS):
            continue
        mentioned = [
            iv
            for iv in interventions
            if iv.name and iv.name in line
        ]
        if len(mentioned) >= 2:
            deps.append(
                InterventionDependency(
                    from_intervention_id=mentioned[0].intervention_id,
                    to_intervention_id=mentioned[1].intervention_id,
                    dependency_type="sequence",
                )
            )
    return deps


def compile_l3_planning(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L3ProgramFragment:
    steps: list[str] = []
    display, instr_from_content = split_content_instruction(content or "")
    from app.modules.parsing.compiler.profiles.l1_observation import _clean_model_text
    display = _clean_model_text(display)
    instr = instruction or instr_from_content
    had_marker = "【INSTRUCTION】" in (content or "")

    interventions: list[PlanningIntervention] = []
    dependencies: list[InterventionDependency] = []
    evidence_gaps: list[EvidenceGap] = []
    program_issues: list[ProgramIssue] = []
    omissions: list[str] = []
    section_locators: list[str] = []

    chapters = _iter_chapters(display)
    steps.append(f"split chapters: {len(chapters)}")
    for title, body in chapters:
        section_locators.append(f"#{title}")

    interventions = _interventions_from_instruction(instr, dimension_key)
    if not interventions:
        interventions = _fallback_interventions(display, dimension_key)
    steps.append(f"interventions: {len(interventions)}")

    # The marker is an internal transport contract, not presentation text.
    # Falling back to prose-only project rows silently creates interventions
    # which the spatial compiler cannot ground.  Record that divergence so
    # the L3 gate can stop before PARSE/EXECUTE instead of guessing a site.
    if interventions and not instr.strip():
        program_issues.append(
            ProgramIssue(
                stage="l3",
                severity="error",
                code="missing_instruction_marker",
                message="L3 response omitted the required 【INSTRUCTION】 section",
                detail=(
                    "Planning interventions were recovered from display text, "
                    "but no source-backed spatial instruction table was present."
                ),
            )
        )
    elif interventions and not had_marker:
        program_issues.append(
            ProgramIssue(
                stage="l3",
                severity="warning",
                code="instruction_marker_recovered",
                message="从模型输出中的结构化表格恢复了缺失的【INSTRUCTION】标记",
                detail="仅恢复传输标记，未推断或补写名称、位置、规模或几何。",
            )
        )

    if dimension_key in _SPATIAL_DIMENSIONS:
        unmapped = [iv for iv in interventions if not iv.spatial_requirements]
        if unmapped:
            program_issues.append(
                ProgramIssue(
                    stage="l3",
                    severity="error",
                    code="missing_spatial_instruction",
                    message=(
                        f"{len(unmapped)} 个 {dimension_key} 干预缺少可核验空间引用"
                    ),
                    detail=", ".join(iv.intervention_id for iv in unmapped[:20]),
                )
            )

    dependencies = _detect_dependencies(display, interventions)
    steps.append(f"dependencies: {len(dependencies)}")

    seen_names: set[str] = set()
    for iv in interventions:
        if iv.name in seen_names:
            program_issues.append(
                ProgramIssue(
                    stage="l3",
                    severity="warning",
                    code="program_contradiction",
                    message=f"干预项目名称重复: {iv.name}",
                )
            )
        seen_names.add(iv.name)

    for line in display.splitlines():
        if any(k in line for k in _CONTRADICTION_KEYWORDS):
            program_issues.append(
                ProgramIssue(
                    stage="l3",
                    severity="warning",
                    code="program_contradiction",
                    message=line.strip(),
                )
            )
    steps.append(f"program issues: {len(program_issues)}")

    for idx, line in enumerate(display.splitlines()):
        if any(k in line for k in _GAP_KEYWORDS):
            evidence_gaps.append(
                EvidenceGap(
                    gap_id=f"{dimension_key}-{idx}",
                    dimension=dimension_key,
                    description=line.strip(),
                    severity="warning",
                )
            )
    steps.append(f"evidence gaps: {len(evidence_gaps)}")

    for line in display.splitlines():
        if any(k in line for k in _OMISSION_KEYWORDS):
            omissions.append(line.strip())
    steps.append(f"omissions: {len(omissions)}")

    diagnostics = collect_diagnostics(dimension_key, display, instr)
    steps.append(f"diagnostics: {len(diagnostics)}")

    return L3ProgramFragment(
        dimension_key=dimension_key,
        interventions=interventions,
        dependencies=dependencies,
        evidence_gaps=evidence_gaps,
        program_issues=program_issues,
        omissions=omissions,
        diagnostics=diagnostics,
        provenance=build_fragment_provenance(
            dimension_key,
            report_id,
            run_id,
            section_locators,
            source_module="l3_plan",
        ),
        trace=CompilerTrace(
            profile=CompilationProfile.L3_PLANNING,
            steps=steps,
        ),
    )


__all__ = ["compile_l3_planning"]
