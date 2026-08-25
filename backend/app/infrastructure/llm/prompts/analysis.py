"""
现状分析子图 Prompt 模板

包含12个分析维度的精简 Prompt。
"""

# ==========================================
# 公共规则（约100字）
# ==========================================

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
- 每个可核验的现状事实单独成行，并以“【事实】”开头；事实必须直接来自输入数据或已注入的 KG evidence
- 正文至少包含 3 条“【事实】”行；若输入没有足够事实，明确写“【事实】数据中未提供”，不得只输出泛泛建议
"""

# ==========================================
# observations 段（P8：文末结构化观察契约 — L1 现状层）
# L1 观测 pass 只输出 typed observations；report_body 在 deterministic
# source validation 之后由独立的 report-synthesis pass 生成。
# observations 是下游空间定位/地名解析的唯一结构化来源；保存时写入 instruction 列，不参与展示。
# ==========================================

OBSERVATIONS_OUTPUT_GUIDE = """
【L1 typed observations 契约】
本段是当前 observe pass 的唯一输出契约，覆盖本 prompt 上方遗留的写作规则、Markdown
表格、输出骨架、【事实】行和“请开始分析”等正文指令。当前 pass 不执行报告写作：根对象
只能是 JSON `{{"observations": [...], "diagnostics": [...]}}`，不能输出自然语言正文、
Markdown、表格或把正文塞进 observations；report_body 只由后续 report-synthesis pass 生成。

本次是 L1 observe pass：只返回 observations，不返回 report_body，也不返回资产台账、
需求台账、coverage 或处理状态。正文会在 source segment、引用和状态通过校验后由
独立的 report-synthesis pass 生成，因此不能在本 pass 中用正文替代结构化观察。

每条 observation 必须先选择一个 fact_type，并且只能填写该类型的字段：
- spatial_entity：entity_type、name、locator（place_names/relation）、scale
- spatial_relation：subject_ref、predicate、object_ref
- scoped_metric：metric、scope、value、unit、counting_basis
- demand：demand_type、scope、beneficiary、spatial_requirement、locator
- constraint：constraint_type、applies_to_scope、strength、locator
- risk 或 opportunity：subject、scope、locator
- document_observation：subject、scope

所有类型都可填写 semantic_type、description、attributes、value、unit、
counting_basis、source_segment_ids、source_quote、source_refs、confidence、status。
空间 locator 只记录来源明确支持的粗粒度地点/关系线索，不填写坐标或几何；指标、全村
需求和政策事实不需要为了格式强行添加点位。每条事实必须可回指 source_segment_ids
与 source_quote；没有直接证据就标记 uncertain。

本维度允许提取的 fact_type 范围：{dimension_focus}

