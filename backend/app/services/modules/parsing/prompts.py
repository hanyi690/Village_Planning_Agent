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

**规划上下文**:
{planning_context}

**规则**:
1. area_ratio 总和必须接近 1.0
2. zones 至少包含 3 个分区
3. 每个分区的 land_use 必须是有效用地类型
4. 设施的 location_hint 应清晰描述位置
5. 精确数值锚定值具有最高优先级——不要偏离已知数据

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
