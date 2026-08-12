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
    pipeline_trace: List[Dict[str, Any]] = None,
    kg_summary: Dict[str, Any] = None,
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
        pipeline_trace: List of per-node trace dicts {node, elapsed_s, tokens, summary, tool_calls, draft_preview}
        kg_summary: Dict with KG build stats {triple_count, facilities, roads, villages}

    Returns:
        Path to the generated Markdown file.
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{village_name}_{date_str}.md"
    filepath = output_dir / filename

    # Normalize: accept list[dict] (ContextBlock serialized) or dict (legacy)
    if isinstance(spatial_context, list):
        context_blocks_data = spatial_context
        ctx = {}
    elif hasattr(spatial_context, "model_dump"):
        ctx = spatial_context.model_dump()
        context_blocks_data = []
    elif isinstance(spatial_context, dict):
        ctx = spatial_context
        context_blocks_data = []
    else:
        ctx = {}
        context_blocks_data = []

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
    if context_blocks_data:
        lines.append(_format_context_blocks(context_blocks_data))
    else:
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

    # Section 8: KG Build Summary
    if kg_summary:
        lines.append("\n---\n")
        lines.append("## 8. 知识图谱构建\n")
        lines.append(_format_kg_summary(kg_summary))

    # Section 9: Pipeline Trace (ALWAYS present)
    lines.append("\n---\n")
    lines.append("## 9. 管线执行追踪\n")
    lines.append(_format_pipeline_trace(pipeline_trace or []))

    # Section A: Tool Call Log (detailed)
    if pipeline_trace:
        tool_trace = _extract_tool_trace(pipeline_trace)
        if tool_trace:
            lines.append("\n---\n")
            lines.append("## 10. 工具调用日志\n")
            lines.append(_format_tool_trace(tool_trace))

    # Section B: LLM Output Previews
    if pipeline_trace:
        llm_previews = _extract_llm_previews(pipeline_trace)
        if llm_previews:
            lines.append("\n---\n")
            lines.append("## 11. LLM 输出预览\n")
            lines.append(_format_llm_previews(llm_previews))

    # Write file
    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    logger.info("[PARSE Report] Generated: %s", filepath)

    return filepath


# ── Section formatters ────────────────────────────────────────────────


def _format_context_blocks(blocks: List[Dict[str, Any]]) -> str:
    """Format ContextBlock list as markdown report section."""
    lines: List[str] = []
    for block in blocks:
        lines.append(f"### {block.get('title', block.get('block_type', ''))}")
        data = block.get("data", {})
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    lines.append(f"\n**{k}** ({len(v)} items):")
                    for item in v[:10]:  # Limit to 10 items
                        if isinstance(item, dict):
                            lines.append(f"- {item}")
                        else:
                            lines.append(f"- {item}")
                    if len(v) > 10:
                        lines.append(f"- ... and {len(v) - 10} more")
                else:
                    lines.append(f"- **{k}**: {v}")
        lines.append("")
    return "\n".join(lines)


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

    # Residential cluster anchors
    villages = ctx.get("residential_clusters", [])
    if villages:
        lines.append("\n### 居民点锚点\n")
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
        if hasattr(op, 'action'):
            # Typed SpatialOperation (Phase 2+)
            action = op.action or "?"
            land_use = op.land_use_name or ""
            area = op.area_sqm
            source = op.source_text or ""
            confidence = op.confidence
            needs_confirm = "🔒" if op.needs_confirmation else ""
            article = op.article_ref or ""
        else:
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

        # Spatial anchor — typed + dict
        anchor = op.spatial_anchor if hasattr(op, 'spatial_anchor') else op.get("spatial_anchor")
        if anchor:
            if hasattr(anchor, 'reference'):
                ref = anchor.reference
                offset = anchor.offset or ""
                sec_ref = anchor.secondary_ref or ""
                sec_offset = anchor.secondary_offset or ""
                candidates = anchor.candidate_parcels
                status = anchor.resolution_status
                anchor_conf = anchor.confidence
            else:
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
            loc = op.location_desc if hasattr(op, 'location_desc') else op.get("location_desc", "")
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
        if hasattr(c, 'type'):
            ctype = c.type or "?"
            priority = c.priority or "mandatory"
            article = c.article_ref or ""
            rule = c.spatial_rule
        else:
            ctype = c.get("type", "?")
            priority = c.get("priority", "mandatory")
            article = c.get("article_ref", "")
            rule = c.get("spatial_rule")
        rule_str = ""
        if rule:
            op = rule.operation if hasattr(rule, 'operation') else rule.get("operation", "")
            subj = rule.subject if hasattr(rule, 'subject') else rule.get("subject", "")
            obj = rule.object if hasattr(rule, 'object') else rule.get("object", "")
            dist = rule.distance_m if hasattr(rule, 'distance_m') else rule.get("distance_m")
            dist_str = f", {dist}m" if dist else ""
            rule_str = f"{op}({subj}, {obj}{dist_str})"
        lines.append(f"| {i+1} | {ctype} | {priority} | {article} | {rule_str} |")

    # Detailed list
    lines.append("\n### 详细约束\n")
    for i, c in enumerate(constraints):
        if hasattr(c, 'type'):
            ctype = c.type or "?"
            priority = c.priority or "mandatory"
            source = c.source_text or ""
            article = c.article_ref or ""
        else:
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
        land_use = c.land_use if hasattr(c, 'land_use') else c.get("land_use")
        target_area = c.target_area_ha if hasattr(c, 'target_area_ha') else c.get("target_area_ha")
        operator = c.operator if hasattr(c, 'operator') else c.get("operator")
        if land_use and target_area:
            lines.append(f"- **面积约束**: {land_use} {operator or ''} {target_area} ha")

        rule = c.spatial_rule if hasattr(c, 'spatial_rule') else c.get("spatial_rule")
        if rule:
            op = rule.operation if hasattr(rule, 'operation') else rule.get("operation", "")
            subj = rule.subject if hasattr(rule, 'subject') else rule.get("subject", "")
            obj = rule.object if hasattr(rule, 'object') else rule.get("object", "")
            dist = rule.distance_m if hasattr(rule, 'distance_m') else rule.get("distance_m")
            dist_str = f", {dist}m" if dist else ""
            lines.append(f"- **空间规则**: `{op}({subj}, {obj}{dist_str})`")

        # Building constraints
        for field in ["max_area_sqm", "max_height_m", "max_floors", "setback_m"]:
            val = getattr(c, field, None) if hasattr(c, field) else c.get(field)
            if val is not None:
                lines.append(f"- **{field}**: {val}")

        lines.append("")

    return "\n".join(lines)


