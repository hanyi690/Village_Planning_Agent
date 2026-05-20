"""
规划思路子图 Prompt 模板

包含4个规划维度的专业 Prompt 和汇总 Prompt。
"""

# ==========================================
# 全局写作规则（所有维度共享，由 get_dimension_prompt 注入）
# ==========================================
GLOBAL_CONCEPT_RULES = """
【全局写作规则】
你撰写的是村庄规划思路文件，直接用于编制审批和规划文本第7条（村庄发展定位和目标）的生成。
- 只写结论性内容，不写推导过程、不写"具有…意义"等评价。
- 禁止使用："需要注意的是…""总体来看""应当""建议"等套话。
- 语言简洁有力，每个定位/策略一行，用换行符分隔。
- 所有数据必须具体，避免模糊表达（"约X人"→"X人"）。
"""

# ==========================================
# 4个规划维度的 Prompt（精简版，只保留输出骨架）
# ==========================================

# 1. 资源禀赋分析
RESOURCE_ENDOWMENT_PROMPT = """你是资源禀赋分析专家。

**任务**：基于现状分析报告，梳理村庄的核心资源禀赋，包括资源的类型、具体名称和规模数量。

**输出骨架**（每行一个资源类别，"资源类型：具体资源（规模/数量）"格式）：
民俗资源：[具体项目]（[级别/传承历史/活动规模]）
自然资源：[具体项目]（[面积/覆盖率/等级]）
历史古迹：[具体项目]（[年代/面积/保护等级]）
特色产业：[具体项目]（[年产值/带动就业/规模]）
唯一性标签：【全镇唯一】[资源]、【全县唯一】[资源]、【区域唯一】[资源]

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 参考规范：{knowledge_context}
{professional_data_section}
"""

# 2. 规划定位分析
PLANNING_POSITIONING_PROMPT = """你是规划定位分析专家。

**任务**：基于资源禀赋、上位规划要求和现状分析，确定村庄的功能定位和分类。

**输出骨架**（多行定位，每行一个；释义放在所有定位之后）：
村庄分类：[集聚提升类/城郊融合类/特色保护类/搬迁撤并类]
[定位1] — 如"XX文化生态保育村"
[定位2] — 如"XX特色产业村"
[定位3] — 如"XX旅游特色村"
上位规划衔接：[说明该定位与上位规划（市县总规、乡镇总规）的关系和依据]

【形象定位】
[对仗工整的8-12字宣传口号]
（释义：[用2-3句话解释形象口号的含义，说明如何将村庄核心资源凝练为品牌表达]）

（定位释义：[用2-3句话解释以上定位的含义和依据，引用具体资源数据和上位规划要求]）

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 参考规范：{knowledge_context}
- 前序资源禀赋分析：{layer2_contexts}
"""

# 3. 发展目标分析
DEVELOPMENT_GOALS_PROMPT = """你是发展目标分析专家。

**任务**：基于规划定位，制定村庄发展的总体目标、核心指标和发展规模预测。

**输出骨架**：
[总体目标：一句话概括，如"XX市特色XX综合开发示范村"]

核心指标目标：
- 耕地保有量：[X]公顷（约束性）
- 永久基本农田保护面积：[X]公顷（约束性）
- 生态保护红线面积：[X]公顷（约束性）
- 村庄建设用地规模：[X]公顷（约束性）
- 林地保有量：[X]公顷（预期性）
- 森林覆盖率：≥[X]%（预期性）
- 常住人口规模：[X]人（预期性）

【发展规模】
一、人口规模预测
采用数学模型 Pn=P0(1+K)^n 进行预测，其中Pn为规划期末人口数，P0为基期年人口总数，K为规划期内人口增长率，n为预测年限。
结合现状户籍人口数据、国家/地区人口自然增长率、以及村庄产业发展吸引的外来就业人口（机械增长），预测规划期末（2035年）的人口规模。
需明确给出：基期人口数[X]人、自然增长率[X]‰、机械增长人口[X]人、预测结果[X]人。

二、用地规模预测
根据未来产业发展和人口增长需求，预测规划期末的用地规模变化。
需明确给出：现状村庄建设用地[X]公顷、规划期末村庄建设用地[X]公顷、新增建设用地[X]公顷。

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 专业数据：{professional_data_section}
- 约束条件：{constraints}
- 参考规范：{knowledge_context}
- 前序规划思路：{layer2_contexts}
"""

