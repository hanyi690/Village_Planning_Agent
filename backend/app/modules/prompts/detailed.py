"""
详细规划子图 Prompt 模板（河岸设计版）

核心改进：
1. 全局写作规则只定义一次
2. 各维度精简到核心内容
3. 输出格式"河岸设计"：刚性标题+软化内容
"""

# ==========================================
# 全局写作规则（只定义一次）
# ==========================================

WRITING_RULES = """
**写作原则**：
- 直接给出方案，不写推导过程
- 不使用"应该""建议""需要注意"等表述
- 数值必须具体，避免模糊表达
- 项目/设施清单必须使用表格格式

**格式禁止**：
- 禁止使用"第一章""第二章"等章节编号
- 禁止使用"第一条""第二条"等条目编号
- 禁止使用"（一）（二）"等分项编号
- 禁止使用"1.""2.""3."等数字编号作为小标题
- 使用【主题】冒号格式或表格替代编号
"""

# ==========================================
# 12个专业规划维度的 Prompt
# ==========================================

# 1. 产业规划
INDUSTRY_PLANNING_PROMPT = """你是乡村规划专家，精通农业产业、乡村旅游、文创产业规划。

**任务**：基于现状分析和规划思路，制定产业发展规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{WRITING_RULES}

**输出结构**：

【产业规划】

【产业发展定位】
定位口号：[10-30字特色定位]
核心目标：[至规划期末实现XX目标，具体指标]

【三链逻辑构建】
| 链条类型 | 核心策略 | 具体措施 |
| 强链 | [策略] | [1-2条措施] |
| 补链 | [策略] | [1-2条措施] |
| 拓链 | [策略] | [1-2条措施] |

【产业项目清单】
| 项目名称 | 建设内容 | 建设规模 | 选址位置 | 实施期限 |

【空间布局】
结构模式：[如"一心、一带、三区"]
功能分区：[各分区名称及定位]

---
"""


# 2. 道路交通规划
TRAFFIC_PLANNING_PROMPT = """你是乡村规划专家，精通农村公路设计规范和交通组织。

**任务**：制定村庄道路交通系统规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{professional_data_section}

{WRITING_RULES}

**输出结构**：

【道路交通规划】

【路网格局】
[一句话描述路网整体形态]

【道路等级规划】
| 道路类型 | 道路名称 | 宽度(m) | 长度(km) | 连接功能 |

【交通设施清单】
| 设施类型 | 规模/数量 | 位置 |

---
"""


# 3. 公共服务设施规划
PUBLIC_SERVICE_PROMPT = """你是乡村规划专家，精通教育、医疗、文化等设施配置标准。

**任务**：制定村庄公共服务设施配置规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{professional_data_section}

{WRITING_RULES}

**输出结构**：

【公共服务设施规划】

【设施配置清单】
| 设施类型 | 建筑规模(㎡) | 位置 | 功能配置 |

---
"""


# 4. 基础设施规划
INFRASTRUCTURE_PROMPT = """你是乡村规划专家，精通给水、排水、电力、通信等系统设计。

**任务**：制定村庄基础设施系统规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{WRITING_RULES}

**输出结构**：

【基础设施规划】

【给水工程】
- 水源：[类型及位置]
- 供水规模：[X]m³/日
- 管网：主管DN[X]，总长[X]km

【排水工程】
- 处理规模：[X]m³/日，工艺[X]
- 管网：管径DN[X]，总长[X]km

【电力工程】
- 用电负荷：[X]kW
- 变压器：容量[X]kVA，位置[X]

【工程量汇总表】
| 设施类型 | 规模 | 单位 | 备注 |

---
"""


# 5. 生态绿地规划
ECOLOGICAL_PROMPT = """你是乡村规划专家，精通生态保护、景观设计、园林绿化。

**任务**：制定村庄生态绿地系统规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{WRITING_RULES}

**输出结构**：

【生态绿地规划】

【生态空间格局】
[一句话描述生态结构]

【绿地指标】
| 指标名称 | 现状值 | 目标值 |
| 绿地率 | [X]% | [X]% |
| 人均公园绿地 | [X]㎡ | [X]㎡ |

【绿地系统】
| 绿地类型 | 名称 | 面积(㎡) | 位置 |

---
"""


