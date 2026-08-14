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
**用途说明**：
- 你的输出将被组装为村庄规划法定文本（.docx）的具体条文
- 参考风格：村庄规划法定文本（如各县市已批复的村庄规划文本）
- 语言特征：法规条文式直接陈述，简洁有力，不用模糊词

**写作原则**：
- 直接给出方案，不写推导过程
- 不使用"应该""建议""需要注意""总体来看""应当"等模糊表述
- 数值必须具体，避免模糊表达（如"约500人"→"500人"）
- 项目/设施清单必须使用表格格式

**表格格式（严格遵循）**：
- 所有表格必须有表头行和分隔行，格式为：
  | 列1 | 列2 | 列3 |
  | :--- | :--- | :--- |
  | 数据1 | 数据2 | 数据3 |
- 分隔行必须紧跟在表头行之后，使用 | --- | 或 | :--- | 格式
- 数值必须带单位（公顷、人、㎡、km等）
- 表格前后各留一个空行

**格式禁止**：
- 禁止使用"第一章""第二章"等章节编号
- 禁止使用"第一条""第二条"等条目编号
- 禁止使用"（一）（二）"等分项编号
- 禁止使用"1.""2.""3."等数字编号作为小标题
- 使用【主题】格式标记段落主题，用自然段落叙述内容
"""

# ==========================================
# GIS 工具与空间数据引导（P0-3 新增）
# 引导 LLM 在涉及空间布局的维度中主动引用现状用地指标和规划目标，
# 实现 L1/L2/L3 数据流闭环（详见 docs/superpowers/specs/2026-07-02-gis-review-exploration.md）
# ==========================================

GIS_TOOL_GUIDE = """
【空间数据与约束】
- 现状用地指标：耕地 {landuse_metrics_farmland} 公顷，建设用地 {landuse_metrics_construction} 公顷，生态红线 {landuse_metrics_ecological} 公顷
- 规划目标：农田保护区 {intent_targets_farmland} 公顷，村庄建设区 {intent_targets_construction} 公顷，生态保护区 {intent_targets_ecological} 公顷
- 涉及空间布局的维度（产业/公共设施/生态/交通/空间结构/土地利用）必须引用上述数据
- 生成设施清单时参考 facility_placer 服务半径标准：教育 500m、医疗 300m、养老 600m、村委会 500m、市场 1000m
- 数值若为 N/A 表示 GIS 数据未注入，按常规规划经验给出合理数值并标注"待 GIS 校核"
"""

CLAIMS_OUTPUT_GUIDE = """
【L3 输出契约】
你需要同时输出两部分（一次结构化返回）：
1. report_body：完整的规划报告正文（Markdown 散文 + 表格），用于组装村庄规划法定文本(.docx)；不得为空。
2. claims：本维度所有带证据的规划判断（结构化 claims 数组）。

每条 claim 必须是带证据的规划判断，包含：claim_id、statement、suggested_category、suggested_output_kind、
suggested_interventions、quantity/quantity_unit（若有）、implementation_phase、location_hints、
constraint_refs、objective_refs、evidence_refs、uncertainty。没有证据支持的位置、面积、地块或项目不得编造，
应留空并说明 uncertainty。suggested_category 只能是 project/facility/road/axis/restoration/protection/zone/action；
suggested_output_kind 只能是 parcel/polygon/point/line/action。对有明确位置证据的具体 project（例如服务中心、广场、停车场、观景点），应使用 point 作为小型定位输出；只有没有任何空间落位含义的管理/政策/培训事项才使用 action。claim 不是执行目标，不得填写最终 BSM、几何或 ClassificationDecision。

