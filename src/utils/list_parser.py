"""
规划列表解析器

将各维度的项目清单解析为结构化数据，用于填入Word模板表格。
"""

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field


@dataclass
class ProjectItem:
    """项目条目"""
    name: str
    content: str
    scale: str
    location: str
    phase: Optional[str] = None  # 分期（近期/中期/远期）


@dataclass
class DimensionData:
    """维度数据"""
    dimension_key: str
    dimension_name: str
    raw_content: str
    projects: List[ProjectItem] = field(default_factory=list)
    structured_data: Dict[str, Any] = field(default_factory=dict)


def parse_project_list(content: str, dimension_key: str) -> List[ProjectItem]:
    """
    解析项目清单

    Args:
        content: 维度输出的原始内容
        dimension_key: 维度键名

    Returns:
        解析后的项目列表
    """
    projects = []

    # 匹配项目清单模式
    # 格式：项目N：[名称]，[内容]，[规模]，[位置]
    pattern = r"项目\d+\s*[：:]\s*(.+?)\s*[，,]\s*(.+?)\s*[，,]\s*(.+?)\s*[，,]\s*(.+?)(?:\n|$)"
    matches = re.findall(pattern, content)

    for match in matches:
        project = ProjectItem(
            name=match[0].strip(),
            content=match[1].strip(),
            scale=match[2].strip(),
            location=match[3].strip()
        )
        projects.append(project)

    # 对于建设项目库，解析分期项目
    if dimension_key == "project_bank":
        projects = _parse_project_bank(content)

    return projects


def _parse_project_bank(content: str) -> List[ProjectItem]:
    """
    解析建设项目库（包含分期信息）

    Args:
        content: 原始内容

    Returns:
        解析后的项目列表（包含分期）
    """
    projects = []

    # 按分期解析
    phases = {
        "近期": "近期（1-2年）",
        "中期": "中期（3-5年）",
        "远期": "远期（5-10年）"
    }

    for phase_label, phase_full in phases.items():
        # 找到分期段落
        phase_pattern = rf"{phase_label}项目.*?\n((?:项目\d+[：:].+\n)+)"
        phase_match = re.search(phase_pattern, content)

        if phase_match:
            phase_content = phase_match.group(1)
            # 解析该分期下的项目
            pattern = r"项目\d+\s*[：:]\s*(.+?)\s*[，,]\s*(.+?)\s*[，,]\s*(.+?)\s*[，,]\s*(.+?)(?:\n|$)"
            matches = re.findall(pattern, phase_content)

            for match in matches:
                project = ProjectItem(
                    name=match[0].strip(),
                    content=match[1].strip(),
                    scale=match[2].strip(),
                    location=match[3].strip(),
                    phase=phase_full
                )
                projects.append(project)

    return projects


def parse_dimension_data(content: str, dimension_key: str) -> DimensionData:
    """
    解析维度数据

    Args:
        content: 维度输出的原始内容
        dimension_key: 维度键名

    Returns:
        解析后的维度数据对象
    """
    dimension_names = {
        "industry": "产业规划",
        "spatial_structure": "空间结构规划",
        "land_use_planning": "土地利用规划",
        "settlement_planning": "居民点规划",
        "traffic": "道路交通规划",
        "traffic_planning": "道路交通规划",
        "public_service": "公共服务设施规划",
        "infrastructure": "基础设施规划",
        "infrastructure_planning": "基础设施规划",
        "ecological": "生态绿地规划",
        "disaster_prevention": "防灾减灾规划",
        "heritage": "历史文化保护规划",
        "landscape": "村庄风貌指引",
        "project_bank": "建设项目库"
    }

    dimension_name = dimension_names.get(dimension_key, dimension_key)
    projects = parse_project_list(content, dimension_key)

    return DimensionData(
        dimension_key=dimension_key,
        dimension_name=dimension_name,
        raw_content=content,
        projects=projects,
        structured_data=_extract_structured_data(content, dimension_key)
    )


def _extract_structured_data(content: str, dimension_key: str) -> Dict[str, Any]:
    """
    提取结构化数据

    Args:
        content: 原始内容
        dimension_key: 维度键名

    Returns:
        结构化数据字典
    """
    data = {}

    # 提取带-的列表项
    list_pattern = r"-\s*(.+?)\s*[：:]\s*(.+?)(?:\n|$)"
    list_matches = re.findall(list_pattern, content)

    for match in list_matches:
        key = match[0].strip()
        value = match[1].strip()
        data[key] = value

    # 提取章节标题下的内容
    section_pattern = r"(?:\d+)\.\s*(.+?)\n(.+?)(?=\n\d+\.\s|\n---|\n【|\Z)"
    section_matches = re.findall(section_pattern, content, re.DOTALL)

    for match in section_matches:
        key = match[0].strip()
        value = match[1].strip()
        data[key] = value

    return data


# ==========================================
# 导出
# ==========================================

__all__ = [
    "ProjectItem",
    "DimensionData",
    "parse_project_list",
    "parse_dimension_data",
]