def _format_planning_intent(intent: Dict[str, Any]) -> str:
    """Format planning intent."""
    if not intent:
        return "_（未提取到规划意图）_"

    lines = []

    # Zone targets — handle both typed SpatialPlanningIntent and legacy dict
    zone_targets = intent.zone_targets if hasattr(intent, 'zone_targets') else intent.get("zone_targets", [])
    if zone_targets:
        lines.append("### 分区目标\n")
        lines.append("| 用途 | 编码 | 面积比例 | 密度 | 空间偏好 | 邻接偏好 | 邻接规避 |")
        lines.append("|------|------|----------|------|----------|----------|----------|")
        total_ratio = 0
        for zt in zone_targets:
            if hasattr(zt, 'land_use'):
                lu = zt.land_use
                dlbm = zt.dlbm or ""
                ratio = zt.area_ratio
                density = zt.density
                pref = zt.spatial_preference
                pref_str = f"{pref.direction} (ref={pref.reference})" if pref and (pref.direction or pref.reference) else ""
                adj = zt.adjacency_rules
                prefer = ", ".join(adj.prefer) if adj else ""
                avoid = ", ".join(adj.avoid) if adj else ""
            else:
                lu = zt.get("land_use", "")
                dlbm = zt.get("dlbm", "")
                ratio = zt.get("area_ratio", 0)
                density = zt.get("density", "")
                pref = zt.get("spatial_preference", {})
                pref_str = f"{pref.get('direction', '')} (ref={pref.get('reference', '')})" if pref else ""
                adj = zt.get("adjacency_rules") or {}
                prefer = ", ".join(adj.get("prefer", []))
                avoid = ", ".join(adj.get("avoid", []))
            total_ratio += ratio
            lines.append(f"| {lu} | {dlbm} | {ratio:.1%} | {density} | {pref_str} | {prefer} | {avoid} |")
        lines.append(f"\n> 面积比例总和: **{total_ratio:.1%}** (目标: 100% ±5%)")

    # Facilities — typed + dict
    facilities = intent.facilities if hasattr(intent, 'facilities') else intent.get("facilities", [])
    if facilities:
        lines.append("\n### 设施需求\n")
        lines.append("| 类型 | 状态 | 位置提示 | 服务半径 | 锚定村落 |")
        lines.append("|------|------|----------|----------|----------|")
        for ft in facilities:
            if hasattr(ft, 'type'):
                ftype = ft.type
                status = ft.status
                hint = ft.location_hint
                radius = str(ft.service_radius or "")
                anchor = ft.anchor_village or ""
            else:
                ftype = ft.get("type", "")
                status = ft.get("status", "")
                hint = ft.get("location_hint", "")
                radius = ft.get("service_radius", "")
                anchor = ft.get("anchor_village", "")
            lines.append(f"| {ftype} | {status} | {hint} | {radius} | {anchor} |")

    # Development axes — typed + dict
    axes = intent.development_axes if hasattr(intent, 'development_axes') else intent.get("development_axes", [])
    if axes:
        lines.append("\n### 发展轴\n")
        lines.append("| 方向 | 参照特征 | 连接 |")
        lines.append("|------|----------|------|")
        for at in axes:
            if hasattr(at, 'direction'):
                direction = at.direction
                ref = at.reference_feature
                connects = ", ".join(getattr(at, 'connects', []))
            else:
                direction = at.get("direction", "")
                ref = at.get("reference_feature", "")
                connects = ", ".join(at.get("connects", []))
            lines.append(f"| {direction} | {ref} | {connects} |")

    # Area constraints — typed + dict compat
    lines.append("\n### 面积指标\n")
    for field, label in [
        ("total_area_ha", "总面积"),
        ("construction_area_ha", "建设用地"),
        ("farmland_area_ha", "耕地保有量"),
        ("ecological_area_ha", "生态用地"),
    ]:
        val = intent.get(field) if isinstance(intent, dict) else getattr(intent, field, None)
        if val is not None:
            lines.append(f"- **{label}**: {val:.1f} ha")
    pop = intent.get("population") if isinstance(intent, dict) else getattr(intent, "population", None)
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
        from app.data.encodings.code_sets import GHYTBM_TO_GHYTMC

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

        # Validate zone_target dlbm — typed + dict
        if isinstance(planning_intent, dict):
            zone_targets = planning_intent.get("zone_targets", [])
        else:
            zone_targets = getattr(planning_intent, "zone_targets", [])
        valid_zones = 0
        invalid_zones = []
        for zt in zone_targets:
            dlbm = zt.dlbm if hasattr(zt, 'dlbm') else zt.get("dlbm", "")
            lu = zt.land_use if hasattr(zt, 'land_use') else zt.get("land_use", "")
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


