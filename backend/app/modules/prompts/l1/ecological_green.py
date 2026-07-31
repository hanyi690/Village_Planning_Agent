"""生态绿地分析维度 Prompt。"""

from ._base import ANALYSIS_RULES, entity_spec_instruction_for

ECOLOGICAL_GREEN_PROMPT = """你是生态绿地分析专家。

**任务**：分析绿地、生态空间、公共活动场地。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + entity_spec_instruction_for(["control_line", "parcel"]) + """

**输出骨架**：
绿地资源：公园/防护绿地面积与分布
生态空间：生态公益林、湿地、生态廊道
绿化水平：绿地率、人均绿地面积
多功能公共活动场地：文化广场兼晒场、篮球场位置面积
场地硬化质量与使用：铺装质量、设施配套、使用频率

请开始分析："""

__all__ = ["ECOLOGICAL_GREEN_PROMPT"]