每个空间 claim 必须在首次生成时给出与对象类型对应的结构化参数，禁止把关键尺度只写在 statement：
- road 使用 road_parameters：action 只能是 preserve/new/upgrade/widen/harden/repair；其余字段为 road_level、length、roadbed_width、pavement_width、alignment_refs、connects；每个量值写成 {"value": 数值, "unit": "m|km"}。长度、路基宽、路面宽必须分开；connects 只写原文明确的两端对象，沿既有道路改造则把道路名写入 alignment_refs。缺少宽度标准且无证据时，不得编造，应改为非空间 action 或在 uncertainty 中说明无法形成可执行道路项目。
- facility 使用 facility_parameters：action 只能是 preserve/new/expand/relocate/repair；其余字段为 facility_type、service_radius、capacity、footprint_area；服务半径用 m/km，占地用 m2/ha。保留、新建、扩建、迁建不得混淆。
- axis 使用 axis_parameters：action 只能是 preserve/new/upgrade；axis_type 只能是 primary/secondary/spatial_control；其余字段为 direction、reference_features、connects、corridor_width；不得把发展轴退化成普通道路。
- zone/protection/restoration 以及 polygon/parcel project 使用 polygon_parameters。materialization_role 只能是 land_use_assignment/functional_overlay/protection_overlay/restoration_overlay/project_footprint。真正改变土地用途的 zone 才使用 land_use_assignment，并必须给 area_range（minimum、maximum、unit=m2|ha）；“一心一带多区”等功能结构使用 functional_overlay，不得伪装成地类重分类或虚构面积；保护和修复分别使用对应 overlay。
- 普通 project 可使用 project_parameters：project_type、action、capacity、footprint_area；action 只能是 preserve/new/expand/relocate/upgrade/widen/harden/repair/demolish。点项目仍须保留 location_hints。
单位必须使用以下闭集，禁止其他写法（禁止把数量/规模单位当作面积或长度单位）：
- 面积：公顷/ha、亩、平方米/m2、㎡
- 长度：米/m、千米/km
- 容量/体积：立方米/m3、升/l、吨/t
- 数量/规模：个、处、座、条、棵、株、人、户、间、栋、根、套
- 功率/电量：千瓦/kw、千瓦时/kwh
禁止写法：hm、hm²、km²、平方米的其它简写、"待定"、"无"；禁止用"处/户/座/人"作为 area_range 或 footprint_area 的面积单位。
所有参数只表达规划语义和来源量值，不得填写坐标、BSM、候选地块或几何；单位换算由确定性编译器完成。
report_body 写完整的法定文本报告正文（用【主题】标记段落、markdown 表格列清单）；claims 只写结构化判断，不要写解释文字。
"""

LOCATION_EVIDENCE_GUIDE = """
【空间位置证据闭集】
以下是上游报告与已绑定 GIS/KG 的可核验位置证据：
{location_evidence}

硬约束：
- 只能使用上面证据中出现、且与当前对象有直接关系的位置；不得从行政区划名单推断对象位置。
- 证据没有支持的位置必须留空，不能为了让表格完整而补写地点名。
- 位置实体不限于自然村，也可以是道路、水体、设施、地块、居民点、行政单元或其他已注册地点；但同一对象与该地点必须在上游证据中存在直接关系，仅出现名称不构成位置证据。
"""


# ==========================================
# 12个专业规划维度的 Prompt
# ==========================================

# 1. 产业规划
INDUSTRY_PLANNING_PROMPT = """你是乡村规划专家，精通农业产业、乡村旅游、文创产业规划。

**任务**：基于现状分析和规划思路，制定产业发展规划。你的输出将被用作规划文本第14条（产业发展空间安排）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【产业规划】

【产业发展定位】
定位口号：[10-30字特色定位]
核心目标：[至规划期末实现XX目标，具体指标]

【产业发展思路】
基于现状，阐述产业发展的总体逻辑。简要说明为何选择该主导产业，以及【三链逻辑构建】中强链、补链、拓链的策略是如何相互配合形成合力的。要求使用自然的段落叙述。

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

【产业体系构建】
纵向功能维度（产业链条）：研发 → 生产 → 加工 → 展销
横向产业维度（三大产业融合）：
- 产研基地（研发顶层）：良种培育、科研成果转化、职业农民培养
- 第一产业（生产）：[主导农产品]种植、[林下/畜牧/水产]养殖，产品流向第二产业
- 第二产业（加工）：药材加工、预制菜加工、木材加工，展示/销售流向第三产业
- 第三产业（展销/农旅融合）：休闲农业、生态旅游、特色农贸（三大板块互相支撑）

【产业项目细化】
第一产业项目：
1. [项目名]：[具体内容和规模]，位于[自然村]
2. [项目名]：...
（至少列出3-5个具体的一产项目）

第二产业项目：
1. [项目名]：[加工内容/工艺]，规模[X]㎡/年产能[X]，位于[自然村]
2. [项目名]：...
（至少列出2-3个具体的二产项目）

