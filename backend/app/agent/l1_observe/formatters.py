"""Unified professional data formatter for all planning layers.

Replaces the duplicate _generate_professional_data_section() in
prompts/analysis.py, prompts/concept.py, and prompts/detailed.py.
"""

from typing import Any, Dict


def generate_professional_data_section(
    dimension_key: str,
    professional_data: Dict[str, Any],
) -> str:
    """Format professional_data dict into prompt-injectable text.

    Args:
        dimension_key: Dimension identifier (e.g. "socio_economic").
        professional_data: Tool execution results keyed by tool name.

    Returns:
        Formatted markdown section, or empty string if no data.
    """
    if not professional_data:
        return ""

    # Handle raw string output from tools
    if isinstance(professional_data, str):
        return f"\n**【专业数据】**：\n{professional_data}\n"

    sections: list[str] = []

    for tool_name, result in professional_data.items():
        if not result:
            continue
        # Tool results are already formatted strings from ToolRegistry
        if isinstance(result, str):
            sections.append(result)
        elif isinstance(result, dict):
            section = _format_dict_result(tool_name, dimension_key, result)
            if section:
                sections.append(section)

    if not sections:
        return ""

    return "\n".join(sections)


def _format_dict_result(
    tool_name: str,
    dimension_key: str,
    data: Dict[str, Any],
) -> str:
    """Format a dict-type tool result into a prompt section."""
    # Population prediction tool returns pre-formatted markdown
    if tool_name == "population_model_v1":
        return data.get("result", "") if isinstance(data.get("result"), str) else ""

    # Generic dict formatter for future tools
    lines = [f"**【专业数据 - {tool_name}】**："]
    for key, value in data.items():
        if value is not None:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""
