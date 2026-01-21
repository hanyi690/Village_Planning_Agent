"""
输出管理模块 (Output Manager)

负责管理村庄规划结果的自动保存和文件输出。
提供默认路径和自定义路径两种模式，支持三层规划的分层保存。

功能特性：
1. 默认保存路径：results/{project_name}/{timestamp}/
2. 支持自定义路径（通过 --output 参数）
3. 自动创建目录结构
4. 保存综合报告和分维度报告
5. 项目名称自动清理（移除特殊字符）
"""

import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
import logging

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

    # 现状分析维度列表（10个）
    ANALYSIS_DIMENSIONS = [
        "dimension_location",
        "dimension_natural_conditions",
        "dimension_socio_economic",
        "dimension_land_use",
        "dimension_infrastructure_status",
        "dimension_public_service_status",
        "dimension_historical_heritage",
        "dimension_governance_status",
        "dimension_development_constraints",
        "dimension_development_potential"
    ]

    # 规划思路维度列表（4个）
    CONCEPT_DIMENSIONS = [
        "dimension_resource_endowment",
        "dimension_planning_positioning",
        "dimension_development_goals",
        "dimension_planning_strategies"
    ]

    # 详细规划维度列表（10个）
    DETAILED_PLAN_DIMENSIONS = [
        "dimension_industry",
        "dimension_master_plan",
        "dimension_traffic",
        "dimension_public_service",
        "dimension_infrastructure",
        "dimension_ecological",
        "dimension_disaster_prevention",
        "dimension_heritage",
        "dimension_landscape",
        "dimension_project_bank"
    ]

    def __init__(
        self,
        project_name: str,
        custom_output_path: Optional[str] = None,
        base_dir: Optional[Path] = None
    ):
        """
        初始化输出管理器

        Args:
            project_name: 项目/村庄名称
            custom_output_path: 自定义输出路径（如果提供，则不使用默认路径）
            base_dir: 基础目录（默认为项目根目录）
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
        """
        清理项目名称，移除不安全的文件名字符

        Args:
            project_name: 原始项目名称

        Returns:
            清理后的项目名称
        """
        # 移除或替换不安全的文件名字符
        # Windows 不允许的字符: < > : " / \ | ? *
        # 替换为下划线
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', project_name)
        # 移除首尾空格
        sanitized = sanitized.strip()
        # 如果为空，使用默认名称
        if not sanitized:
            sanitized = "unnamed_project"

        return sanitized

    def _save_file(self, file_path: Path, content: str) -> bool:
        """
        保存文件到指定路径

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            bool: 是否成功保存
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
        dimension_reports: Dict[str, str]
    ) -> Dict[str, Any]:
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
        for dimension_key in self.ANALYSIS_DIMENSIONS:
            if dimension_key in dimension_reports:
                dimension_path = self.layer1_dir / f"{dimension_key}.md"
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
        dimension_reports: Dict[str, str]
    ) -> Dict[str, Any]:
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
        for dimension_key in self.CONCEPT_DIMENSIONS:
            if dimension_key in dimension_reports:
                dimension_path = self.layer2_dir / f"{dimension_key}.md"
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
        dimension_reports: Dict[str, str]
    ) -> Dict[str, Any]:
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
        for dimension_key in self.DETAILED_PLAN_DIMENSIONS:
            if dimension_key in dimension_reports:
                dimension_path = self.layer3_dir / f"{dimension_key}.md"
                if self._save_file(dimension_path, dimension_reports[dimension_key]):
                    result["dimension_report_paths"][dimension_key] = str(dimension_path)
                    result["saved_count"] += 1
                else:
                    result["failed_count"] += 1

        logger.info(f"[OutputManager] Layer 3 保存完成: {result['saved_count']} 个文件, {result['failed_count']} 个失败")
        return result

    def save_final_combined(self, final_output: str) -> Optional[str]:
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

    def get_output_summary(self) -> Dict[str, Any]:
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


# ==========================================
# 工厂函数
# ==========================================

def create_output_manager(
    project_name: str,
    custom_output_path: Optional[str] = None
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
