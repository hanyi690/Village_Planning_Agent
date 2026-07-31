"""道路交通分析维度 Prompt。"""

from ._base import ANALYSIS_RULES, entity_spec_instruction_for

TRAFFIC_PROMPT = """你是道路交通分析专家。

**任务**：分析对外与内部道路系统。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + entity_spec_instruction_for(["road", "facility"]) + """

**输出骨架**：
对外交通：连接道路等级、与主干道距离
内部交通：铺装质量分类（硬化/砂石/土路占比）、道路宽度
交通设施：公交候车亭位置、停车场位置规模、货运通道
出行特征：出行方式、高峰时段压力

请开始分析："""

__all__ = ["TRAFFIC_PROMPT"]
