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
- 村名强制使用：**{village_name}**
"""

# ==========================================
# 12个分析维度的 Prompt（精简版）
# ==========================================

ANALYSIS_DIMENSIONS = {
    "location": {
        "name": "区位与对外交通分析",
        "prompt": """你是区位分析专家。

**任务**：分析村庄地理位置与交通区位。

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

**任务**：分析村庄人口、经济、产业状况。

**输入数据**：
{raw_data}

{professional_data_section}

""" + ANALYSIS_RULES + """

**输出骨架**：
行政区划：下辖自然村名单（完整列出）
人口情况：户籍/常住人口、劳动力流失、老龄化程度
产业构成：第一/二/三产业描述，区分传统农业与特色农产品

请开始分析："""
    },

    "villager_wishes": {
        "name": "村民意愿与诉求分析",
        "prompt": """你是村民意愿分析专家。

**任务**：分析村民发展期望与诉求。

**规划任务**：{task_description}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
诉求迫切性排序：按第一至第四层级排序（生活保障→环境改善→增收致富→公共服务）
生活环境改善诉求：道路硬化、路灯、垃圾处理等具体需求
增收致富诉求：产业引入、就业机会等
参与意愿：参与积极性、投工投劳能力

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

**任务**：分析气候、地形、林地、水文条件。

**输入数据**：
{raw_data}

{professional_data_section}

""" + ANALYSIS_RULES + """

**输出骨架**（四个子主题）：
气候：气候类型、降水、温度、光照
地质与地形地貌：地形类型、地质灾害隐患点
林地资源：林地面积、类型、森林覆盖率
水文与田园资源：河流、水库、灌溉水源

请开始分析："""
    },

    "land_use": {
        "name": "土地利用分析",
        "prompt": """你是土地利用分析专家。

**任务**：分析各类用地分布与利用效率。

**参考规范**：
{knowledge_context}

**输入数据**：
{raw_data}

""" + ANALYSIS_RULES + """

**输出骨架**：
用地结构：农业/建设/生态用地面积与占比
空间分布特征：建设用地形态（条带状/团块状/点状）
土地破碎化与闲置：耕地破碎度、闲置建设用地位置与原因
利用效率：建筑密度、容积率、土地利用强度

请开始分析："""
    },

    "traffic": {
        "name": "道路交通分析",
        "prompt": """你是道路交通分析专家。

**任务**：分析对外与内部道路系统。

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
历史环境要素：古树名木树种树龄、古驿道古桥位置
非物质文化遗产：传统技艺、民俗表演、节庆习俗
传统美食与习俗：特色小吃、制作工艺传承
民间信仰：伯公坛、公王庙位置、祭祀活动
文化价值与传承：建村年代、名人轶事、保护措施

请开始分析："""
    }
}

# ==========================================
# 辅助函数
# ==========================================

def get_dimension_prompt(dimension_key: str, raw_data: str = "", village_name: str = "",
                        professional_data: dict = None,
                        task_description: str = "", constraints: str = "",
                        knowledge_context: str = "",
                        has_images: bool = False) -> str:
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

    # 生成专业数据部分
    professional_data_section = _generate_professional_data_section(dimension_key, professional_data)

    result = prompt.format(
        raw_data=raw_data,
        professional_data_section=professional_data_section,
        task_description=task_description if task_description else "未提供具体规划任务",
        constraints=constraints if constraints else "无特殊约束",
        knowledge_context=knowledge_context if knowledge_context else "暂无相关规范标准参考"
    )

    # 添加图片分析提示（多模态场景）
    if has_images:
        result += "\n\n**【上传图片分析指引】**：\n请结合上传的图片分析村庄现状。图片可能展示村庄实景、设施、环境、建筑等。"

    return result


def _generate_professional_data_section(dimension_key: str, professional_data: dict = None) -> str:
    """
    生成专业数据部分的 Prompt 文本

    Args:
        dimension_key: 维度键名
        professional_data: 来自黑板的专业数据

    Returns:
        专业数据部分的 Prompt 文本
    """
    if not professional_data:
        return ""

    # 处理字符串输入
    if isinstance(professional_data, str):
        return f"\n**【专业数据】**：\n{professional_data}\n"

    sections = []

    # 自然环境维度的专业数据
    if dimension_key == "natural_environment":
        if professional_data.get("soil_analysis"):
            soil = professional_data["soil_analysis"]
            sections.append(f"""
**【专业数据 - 土壤分析】**：
- 土壤类型：{', '.join([s['type'] for s in soil.get('soil_types', [])])}
- 土壤质量指数：{soil.get('soil_quality_index', 'N/A')}
""")

        if professional_data.get("hydrology_analysis"):
            hydro = professional_data["hydrology_analysis"]
            sections.append(f"""
**【专业数据 - 水文分析】**：
- 主要水系：{', '.join([w['name'] for w in hydro.get('water_systems', [])])}
""")

    # 社会经济维度的专业数据
    elif dimension_key == "socio_economic":
        if professional_data.get("population_structure"):
            pop = professional_data["population_structure"]
            sections.append(f"""
**【专业数据 - 人口结构】**：
- 劳动参与率：{pop.get('labor_force_participation_rate', 'N/A')}%
""")

        if professional_data.get("labor_force_analysis"):
            labor = professional_data["labor_force_analysis"]
            sections.append(f"""
**【专业数据 - 劳动力】**：
- 劳动力规模：{labor.get('labor_force_size', 'N/A')} 人
""")

    # 土地利用维度的专业数据
    elif dimension_key == "land_use":
        if professional_data.get("land_use_analysis"):
            land_use = professional_data["land_use_analysis"]
            sections.append(f"""
**【专业数据 - 土地利用】**：
- 总面积：{land_use.get('total_area', 'N/A')} 平方公里
""")

    # 道路交通维度的专业数据
    elif dimension_key == "traffic":
        if professional_data.get("connectivity_metrics"):
            conn = professional_data["connectivity_metrics"]
            sections.append(f"""
**【专业数据 - 路网连通度】**：
- 路网密度：{conn.get('network_density', 'N/A')} 公里/平方公里
""")

    if sections:
        return "\n".join(sections)

    return ""


def list_dimensions():
    """列出所有分析维度"""
    return [
        {
            "key": key,
            "name": value["name"]
        }
        for key, value in ANALYSIS_DIMENSIONS.items()
    ]


def get_specialized_data(dimension_key: str, state: dict) -> dict:
    """
    获取专业数据（占位函数）

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
    "ANALYSIS_DIMENSIONS",
    "ANALYSIS_RULES",
    "get_dimension_prompt",
    "list_dimensions",
    "get_specialized_data",
]