# 4. 规划策略分析
PLANNING_STRATEGIES_PROMPT = """你是规划策略分析专家。

**任务**：基于规划定位和发展目标，制定系统性的规划策略。策略之间应有逻辑关联，形成"诊断→方向→措施"的闭环。

**输出骨架**（每行一个策略，"关键词——策略名（针对[现状问题]，[具体措施]）"格式）：
生态优先——生态保护网格化（针对[现状问题]，[具体措施]，覆盖[面积/范围]）
产业振兴——主导产业特色化（针对[现状问题]，[具体措施]，预期带动[就业/收入]）
设施完善——基础设施标准化（针对[现状问题]，[具体措施]，覆盖[X]个自然村）
人居提升——村庄风貌优质化（针对[现状问题]，[具体措施]，涉及[X]处建筑/节点）
治理有效——乡村治理现代化（针对[现状问题]，[具体措施]）
[可补充其他策略，每条一行]

策略逻辑关系：[用1-2句话说明以上策略之间的配合关系，如"生态保护是产业发展的基础，产业发展为设施建设提供资金，设施完善支撑人居提升"]

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 参考规范：{knowledge_context}
- 前序规划思路：{layer2_contexts}
"""



# 获取维度 Prompt 的函数
# ==========================================

def get_dimension_prompt(dimension_key: str, analysis_report: str = "",
                         task_description: str = "", constraints: str = "",
                         professional_data: dict = None,
                         knowledge_context: str = "",
                         summary_context: str = "",
                         layer2_contexts: str = "") -> str:
    """
    获取规划思路维度的 Prompt 模板

    Args:
        dimension_key: 维度键名
        analysis_report: 现状分析报告
        task_description: 规划任务描述
        constraints: 约束条件
        professional_data: 专业数据（可选）
        knowledge_context: RAG 知识上下文（可选）
        summary_context: 摘要背景上下文（Phase 4，可选）

    Returns:
        格式化后的 Prompt 字符串
    """
    dimension_map = {
        "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
        "planning_positioning": PLANNING_POSITIONING_PROMPT,
        "development_goals": DEVELOPMENT_GOALS_PROMPT,
        "planning_strategies": PLANNING_STRATEGIES_PROMPT,
    }

    prompt_template = dimension_map.get(dimension_key, "")
    if not prompt_template:
        return ""

    # 生成专业数据部分
    professional_data_section = ""
    if isinstance(professional_data, str):
        professional_data_section = f"\n专业数据参考：\n{professional_data}\n"
    elif professional_data:
        # 可扩展 dict 格式化逻辑
        pass

    # 构建知识上下文
    knowledge_section = ""
    if knowledge_context:
        knowledge_section = f"\n**参考规范与标准**\n{knowledge_context}\n"

    # Phase 4 摘要背景
    summary_section = ""
    if summary_context:
        summary_section = f"\n{summary_context}\n"

    format_params = {
        "analysis_report": analysis_report,
        "task_description": task_description,
        "constraints": constraints,
        "professional_data_section": professional_data_section,
        "knowledge_context": knowledge_context,
        "knowledge_section": knowledge_section,
        "summary_section": summary_section,
        "layer2_contexts": layer2_contexts or "暂无前序维度参考",
    }

    formatted = prompt_template.format(**format_params)

    # 追加知识上下文（如果模板中没有 knowledge_context 占位符）
    if knowledge_section and "{knowledge_context}" not in prompt_template:
        formatted += knowledge_section

    # 追加 Phase 4 摘要背景
    if summary_section:
        formatted += summary_section

    # 注入全局写作规则
    formatted += GLOBAL_CONCEPT_RULES

    return formatted


def get_specialized_data(dimension_key: str, state: dict) -> dict:
    """
    获取专业数据（占位函数）
    
    用于 GenericPlanner 的 Hook 接口，可在子类中重写以注入专业脚本生成的数据。
    
    Args:
        dimension_key: 维度键名
        state: 当前状态字典
        
    Returns:
        专业数据字典
    """
    return {}


# ==========================================
# 导出
# ==========================================

__all__ = [
    "RESOURCE_ENDOWMENT_PROMPT",
    "PLANNING_POSITIONING_PROMPT",
    "DEVELOPMENT_GOALS_PROMPT",
    "PLANNING_STRATEGIES_PROMPT",
    "get_dimension_prompt",
    "get_specialized_data",
]
