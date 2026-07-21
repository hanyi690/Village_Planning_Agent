"""PARSE Agent prompts — 6 structured prompts for spatially-aware text parsing.

Each prompt is designed for a specific node in the PARSE Agent StateGraph:
  classify_sections -> route_by_section -> extract_* -> validate_and_merge

Design principles:
  - Inject SpatialContext summary (not raw geometry) for spatial grounding
  - Use structured output with Pydantic models for reliable parsing
  - Follow "Agent is drafter, not planner" principle
  - Encoding lookups via DictionaryCenter, no auto-conversion
  - Chinese prompts for Chinese village planning text (qwen3.7-plus)
  - Encoding system awareness (GHYTBM/QMDLBM/VNE)
"""

# ── Helper: format SpatialContext for LLM injection ─────────────────


from typing import Literal


def format_spatial_context_for_prompt(
    ctx,
    detail_level: Literal["minimal", "standard", "full"] = "standard",
) -> str:
    """Format SpatialContext as compact text for LLM injection.

    This is the "spatial working memory" that lets PARSE understand
    spatial references like "east of Liu village group".

    detail_level controls how much information to include:
    - "minimal": Base stats + natural village names (~500 chars, for classify)
    - "standard": + landuse distribution + protection zones (~4000 chars, for extract)
    - "full": + spatial relations + zone adjacency (~12000 chars, for validate)

    Without detail_level, the full 12637-char output overwhelmed the LLM context
    and caused max_tokens truncation in thinking mode.
    """
    lines = []

    # Base stats (always included)
    lines.append(f"地块总数: {ctx.parcel_count}")
    lines.append(f"总面积: {ctx.total_area_ha:.1f} 公顷")
    lines.append(f"建设边界面积: {ctx.construction_boundary_ha:.1f} 公顷")

    # Village center (always included)
    if ctx.village_center:
        lines.append(f"村中心坐标: ({ctx.village_center[0]:.4f}, {ctx.village_center[1]:.4f})")

    # Natural village anchors (always included — key for spatial grounding)
    if ctx.natural_villages:
        lines.append("\n自然村落:")
        for v in ctx.natural_villages:
            if detail_level == "minimal":
                # Minimal: just name and dominant land use
                lines.append(f"  - {v.name}: 主地类={v.dominant_landuse}")
            else:
                # Standard/Full: include adjacency info
                adj = f", 邻接 {', '.join(v.adjacent_to)}" if v.adjacent_to else ""
                lines.append(
                    f"  - {v.name}: 主地类={v.dominant_landuse}, "
                    f"地块数={len(v.parcel_ids)}{adj}"
                )

    # Land-use distribution (standard + full only)
    if detail_level in ("standard", "full") and ctx.landuse_distribution:
        lines.append("\n地类分布:")
        for lu in ctx.landuse_distribution:
            lines.append(
                f"  - {lu.name} ({lu.dlbm}): {lu.count}个地块, "
                f"{lu.area_ha:.1f}公顷, 分区={lu.planning_zone}"
            )

    # Spatial relations (full only — 225 relations = ~6KB)
    if detail_level == "full" and ctx.spatial_relations:
        lines.append("\n空间关系:")
        for r in ctx.spatial_relations:
            rel_cn = {
                "east_of": "东邻", "west_of": "西邻",
                "north_of": "北邻", "south_of": "南邻",
                "adjacent_to": "邻接", "contains": "包含",
                "contained_by": "被包含", "near": "靠近",
                "along": "沿", "between": "介于",
            }.get(r.relation, r.relation)
            lines.append(f"  - {r.subject} {rel_cn} {r.object} (置信度={r.confidence:.1f})")

    # Constraint summary (standard + full only)
    if detail_level in ("standard", "full") and ctx.constraint_summary:
        lines.append("\n保护区域:")
        for c in ctx.constraint_summary:
            overlaps = f", 与 {', '.join(c.overlaps_with)} 重叠" if c.overlaps_with else ""
            lines.append(
                f"  - {c.zone_type}: 规则={c.rule}, "
                f"面积={c.area_ha:.1f}公顷{overlaps}"
            )

    # Zone adjacency (full only)
    if detail_level == "full" and ctx.zone_adjacency:
        lines.append("\n分区邻接:")
        for zone, neighbors in ctx.zone_adjacency.items():
            lines.append(f"  - {zone}: 邻接 {', '.join(neighbors)}")

    return "\n".join(lines)


# ── 1. Classify Sections Prompt ────────────────────────────────────

