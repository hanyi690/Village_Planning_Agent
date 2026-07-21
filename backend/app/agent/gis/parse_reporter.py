"""PARSE Agent result reporter — generate human-friendly Markdown reports.

Output: output/parse_results/{village_name}_{date}.md

Report sections:
  1. Spatial Context Summary (land-use table, village anchors, spatial relations)
  2. Operation Sequence Table (action / land-use / area / anchor status / source)
  3. Constraint Set Table (type / priority / computable rule / article ref)
  4. Planning Intent (zone targets + area ratios / facilities / development axes)
  5. Validation Result (pass/fail + error list)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

OUTPUT_DIR = Path("output/parse_results")


# ── Main entry point ────────────────────────────────────────────────


def generate_parse_report(
    village_name: str,
    spatial_context: Any,
    operation_sequence: List[Dict[str, Any]],
    constraint_set: List[Dict[str, Any]],
    planning_intent: Dict[str, Any],
    validation_errors: List[str] = None,
    is_valid: bool = False,
    section_map: List[Any] = None,
    output_dir: Path = None,
    timing_info: Dict[str, Any] = None,
) -> Path:
    """Generate a Markdown report from PARSE Agent results.

    Args:
        village_name: Village name (used in filename)
        spatial_context: SpatialContext model or dict
        operation_sequence: List of SpatialOperation dicts
        constraint_set: List of SpatialConstraint dicts
        planning_intent: SpatialPlanningIntent dict
        validation_errors: List of validation error strings
        is_valid: Whether validation passed
        section_map: List of SectionInfo for document structure
        output_dir: Override output directory
        timing_info: Dict with timing metadata (total_seconds, model, etc.)

    Returns:
        Path to the generated Markdown file.
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{village_name}_{date_str}.md"
    filepath = output_dir / filename

    # Normalize spatial_context to dict
    if hasattr(spatial_context, "model_dump"):
        ctx = spatial_context.model_dump()
    elif isinstance(spatial_context, dict):
        ctx = spatial_context
    else:
        ctx = {}

    # Build report
    lines = []
    lines.append(f"# {village_name} PARSE Agent 解析报告")
    lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 校验状态: {'✅ 通过' if is_valid else '❌ 未通过'}")

    # Timing info
    if timing_info:
        total_s = timing_info.get("total_seconds", 0)
        model = timing_info.get("model", "unknown")
        method = timing_info.get("structured_output_method", "unknown")
        lines.append(f"> 执行耗时: {total_s:.1f}s | 模型: {model} | 结构化输出: {method}")

    # Section 1: Spatial Context
    lines.append("\n---\n")
    lines.append("## 1. 空间上下文摘要\n")
    lines.append(_format_spatial_context(ctx))

    # Section 2: Document Sections
    if section_map:
        lines.append("\n---\n")
        lines.append("## 2. 文档分段\n")
        lines.append(_format_section_map(section_map))

    # Section 3: Operation Sequence
    lines.append("\n---\n")
    lines.append("## 3. 操作序列\n")
    lines.append(_format_operation_sequence(operation_sequence))

    # Section 4: Constraint Set
    lines.append("\n---\n")
    lines.append("## 4. 约束集\n")
    lines.append(_format_constraint_set(constraint_set))

    # Section 5: Planning Intent
    lines.append("\n---\n")
    lines.append("## 5. 规划意图\n")
    lines.append(_format_planning_intent(planning_intent))

    # Section 6: Validation
    lines.append("\n---\n")
    lines.append("## 6. 校验结果\n")
    lines.append(_format_validation(validation_errors or [], is_valid))

    # Section 7: Encoding Validation (NEW)
    lines.append("\n---\n")
    lines.append("## 7. 编码验证\n")
    lines.append(_format_encoding_validation(operation_sequence, planning_intent))

    # Write file
    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    logger.info("[PARSE Report] Generated: %s", filepath)

    return filepath


# ── Section formatters ────────────────────────────────────────────────