# 6. 防灾减灾规划
DISASTER_PREVENTION_PROMPT = """你是乡村规划专家，精通灾害风险评估和防灾设施配置。

**任务**：制定村庄防灾减灾规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{WRITING_RULES}

**输出结构**：

【防灾减灾规划】

【灾害风险评估】
- 主要灾害：[类型]
- 高风险区：[位置]，面积[X]公顷

【防灾设施清单】
| 设施类型 | 数量 | 位置 | 规模/标准 |

---
"""


# 7. 历史文保规划
HERITAGE_PROMPT = """你是乡村规划专家，精通文化遗产保护、文物建筑修复。

**任务**：制定村庄历史文化遗产保护规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{WRITING_RULES}

**输出结构**：

【历史文化保护规划】

【文化遗产清单】
| 类型 | 名称 | 等级 | 位置 | 保护措施 |

---
"""


# 8. 村庄风貌指引
LANDSCAPE_PROMPT = """你是乡村规划专家，精通建筑立面整治和乡土材料运用。

**任务**：制定村庄风貌控制和引导规划。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{WRITING_RULES}

**输出结构**：

【村庄风貌指引】

【风貌定位】
[一句话描述风貌类型及主题]

【建筑风貌控制】
- 高度：核心区≤[X]层，一般区≤[X]层
- 风格：[类型]
- 色彩：主色调[X]，辅助色[X]

【整治清单表】
| 类型 | 内容 | 数量 | 单位 |

---
"""


# 9. 建设项目库
PROJECT_BANK_PROMPT = """你是乡村规划专家，精通项目策划与实施管理。

**任务**：整合各专业规划，建立建设项目库。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**各专业规划摘要**：
{dimension_plans}

{WRITING_RULES}

**输出结构**：

【建设项目库】

【近期项目】（1-2年）
| 项目名称 | 建设内容 | 规模 | 选址 |

【中期项目】（3-5年）
| 项目名称 | 建设内容 | 规模 | 选址 |

【远期项目】（5-10年）
| 项目名称 | 建设内容 | 规模 | 选址 |

---
"""


# 10. 空间结构规划
SPATIAL_STRUCTURE_PROMPT = """你是乡村规划专家，精通国土空间规划与功能分区。

**任务**：制定村庄空间结构规划方案。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{WRITING_RULES}

**输出结构**：

【空间结构规划】

【空间结构模式】
[如"一核两带三区"]

【功能分区表】
| 分区类型 | 面积(公顷) | 位置 | 功能定位 |

【边界管控】
- 村庄建设边界：面积[X]公顷
- 基本农田红线：面积[X]公顷

---
"""


# 11. 土地利用规划
LAND_USE_PLANNING_PROMPT = """你是乡村规划专家，精通土地调查评价与用途管制。

**任务**：制定村庄土地利用规划方案。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{WRITING_RULES}

**输出结构**：

【土地利用规划】

【土地利用结构调整表】
| 地类 | 现状(公顷) | 规划(公顷) | 变化(公顷) |

【土地用途分区表】
| 分区名称 | 面积(公顷) | 管控要求 |

---
"""


# 12. 居民点规划
SETTLEMENT_PLANNING_PROMPT = """你是乡村规划专家，精通农村住宅设计与村庄整治。

**任务**：制定村庄居民点规划方案。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

{WRITING_RULES}

**输出结构**：

【居民点规划】

【居民点布局模式】
[集中/组团式/散点式]

【宅基地规划表】
| 项目 | 数量/规模 |
| 现状宅基地 | [X]处，总面积[X]公顷 |
| 新增宅基地 | [X]处，面积[X]公顷 |
| 腾退宅基地 | [X]处，面积[X]公顷 |

---
"""


# ==========================================
# 辅助函数
# ==========================================