约束：
- 只可摘录来源已出现的事实，不得新增对象、数量、地点或关系
- 空间实体有明确地点时填写 locator；没有地点时保留为空并说明证据缺口
- 非空间事实不得把名称、指标或需求类型伪装成地点
- 无对象时 observations 返回空数组
"""

# ==========================================
# 12个分析维度的 Prompt（精简版）
# ==========================================

ANALYSIS_DIMENSIONS = {
    "location": {
        "name": "区位与对外交通分析",
        "prompt": """你是区位分析专家。

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
    },

    "socio_economic": {
        "name": "社会经济分析",
        "prompt": """你是社会经济分析专家。

**任务**：分析村庄人口、经济、产业状况。你的输出将被用于提取规划文本第5条（规划范围）的村庄名称和第8条（规划指标）的人口数据。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

{professional_data_section}

""" + ANALYSIS_RULES + """

**输出骨架**：
行政区划：下辖[X]个自然村，完整名单：[村名1]、[村名2]、[村名3]…（逐一完整列出，用顿号分隔）

人口结构表（必须含分隔行）：
| 指标 | 数值 |
| :--- | :--- |
| 户籍人口 | [X]人 |
| 常住人口 | [X]人 |
| 户数 | [X]户 |
| 劳动力 | [X]人 |
| 外出务工 | [X]人 |
| 老龄化率 | [X]% |

产业构成：
第一产业：[具体作物/养殖类型]，种植面积[X]亩/公顷，年产量[X]，年产值[X]万元
第二产业：[具体加工类型]，企业/作坊[X]家，年产值[X]万元，带动就业[X]人
第三产业：[具体服务业类型]，年接待/服务量[X]，年收入[X]万元
特色农产品：[名称]（种植[X]亩，年产值[X]万元，品牌/认证情况）
收入水平：人均纯收入[X]元/年，主要收入来源分布（农业[X]%/务工[X]%/经营[X]%）
劳动力情况：劳动力[X]人（占总人口[X]%），外出务工[X]人（占劳动力[X]%），本地就业[X]人

请开始分析："""
    },

    "villager_wishes": {
        "name": "村民意愿与诉求分析",
        "prompt": """你是村民意愿分析专家。

**任务**：分析村民发展期望与诉求。参照村庄现状台账和需求台账的结构化格式输出。

**规划任务**：{task_description}

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出结构**：

【村庄发展诉求】

产业发展诉求：
【现状问题】[具体描述产业结构单一、经济效益不高等问题]
【发展诉求】[具体诉求，如发展XX种植、结合XX资源发展XX产业]

环境美化诉求：
【现状问题】[具体描述道路硬化不足、景观缺乏等问题]
【发展诉求】[具体诉求，如推进道路硬化、河道修复、生态修复等]

配套设施诉求：
【现状问题】[具体描述公共服务与基础设施缺乏、维护不善等问题]
【发展诉求】[具体诉求，如盘活废弃设施、建设综合服务中心、加强设施管理维护等]

诉求迫切性排序：生活保障→环境改善→增收致富→公共服务（按优先级排列）

请开始分析："""
    },

    "superior_planning": {
        "name": "上位规划与政策导向分析",
        "prompt": """你是上位规划分析专家。

**任务**：分析上位规划要求与政策约束。

**约束条件**：{constraints}

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
规划定位要求：功能定位类型（生态保护型/农业发展型/工业带动型/特色旅游型/综合发展型）
规划约束识别：生态红线、基本农田、城镇开发边界
政策背景分析：乡村振兴政策、地方专项政策（如百千万工程）
指标任务分解：耕地保有量、生态保护指标

请开始分析："""
    },

    "natural_environment": {
        "name": "自然环境分析",
        "prompt": """你是自然环境分析专家。

**任务**：分析气候、地形、林地、水文条件。地质灾害数据将被用于规划文本第17条（村庄安全和防灾减灾）。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

{professional_data_section}

""" + ANALYSIS_RULES + """

**输出骨架**（四个子主题）：
气候：气候类型、年均降水[X]mm、年均温度[X]℃、日照时数[X]h
地质与地形地貌：地形类型（山地/丘陵/平原）、海拔范围[X]-[X]m
地质灾害隐患点（必须含表格，含分隔行）：
| 灾害类型 | 数量(处) | 影响范围 | 主要分布位置 |
| :--- | :--- | :--- | :--- |
| 滑坡 | [X] | [自然村/道路/农田] | [具体位置] |
| 崩塌 | [X] | [自然村/道路/农田] | [具体位置] |
| 泥石流 | [X] | [自然村/道路/农田] | [具体位置] |
林地资源：林地面积[X]公顷（占比[X]%）、主要树种、森林覆盖率[X]%
水文与田园资源：主要河流[X]条、水库[X]座（总库容[X]万m³）、灌溉水源类型

请开始分析："""
    },

    "land_use": {
        "name": "土地利用分析",
        "prompt": """你是土地利用分析专家。

**任务**：分析各类用地分布与利用效率。你的输出将被用于规划文本的规划指标表（表2-1）和土地利用结构调整表（表3-X）。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
土地总用地面积：[X]公顷

用地结构表（必须含分隔行）：
| 用地类型 | 面积(公顷) | 占比(%) |
| :--- | :--- | :--- |
| 农业用地 | [X] | [X] |
| 建设用地 | [X] | [X] |
| 生态用地 | [X] | [X] |
| 水域 | [X] | [X] |
| 合计 | [X] | 100 |

耕地详情：耕地总面积[X]公顷（水田[X]公顷、旱地[X]公顷）、人均耕地[X]亩
林地详情：林地总面积[X]公顷（商业林[X]公顷、生态公益林[X]公顷）、森林覆盖率[X]%
建设用地详情：村庄建设用地[X]公顷（宅基地[X]公顷、公共设施用地[X]公顷、道路交通用地[X]公顷）
空间分布特征：建设用地形态（条带状/团块状/点状），描述分布规律
土地破碎化与闲置：耕地破碎度、闲置建设用地位置与原因
利用效率：建筑密度、容积率、土地利用强度

请开始分析："""
    },

    "traffic": {
        "name": "道路交通分析",
        "prompt": """你是道路交通分析专家。

**任务**：分析对外与内部道路系统。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
对外交通：连接道路等级、与主干道距离
内部交通：铺装质量分类（硬化/砂石/土路占比）、道路宽度
交通设施：公交候车亭位置、停车场位置规模、货运通道
出行特征：出行方式、高峰时段压力

请开始分析："""
    },

    "public_services": {
        "name": "公共服务设施分析",
        "prompt": """你是公共服务设施分析专家。

**任务**：分析教育、医疗、文化等设施配置。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
教育设施：学校数量规模、服务半径
医疗卫生：卫生室数量、医务人员、服务半径
文化体育：文化活动中心、体育场地位置
社会福利：养老设施、社区服务中心
商业服务：便利店、农资店分布
设施组团分布特征：公共服务中心位置
偏远自然村覆盖：服务均等化程度

请开始分析："""
    },

    "infrastructure": {
        "name": "基础设施分析",
        "prompt": """你是基础设施分析专家。

**任务**：分析供水、供电、排水、通信、环卫设施。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
供水系统：水源类型、供水方式、管网覆盖率
排水系统：雨水排放形式、污水处理方式
供电系统：电网接入、变压器容量
能源设施：水电站位置容量、新能源设施
通信网络：移动/宽带覆盖
环卫设施：垃圾收集点分布、转运频率、保洁体系

请开始分析："""
    },

    "ecological_green": {
        "name": "生态绿地分析",
        "prompt": """你是生态绿地分析专家。

**任务**：分析绿地、生态空间、公共活动场地。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
绿地资源：公园/防护绿地面积与分布
生态空间：生态公益林、湿地、生态廊道
绿化水平：绿地率、人均绿地面积
多功能公共活动场地：文化广场兼晒场、篮球场位置面积
场地硬化质量与使用：铺装质量、设施配套、使用频率

请开始分析："""
    },

    "architecture": {
        "name": "建筑分析",
        "prompt": """你是建筑分析专家。

**任务**：分析建筑质量、年代、高度、功能特征。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
建筑规模：建筑总量、总面积、建筑密度
建筑年代：各年代建筑比例
建筑质量等级：A/B/C/D四级数量占比、危房分布
新老建筑空间关系：新旧分布特征、新建区域位置
建筑高度特征：普遍层数、高层建筑位置功能
建筑风格：传统风貌、地域特色

请开始分析："""
    },

    "historical_culture": {
        "name": "历史文化分析",
        "prompt": """你是历史文化分析专家。

**任务**：分析历史文化遗产、民俗、非遗、传统美食、民间信仰。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**（六个子主题）：
传统风貌建筑：祠堂数量位置规模、特色民居类型
历史环境要素：古树名木树种树龄、古道古桥等遗存位置
非物质文化遗产：传统技艺、民俗表演、节庆习俗
传统美食与习俗：特色小吃、制作工艺传承
民间信仰：位置、祭祀活动
文化价值与传承：建村年代、名人轶事、保护措施

请开始分析："""
    }
}