def _format_spatial_context(ctx: Dict[str, Any]) -> str:
    """Format spatial context summary."""
    lines = []

    # Base stats
    lines.append("### 基础统计\n")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 地块总数 | {ctx.get('parcel_count', 0)} |")
    lines.append(f"| 总面积 | {ctx.get('total_area_ha', 0):.1f} ha |")
    lines.append(f"| 建设边界面积 | {ctx.get('construction_boundary_ha', 0):.1f} ha |")
    center = ctx.get("village_center")
    lines.append(f"| 村中心坐标 | {f'({center[0]:.6f}, {center[1]:.6f})' if center else '未计算'} |")

    # Land-use distribution
    dist = ctx.get("landuse_distribution", [])
    if dist:
        lines.append("\n### 地类分布\n")
        lines.append("| 地类 | 编码 | 地块数 | 面积(ha) | 规划分区 |")
        lines.append("|------|------|--------|----------|----------|")
        for e in dist:
            lines.append(
                f"| {e.get('name', '')} | {e.get('dlbm', '')} | "
                f"{e.get('count', 0)} | {e.get('area_ha', 0):.1f} | "
                f"{e.get('planning_zone', '')} |"
            )

    # Natural village anchors
    villages = ctx.get("natural_villages", [])
    if villages:
        lines.append("\n### 自然村落锚点\n")
        lines.append("| 村落 | 中心坐标 | 地块数 | 主地类编码 | 邻接 |")
        lines.append("|------|----------|--------|------------|------|")
        for v in villages:
            center = v.get("center", [0, 0])
            center_str = f"({center[0]:.4f}, {center[1]:.4f})" if center else "-"
            adj = ", ".join(v.get("adjacent_to", []))
            lines.append(
                f"| {v.get('name', '')} | {center_str} | "
                f"{len(v.get('parcel_ids', []))} | {v.get('dominant_landuse', '')} | {adj} |"
            )

    # Spatial relations
    relations = ctx.get("spatial_relations", [])
    if relations:
        lines.append(f"\n### 空间关系 ({len(relations)} 条)\n")
        # Show first 20
        for r in relations[:20]:
            lines.append(
                f"- **{r.get('subject', '')}** → _{r.get('relation', '')}_ → **{r.get('object', '')}** "
                f"(置信度={r.get('confidence', 0):.1f}, 来源={r.get('source', '')})"
            )
        if len(relations) > 20:
            lines.append(f"- ...还有 {len(relations) - 20} 条关系")

    # Constraint summary
    constraints = ctx.get("constraint_summary", [])
    if constraints:
        lines.append("\n### 保护约束概要\n")
        lines.append("| 约束类型 | 规则 | 面积(ha) | 重叠 |")
        lines.append("|----------|------|----------|------|")
        for c in constraints:
            overlaps = ", ".join(c.get("overlaps_with", []))
            lines.append(
                f"| {c.get('zone_type', '')} | {c.get('rule', '')} | "
                f"{c.get('area_ha', 0):.1f} | {overlaps} |"
            )

    # Zone adjacency
    adj = ctx.get("zone_adjacency", {})
    if adj:
        lines.append("\n### 分区邻接矩阵\n")
        for zone, neighbors in adj.items():
            lines.append(f"- **{zone}**: 邻接 {', '.join(neighbors)}")

    return "\n".join(lines)


def _format_section_map(section_map: List[Any]) -> str:
    """Format document section classification."""
    lines = []
    lines.append("| 段落ID | 类型 | 标题 | 含表格 |")
    lines.append("|--------|------|------|--------|")
    for s in section_map:
        if isinstance(s, dict):
            sid = s.get("section_id", "")
            stype = s.get("section_type", "")
            title = s.get("title", "")
            has_table = "✅" if s.get("has_table") else ""
        else:
            sid = s.section_id
            stype = s.section_type
            title = s.title
            has_table = "✅" if s.has_table else ""
        lines.append(f"| {sid} | {stype} | {title} | {has_table} |")
    return "\n".join(lines)


def _format_operation_sequence(ops: List[Dict[str, Any]]) -> str:
    """Format operation sequence as table + details."""
    if not ops:
        return "_（未提取到操作）_"

    lines = []
    lines.append(f"共 **{len(ops)}** 条操作\n")

    for i, op in enumerate(ops):
        action = op.get("action", "?")
        land_use = op.get("land_use_name", "")
        area = op.get("area_sqm")
        source = op.get("source_text", "")
        confidence = op.get("confidence", 1.0)
        needs_confirm = "🔒" if op.get("needs_confirmation", True) else ""
        article = op.get("article_ref", "")

        lines.append(f"#### {i+1}. [{action.upper()}]{needs_confirm}")
        if land_use:
            lines.append(f"- **用途**: {land_use}")
        if area:
            lines.append(f"- **面积**: {area} ㎡")
        lines.append(f"- **置信度**: {confidence:.1f}")
        if article:
            lines.append(f"- **条文引用**: {article}")
        lines.append(f"- **来源文本**: > {source[:200]}{'...' if len(source) > 200 else ''}")

        # Spatial anchor
        anchor = op.get("spatial_anchor")
        if anchor:
            ref = anchor.get("reference", "")
            offset = anchor.get("offset", "")
            sec_ref = anchor.get("secondary_ref", "")
            sec_offset = anchor.get("secondary_offset", "")
            candidates = anchor.get("candidate_parcels", [])
            status = anchor.get("resolution_status", "")
            anchor_conf = anchor.get("confidence", 0)

            status_emoji = {"anchored": "🟢", "partial": "🟡", "unresolved": "🔴"}.get(status, "⚪")

            lines.append(f"- **空间锚定**: {status_emoji} {status}")
            lines.append(f"  - 参照: {ref} {offset}")
            if sec_ref:
                lines.append(f"  - 次参照: {sec_ref} {sec_offset}")
            if candidates:
                lines.append(f"  - 候选图斑: {', '.join(str(c) for c in candidates[:5])}")
            lines.append(f"  - 锚定置信度: {anchor_conf:.1f}")
        else:
            loc = op.get("location_desc", "")
            if loc:
                lines.append(f"- **位置描述**: {loc}")

        lines.append("")

    return "\n".join(lines)


