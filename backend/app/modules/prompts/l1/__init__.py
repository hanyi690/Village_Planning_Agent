"""L1 维度 Prompt 聚合 - 取代原 analysis.py 中的 ANALYSIS_DIMENSIONS 字典。"""

from ._config import DIMENSION_CONFIG, DIMENSION_NAMES
from .location import LOCATION_PROMPT
from .socio_economic import SOCIO_ECONOMIC_PROMPT
from .villager_wishes import VILLAGER_WISHES_PROMPT
from .superior_planning import SUPERIOR_PLANNING_PROMPT
from .natural_environment import NATURAL_ENVIRONMENT_PROMPT
from .land_use import LAND_USE_PROMPT
from .traffic import TRAFFIC_PROMPT
from .public_services import PUBLIC_SERVICES_PROMPT
from .infrastructure import INFRASTRUCTURE_PROMPT
from .ecological_green import ECOLOGICAL_GREEN_PROMPT
from .architecture import ARCHITECTURE_PROMPT
from .historical_culture import HISTORICAL_CULTURE_PROMPT

DIMENSION_PROMPTS = {
    "location": LOCATION_PROMPT,
    "socio_economic": SOCIO_ECONOMIC_PROMPT,
    "villager_wishes": VILLAGER_WISHES_PROMPT,
    "superior_planning": SUPERIOR_PLANNING_PROMPT,
    "natural_environment": NATURAL_ENVIRONMENT_PROMPT,
    "land_use": LAND_USE_PROMPT,
    "traffic": TRAFFIC_PROMPT,
    "public_services": PUBLIC_SERVICES_PROMPT,
    "infrastructure": INFRASTRUCTURE_PROMPT,
    "ecological_green": ECOLOGICAL_GREEN_PROMPT,
    "architecture": ARCHITECTURE_PROMPT,
    "historical_culture": HISTORICAL_CULTURE_PROMPT,
}


ANALYSIS_DIMENSIONS = {
    k: {"name": v, "prompt": DIMENSION_PROMPTS[k], **DIMENSION_CONFIG[k]}
    for k, v in DIMENSION_NAMES.items()
}


def get_dimension_prompt(dimension_key: str, raw_data: str = "",
                         village_name: str = "", task_description: str = "",
                         constraints: str = "", knowledge_context: str = "",
                         revision_instruction: str = "",
                         has_images: bool = False,
                         professional_data: str = "") -> str:
    """L1 维度 Prompt 组装函数 - 与原 analysis.py 同签名。"""
    prompt_template = DIMENSION_PROMPTS.get(dimension_key, "")
    if not prompt_template:
        raise ValueError(f"未知的分析维度: {dimension_key}")

    effective_village_name = village_name or "该村"

    knowledge_section = ""
    if knowledge_context:
        knowledge_section = f"\n**参考规范与标准**\n{knowledge_context}\n"

    professional_data_section = professional_data or ""
    if professional_data_section and "{professional_data_section}" not in prompt_template:
        pass

    format_params = {
        "raw_data": raw_data,
        "village_name": effective_village_name,
        "task_description": task_description or "未提供具体规划任务",
        "constraints": constraints or "无特殊约束",
        "knowledge_context": knowledge_context or "暂无相关规范标准参考",
        "professional_data_section": professional_data_section,
    }

    formatted = prompt_template.format(**format_params)
    if knowledge_section and "{knowledge_context}" not in prompt_template:
        formatted += knowledge_section

    if revision_instruction:
        formatted = revision_instruction + "\n\n" + formatted

    if has_images:
        formatted += "\n\n**【上传图片分析指引】**：\n请结合上传的图片分析村庄现状。图片可能展示村庄实景、设施、环境、建筑等。"

    return formatted


def list_dimensions():
    """列出所有分析维度"""
    return [
        {"key": key, "name": value["name"]}
        for key, value in ANALYSIS_DIMENSIONS.items()
    ]


__all__ = [
    "ANALYSIS_DIMENSIONS",
    "DIMENSION_PROMPTS",
    "DIMENSION_NAMES",
    "DIMENSION_CONFIG",
    "get_dimension_prompt",
    "list_dimensions",
]