第三产业项目：
1. [项目名]：[业态/服务内容]，规模[X]㎡，位于[自然村]
2. [项目名]：...
（至少列出3-5个具体的三产项目）

【产业项目布局】
空间结构模式：[如"三心带动，五区联动"]
各功能区详细说明：
- [中心名称]：位于[X]，主要功能[简述]，带动区域[简述]
- [分区名称]：位于[X]，产业类型[简述]，发展形态[简述]
（对每个功能区和产业分区进行1-2句话说明）

产业项目布局表：
| 分区 | 产业类型 | 项目名 | 项目内容 | 位置 |
| :--- | :--- | :--- | :--- | :--- |
| [分区名] | [一产/二产/三产] | [项目名] | [具体内容] | [自然村] |

**输入背景**：同前

---
"""


# 2. 道路交通规划
TRAFFIC_PLANNING_PROMPT = """你是乡村规划专家，精通农村公路设计规范和交通组织。

**任务**：制定村庄道路交通系统规划。你的输出将被用作规划文本第16条（基础设施和公共服务设施建设）中道路交通部分的核心内容。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{professional_data_section}

{WRITING_RULES}

{GIS_TOOL_GUIDE}

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

**任务**：制定村庄公共服务设施配置规划。你的输出将被用作规划文本第16条（基础设施和公共服务设施建设）中公共服务部分的核心内容。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

{professional_data_section}

{WRITING_RULES}

{GIS_TOOL_GUIDE}

**输出结构**：

【公共服务设施规划】

【配置原则与策略】
基于村庄现状人口、可改造用地，阐述公共服务设施的总体布局策略。例如：是否计划利用闲置设施进行整合？是否形成新的公共服务中心？是否针对分散自然村采取特定覆盖方案？要求2-3句话的段落描述。

【设施配置清单】
| 设施类型 | 建筑规模(㎡) | 位置 | 功能配置 |

---
"""


# 4. 基础设施规划
INFRASTRUCTURE_PROMPT = """你是乡村规划专家，精通给水、排水、电力、通信等系统设计。

**任务**：制定村庄基础设施系统规划。你的输出将被用作规划文本第16条（基础设施和公共服务设施建设）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【基础设施规划】
用1段话概述基础设施的总体配置策略：各系统的规划原则、覆盖目标、建设标准。

【给水工程】
- 水源：[类型及位置]
- 供水规模：[X]m³/日
- 供水方式：[集中式/分散式]
- 管网：主管DN[X]，总长[X]km

【排水工程】
- 排水体制：[雨污分流/合流制]
- 处理规模：[X]m³/日，工艺[X]
- 管网：管径DN[X]，总长[X]km

【电力工程】
- 用电负荷：[X]kW
- 变压器：容量[X]kVA，数量[X]处
- 线路：总长[X]km

【通信工程】
- 宽带接入：[光纤/4G/5G]，覆盖率[X]%
- 基站：数量[X]处，位置[X]
- 管线：总长[X]km

【环卫工程】
- 垃圾收集点：[X]处，服务半径[X]m
- 垃圾处理方式：[转运/就地处理]
- 公共厕所：[X]座，位置[分布说明]

【工程量汇总表】
| 设施类型 | 规模 | 单位 | 数量 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| [给水管道/排水管道/电力线路/通信线路/环卫设施] | [规格] | [m/座/kVA] | [X] | [备注] |

---
"""


# 5. 生态绿地规划
ECOLOGICAL_PROMPT = """你是乡村规划专家，精通生态保护、景观设计、园林绿化。

**任务**：制定村庄生态绿地系统规划。你的输出将被用作规划文本第11条（生态保护修复）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【生态绿地规划】
用1-2段自然段落概述生态绿地系统的总体结构：生态本底特征、保护框架、核心指标目标。要求连贯叙述。

【生态空间格局】
用1-2句话描述生态空间的总体格局（如"一屏两廊多节点"），说明各生态要素的空间关系。

【绿地指标】
| 指标名称 | 现状值 | 目标值 | 依据标准 |
| :--- | :--- | :--- | :--- |
| 绿地率 | [X]% | [X]% | [标准] |
| 人均公园绿地 | [X]㎡ | [X]㎡ | [标准] |
| 森林覆盖率 | [X]% | [X]% | [标准] |
| 公共活动场地 | [X]处 | [X]处 | [标准] |