# ==========================================
# 辅助函数
# ==========================================

_L1_OBSERVATION_FOCUS = {
    "location": "自然村、现状道路、对外交通节点、现状交通设施",
    "socio_economic": "自然村、现状产业点、现状经营设施",
    "villager_wishes": "村民明确提到的现状设施、现状项目和所在自然村",
    "superior_planning": "上位规划明确提到的现状边界、保护对象、现状约束位置",
    "natural_environment": "现状河流、山体、林地、灾害点和所在自然村",
    "land_use": "现状地类、现状分区和所在自然村",
    "traffic": "现状道路、桥梁、交通设施和所在自然村",
    "public_services": "现状公共服务设施和所在自然村",
    "infrastructure": "现状给排水、电力、通信、环卫设施和所在自然村",
    "ecological_green": "现状生态斑块、河流、林地和所在自然村",
    "architecture": "现状建筑、建筑群和所在自然村",
    "historical_culture": "现状古建筑、古树、遗址、传统村落和所在自然村",
}


def _observations_output_guide(natural_villages: str = "", dimension_key: str = "") -> str:
    nv = (natural_villages or "").strip()
    nv_suffix = f"（如 {nv}）" if nv else ""
    focus = _L1_OBSERVATION_FOCUS.get(dimension_key, "本维度报告正文明确出现的现状对象")
    from app.domain.assessment.dimension_contracts import get_dimension_semantic_contract

    allowed = ", ".join(
        get_dimension_semantic_contract(dimension_key, 1).get("l1_fact_types", [])
    )
    return OBSERVATIONS_OUTPUT_GUIDE.format(
        nv_suffix=nv_suffix,
        dimension_focus=f"{allowed}（关注：{focus}）",
    )


