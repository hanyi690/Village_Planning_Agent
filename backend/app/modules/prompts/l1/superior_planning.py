"""上位规划分析维度 Prompt。"""

from ._base import ANALYSIS_RULES

SUPERIOR_PLANNING_PROMPT = """你是上位规划分析专家。

**任务**：分析上位规划要求与政策约束。

**约束条件**：{constraints}

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
规划定位要求：功能定位类型（生态保护型/农业发展型/工业带动型/特色旅游型/综合发展型）
规划约束识别：生态红线、基本农田、城镇开发边界
政策背景分析：乡村振兴政策、地方专项政策（如百千万工程）
指标任务分解：耕地保有量、生态保护指标

请开始分析："""

__all__ = ["SUPERIOR_PLANNING_PROMPT"]
