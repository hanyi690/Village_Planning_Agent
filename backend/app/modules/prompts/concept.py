"""
规划思路子图 Prompt 模板

包含4个规划维度的专业 Prompt 和汇总 Prompt。
"""

# ==========================================
# 全局写作规则（所有维度共享，由 get_dimension_prompt 注入）
# ==========================================
GLOBAL_CONCEPT_RULES = """
【全局写作规则】
你撰写的是村庄规划思路文件，直接用于编制审批。
- 只写结论性内容，不写推导过程、不写"具有…意义"等评价。
- 禁止使用："需要注意的是…""总体来看""应当""建议"等套话。
- 语言简洁有力，每个定位/策略一行，用换行符分隔。
"""

# ==========================================
# 4个规划维度的 Prompt（精简版，只保留输出骨架）
# ==========================================

# 1. 资源禀赋分析
RESOURCE_ENDOWMENT_PROMPT = """你是资源禀赋分析专家。

**任务**：基于现状分析报告，梳理村庄的核心资源禀赋。

**输出骨架**（每行一个资源类别，"资源类型：具体资源"格式）：
民俗资源：[具体项目]
自然资源：[具体项目]
历史古迹：[具体项目]
特色产业：[具体项目]
唯一性标签：【全镇唯一】[资源]、【全县唯一】[资源]、【区域唯一】[资源]

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
{professional_data_section}
"""

# 2. 规划定位分析
PLANNING_POSITIONING_PROMPT = """你是规划定位分析专家。

**任务**：基于资源禀赋和现状分析，确定村庄的功能定位。

**输出骨架**（多行定位，每行一个；释义放在所有定位之后）：
[定位1]
[定位2]
[定位3]
（释义：[用2-3句话解释以上定位的含义和依据]）

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 上位规划参考：{superior_planning_context}
- 前序资源禀赋分析：{layer2_contexts}
"""

# 3. 发展目标分析
DEVELOPMENT_GOALS_PROMPT = """你是发展目标分析专家。

**任务**：基于规划定位，用一句话概括村庄发展的总体目标。

**输出骨架**：
[一句话目标陈述，如"XX市特色XX综合开发示范村"]

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 前序规划思路：{layer2_contexts}
"""

# 4. 规划策略分析
PLANNING_STRATEGIES_PROMPT = """你是规划策略分析专家。

**任务**：基于规划定位和发展目标，制定系统性的规划策略。

**输出骨架**（每行一个策略，"关键词——策略名（针对的问题及具体措施）"格式）：
生态优先——生态保护网格化（针对[现状问题]，[具体措施]）
产业振兴——主导产业特色化（针对[现状问题]，[具体措施]）
治理有效——乡村治理现代化（针对[现状问题]，[具体措施]）
人居提升——村庄风貌优质化（针对[现状问题]，[具体措施]）
[可补充其他策略，每条一行]

**输入背景**：
- 现状分析报告：{analysis_report}
- 规划任务：{task_description}
- 约束条件：{constraints}
- 前序规划思路：{layer2_contexts}
"""



# 获取维度 Prompt 的函数
# ==========================================

def get_dimension_prompt(dimension_key: str, analysis_report: str = "",
                         task_description: str = "", constraints: str = "",
                         professional_data: dict = None,
                         superior_planning_context: str = "",
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
        superior_planning_context: 上位规划上下文（positioning 维度专用）
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
        "superior_planning_context": superior_planning_context or "暂无上位规划参考",
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
