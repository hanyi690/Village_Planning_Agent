"""Unified prompt templates for structured LLM parsing.

Replaces SPATIAL_LAYOUT_PARSE_PROMPT and ZONE_AREA_ADJUSTMENT_PROMPT
with schema-constrained versions that include metric anchors.
"""

STRUCTURED_PARSE_PROMPT = """你是乡村规划空间结构解析助手。

**任务**: 将规划报告解析为结构化意图数据，输出严格遵循指定 schema。

**村庄**: {village_name}

**已知精确数值（请严格遵循）**:
{anchors}
例: 如果"建设用地=30.5ha"且"总面积=2352.56ha"，则建设类分区 area_ratio 总和应≈30.5/2352.56

**概念澄清（关键）**:
本系统存在两套独立的分类体系，请勿混淆:

1. 功能区(7类) — 基于现状地类(你输出的 land_use 使用此体系):
   - 农业用地、生态绿地、居住用地、产业用地、公共服务用地、商业用地、交通用地、水域

2. 土地用途分区(4区) — 基于国土空间规划"三区三线"(用于规划图层):
   - 农田保护区: 永久基本农田划定区域
   - 生态保护区: 生态红线保护区域
   - 村庄建设区: 未来建设空间
   - 一般农业区: 非受保护的农业用地

**7类→4区映射关系**:
   居住用地 + 产业用地 + 公共服务用地 + 商业用地 + 交通用地 → 村庄建设区
   农业用地 → 农田保护区 或 一般农业区（取决于是否为永久基本农田）
   生态绿地 + 水域 → 生态保护区 或 一般农业区

**规则**:
1. area_ratio 总和必须接近 1.0
2. zones 至少包含 3 个分区
3. 每个分区的 land_use 必须是有效用地类型（7类体系）
4. 设施的 location_hint 应清晰描述位置
5. 精确数值锚定值具有最高优先级——不要偏离已知数据
6. 如果锚定值中有"XX区比例"，请参考该比例分配对应类型分区的面积

**规划上下文**:
{planning_context}

请输出结构化规划意图。
"""


def format_structured_parse_prompt(
    village_name: str,
    anchors: str,
    planning_context: str,
) -> str:
    """Format structured parse prompt with anchors."""
    return STRUCTURED_PARSE_PROMPT.format(
        village_name=village_name,
        anchors=anchors,
        planning_context=planning_context,
    )


def build_planning_context(reports: dict) -> str:
    """Build planning context text from reports for prompt injection.

    Extracts key content from each dimension report, prioritizing
    text_summary over raw content for conciseness.
    """
    parts = []
    for dim_key, report in reports.items():
        summary = report.get("summary", {})
        content = report.get("content", "")

        # Prefer text_summary (concise), fall back to content
        text = summary.get("text_summary", "")
        if not text and content:
            text = content[:500]

        if text:
            parts.append(f"## {dim_key}\n{text}")

    return "\n\n".join(parts)


def format_anchors_text(anchors_dict: dict) -> str:
    """Format anchors dict into prompt text.

    Args:
        anchors_dict: Output of MetricAnchors.to_anchor_dict()

    Returns:
        Formatted text suitable for prompt injection.
    """
    if not anchors_dict:
        return "（无精确数值）"

    lines = []
    for key, info in anchors_dict.items():
        if isinstance(info, dict):
            value = info.get("value", "?")
            unit = info.get("unit", "")
            source = info.get("source", "")
            lines.append(f"  {key} = {value}{unit} (来源: {source})")
        else:
            lines.append(f"  {key} = {info}")
    return "\n".join(lines)
