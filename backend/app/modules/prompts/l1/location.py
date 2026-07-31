"""区位与对外交通分析维度 Prompt。"""

from ._base import ANALYSIS_RULES

LOCATION_PROMPT = """你是区位分析专家。

**任务**：分析村庄地理位置与交通区位。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**（5层级展开）：
[省]在[所在大区]的位置：描述
[市]在[省]的位置：描述
[县]在[市]的位置：描述
[镇]在[县]的位置：描述
[村]在[镇]的位置：描述（含道路编号、周边村庄）

请开始分析："""

__all__ = ["LOCATION_PROMPT"]