def get_dimension_prompt(dimension_key: str, **kwargs) -> str:
    """获取指定维度的格式化Prompt"""
    dimension_map = {
        "industry": INDUSTRY_PLANNING_PROMPT,
        "spatial_structure": SPATIAL_STRUCTURE_PROMPT,
        "land_use_planning": LAND_USE_PLANNING_PROMPT,
        "settlement_planning": SETTLEMENT_PLANNING_PROMPT,
        "traffic": TRAFFIC_PLANNING_PROMPT,
        "traffic_planning": TRAFFIC_PLANNING_PROMPT,
        "public_service": PUBLIC_SERVICE_PROMPT,
        "infrastructure": INFRASTRUCTURE_PROMPT,
        "infrastructure_planning": INFRASTRUCTURE_PROMPT,
        "ecological": ECOLOGICAL_PROMPT,
        "disaster_prevention": DISASTER_PREVENTION_PROMPT,
        "heritage": HERITAGE_PROMPT,
        "landscape": LANDSCAPE_PROMPT,
        "project_bank": PROJECT_BANK_PROMPT
    }

    template = dimension_map.get(dimension_key, "")
    if not template:
        return ""

    # 注入全局写作规则
    kwargs["WRITING_RULES"] = WRITING_RULES

    # 动态生成当前日期
    if not kwargs.get("current_date"):
        from datetime import datetime
        kwargs["current_date"] = datetime.now().strftime("%Y年%m月")

    # 处理 professional_data 参数
    professional_data = kwargs.pop("professional_data", None)
    if professional_data:
        kwargs["professional_data_section"] = _generate_professional_data_section(dimension_key, professional_data)
    elif "professional_data_section" not in kwargs:
        kwargs["professional_data_section"] = ""

    # 处理缺失参数
    for param in ["project_name", "analysis_report", "planning_concept", "constraints",
                  "knowledge_context", "dimension_plans"]:
        if param not in kwargs:
            kwargs[param] = ""

    return template.format(**kwargs)


def _generate_professional_data_section(dimension_key: str, professional_data: dict = None) -> str:
    """生成专业数据部分的 Prompt 文本"""
    if not professional_data:
        return ""

    # 处理字符串输入
    if isinstance(professional_data, str):
        return f"\n**【专业数据】**：\n{professional_data}\n"

    sections = []

    # 道路交通规划维度的专业数据
    if dimension_key in ["traffic", "traffic_planning"]:
        if professional_data.get("connectivity_metrics"):
            conn = professional_data["connectivity_metrics"]
            sections.append(f"""
**【专业数据 - 路网连通度分析】**：
- 路网密度：{conn.get('network_density', 'N/A')} 公里/平方公里
- 连通性指数：{conn.get('connectivity_index', 'N/A')}
""")

        if professional_data.get("accessibility_analysis"):
            acc = professional_data["accessibility_analysis"]
            sections.append(f"""
**【专业数据 - 可达性分析】**：
- 服务区域覆盖：{acc.get('coverage_ratio', 'N/A')}
""")

    # 公共服务设施规划维度的专业数据
    elif dimension_key == "public_service":
        if professional_data.get("population_structure"):
            pop = professional_data["population_structure"]
            sections.append(f"""
**【专业数据 - 人口结构】**：
- 预测人口：{pop.get('total_population', 'N/A')} 人
""")

    if sections:
        return "\n".join(sections)

    return ""


def get_specialized_data(dimension_key: str, state: dict) -> dict:
    """获取专业数据（占位函数）"""
    return {}


# ==========================================
# 导出
# ==========================================

__all__ = [
    "WRITING_RULES",
    "INDUSTRY_PLANNING_PROMPT",
    "TRAFFIC_PLANNING_PROMPT",
    "PUBLIC_SERVICE_PROMPT",
    "INFRASTRUCTURE_PROMPT",
    "ECOLOGICAL_PROMPT",
    "DISASTER_PREVENTION_PROMPT",
    "HERITAGE_PROMPT",
    "LANDSCAPE_PROMPT",
    "PROJECT_BANK_PROMPT",
    "SPATIAL_STRUCTURE_PROMPT",
    "LAND_USE_PLANNING_PROMPT",
    "SETTLEMENT_PLANNING_PROMPT",
    "get_dimension_prompt",
    "get_specialized_data",
]