CLASSIFY_SECTIONS_PROMPT = """你是村庄规划文档结构分类器。

**任务**: 将规划文档的每个段落按类型分类。

**村庄空间上下文**:
{spatial_context}

**文档文本**:
{planning_text}

**段落类型**:
- preamble: 前言、概述、背景
- target: 规划目标、指标、发展目标
- regulation: 分区规则、建设管控、保护规则
- project_table: 建设项目表（含项目名称/面积/位置）
- land_use_table: 土地利用分类表
- indicator_table: 规划指标表
- heritage_table: 历史文化保护表
- facility_table: 公共设施表
- ecological_table: 生态保护表
- spatial_layout: 空间布局描述
- protection: 保护区域描述
- infrastructure: 基础设施规划
- governance: 实施与治理

**规则**:
- 每个段落只能有一个类型
- 含表格的段落标记 has_table=true
- 长段落若含混合内容则拆分
- 保留段落原文（不要摘要）

输出分类结果。
"""

# ── 2. Extract Regulations Prompt ──────────────────────────────────

EXTRACT_REGULATIONS_PROMPT = """你是村庄规划管制规则提取器。

**任务**: 从管制规则段落提取规划约束和规则。

**村庄空间上下文**:
{spatial_context}

**保护区域概要**:
{constraint_summary}

**段落内容**:
{section_content}

**提取规则**:
1. 每条规则生成一个 SpatialConstraint
2. 面积约束: 提取 land_use, target_area_ha, operator (<=/>=/==)
3. 空间约束: 必须包含可计算的 SpatialRule
   - "农田内禁止建设" → no_overlap(construction, farmland)
   - "产业用地距居住区≥200米" → buffer_exclusion(industry, residential, 200m)
   - "建设必须在边界内" → contained_by(construction, boundary)
4. 建筑约束: 提取 max_area_sqm, max_height_m, max_floors, setback_m
5. 必须包含 source_text（原文引用）和 article_ref（条文编号）
6. 设置优先级: mandatory（法定要求）> recommended（指导性）> aspirational（目标性）

**SpatialRule 操作**:
- no_overlap: 主体与客体不得重叠 → intersection() == empty
- buffer_exclusion: 主体与客体距离 > distance_m → distance() > threshold
- contained_by: 主体在客体内部 → within()
- adjacent_to: 主体与客体邻接 → touches() / distance() < 30m
- distance_within: 主体与客体距离 < distance_m → distance() < threshold

提取段落中所有约束。
"""

# ── 3. Extract Tables Prompt ───────────────────────────────────────

EXTRACT_TABLES_PROMPT = """你是村庄规划表格结构化提取器。

**任务**: 从表格段落提取结构化行数据。

**段落内容**:
{section_content}

**规则**:
1. 每行表格数据生成一个结构化字典
2. 保留所有数值（不要四舍五入）
3. 保留原始中文字段名
4. 不确定值标记 confidence < 1.0
5. 土地利用表须同时包含 land_use_name 和 land_use_code

提取结构化表格数据。
"""

# ── 4. Extract Projects Prompt ─────────────────────────────────────

EXTRACT_PROJECTS_PROMPT = """你是村庄规划项目提取器，具备空间感知能力。

**任务**: 从建设项目段落提取规划操作，并进行空间锚定。

**村庄空间上下文**:
{spatial_context}

**自然村落锚点**（用于空间锚定）:
{natural_villages_detail}

**段落内容**:
{section_content}

**5种原子操作**:
- create: 在空地新建（需 area_sqm, land_use_name, location）
- split: 将一个图斑分割（需 source_bsm, split_ratio）
- merge: 合并相邻同用途图斑（需 source_bsms）
- modify: 修改图斑属性不改几何（需 field_changes）
- reclassify: 变更地类编码（需 new_qmdlbm）

**空间锚定规则**（关键）:
1. 每个含位置描述的操作创建 SpatialAnchor
2. 将位置引用匹配到自然村落锚点名称:
   - "刘村小组东侧" → reference="刘村小组", offset="东侧"
   - "晒谷场北边近刘村" → reference="刘村小组", offset="北边", secondary_ref="晒谷场"
3. 从自然村落的 parcel_ids 预解析 candidate_parcels
4. 设置 resolution_status:
   - "anchored": 匹配到具体图斑, confidence >= 0.7
   - "partial": 匹配到区域但非具体图斑, confidence 0.3-0.7
   - "unresolved": 未匹配, confidence < 0.3
5. 锚定失败时保留 location_desc 作为回退
**编码和地名请不要猜测，使用以下工具查询**：
- land_use_code: 使用 lookup_code 工具查询
  示例: lookup_code("经营性建设用地") -> ghytbm:2124, zone_type:产业用地
- 地名->GIS地块锚定: 使用 resolve_place 工具查询
  示例: resolve_place("刘村小组") -> village_name, parcel_ids, confidence
- 也可用 query_village_kg 查询地块分布

**示例**:
输入: "在刘村小组东侧、晒谷场北边空地，新建400㎡农产品展销中心"
输出:
  action: "create"
  spatial_anchor:
    reference: "刘村小组"
    offset: "东侧"
    secondary_ref: "晒谷场"
    secondary_offset: "北边"
    candidate_parcels: ["XG-005", "XG-006"]
    confidence: 0.8
    resolution_status: "partial"
  area_sqm: 400
  land_use_name: "经营性建设用地"
  needs_confirmation: true

提取段落中所有操作。
"""