【绿地系统】
| 绿地类型 | 名称 | 面积(㎡) | 位置 | 功能 |
| :--- | :--- | :--- | :--- | :--- |
| [公园绿地/防护绿地/广场用地] | [名称] | [X] | [位置] | [功能] |

【生态管控要求】
说明生态保护的具体管控要求：生态保护红线范围、禁止建设活动类型、林地保护等级、水系保护要求等。要求自然段落叙述。

【实施计划】
| 阶段 | 时间 | 主要任务 | 责任主体 |
| :--- | :--- | :--- | :--- |
| 近期 | 1-2年 | [任务] | [主体] |
| 中期 | 3-5年 | [任务] | [主体] |
| 远期 | 5-10年 | [任务] | [主体] |

---
"""


# 6. 防灾减灾规划
DISASTER_PREVENTION_PROMPT = """你是乡村规划专家，精通灾害风险评估和防灾设施配置。

**任务**：制定村庄防灾减灾规划。你的输出将被用作规划文本第17条（村庄安全和防灾减灾）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【防灾减灾规划】
用1段话概述村庄面临的主要灾害风险类型和总体防灾策略。

【灾害风险评估】
| 灾害类型 | 风险等级 | 影响范围 | 隐患点数量 | 威胁对象 |
| :--- | :--- | :--- | :--- | :--- |
| [滑坡/崩塌/泥石流/洪水/火灾] | [高/中/低] | [区域] | [X]处 | [居民点/道路/农田] |

【防灾设施清单】
| 设施类型 | 数量 | 位置 | 规模/标准 |
| :--- | :--- | :--- | :--- |
| [避难场所/消防设施/监测点/排洪沟] | [X] | [位置] | [标准] |

【工程防治措施】
说明针对主要灾害的具体工程措施：挡土墙、截排水沟、削坡减载、锚固工程等。要求明确措施类型、布设位置和工程规模。

【应急管理体系】
说明应急管理的组织架构、预警机制、疏散路线、物资储备等软性措施。要求自然段落叙述。

---
"""


# 7. 历史文保规划
HERITAGE_PROMPT = """你是乡村规划专家，精通文化遗产保护、文物建筑修复。

**任务**：制定村庄历史文化遗产保护规划。你的输出将被用作规划文本第13条（历史文化传承与保护）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【历史文化保护规划】
用1-2段自然段落概述历史文化保护的总体策略：保护对象概要、保护原则、总体目标。要求连贯叙述。

【文化遗产清单】
历史文化资源保护表（划入历史文化保护线）：
| 序号 | 名称 | 级别 | 位置 | 管制范围 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [文物名称] | [未定级别/县级/省级] | [自然村] | 文物本体[X]㎡，建设控制地带[X]㎡ |

历史文化资源保护表（未划入历史文化保护线）：
| 序号 | 名称 | 级别 | 位置 | 管制范围 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | [文物名称] | [未定级别/县级/省级] | [自然村] | 文物本体[X]㎡ |

【保护范围划定】
说明核心保护区和建设控制地带的具体划定方式和管控要求：文物保护单位保护范围内不得进行其他建设工程或爆破/钻探/挖掘等作业。古树名木保护应以树冠投影向外[X]米为保护范围。

【建筑分类整治】
| 建筑类别 | 数量(处) | 整治措施 | 控制要求 |
| :--- | :--- | :--- | :--- |
| 文物保护建筑 | [X] | 修缮保护 | [要求] |
| 历史建筑 | [X] | 维修改善 | [要求] |
| 传统风貌建筑 | [X] | 保留整治 | [要求] |
| 其他建筑 | [X] | 整治改造 | [要求] |

【非物质文化遗产活化】
说明非物质文化遗产（如当地传统表演、节庆习俗等）的保护与活化利用策略。包括：传承人培养机制、展示空间规划、文化活动策划（如文化节）、传统技艺与现代元素的融合。

【活化利用】
说明如何将文化遗产保护与活化利用相结合：
- 祠堂活化：修缮后满足祭祀等传统活动需求外，改造为小书屋/自习室/村民文化活动中心
- 古树名木活化：挂牌保护+定期检查，规划为主题公园，介绍历史文化价值
- 传统文化习俗活化：推举乡贤主持仪式，鼓励手艺人申请非遗，改造闲置祠堂为文化展示基地，策划主题活动吸引游客参与

