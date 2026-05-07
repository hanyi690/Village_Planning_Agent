"""
规划编译器

将各维度输出的文本内容编译为最终规划文档。
- 解析项目清单为结构化数据
- 填入Word模板表格
- 填充章节文本
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime

from .list_parser import parse_dimension_data, DimensionData, ProjectItem


class PlanningCompiler:
    """规划编译器"""

    def __init__(self, template_dir: Optional[Path] = None):
        """
        初始化编译器

        Args:
            template_dir: Word模板目录路径，默认为 src/utils/templates
        """
        if template_dir is None:
            template_dir = Path(__file__).parent / "templates"
        self.template_dir = template_dir

    def compile(self, village_name: str, layer_reports: Dict[str, Any]) -> Dict[str, Any]:
        """
        编译最终规划

        Args:
            village_name: 村庄名称
            layer_reports: 各层级报告数据

        Returns:
            编译结果（包含结构化数据和文档路径）
        """
        # 提取Layer 3各维度数据
        layer3 = layer_reports.get("layer3", {})
        dimensions = layer3.get("dimensions", {})

        # 解析各维度
        parsed_dimensions = {}
        for dim_key, dim_content in dimensions.items():
            if isinstance(dim_content, str):
                parsed_dimensions[dim_key] = parse_dimension_data(dim_content, dim_key)
            elif isinstance(dim_content, dict):
                # 如果已经是结构化数据，直接使用
                raw_content = dim_content.get("raw_content", "")
                parsed_dimensions[dim_key] = parse_dimension_data(raw_content, dim_key)

        # 汇总项目清单
        all_projects = self._aggregate_projects(parsed_dimensions)

        # 生成结构化输出
        result = {
            "village_name": village_name,
            "compile_time": datetime.now().isoformat(),
            "dimensions": {
                key: {
                    "dimension_name": dim.dimension_name,
                    "projects": [
                        {
                            "name": p.name,
                            "content": p.content,
                            "scale": p.scale,
                            "location": p.location,
                            "phase": p.phase
                        }
                        for p in dim.projects
                    ],
                    "structured_data": dim.structured_data
                }
                for key, dim in parsed_dimensions.items()
            },
            "project_summary": {
                "total_count": len(all_projects),
                "by_phase": self._count_by_phase(all_projects),
                "by_dimension": self._count_by_dimension(parsed_dimensions)
            }
        }

        return result

    def _aggregate_projects(self, dimensions: Dict[str, DimensionData]) -> List[ProjectItem]:
        """
        汇总所有项目

        Args:
            dimensions: 解析后的维度数据

        Returns:
            所有项目列表
        """
        all_projects = []
        for dim in dimensions.values():
            all_projects.extend(dim.projects)
        return all_projects

    def _count_by_phase(self, projects: List[ProjectItem]) -> Dict[str, int]:
        """
        按分期统计项目数量

        Args:
            projects: 项目列表

        Returns:
            分期统计字典
        """
        counts = {"近期": 0, "中期": 0, "远期": 0, "未分期": 0}
        for p in projects:
            if p.phase:
                if "近期" in p.phase:
                    counts["近期"] += 1
                elif "中期" in p.phase:
                    counts["中期"] += 1
                elif "远期" in p.phase:
                    counts["远期"] += 1
            else:
                counts["未分期"] += 1
        return counts

    def _count_by_dimension(self, dimensions: Dict[str, DimensionData]) -> Dict[str, int]:
        """
        按维度统计项目数量

        Args:
            dimensions: 维度数据

        Returns:
            维度统计字典
        """
        return {
            dim.dimension_name: len(dim.projects)
            for dim in dimensions.values()
            if dim.projects
        }

    def generate_summary_text(self, parsed_dimensions: Dict[str, DimensionData]) -> str:
        """
        生成汇总文本

        Args:
            parsed_dimensions: 解析后的维度数据

        Returns:
            汇总后的文本内容
        """
        lines = []

        # 按维度顺序输出
        dimension_order = [
            "industry", "spatial_structure", "land_use_planning",
            "settlement_planning", "traffic", "public_service",
            "infrastructure", "ecological", "disaster_prevention",
            "heritage", "landscape", "project_bank"
        ]

        for dim_key in dimension_order:
            if dim_key in parsed_dimensions:
                dim = parsed_dimensions[dim_key]
                lines.append(f"【{dim.dimension_name}】")
                lines.append(dim.raw_content)
                lines.append("\n")

        return "\n".join(lines)


# ==========================================
# 导出
# ==========================================

__all__ = [
    "PlanningCompiler",
]