# ── 5. Extract Targets Prompt ──────────────────────────────────────

EXTRACT_TARGETS_PROMPT = """你是村庄规划目标提取器，具备空间感知能力。

**任务**: 提取规划目标、分区配置、设施需求和发展轴线。

**村庄空间上下文**:
{spatial_context}

**地类分布**:
{landuse_distribution}

**分区邻接**:
{zone_adjacency}

**段落内容**:
{section_content}

**V/N/E 用途分区分类体系**（住建部《村庄规划用地分类指南》）:
- V: 村庄建设用地
  V11=住宅用地, V21=村庄公共服务设施用地, V22=村庄公共场地
  V31=村庄商业服务业设施用地, V32=村庄生产仓储用地
  V41=村庄道路用地, V42=村庄交通设施用地, V43=村庄公用设施用地
- N: 非村庄建设用地
  N1=对外交通设施用地, N2=国有建设用地
- E: 非建设用地
  E11=自然水域, E12=水库, E13=坑塘沟渠
  E21=设施农用地, E22=农用道路, E23=其他农林用地
  E9=其他非建设用地

**编码体系说明**:
- dlbm 字段使用 GHYTBM 编码（附录5）: 2121=宅基地, 1100=耕地 等
- 面积比例 area_ratio 为该地类占总面积的比例（所有比例之和应接近 1.0）

**分区目标规则**:
1. 每个分区目标须包含: land_use, area_ratio
2. area_ratio 须合理（所有分区比例之和接近 1.0）
3. 文本提及空间布局时包含 spatial_preference:
   - "住宅集中在村中心" → direction="center", reference="村委会"
   - "产业沿主干道布局" → direction="along", reference="主干道"
4. 规则指定邻接偏好时包含 adjacency_rules:
   - "公共服务靠近住宅" → prefer=["居住用地"]
   - "产业远离住宅" → avoid=["居住用地"]

**设施目标规则**:
1. 每个设施须包含: type, status, location_hint
2. 位置引用自然村落时设置 anchor_village
3. 文本指定覆盖范围时设置 service_radius

**发展轴规则**:
1. 每条轴须包含: direction, reference_feature
2. 轴线连接特定村落/区域时包含 connects 列表

提取所有规划目标。
"""

# ── 6. Validate and Merge Prompt ───────────────────────────────────

VALIDATE_AND_MERGE_PROMPT = """你是村庄规划数据校验与合并器。

**任务**: 校验提取结果并合并为最终输出。

**村庄上下文**:
{spatial_context}

**提取的操作** ({operation_count} 条):
{operations_json}

**提取的约束** ({constraint_count} 条):
{constraints_json}

**提取的规划意图**:
{intent_json}

**校验检查**:
1. 面积比例: zone_targets.area_ratio 之和应接近 1.0（容差 5%）
2. 编码有效性: 所有 land_use_code 须为合法 GHYTBM 编码
3. 空间锚定一致性: confidence < 0.3 的锚定应标记
4. 约束完整性: 至少须有耕地保护和生态保护约束
5. 无重复操作: 相同 source_text 不应产生多条操作
6. 必填字段: 每条 SpatialOperation 须有 source_text，每条 SpatialConstraint 须有 article_ref

**合并规则**:
1. 同一操作出现在多个段落时，保留 confidence 较高者
2. 冲突约束存在时，mandatory > recommended > aspirational
3. 空间锚定: 同一位置有多个锚定时，合并 candidate_parcels

**输出**:
- 校验通过: 合并后的 operation_sequence, constraint_set, planning_intent
- 校验失败: 设置 validation_errors 列表和 is_valid=false

校验并合并提取结果。
"""