【防灾减灾与安全】
说明文化遗产面临的主要灾害风险（火灾、洪水、地质灾害等）及相应的防护措施。

【产业融合利用】
说明如何将文化遗产保护与产业发展相结合，如文化旅游、文创产品开发等。给出1-2个具体融合路径。

【基础设施配套】
说明文化遗产保护所需的基础设施配套：消防设施、监控系统、游客服务中心、标识系统等。

【人口与用地管控】
说明文化遗产保护范围内的人口与建设用地管控要求：是否控制核心区常住人口、是否限制新增建设用地。

---
"""


# 8. 村庄风貌指引
LANDSCAPE_PROMPT = """你是乡村规划专家，精通建筑立面整治和乡土材料运用。

**任务**：制定村庄风貌控制和引导规划。你的输出将被用作规划文本第15条（农村住房建设）中风貌控制部分的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【村庄风貌指引】

【整体风貌定位与景观格局】
[用1-2段话描述村庄总体风貌设计主题，包括宏观的山水田园格局（如"山-村-河-田-村-山"格局）、核心景观特色]

【核心景观节点设计指引】
详见【景观类型指引】中对各景观节点的具体设计要求和【新建建筑指引】中的建筑设计方案。

【人居环境整治指引】
详见【景观类型指引】中对不同区域（耕地/林地/房前屋后/河流/坑塘/入口/四小园/乡道/村道/巷道）的环境整治原则和标准。

【景观类型指引】
对以下6种景观类型逐一给出具体指引（每种2-4句话）：

耕地景观：种植不同作物增加多样性，轮耕/间种手法，提升生产设施美学价值，根据时令种植观赏性作物。

林地景观：依形就势安排种植，按季相种植乡土植物，顺应山地形势肌理，丰富景观层次。

房前屋后景观：尊重村民意愿，易管理实用性乡土植物，禁止杂物垃圾堆放，发展庭院经济，庭院围墙攀缘植物美化。

河流景观：保留利用现有自然形态，生态护坡整治边坡岸线，设置亲水景观平台，挺水/沉水植物配置。

坑塘景观：保护现有坑塘，改善水质，增设水生植物，池塘周围乡土植物，生态驳岸设计，滨水步道。

村庄入口景观：整体出发彰显特色，因地制宜选用乡土材质（瓦片/文化石/青砖/夯土），以人为本满足人体尺度，打造不同层次入口景观。

"四小园"：小菜园/小果园/小花园/小游园改造，小微尺度建设，乡土特色建材（青砖/竹条），增设基础设施。

祠堂：[保持传统风貌加固外观整饬，活化为农家书屋/文化展览馆/活动中心/传统作坊]

村民活动交流场地：[生态化建设（硬质+生态透水铺装），人本化建设（桌凳/健身/环卫设施），集约化建设（多功能活动场地），乡土植物（紫薇/桂花）]

乡道：[硬底化+黑底化，保留美化景观，留出视觉通廊，修整山体切坡，滨水空间硬质驳岸+防护栏]

村道：[硬底化，绿化整治，打造景观小品，路旁种植兼具景观性和易管理性的乡土草本植物]

巷道：[因地制宜块石/预制混凝土方砖/传统铺装，利用空置地块打造小公园/小花园/小菜园]

步道：[田间步道：生产功能+大地景观；森林步道：森林康养主题+乡土树种（香樟/悬铃木/竹）；滨水步道：沿河设立+观景平台]

【建筑风貌控制导则】
详见【景观类型指引】和【建筑风貌指引】中的具体控制要求。

【建筑风貌指引】
风格定位：[雅致、和谐的现代[当地传统建筑风格]乡村风格]
主体风格：[屋面形式、屋顶特征、建筑轮廓、色彩基调]
立面风格：[虚实对比、风格特点、色彩点缀]
本土融合：[乡村类型特点、本土资源融入、新建/改建融合策略]
控制原则：[新建/改建/扩建要求、传统格局保护、棚舍整治、外立面美化]
色彩管控：
| 控制对象 | 推荐色系 | RGB参考值 | 说明 |
| :--- | :--- | :--- | :--- |
| 屋顶 | [深灰色系] | [RGB值] | [说明] |
| 民居墙身 | [灰白色系] | [RGB值] | [说明] |
| 公共建筑 | [淡黄色系] | [RGB值] | [说明] |

