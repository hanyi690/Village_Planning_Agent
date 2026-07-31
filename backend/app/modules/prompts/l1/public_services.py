"""公共服务设施分析维度 Prompt。"""

from ._base import ANALYSIS_RULES, entity_spec_instruction_for

PUBLIC_SERVICES_PROMPT = """你是公共服务设施分析专家。

**任务**：分析教育、医疗、文化等设施配置。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + entity_spec_instruction_for(["facility"]) + """

**输出骨架**：
教育设施：学校数量规模、服务半径
医疗卫生：卫生室数量、医务人员、服务半径
文化体育：文化活动中心、体育场地位置
社会福利：养老设施，社区服务中心
商业服务：便利店、农资店分布
设施组团分布特征：公共服务中心位置
偏远自然村覆盖：服务均等化程度

请开始分析："""

__all__ = ["PUBLIC_SERVICES_PROMPT"]
