"""Output management module.

Manages automatic saving and file output for village planning results.
Provides both default path and custom path modes, supporting three-layer
planning with hierarchical saving.

Features:
1. Default save path: results/{project_name}/{timestamp}/
2. Custom path support (via --output parameter)
3. Automatic directory structure creation
4. Combined report and dimension report saving
5. Automatic project name sanitization (removes special characters)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OutputManager:
    """
    输出管理器

    管理村庄规划结果的保存路径和文件输出。
    """

    # 默认输出目录
    DEFAULT_OUTPUT_DIR = Path("results")

    # 时间戳格式：YYYYMMDD_HHMMSS
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

    # 现状分析维度列表（12个）- 遵循 ANALYSIS_DIMENSION_NAMES 定义顺序
    ANALYSIS_DIMENSIONS = [
        "location",
        "socio_economic",
        "villager_wishes",
        "superior_planning",
        "natural_environment",
        "land_use",
        "traffic",
        "public_services",
        "infrastructure",
        "ecological_green",
        "architecture",
        "historical_culture",
    ]

    # 规划思路维度列表（4个）
    CONCEPT_DIMENSIONS = [
        "resource_endowment",
        "planning_positioning",
        "development_goals",
        "planning_strategies"
    ]

    # 详细规划维度列表（12个）
    DETAILED_PLAN_DIMENSIONS = [
        "industry",
        "spatial_structure",
        "land_use_planning",
        "settlement_planning",
        "traffic",
        "public_service",
        "infrastructure",
        "ecological",
        "disaster_prevention",
        "heritage",
        "landscape",
        "project_bank"
    ]

    def __init__(
        self,
        project_name: str,
        custom_output_path: str | None = None,
        base_dir: Path | None = None
    ) -> None:
        """Initialize the output manager.

        Args:
            project_name: Project/village name
            custom_output_path: Custom output path (if provided, default path is not used)
            base_dir: Base directory (defaults to project root)
        """
        self.project_name = self._sanitize_project_name(project_name)
        self.custom_output_path = custom_output_path
        self.base_dir = base_dir or Path.cwd()

        # 生成时间戳
        self.timestamp = datetime.now().strftime(self.TIMESTAMP_FORMAT)

        # 确定输出路径
        if custom_output_path:
            # 自定义路径：仅保存综合报告
            self.output_path = Path(custom_output_path)
            self.use_default_structure = False
        else:
            # 默认路径：使用分层目录结构
            self.output_path = self.base_dir / self.DEFAULT_OUTPUT_DIR / self.project_name / self.timestamp
            self.use_default_structure = True
            self.layer1_dir = self.output_path / "layer_1_analysis"
            self.layer2_dir = self.output_path / "layer_2_concept"
            self.layer3_dir = self.output_path / "layer_3_detailed"

    def ensure_directories(self) -> bool:
        """
        确保所有必要的目录已创建

        Returns:
            bool: 是否成功创建目录
        """
        try:
            if self.use_default_structure:
                # 创建分层目录结构
                self.output_path.mkdir(parents=True, exist_ok=True)
                self.layer1_dir.mkdir(parents=True, exist_ok=True)
                self.layer2_dir.mkdir(parents=True, exist_ok=True)
                self.layer3_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"[OutputManager] 创建默认目录结构: {self.output_path}")
            else:
                # 创建自定义路径的父目录
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"[OutputManager] 创建自定义输出目录: {self.output_path.parent}")

            return True

        except Exception as e:
            logger.error(f"[OutputManager] 目录创建失败: {e}")
            return False

    def _sanitize_project_name(self, project_name: str) -> str:
        """Sanitize project name by removing unsafe filename characters.

        Args:
            project_name: Original project name

        Returns:
            Sanitized project name
        """
        # Remove or replace unsafe filename characters
        # Windows disallows: < > : " / \ | ? *
        # Replace with underscore
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', project_name)
        # Remove leading/trailing whitespace
        sanitized = sanitized.strip()
        # Use default name if empty
        if not sanitized:
            sanitized = "unnamed_project"

        return sanitized

    def _save_file(self, file_path: Path, content: str) -> bool:
        """Save file to specified path.

        Args:
            file_path: File path
            content: File content

        Returns:
            True if save succeeded, False otherwise
        """
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"[OutputManager] 文件已保存: {file_path}")
            return True

        except Exception as e:
            logger.error(f"[OutputManager] 文件保存失败 {file_path}: {e}")
            return False

    def save_layer1_results(
        self,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> dict[str, Any]:
        """
        保存 Layer 1 现状分析结果

        Args:
            combined_report: 综合分析报告
            dimension_reports: 各维度分析报告字典

        Returns:
            包含保存结果的字典
        """
        if not self.use_default_structure:
            # 自定义路径模式下不保存分层数据
            return {"saved": False, "reason": "Custom output path enabled"}

        result = {
            "combined_report_path": None,
            "dimension_report_paths": {},
            "saved_count": 0,
            "failed_count": 0
        }

        # 保存综合报告
        combined_path = self.layer1_dir / f"combined_analysis_{self.timestamp}.md"
        if self._save_file(combined_path, combined_report):
            result["combined_report_path"] = str(combined_path)
            result["saved_count"] += 1
        else:
            result["failed_count"] += 1

        # 保存各维度报告
        # 维度键名到友好名称的映射（遵循 ANALYSIS_DIMENSION_NAMES 顺序）
        dimension_names = {
            "location": "01_区位分析",
            "socio_economic": "02_社会经济分析",
            "villager_wishes": "03_村民意愿与诉求分析",
            "superior_planning": "04_上位规划与政策导向分析",
            "natural_environment": "05_自然环境分析",
            "land_use": "06_土地利用分析",
            "traffic": "07_道路交通分析",
            "public_services": "08_公共服务设施分析",
            "infrastructure": "09_基础设施分析",
            "ecological_green": "10_生态绿地分析",
            "architecture": "11_建筑分析",
            "historical_culture": "12_历史文化分析",
        }

        for dimension_key in self.ANALYSIS_DIMENSIONS:
            if dimension_key in dimension_reports:
                # 使用友好的文件名
                friendly_name = dimension_names.get(dimension_key, dimension_key)
                dimension_path = self.layer1_dir / f"{friendly_name}.md"
                if self._save_file(dimension_path, dimension_reports[dimension_key]):
                    result["dimension_report_paths"][dimension_key] = str(dimension_path)
                    result["saved_count"] += 1
                else:
                    result["failed_count"] += 1

        logger.info(f"[OutputManager] Layer 1 保存完成: {result['saved_count']} 个文件, {result['failed_count']} 个失败")
        return result

    def save_layer2_results(
        self,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> dict[str, Any]:
        """
        保存 Layer 2 规划思路结果

        Args:
            combined_report: 综合规划思路报告
            dimension_reports: 各维度规划思路报告字典

        Returns:
            包含保存结果的字典
        """
        if not self.use_default_structure:
            return {"saved": False, "reason": "Custom output path enabled"}

        result = {
            "combined_report_path": None,
            "dimension_report_paths": {},
            "saved_count": 0,
            "failed_count": 0
        }

        # 保存综合报告
        combined_path = self.layer2_dir / f"combined_concept_{self.timestamp}.md"
        if self._save_file(combined_path, combined_report):
            result["combined_report_path"] = str(combined_path)
            result["saved_count"] += 1
        else:
            result["failed_count"] += 1

        # 保存各维度报告
        # 维度键名到友好名称的映射
        dimension_names = {
            "resource_endowment": "01_资源禀赋分析",
            "planning_positioning": "02_规划定位分析",
            "development_goals": "03_发展目标分析",
            "planning_strategies": "04_规划策略分析"
        }

        for dimension_key in self.CONCEPT_DIMENSIONS:
            if dimension_key in dimension_reports:
                # 使用友好的文件名
                friendly_name = dimension_names.get(dimension_key, dimension_key)
                dimension_path = self.layer2_dir / f"{friendly_name}.md"
                if self._save_file(dimension_path, dimension_reports[dimension_key]):
                    result["dimension_report_paths"][dimension_key] = str(dimension_path)
                    result["saved_count"] += 1
                else:
                    result["failed_count"] += 1

        logger.info(f"[OutputManager] Layer 2 保存完成: {result['saved_count']} 个文件, {result['failed_count']} 个失败")
        return result

    def save_layer3_results(
        self,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> dict[str, Any]:
        """
        保存 Layer 3 详细规划结果

        Args:
            combined_report: 综合详细规划报告
            dimension_reports: 各维度详细规划报告字典

        Returns:
            包含保存结果的字典
        """
        if not self.use_default_structure:
            return {"saved": False, "reason": "Custom output path enabled"}

        result = {
            "combined_report_path": None,
            "dimension_report_paths": {},
            "saved_count": 0,
            "failed_count": 0
        }

        # 保存综合报告
        combined_path = self.layer3_dir / f"combined_detailed_plan_{self.timestamp}.md"
        if self._save_file(combined_path, combined_report):
            result["combined_report_path"] = str(combined_path)
            result["saved_count"] += 1
        else:
            result["failed_count"] += 1

        # 保存各维度报告
        # 维度键名到友好名称的映射
        dimension_names = {
            "industry": "01_产业规划",
            "spatial_structure": "02_空间结构规划",
            "land_use_planning": "03_土地利用规划",
            "settlement_planning": "04_居民点规划",
            "traffic": "05_综合交通规划",
            "public_service": "06_公共服务设施规划",
            "infrastructure": "07_基础设施规划",
            "ecological": "08_生态绿地系统规划",
            "disaster_prevention": "09_防灾减灾规划",
            "heritage": "10_历史文化保护规划",
            "landscape": "11_村庄风貌规划",
            "project_bank": "12_项目库"
        }

        for dimension_key in self.DETAILED_PLAN_DIMENSIONS:
            if dimension_key in dimension_reports:
                # 使用友好的文件名
                friendly_name = dimension_names.get(dimension_key, dimension_key)
                dimension_path = self.layer3_dir / f"{friendly_name}.md"
                if self._save_file(dimension_path, dimension_reports[dimension_key]):
                    result["dimension_report_paths"][dimension_key] = str(dimension_path)
                    result["saved_count"] += 1
                else:
                    result["failed_count"] += 1

        logger.info(f"[OutputManager] Layer 3 保存完成: {result['saved_count']} 个文件, {result['failed_count']} 个失败")
        return result

    def save_final_combined(self, final_output: str) -> str | None:
        """
        保存最终综合报告

        Args:
            final_output: 最终综合报告内容

        Returns:
            保存的文件路径，如果失败则返回 None
        """
        if self.use_default_structure:
            # 默认路径：保存到根目录
            output_path = self.output_path / f"final_combined_{self.timestamp}.md"
        else:
            # 自定义路径：直接保存到指定路径
            output_path = self.output_path

        if self._save_file(output_path, final_output):
            logger.info(f"[OutputManager] 最终报告已保存: {output_path}")
            return str(output_path)
        else:
            logger.error(f"[OutputManager] 最终报告保存失败: {output_path}")
            return None

    def get_output_summary(self) -> dict[str, Any]:
        """
        获取输出路径的摘要信息

        Returns:
            包含输出路径信息的字典
        """
        return {
            "project_name": self.project_name,
            "timestamp": self.timestamp,
            "output_path": str(self.output_path),
            "use_default_structure": self.use_default_structure,
            "layer1_dir": str(self.layer1_dir) if self.use_default_structure else None,
            "layer2_dir": str(self.layer2_dir) if self.use_default_structure else None,
            "layer3_dir": str(self.layer3_dir) if self.use_default_structure else None,
        }

    def get_console_message(self) -> str:
        """
        获取用于控制台显示的消息

        Returns:
            格式化的输出路径消息
        """
        if self.use_default_structure:
            return (
                f"\n📁 结果已保存到默认目录:\n"
                f"   根目录: {self.output_path}\n"
                f"   ├─ Layer 1 (现状分析): {self.layer1_dir}\n"
                f"   ├─ Layer 2 (规划思路): {self.layer2_dir}\n"
                f"   ├─ Layer 3 (详细规划): {self.layer3_dir}\n"
                f"   └─ 最终报告: final_combined_{self.timestamp}.md"
            )
        else:
            return f"\n📄 结果已保存到: {self.output_path}"

    @staticmethod
    def _get_dimension_order(layer_number: int = 1) -> list[str]:
        """
        获取标准维度顺序（从 dimension_mapping.py 导入）

        Args:
            layer_number: 层级编号 (1=现状分析, 2=规划思路, 3=详细规划)

        Returns:
            按照定义顺序排列的维度键列表
        """
        from ..core.dimension_mapping import (
            ANALYSIS_DIMENSION_NAMES,
            CONCEPT_DIMENSION_NAMES,
            DETAILED_DIMENSION_NAMES
        )

        if layer_number == 1:
            return list(ANALYSIS_DIMENSION_NAMES.keys())
        elif layer_number == 2:
            return list(CONCEPT_DIMENSION_NAMES.keys())
        elif layer_number == 3:
            return list(DETAILED_DIMENSION_NAMES.keys())
        else:
            return []


# ==========================================
# 工厂函数
# ==========================================

def create_output_manager(
    project_name: str,
    custom_output_path: str | None = None
) -> OutputManager:
    """
    创建输出管理器实例

    Args:
        project_name: 项目/村庄名称
        custom_output_path: 自定义输出路径（可选）

    Returns:
        OutputManager 实例
    """
    return OutputManager(
        project_name=project_name,
        custom_output_path=custom_output_path
    )


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试默认路径
    print("=== 测试默认路径 ===")
    manager = create_output_manager("测试<>:村", custom_output_path=None)
    print(f"项目名称: {manager.project_name}")
    print(f"输出路径: {manager.output_path}")
    print(f"使用默认结构: {manager.use_default_structure}")
    print(f"\n控制台消息:\n{manager.get_console_message()}")

    # 测试自定义路径
    print("\n\n=== 测试自定义路径 ===")
    manager2 = create_output_manager("测试村", custom_output_path="custom_output.md")
    print(f"项目名称: {manager2.project_name}")
    print(f"输出路径: {manager2.output_path}")
    print(f"使用默认结构: {manager2.use_default_structure}")
    print(f"\n控制台消息:\n{manager2.get_console_message()}")