【新建建筑指引】
新建农房类型一：
- 类型：[如四室四厅四卫]
- 面积：[X]㎡
- 设计说明：[建筑风格、功能分区、空间布局、特色元素等，4-5句话描述]

新建农房类型二：
- 类型：[如五室三厅两卫]
- 面积：[X]㎡
- 设计说明：[同上]

**输入背景**：同前

---
"""


# 9. 建设项目库
PROJECT_BANK_PROMPT = """你是乡村规划专家，精通项目策划与实施管理。

**任务**：整合各专业规划，建立建设项目库。你的输出将被用作规划文本第18条（近期建设行动）的核心内容。

**当前时间**: {current_date}
**项目名称**: {project_name}

**现状分析报告**：
{analysis_report}

**规划思路**：
{planning_concept}

**约束条件**: {constraints}

**参考规范**：
{knowledge_context}

**各专业规划摘要**：
{dimension_plans}

{WRITING_RULES}

{GIS_TOOL_GUIDE}

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

**任务**：制定村庄空间结构规划方案。你的输出将被用作规划文本第10条（村庄国土空间布局）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【空间结构规划】

【空间结构模式】


【功能节点规划】
基于空间结构模式，定义至少2-3个核心功能节点（如服务中心、产业中心、旅游中心），并说明每个节点的核心功能、服务范围和主要布局。
| 节点名称 | 核心功能 | 服务范围 | 主要布局 |

【功能分区表】
| 分区类型 | 面积(公顷) | 位置 | 功能定位 |

【边界管控】
- 村庄建设边界：面积[X]公顷
- 基本农田红线：面积[X]公顷

---
"""


# 11. 土地利用规划
LAND_USE_PLANNING_PROMPT = """你是乡村规划专家，精通土地调查评价与用途管制。

**任务**：制定村庄土地利用规划方案。你的输出将被用作规划文本第9条（建设用地布局优化）和第12条（耕地和永久基本农田保护）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【土地利用规划】
用1段话概括土地利用规划的总体策略：土地结构调整方向、节约集约用地措施、用途管制原则。

【土地利用结构调整表】
| 地类 | 现状(公顷) | 占比(%) | 规划(公顷) | 占比(%) | 变化(公顷) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 耕地 | [X] | [X] | [X] | [X] | [X] |
| 园地 | [X] | [X] | [X] | [X] | [X] |
| 林地 | [X] | [X] | [X] | [X] | [X] |
| 建设用地 | [X] | [X] | [X] | [X] | [X] |
| 水域 | [X] | [X] | [X] | [X] | [X] |
| 其他土地 | [X] | [X] | [X] | [X] | [X] |
| 合计 | [X] | 100 | [X] | 100 | — |

【土地用途分区表】
| 分区名称 | 面积(公顷) | 占比(%) | 管控要求 |
| :--- | :--- | :--- | :--- |
| [基本农田保护区] | [X] | [X] | [要求] |
| [一般农业区] | [X] | [X] | [要求] |
| [村庄建设区] | [X] | [X] | [要求] |
| [生态保护区] | [X] | [X] | [要求] |

【重点建设项目清单】
| 项目名称 | 用地面积(公顷) | 选址位置 | 用地类型 |
| :--- | :--- | :--- | :--- |
| [项目名] | [X] | [位置] | [新增/改建] |

【风貌与设施管控要求】
说明建设用地的风貌与设施管控标准：建筑风格引导、高度控制、退线要求、公共设施配建标准等。要求自然段落叙述。

---
"""


# 12. 居民点规划
SETTLEMENT_PLANNING_PROMPT = """你是乡村规划专家，精通农村住宅设计与村庄整治。

**任务**：制定村庄居民点规划方案。你的输出将被用作规划文本第9条（建设用地布局优化）和第15条（农村住房建设）的核心内容。

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

{GIS_TOOL_GUIDE}

**输出结构**：

【居民点规划】
用1-2段自然段落概述居民点规划的总体思路：现状居民点分布特征、规划采取的空间策略（集中/组团式/散点式）、总体管控目标。要求连贯叙述，不列清单。

【规划目标】
说明居民点规划的总体目标，如：建设用地集约节约利用、人居环境品质提升、宅基地管理规范化等。2-3句话段落叙述。