# ── New sections: KG summary, pipeline trace, tool calls, LLM previews ──


def _format_kg_summary(kg: Dict[str, Any]) -> str:
    """Format KG build summary."""
    lines = []
    lines.append(f"| 指标 | 值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 三元组总数 | {kg.get('triple_count', 0)} |")
    lines.append(f"| 地块实体 | {kg.get('parcel_count', 0)} |")
    lines.append(f"| 设施实体 | {kg.get('facility_count', 0)} |")
    lines.append(f"| 道路实体 | {kg.get('road_count', 0)} |")
    lines.append(f"| 村庄锚点 | {kg.get('village_count', 0)} |")
    constraints = kg.get("constraint_count", 0)
    lines.append(f"| 约束实体 | {constraints} |")
    if kg.get("error"):
        lines.append(f"\n⚠️ KG 构建警告: {kg['error']}")
    return "\n".join(lines)


def _format_pipeline_trace(trace: List[Dict[str, Any]]) -> str:
    """Format pipeline execution trace as a detailed table."""
    if not trace:
        return "_（无追踪数据）_"

    lines = []
    lines.append("| 节点 | 耗时 | Tokens | 状态 | 产出摘要 |")
    lines.append("|------|------|--------|------|----------|")
    total_time = 0
    for entry in trace:
        node = entry.get("node", "?")
        elapsed = entry.get("elapsed_s", 0)
        total_time += elapsed
        tokens = entry.get("tokens", 0)
        status = entry.get("status", "done")
        summary = entry.get("summary", "")

        status_icon = {"ok": "✅", "fail": "❌", "skip": "⏭️"}.get(status, "✅")
        lines.append(f"| {node} | {elapsed:.0f}s | {tokens} | {status_icon} {status} | {summary[:80]} |")

    lines.append(f"\n> 节点总耗时: **{total_time:.0f}s**")
    return "\n".join(lines)


