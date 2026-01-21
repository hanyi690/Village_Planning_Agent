"""
修复管理器 (Revision Manager)

管理基于人工反馈的修复流程，支持：
1. 解析人工反馈，识别需要修复的维度
2. 用户确认修复范围
3. 调用相应skill执行修复
"""

import re
from typing import Dict, List, Any, Optional
from ..utils.logger import get_logger

logger = get_logger(__name__)


class RevisionManager:
    """
    修复管理器

    处理人工审查驳回后的修复流程。
    """

    # 维度关键词映射（用于从反馈中识别需要修复的维度）
    DIMENSION_KEYWORDS = {
        "industry": ["产业", "经济", "农业", "工业", "旅游", "收入", "gdp"],
        "master_plan": ["总体规划", "空间布局", "用地", "村庄布局", "总规"],
        "traffic": ["交通", "道路", "运输", "出行", "路网", "停车"],
        "public_service": ["公共服务", "教育", "医疗", "卫生", "养老", "文化", "体育"],
        "infrastructure": ["基础设施", "水电", "给排水", "电力", "通信", "管网"],
        "ecological": ["生态", "环境", "绿地", "绿化", "环保", "污染", "景观"],
        "disaster_prevention": ["防灾", "减灾", "安全", "消防", "防洪", "地震"],
        "heritage": ["历史", "文化", "文物", "保护", "古迹", "传统"],
        "landscape": ["风貌", "建筑", "风格", "外观", "色彩", "高度"],
        "project_bank": ["项目", "建设", "工程", "投资", "实施", "计划"]
    }

    def __init__(self):
        """初始化RevisionManager"""
        self.revision_history: List[Dict[str, Any]] = []

    def parse_feedback(self, feedback: str) -> List[str]:
        """
        解析人工反馈，智能识别需要修复的维度

        Args:
            feedback: 人工反馈文本

        Returns:
            需要修复的维度列表
        """
        logger.info(f"[RevisionManager] 解析反馈: {feedback[:100]}...")

        identified_dimensions = []

        # 将反馈转为小写进行匹配
        feedback_lower = feedback.lower()

        # 检查每个维度的关键词
        for dimension, keywords in self.DIMENSION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in feedback_lower:
                    if dimension not in identified_dimensions:
                        identified_dimensions.append(dimension)
                    break

        logger.info(f"[RevisionManager] 识别到需要修复的维度: {identified_dimensions}")
        return identified_dimensions

    def confirm_dimensions(self, dimensions: List[str]) -> List[str]:
        """
        用户确认修复维度（混合模式）

        Args:
            dimensions: 识别出的维度列表

        Returns:
            用户确认后的维度列表
        """
        if not dimensions:
            print("\n" + "=" * 80)
            print("未识别到需要修复的维度。")
            print("可能的原因：反馈内容不够具体或与规划维度无关。")
            print("=" * 80)

            choice = input("\n是否手动指定修复维度? (Y/N): ").strip().upper()

            if choice == 'Y':
                return self._manual_select_dimensions()
            else:
                return []

        print("\n" + "=" * 80)
        print("系统识别到以下需要修复的维度:")
        print("=" * 80)

        dimension_names = {
            "industry": "产业规划",
            "master_plan": "村庄总体规划",
            "traffic": "道路交通规划",
            "public_service": "公服设施规划",
            "infrastructure": "基础设施规划",
            "ecological": "生态绿地规划",
            "disaster_prevention": "防震减灾规划",
            "heritage": "历史文保规划",
            "landscape": "村庄风貌指引",
            "project_bank": "建设项目库"
        }

        for i, dim in enumerate(dimensions, 1):
            name = dimension_names.get(dim, dim)
            print(f"{i}. {name}")

        print("=" * 80)

        choice = input("\n确认这些维度? (Y/N/M=修改): ").strip().upper()

        if choice == 'Y':
            return dimensions
        elif choice == 'M':
            return self._manual_select_dimensions()
        else:
            # 取消修复
            return []

    def _manual_select_dimensions(self) -> List[str]:
        """
        手动选择修复维度

        Returns:
            用户选择的维度列表
        """
        dimension_names = {
            "industry": "产业规划",
            "master_plan": "村庄总体规划",
            "traffic": "道路交通规划",
            "public_service": "公服设施规划",
            "infrastructure": "基础设施规划",
            "ecological": "生态绿地规划",
            "disaster_prevention": "防震减灾规划",
            "heritage": "历史文保规划",
            "landscape": "村庄风貌指引",
            "project_bank": "建设项目库"
        }

        print("\n" + "=" * 80)
        print("所有规划维度:")
        print("=" * 80)

        dimensions_list = list(dimension_names.keys())

        for i, (key, name) in enumerate(dimension_names.items(), 1):
            print(f"{i}. {name} ({key})")

        print("=" * 80)

        while True:
            input_str = input("\n请输入要修复的维度编号（多个用逗号分隔，0=取消）: ").strip()

            if input_str == '0':
                return []

            try:
                indices = [int(x.strip()) for x in input_str.split(',')]

                selected = []
                valid = True
                for idx in indices:
                    if 1 <= idx <= len(dimensions_list):
                        selected.append(dimensions_list[idx - 1])
                    else:
                        print(f"无效的编号: {idx}")
                        valid = False

                if valid and selected:
                    print(f"\n已选择: {[dimension_names[d] for d in selected]}")
                    confirm = input("确认? (Y/N): ").strip().upper()
                    if confirm == 'Y':
                        return selected

            except ValueError:
                print("输入格式错误，请重新输入。")

    def revise_dimension(
        self,
        dimension: str,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0
    ) -> str:
        """
        修复指定维度

        Args:
            dimension: 维度标识
            state: 当前状态
            feedback: 人工反馈
            original_result: 原始结果
            revision_count: 修复次数

        Returns:
            修复后的结果
        """
        logger.info(f"[RevisionManager] 开始修复维度: {dimension} (第{revision_count + 1}次)")

        # 这里应该调用对应skill的execute_with_feedback方法
        # 实际实现需要在detailed_plan_subgraph中完成

        # 简化实现：使用LLM生成修复建议
        prompt = f"""
请根据以下人工反馈，修复对应的规划内容：

【原规划内容】
{original_result[:1000]}

【人工反馈】
{feedback}

【要求】
1. 针对反馈意见进行修改
2. 保持原有结构和格式
3. 修改部分要明确标注
4. 这是第{revision_count + 1}次修复

请生成修复后的规划内容：
"""

        # 调用LLM
        try:
            from ..core.llm_factory import create_llm
            from ..core.config import LLM_MODEL

            llm = create_llm(model=LLM_MODEL, temperature=0.7)

            result = llm.invoke(prompt)
            revised_content = result.content

            logger.info(f"[RevisionManager] 维度 {dimension} 修复完成，内容长度: {len(revised_content)}")

            # 记录修复历史
            self.revision_history.append({
                "dimension": dimension,
                "revision_count": revision_count + 1,
                "feedback": feedback,
                "original_length": len(original_result),
                "revised_length": len(revised_content)
            })

            return revised_content

        except Exception as e:
            logger.error(f"[RevisionManager] 修复维度 {dimension} 失败: {e}")
            # 返回原始结果
            return original_result

    def revise_multiple_dimensions(
        self,
        dimensions: List[str],
        state: Dict[str, Any],
        feedback: str
    ) -> Dict[str, str]:
        """
        修复多个维度

        Args:
            dimensions: 需要修复的维度列表
            state: 当前状态
            feedback: 人工反馈

        Returns:
            修复后的维度结果字典 {dimension: revised_result}
        """
        revised_results = {}

        for dimension in dimensions:
            # 获取原始结果
            original_result = self._get_dimension_result(dimension, state)

            if original_result:
                # 执行修复
                revised_result = self.revise_dimension(
                    dimension=dimension,
                    state=state,
                    feedback=feedback,
                    original_result=original_result,
                    revision_count=0
                )
                revised_results[dimension] = revised_result
            else:
                logger.warning(f"[RevisionManager] 维度 {dimension} 没有找到原始结果")

        return revised_results

    def _get_dimension_result(self, dimension: str, state: Dict[str, Any]) -> Optional[str]:
        """
        从状态中获取指定维度的原始结果

        Args:
            dimension: 维度标识
            state: 当前状态

        Returns:
            原始结果，如果不存在则返回None
        """
        detailed_dimension_reports = state.get("detailed_dimension_reports", {})

        # 维度键名映射
        dimension_key_map = {
            "industry": "dimension_industry",
            "master_plan": "dimension_master_plan",
            "traffic": "dimension_traffic",
            "public_service": "dimension_public_service",
            "infrastructure": "dimension_infrastructure",
            "ecological": "dimension_ecological",
            "disaster_prevention": "dimension_disaster_prevention",
            "heritage": "dimension_heritage",
            "landscape": "dimension_landscape",
            "project_bank": "dimension_project_bank"
        }

        key = dimension_key_map.get(dimension)
        if key:
            return detailed_dimension_reports.get(key, "")

        return None

    def get_revision_history(self) -> List[Dict[str, Any]]:
        """获取修复历史"""
        return self.revision_history.copy()


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    print("=== 测试RevisionManager ===\n")

    manager = RevisionManager()

    # 测试反馈解析
    test_feedback = "产业规划部分需要加强乡村旅游发展，道路交通规划不够详细"
    dimensions = manager.parse_feedback(test_feedback)

    print(f"识别到的维度: {dimensions}")

    # 测试用户确认
    confirmed = manager.confirm_dimensions(dimensions)
    print(f"确认后的维度: {confirmed}")

    # 显示修复历史
    print(f"\n修复历史: {manager.get_revision_history()}")
