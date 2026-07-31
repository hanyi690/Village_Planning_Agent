"""L1 Prompt 共享规则与实体类型定义。"""

ANALYSIS_RULES = """
**写作规则**：
- 使用"[主题]：描述内容"冒号格式
- 使用自然段落，不用编号列表（1.2.3.）
- 基于输入数据，不编造信息
- 缺失数据标注"数据中未提供"
- 村名：**{village_name}**
- 数值必须具体，带单位（公顷、人、㎡、km等）
- 需要用表格呈现的数据使用markdown表格，必须含分隔行（| :--- |）
**格式禁止**：
- 禁止使用"第一章""第二章"等章节编号
- 禁止使用"第一条""第二条"等条目编号
- 禁止使用"（一）（二）"等分项编号
- 禁止使用"1.""2.""3."等数字编号作为小标题
- 使用【主题】格式标记段落主题，用自然段落叙述内容
"""

ENTITY_TYPES = {
    "parcel": {
        "label": "地块",
        "instruction": "## EntitySpec: parcel - BSM={{bsm}}, DLBM={{dlbm}}, area_ha={{area}}, intended_use={{intended_use}}",
    },
    "road": {
        "label": "道路",
        "instruction": "## EntitySpec: road - name={{name}}, level={{level}}, width_m={{width_m}}, connects={{connects}}",
    },
    "facility": {
        "label": "设施",
        "instruction": "## EntitySpec: facility - type={{type}}, location={{loc}}, service_radius_m={{radius}}, status={{status}}",
    },
    "water": {
        "label": "水体",
        "instruction": "## EntitySpec: water - name={{name}}, area_ha={{area}}, type={{wtype}}",
    },
    "control_line": {
        "label": "控制线",
        "instruction": "## EntitySpec: control_line - type={{ctype}}, constraint={{constraint}}",
    },
    "building": {
        "label": "建筑物",
        "instruction": "## EntitySpec: building - bsm={{bsm}}, style={{style}}, heritage_status={{heritage}}",
    },
    "historical_site": {
        "label": "历史遗迹",
        "instruction": "## EntitySpec: historical_site - name={{name}}, level={{level}}, era={{era}}",
    },
}

ENTITY_SPEC_HEADER = """
## 实体填充指令
请在报告中识别下列类型的空间实体描述，使用以下格式之一标记：

"""


def entity_spec_instruction_for(types: list) -> str:
    """根据 entity types 列表渲染对应的指令段。"""
    if not types:
        return ""
    snippets = []
    for t in types:
        if t in ENTITY_TYPES:
            snippets.append(f"- {ENTITY_TYPES[t]['label']}: `{ENTITY_TYPES[t]['instruction']}`")
    if not snippets:
        return ""
    return ENTITY_SPEC_HEADER + "\n".join(snippets) + "\n"


__all__ = ["ANALYSIS_RULES", "ENTITY_TYPES", "ENTITY_SPEC_HEADER", "entity_spec_instruction_for"]
