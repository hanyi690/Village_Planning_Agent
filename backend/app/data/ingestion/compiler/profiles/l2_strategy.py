"""L2 Strategy profile - compile one L2 dimension report into a fragment.

L2 dimension reports are POSITIONING / GOALS / STRATEGIES text, not spatial
geometry. Enforces the roadmap constraint (Wave A.1): 禁止自动推出规划用途/
分区/点位 — the compiled fragment carries goals, strategies, priorities,
conflicts, and evidence gaps only; it never derives planning zones, planning
uses, or site positions from the strategy text.
"""
from __future__ import annotations

import re

from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l2_contracts import (
    L2StrategyFragment,
    StrategyConflict,
    StrategyIssue,
)
from app.modules.schema.contracts.parsing_contracts import CompilationProfile, CompilerTrace

from ..diagnostics import collect_diagnostics
from ..instruction_parser import split_content_instruction
from ..provenance import build_fragment_provenance

_CHAPTER_RE = re.compile(r"^#{1,3}\s+(\S.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)

_TARGET_MARKERS = ("【核心指标目标】", "【人口规模预测】", "【用地规模预测】")
_ALL_MARKERS = _TARGET_MARKERS + ("【规划策略】",)

_CONFLICT_KEYWORDS = ("冲突", "矛盾", "不一致", "制约")
_GAP_KEYWORDS = ("缺失", "待定", "需进一步", "尚不明确", "缺乏")
_PRIORITY_KEYWORDS = ("优先", "首先", "重点")


def _iter_chapters(content: str) -> list[tuple[str, str]]:
    """Yield (chapter_title, chapter_body) from markdown content."""
    matches = list(_CHAPTER_RE.finditer(content or ""))
    chapters: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content or "")
        chapters.append((m.group(1).strip(), content[m.end():end]))
    return chapters


def _marker_section(body: str, marker: str) -> str:
    """Return text after ``marker`` up to the next marker or end of body."""
    idx = body.find(marker)
    if idx < 0:
        return ""
    start = idx + len(marker)
    ends = [body.find(m, start) for m in _ALL_MARKERS if body.find(m, start) >= 0]
    end = min(ends) if ends else len(body)
    return body[start:end]


def _extract_bullets(section: str) -> list[str]:
    return [b.strip() for b in _BULLET_RE.findall(section)]


def _extract_content_lines(section: str) -> list[str]:
    """Extract prose rows when the LLM omits Markdown bullet markers."""
    rows: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```", "---", "【")):
            continue
        if len(line) >= 8:
            rows.append(line)
    return rows


def compile_l2_strategy(
    *,
    dimension_key: str,
    content: str,
    instruction: str,
    summary: str = "",
    report_id: str = "",
    run_id: str = "",
) -> L2StrategyFragment:
    steps: list[str] = []
    display, instr_from_content = split_content_instruction(content or "")
    instr = instruction or instr_from_content

    goals: list[str] = []
    strategies: list[str] = []
    priorities: list[str] = []
    conflicts: list[StrategyConflict] = []
    evidence_gaps: list[EvidenceGap] = []
    strategy_issues: list[StrategyIssue] = []
    spatial_structure = ""
    section_locators: list[str] = []

    chapters = _iter_chapters(display)
    steps.append(f"split chapters: {len(chapters)}")

    for title, body in chapters:
        section_locators.append(f"#{title}")

    if dimension_key == "planning_strategies":
        for marker in _TARGET_MARKERS:
            if marker in display:
                section_locators.append(marker)
                goals.extend(_extract_bullets(_marker_section(display, marker)))
        if "【规划策略】" in display:
            section_locators.append("【规划策略】")
            strategies = _extract_bullets(_marker_section(display, "【规划策略】"))
            if not strategies:
                strategies = _extract_content_lines(_marker_section(display, "【规划策略】"))
        priorities = [s for s in strategies if any(m in s for m in _PRIORITY_KEYWORDS)]
        steps.append(f"markers: goals={len(goals)} strategies={len(strategies)}")

    if dimension_key == "development_goals":
        for title, body in chapters:
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "总体目标" in line:
                    goals.append(line)
                    section_locators.append(f"goal:{line[:20]}")
        steps.append(f"development goals: {len(goals)}")
        if not goals:
            for line in display.splitlines():
                line = line.strip()
                if "总体目标" in line and len(line) >= 8:
                    goals.append(line)
                    section_locators.append(f"goal:{line[:20]}")
                    break

    if dimension_key == "planning_positioning":
        for title, body in chapters:
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("村庄分类："):
                    spatial_structure = line.split("：", 1)[1].strip()
                    section_locators.append("村庄分类")
                    break
            if spatial_structure:
                break
        if not spatial_structure:
            for line in display.splitlines():
                line = line.strip()
                if line.startswith("村庄分类") and "：" in line:
                    spatial_structure = line.split("：", 1)[1].strip()
                    section_locators.append("村庄分类")
                    break
        if not spatial_structure:
            for title, body in chapters:
                for line in body.splitlines():
                    line = line.strip()
                    if line and not line.startswith(("【", "#")):
                        spatial_structure = line
                        section_locators.append(f"positioning:{line[:20]}")
                        break
                if spatial_structure:
                    break
        steps.append("spatial structure from planning positioning (text only, no geometry)")

    for line in display.splitlines():
        if any(k in line for k in _CONFLICT_KEYWORDS):
            conflicts.append(
                StrategyConflict(
                    description=line.strip(),
                    between=[dimension_key],
                    severity="warning",
                )
            )

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

    has_development = any(("开发" in s or "建设" in s) for s in strategies)
    has_eco = any(("生态" in s or "保护" in s) for s in strategies)
    has_constraint_target = any("约束性" in g for g in goals)
    if has_development and has_eco and has_constraint_target:
        strategy_issues.append(
            StrategyIssue(
                stage="l2",
                severity="warning",
                code="strategy_contradiction",
                message="开发/建设策略与生态/保护策略并存且存在约束性目标，需复核策略一致性。",
            )
        )

    diagnostics = collect_diagnostics(dimension_key, display, instr)
    steps.append(f"diagnostics: {len(diagnostics)}")

    return L2StrategyFragment(
        dimension_key=dimension_key,
        goals=goals,
        strategies=strategies,
        priorities=priorities,
        conflicts=conflicts,
        evidence_gaps=evidence_gaps,
        strategy_issues=strategy_issues,
        spatial_structure=spatial_structure,
        diagnostics=diagnostics,
        provenance=build_fragment_provenance(
            dimension_key,
            report_id,
            run_id,
            section_locators,
            source_module="l2_strategize",
        ),
        trace=CompilerTrace(
            profile=CompilationProfile.L2_STRATEGY,
            steps=steps,
        ),
    )


__all__ = ["compile_l2_strategy"]
