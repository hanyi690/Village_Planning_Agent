"""建筑风貌分析维度 Prompt。"""

from ._base import ANALYSIS_RULES, entity_spec_instruction_for

ARCHITECTURE_PROMPT = """你是建筑分析专家。

**任务**：分析建筑质量、年代、高度、功能特征。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + entity_spec_instruction_for(["building"]) + """

**输出骨架**：
建筑规模：建筑总量、总面积、建筑密度
建筑年代：各年代建筑比例
建筑质量等级：A/B/C/D四级数量占比、危房分布
新老建筑空间关系：新旧分布特征、新建区域位置
建筑高度特征：普遍层数、高层建筑位置功能
建筑风格：传统风貌、地域特色

请开始分析："""

__all__ = ["ARCHITECTURE_PROMPT"]
