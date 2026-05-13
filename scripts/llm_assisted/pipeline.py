"""
Pipeline V3.0 - 简化版主流程

直接调用 simple_export 导出规划文档。
"""

import sys
from pathlib import Path
from typing import List
from dataclasses import dataclass, field

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class PipelineResult:
    """Pipeline 执行结果"""
    success: bool
    markdown_path: str
    word_path: str = ""
    article_count: int = 0
    errors: List[str] = field(default_factory=list)


def run_pipeline(
    layer3_path: str,
    output_dir: str = "output",
    project_name: str = "村庄规划"
) -> PipelineResult:
    """
    执行规划文档导出流程

    Args:
        layer3_path: Layer3 Markdown 文件路径
        output_dir: 输出目录
        project_name: 项目名称

    Returns:
        PipelineResult
    """
    from scripts.llm_assisted.simple_export import export_planning_document

    result = export_planning_document(
        layer3_path=layer3_path,
        output_dir=output_dir,
        project_name=project_name
    )

    return PipelineResult(
        success=result.success,
        markdown_path=result.markdown_path,
        word_path=result.word_path,
        article_count=result.article_count,
        errors=result.errors
    )


__all__ = [
    "run_pipeline",
    "PipelineResult",
]