def _extract_tool_trace(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract tool call details from pipeline trace.

    Sources:
      1. entry["tool_calls"] — flattened from _build_trace_entry (has name, args, _phase)
      2. entry["llm_calls"][*]["tool_results"] — per-call results (has name, args, result)
    """
    tool_entries = []
    for entry in trace:
        node = entry.get("node", "?")

        # Source 1: flattened tool_calls from _build_trace_entry
        for tc in entry.get("tool_calls", []):
            tc_copy = dict(tc)
            tc_copy["_node"] = node
            tool_entries.append(tc_copy)

        # Source 2: tool_results from llm_calls (has actual result content)
        for call in entry.get("llm_calls", []):
            phase = call.get("phase", "")
            for tr in call.get("tool_results", []):
                tr_copy = dict(tr)
                tr_copy["_node"] = node
                tr_copy["_phase"] = phase
                tool_entries.append(tr_copy)

        # Legacy: tool_results_summary
        if entry.get("tool_results_summary"):
            tool_entries.append({
                "_node": node,
                "name": "SUMMARY",
                "args": entry.get("tool_results_summary", ""),
                "result": "",
            })
    return tool_entries


def _format_tool_trace(tool_trace: List[Dict[str, Any]]) -> str:
    """Format tool call log as a detailed table with results."""
    import json as _json

    lines = []
    lines.append(f"共 **{len(tool_trace)}** 条工具调用\n")
    lines.append("| # | 节点 | 阶段 | 工具 | 参数 | 结果预览 |")
    lines.append("|---|------|------|------|------|----------|")

    for i, tc in enumerate(tool_trace[:100]):  # max 100 for readability
        node = tc.get("_node", "?")
        phase = tc.get("_phase", "")
        tool_name = tc.get("name", tc.get("tool_name", "?"))
        if tool_name == "SUMMARY" and not tc.get("result"):
            lines.append(f"| {i+1} | {node} | {phase} | 📊 工具汇总 | {tc['args'][:60]} | — |")
            continue
        args = tc.get("args", {})
        args_str = _json.dumps(args, ensure_ascii=False, default=str)[:120]
        # Use "result" (from tool_results) or "result_preview" (legacy)
        result = tc.get("result", tc.get("result_preview", ""))[:120]
        lines.append(f"| {i+1} | {node} | {phase} | `{tool_name}` | {args_str} | {result} |")

    if len(tool_trace) > 100:
        lines.append(f"\n> ...还有 {len(tool_trace) - 100} 条调用（已省略）")
    return "\n".join(lines)


def _extract_llm_previews(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract LLM call details from pipeline trace.

    Returns list of dicts with:
      - node, phase, system_prompt, user_prompt, thinking_content,
        response_content, tool_call_count, draft_full, draft_preview
    """
    previews = []
    for entry in trace:
        node = entry.get("node", "?")

        # From llm_calls (detailed per-call data)
        for call in entry.get("llm_calls", []):
            preview_item = {
                "node": node,
                "phase": call.get("phase", ""),
                "system_prompt": call.get("system_prompt", ""),
                "user_prompt": call.get("user_prompt", ""),
                "thinking_content": call.get("thinking_content", ""),
                "response_content": call.get("response_content", ""),
                "tool_call_count": call.get("tool_call_count", 0),
                "elapsed_s": call.get("elapsed_s", 0),
            }
            previews.append(preview_item)

        # Also include draft full content for explore nodes
        draft_full = entry.get("draft_full", "")
        if draft_full and not entry.get("llm_calls"):
            previews.append({
                "node": node,
                "phase": "draft",
                "system_prompt": "",
                "user_prompt": "",
                "thinking_content": "",
                "response_content": draft_full,
                "tool_call_count": 0,
                "elapsed_s": 0,
                "draft_len": entry.get("draft_length", 0),
            })

        # Format node results (legacy)
        format_result = entry.get("format_result", "")
        if format_result and not entry.get("llm_calls"):
            previews.append({
                "node": node,
                "phase": "format",
                "system_prompt": "",
                "user_prompt": "",
                "thinking_content": "",
                "response_content": format_result,
                "tool_call_count": 0,
                "elapsed_s": 0,
            })
    return previews


def _format_llm_previews(previews: List[Dict[str, Any]]) -> str:
    """Format LLM call details with system/user prompts, thinking, and response."""
    lines = []
    for p in previews:
        node = p.get("node", "?")
        phase = p.get("phase", "")
        header = f"{node}" if not phase else f"{node} ({phase})"
        lines.append(f"### {header}\n")

        # System prompt
        sys_prompt = p.get("system_prompt", "")
        if sys_prompt:
            lines.append("**System Prompt:**\n")
            lines.append("```")
            lines.append(sys_prompt[:3000])
            lines.append("```\n")

        # User prompt
        user_prompt = p.get("user_prompt", "")
        if user_prompt:
            lines.append("**User Prompt:**\n")
            lines.append("```")
            lines.append(user_prompt[:3000])
            lines.append("```\n")

        # Thinking chain
        thinking = p.get("thinking_content", "")
        if thinking:
            lines.append(f"**Thinking Chain** ({len(thinking)} chars):\n")
            lines.append("<details>\n<summary>展开 thinking</summary>\n\n")
            lines.append("```")
            lines.append(thinking[:4000])
            lines.append("```\n</details>\n")

        # Response
        response = p.get("response_content", "")
        if response:
            draft_len = p.get("draft_len", len(response))
            lines.append(f"**Response** ({draft_len} chars, {p.get('tool_call_count', 0)} tool calls, "
                         f"{p.get('elapsed_s', 0):.1f}s):\n")
            lines.append("```")
            lines.append(response[:5000])
            lines.append("```\n")

        lines.append("---\n")

    return "\n".join(lines)


__all__ = ["generate_parse_report"]