def _format_constraint_set(constraints: List[Dict[str, Any]]) -> str:
    """Format constraint set as table + details."""
    if not constraints:
        return "_（未提取到约束）_"

    lines = []
    lines.append(f"共 **{len(constraints)}** 条约束\n")

    # Summary table
    lines.append("| # | 类型 | 优先级 | 来源条文 | 可计算规则 |")
    lines.append("|---|------|--------|----------|------------|")
    for i, c in enumerate(constraints):
        ctype = c.get("type", "?")
        priority = c.get("priority", "mandatory")
        article = c.get("article_ref", "")
        rule = c.get("spatial_rule")
        rule_str = ""
        if rule:
            op = rule.get("operation", "")
            subj = rule.get("subject", "")
            obj = rule.get("object", "")
            dist = rule.get("distance_m")
            dist_str = f", {dist}m" if dist else ""
            rule_str = f"{op}({subj}, {obj}{dist_str})"
        lines.append(f"| {i+1} | {ctype} | {priority} | {article} | {rule_str} |")

    # Detailed list
    lines.append("\n### 详细约束\n")
    for i, c in enumerate(constraints):
        ctype = c.get("type", "?")
        priority = c.get("priority", "mandatory")
        source = c.get("source_text", "")
        article = c.get("article_ref", "")

        lines.append(f"#### {i+1}. [{ctype}] 优先级={priority}")
        if source:
            lines.append(f"- **来源文本**: > {source[:200]}{'...' if len(source) > 200 else ''}")
        if article:
            lines.append(f"- **条文引用**: {article}")

        # Type-specific fields
        land_use = c.get("land_use")
        target_area = c.get("target_area_ha")
        operator = c.get("operator")
        if land_use and target_area:
            lines.append(f"- **面积约束**: {land_use} {operator or ''} {target_area} ha")

        rule = c.get("spatial_rule")
        if rule:
            op = rule.get("operation", "")
            subj = rule.get("subject", "")
            obj = rule.get("object", "")
            dist = rule.get("distance_m")
            dist_str = f", {dist}m" if dist else ""
            lines.append(f"- **空间规则**: `{op}({subj}, {obj}{dist_str})`")

        # Building constraints
        for field in ["max_area_sqm", "max_height_m", "max_floors", "setback_m"]:
            val = c.get(field)
            if val is not None:
                lines.append(f"- **{field}**: {val}")

        lines.append("")

    return "\n".join(lines)


def _format_planning_intent(intent: Dict[str, Any]) -> str:
    """Format planning intent."""
    if not intent:
        return "_（未提取到规划意图）_"

    lines = []

    # Zone targets
    zone_targets = intent.get("zone_targets", [])
    if zone_targets:
        lines.append("### 分区目标\n")
        lines.append("| 用途 | 编码 | 面积比例 | 密度 | 空间偏好 | 邻接偏好 | 邻接规避 |")
        lines.append("|------|------|----------|------|----------|----------|----------|")
        total_ratio = 0
        for zt in zone_targets:
            lu = zt.get("land_use", "")
            dlbm = zt.get("dlbm", "")
            ratio = zt.get("area_ratio", 0)
            total_ratio += ratio
            density = zt.get("density", "")
            pref = zt.get("spatial_preference", {})
            pref_str = f"{pref.get('direction', '')} (ref={pref.get('reference', '')})" if pref else ""
            adj = zt.get("adjacency_rules", {})
            prefer = ", ".join(adj.get("prefer", []))
            avoid = ", ".join(adj.get("avoid", []))
            lines.append(f"| {lu} | {dlbm} | {ratio:.1%} | {density} | {pref_str} | {prefer} | {avoid} |")
        lines.append(f"\n> 面积比例总和: **{total_ratio:.1%}** (目标: 100% ±5%)")

    # Facilities
    facilities = intent.get("facilities", [])
    if facilities:
        lines.append("\n### 设施需求\n")
        lines.append("| 类型 | 状态 | 位置提示 | 服务半径 | 锚定村落 |")
        lines.append("|------|------|----------|----------|----------|")
        for ft in facilities:
            ftype = ft.get("type", "")
            status = ft.get("status", "")
            hint = ft.get("location_hint", "")
            radius = ft.get("service_radius", "")
            anchor = ft.get("anchor_village", "")
            lines.append(f"| {ftype} | {status} | {hint} | {radius} | {anchor} |")

    # Development axes
    axes = intent.get("development_axes", [])
    if axes:
        lines.append("\n### 发展轴\n")
        lines.append("| 方向 | 参照特征 | 连接 |")
        lines.append("|------|----------|------|")
        for at in axes:
            direction = at.get("direction", "")
            ref = at.get("reference_feature", "")
            connects = ", ".join(at.get("connects", []))
            lines.append(f"| {direction} | {ref} | {connects} |")

    # Area constraints
    lines.append("\n### 面积指标\n")
    for field, label in [
        ("total_area_ha", "总面积"),
        ("construction_area_ha", "建设用地"),
        ("farmland_area_ha", "耕地保有量"),
        ("ecological_area_ha", "生态用地"),
    ]:
        val = intent.get(field)
        if val is not None:
            lines.append(f"- **{label}**: {val:.1f} ha")
    pop = intent.get("population")
    if pop:
        lines.append(f"- **规划人口**: {pop} 人")

    return "\n".join(lines)