【人口与用地规模】
| 指标 | 数值 |
| :--- | :--- |
| 现状常住人口 | [X]人 |
| 规划期末人口 | [X]人 |
| 现状村庄建设用地 | [X]公顷 |
| 规划村庄建设用地 | [X]公顷 |
| 人均建设用地 | [X]㎡/人 |

注意：规划村庄建设用地 = 现状建设用地 + 新增建设用地 - 腾退建设用地。新增建设用地应包含产业发展、公共服务设施、基础设施等合理用地需求，不应无理由大幅缩减现有建设用地规模。腾退量不应超过现状闲置/危房面积。

【居民点布局模式】
说明居民点采用的空间布局模式（如"组团式+散点布局"），描述各组团的空间关系、发展方向、核心功能。要求自然段落叙述。

【布局说明】
详细描述各居民点组团/片区的位置、规模、主要功能、发展指引。每个组团用1-2句话说明。如涉及多个自然村，需逐一说明其归属组团。

【宅基地规划表】
| 项目 | 数量 | 面积(公顷) |
| :--- | :--- | :--- |
| 现状宅基地 | [X]处 | [X] |
| 新增宅基地 | [X]处 | [X] |
| 腾退宅基地 | [X]处 | [X] |

【防灾减灾规划】
说明居民点选址的防灾要求：避开的地质灾害区、与灾害点的安全距离、防洪标准等。2-3句话段落叙述。

【基础设施规划】
说明居民点的基础设施配置标准：供水方式、排水体制、电力供应、通信覆盖等。简要描述各设施的配置要求。

【历史文化保护】
说明居民点范围内涉及的历史文化资源保护要求：祠堂、古树名木、古道遗存等文物古迹的保护范围、建筑控制要求。

【产业空间布局】
说明居民点与产业空间的关系：哪些组团配套产业服务功能、产业用地与居住用地的空间关系。

【实施时序】
| 阶段 | 时间 | 主要建设内容 |
| :--- | :--- | :--- |
| 近期 | 1-2年 | [主要任务] |
| 中期 | 3-5年 | [主要任务] |
| 远期 | 5-10年 | [主要任务] |

---
"""


# ==========================================
# 辅助函数
# ==========================================

def get_dimension_prompt(dimension_key: str, revision_instruction: str = "", **kwargs) -> str:
    """获取指定维度的格式化Prompt

    Args:
        dimension_key: 维度键名
        revision_instruction: 级联修订指令（可选）
        **kwargs: 其他模板参数
    """
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

    # Inject presentation guidance only.  Authoritative land-use metrics are
    # read by domain stages from data/artifacts, never copied through state.
    kwargs["GIS_TOOL_GUIDE"] = GIS_TOOL_GUIDE
    for key in (
        "landuse_metrics_farmland", "landuse_metrics_construction",
        "landuse_metrics_ecological", "intent_targets_farmland",
        "intent_targets_construction", "intent_targets_ecological",
    ):
        kwargs[key] = "N/A"

    # 动态生成当前日期
    if not kwargs.get("current_date"):
        from datetime import datetime
        kwargs["current_date"] = datetime.now().strftime("%Y年%m月")

    # 处理 professional_data 参数
    professional_data = kwargs.pop("professional_data", None)
    if professional_data:
        kwargs["professional_data_section"] = professional_data if isinstance(professional_data, str) else ""
    elif "professional_data_section" not in kwargs:
        kwargs["professional_data_section"] = ""

    # 处理缺失参数
    for param in ["project_name", "analysis_report", "planning_concept", "constraints",
                  "knowledge_context", "dimension_plans"]:
        if param not in kwargs:
            kwargs[param] = ""

    result = template.format(**kwargs)

    location_evidence = str(kwargs.get("location_evidence") or "").strip()
    if location_evidence:
        result += LOCATION_EVIDENCE_GUIDE.format(location_evidence=location_evidence)

    # 添加修订指令（级联修订场景）
    if revision_instruction:
        result = revision_instruction + "\n\n" + result

    # L3 emits evidence-bearing claims.  Spatial execution is decided later
    # by the domain engines and never by a report suffix or Markdown table.
    result += CLAIMS_OUTPUT_GUIDE

    return result



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




# ==========================================
# 导出
# ==========================================

__all__ = [
    "WRITING_RULES",
    "GIS_TOOL_GUIDE",
    "CLAIMS_OUTPUT_GUIDE",
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
]