def get_dimension_prompt(dimension_key: str, raw_data: str = "", village_name: str = "",
                        professional_data: dict = None,
                        task_description: str = "", constraints: str = "",
                        knowledge_context: str = "",
                        revision_instruction: str = "",
                        has_images: bool = False,
                        natural_villages: str = "") -> str:
    """
    获取指定维度的 Prompt 模板

    Args:
        dimension_key: 维度键名
        raw_data: 原始村庄数据
        village_name: 村庄名称（用于数据约束）
        professional_data: 来自黑板的专业数据（可选）
        task_description: 规划任务描述（用于 villager_wishes 维度）
        constraints: 约束条件（用于 superior_planning 维度）
        knowledge_context: 知识库检索内容（可选）
        revision_instruction: 级联修订指令（可选）
        has_images: 是否有上传图片（用于多模态分析提示）

    Returns:
        格式化后的 Prompt 字符串
    """
    if dimension_key not in ANALYSIS_DIMENSIONS:
        raise ValueError(f"未知的分析维度: {dimension_key}")

    prompt = ANALYSIS_DIMENSIONS[dimension_key]["prompt"]

    # 替换村名
    effective_village_name = village_name or "该村"
    prompt = prompt.replace("{village_name}", effective_village_name)

    # Professional data section is now injected by DataPipeline upstream

    result = prompt.format(
        raw_data=raw_data,
        professional_data_section=professional_data if professional_data else "",
        task_description=task_description if task_description else "未提供具体规划任务",
        constraints=constraints if constraints else "无特殊约束",
        knowledge_context=knowledge_context if knowledge_context else "暂无相关规范标准参考"
    )

    # 添加修订指令（级联修订场景）
    if revision_instruction:
        result = revision_instruction + "\n\n" + result

    # 添加图片分析提示（多模态场景）
    if has_images:
        result += "\n\n**【上传图片分析指引】**：\n请结合上传的图片分析村庄现状。图片可能展示村庄实景、设施、环境、建筑等。"

    # P8: 文末 observations 段引导（内部指令，保存时写入 instruction 列，不参与展示）
    result += _observations_output_guide(natural_villages, dimension_key=dimension_key)

    return result



def list_dimensions():
    """列出所有分析维度"""
    return [
        {
            "key": key,
            "name": value["name"]
        }
        for key, value in ANALYSIS_DIMENSIONS.items()
    ]




# ==========================================
# 导出
# ==========================================

__all__ = [
    "ANALYSIS_DIMENSIONS",
    "ANALYSIS_RULES",
    "OBSERVATIONS_OUTPUT_GUIDE",
    "get_dimension_prompt",
    "list_dimensions",
]
