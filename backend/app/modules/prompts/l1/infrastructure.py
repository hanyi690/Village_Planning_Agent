"""基础设施分析维度 Prompt。"""

from ._base import ANALYSIS_RULES, entity_spec_instruction_for

INFRASTRUCTURE_PROMPT = """你是基础设施分析专家。

**任务**：分析供水、供电、排水、通信、环卫设施。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + entity_spec_instruction_for(["facility", "control_line"]) + """

**输出骨架**：
供水系统：水源类型、供水方式、管网覆盖率
排水系统：雨水排放形式、污水处理方式
供电系统：电网接入、变压器容量
能源设施：水电站位置容量、新能源设施
通信网络：移动/宽带覆盖
环卫设施：垃圾收集点分布、转运频率、保洁体系

请开始分析："""

__all__ = ["INFRASTRUCTURE_PROMPT"]