def _format_validation(errors: List[str], is_valid: bool) -> str:
    """Format validation result."""
    lines = []

    if is_valid:
        lines.append("✅ **校验通过** — 所有检查项均已满足")
    else:
        lines.append(f"❌ **校验未通过** — {len(errors)} 个错误\n")
        for i, err in enumerate(errors):
            lines.append(f"{i+1}. {err}")

    return "\n".join(lines)


def _format_encoding_validation(
    operation_sequence: List[Dict[str, Any]],
    planning_intent: Dict[str, Any],
) -> str:
    """Validate encoding codes in operations and planning intent."""
    lines = []

    try:
        from app.modules.gis.schema import GHYTBM_TO_GHYTMC

        # Validate operation land_use_code
        valid_ops = 0
        invalid_ops = []
        for i, op in enumerate(operation_sequence):
            code = op.get("land_use_code", "") if isinstance(op, dict) else getattr(op, "land_use_code", "")
            name = op.get("land_use_name", "") if isinstance(op, dict) else getattr(op, "land_use_name", "")
            if code:
                if code in GHYTBM_TO_GHYTMC:
                    valid_ops += 1
                else:
                    invalid_ops.append(f"操作{i+1}: land_use_code={code} ({name}) 不在附录5编码中")

        total_with_code = valid_ops + len(invalid_ops)
        if total_with_code > 0:
            lines.append(f"### 操作编码验证\n")
            lines.append(f"- 有效 GHYTBM 编码: {valid_ops}/{total_with_code}")
            if invalid_ops:
                lines.append(f"- ❌ 无效编码 ({len(invalid_ops)}):")
                for inv in invalid_ops[:10]:
                    lines.append(f"  - {inv}")
            else:
                lines.append(f"- ✅ 所有编码均有效")

        # Validate zone_target dlbm
        zone_targets = planning_intent.get("zone_targets", []) if isinstance(planning_intent, dict) else []
        valid_zones = 0
        invalid_zones = []
        for zt in zone_targets:
            dlbm = zt.get("dlbm", "") if isinstance(zt, dict) else getattr(zt, "dlbm", "")
            lu = zt.get("land_use", "") if isinstance(zt, dict) else zt.land_use
            if dlbm:
                if dlbm in GHYTBM_TO_GHYTMC:
                    valid_zones += 1
                else:
                    invalid_zones.append(f"dlbm={dlbm} ({lu}) 不在附录5编码中")

        total_with_dlbm = valid_zones + len(invalid_zones)
        if total_with_dlbm > 0:
            lines.append(f"\n### 分区目标编码验证\n")
            lines.append(f"- 有效 GHYTBM 编码: {valid_zones}/{total_with_dlbm}")
            if invalid_zones:
                lines.append(f"- ❌ 无效编码 ({len(invalid_zones)}):")
                for inv in invalid_zones[:10]:
                    lines.append(f"  - {inv}")
            else:
                lines.append(f"- ✅ 所有编码均有效")

        # Area ratio check
        if zone_targets:
            total_ratio = sum(
                zt.get("area_ratio", 0) if isinstance(zt, dict) else zt.area_ratio
                for zt in zone_targets
            )
            lines.append(f"\n### 面积比例校验\n")
            lines.append(f"- 面积比例总和: **{total_ratio:.1%}** (目标: 100% ±5%)")
            if 0.95 <= total_ratio <= 1.05:
                lines.append(f"- ✅ 比例合理")
            else:
                lines.append(f"- ⚠️ 比例偏离目标范围")

    except Exception as e:
        lines.append(f"编码验证失败: {e}")

    if not lines:
        lines.append("_（无编码数据可验证）_")

    return "\n".join(lines)


__all__ = ["generate_parse_report"]
