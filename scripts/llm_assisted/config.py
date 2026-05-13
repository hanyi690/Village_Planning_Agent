"""
Configuration for LLM Assisted Generation V3.0

V3.0 Architecture:
- 核心策略：S-ASSEMBLE（数据组装）+ S-TRANSLATE（预制件转译）
- LLM角色降级为"翻译和格式化助手"
- 关键数字通过数据组装直接填入，不经过LLM

Key Changes from V2.0:
- CRITICAL_NUMBERS: 作为单一数据源
- CHAPTER_SCRIPTS: 更新生成策略映射
- S-ASSEMBLE/S-TRANSLATE: 新增策略定义
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


# ==========================================
# 生成策略定义
# ==========================================

GENERATION_STRATEGIES = {
    "S-ASSEMBLE": {
        "description": "数据组装策略 - 直接从结构化字段填入数字，不调用LLM",
        "applicable": ["第5条", "第8条", "第18条", "第19条"],
        "features": ["数据100%准确", "无幻觉风险", "直接组装表格"]
    },
    "S-TRANSLATE": {
        "description": "原文直接注入策略 - 直接使用Layer3原文，不调用LLM",
        "applicable": ["第9条", "第10条", "第11条", "第12条", "第13条", "第14条", "第15条", "第16条", "第17条"],
        "features": ["保留完整规划内容", "不经过LLM", "100%内容保真"]
    },
    "S-TEMPLATE": {
        "description": "固定模板策略 - 使用预设模板，不调用LLM",
        "applicable": ["第6条", "第7条"],
        "features": ["格式统一", "内容可控"]
    },
    "S-EXTRACT": {
        "description": "LLM提取策略 - 从背景信息中提取关键内容",
        "applicable": ["第1条", "第2条", "第3条", "第4条"],
        "features": ["灵活处理非结构化内容"]
    },
    "S-GENERATE": {
        "description": "LLM生成策略 - 完全由LLM生成",
        "applicable": ["第20条", "第21条", "第22条"],
        "features": ["用于无直接数据源的内容"]
    }
}


# ==========================================
# 关键数据点（单一数据源，必须准确）
# ==========================================

CRITICAL_NUMBERS = {
    "户籍人口": 1403,  # 人
    "常住人口": 500,   # 人
    "村域总面积": 2352.89,  # 公顷
    "耕地保有量": 85.20,    # 公顷
    "永久基本农田": 85.20,  # 公顷
    "生态保护红线": 325.92, # 公顷（生态公益林面积）
    "村庄建设用地_现状": 30.17,  # 公顷
    "村庄建设用地_规划": 31.00,  # 公顷
    "林地保有量": 2117.60,  # 公顷
    "森林覆盖率": 90,  # %
    "规划基期": 2022,
    "规划目标年": 2035,
    "自然村数量": 12,
    "自然村名单": ["园寨", "田坑", "社前", "分水", "清明", "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹"],
    "崩塌隐患点": 5,
    "滑坡隐患点": 35,
}


# ==========================================
# 默认值配置（建筑控制指标等）
# ==========================================

DEFAULT_VALUES = {
    # 建筑控制指标
    "建筑容积率_居住": 0.8,
    "建筑密度_居住": 30,  # %
    "建筑限高_居住": 10,  # 米
    "建筑容积率_公共服务": 1.0,
    "建筑密度_公共服务": 35,  # %
    "建筑限高_公共服务": 12,  # 米
    "建筑容积率_产业": 1.2,
    "建筑密度_产业": 40,  # %
    "建筑限高_产业": 15,  # 米

    # 道路宽度默认值
    "道路宽度_主干路": 6.0,  # 米
    "道路宽度_支路": 3.5,  # 米
    "道路宽度_入户路": 2.5,  # 米

    # 公共服务设施配置标准
    "人均公共服务用地": 5.0,  # 平方米/人
    "停车位_每户": 1,  # 个

    # 基础设施标准
    "供水人均标准": 100,  # 升/人/日
    "污水处理覆盖率": 100,  # %
    "电力负荷人均": 0.5,  # kW/人
    "宽带接入能力": 100,  # Mbps

    # 缺失数据默认文本
    "缺失数据文本": "按照相关专项规划执行",
}


# ==========================================
# 单位换算规则
# ==========================================

UNIT_CONVERSION = {
    "公顷_to_平方米": 10000,
    "平方米_to_公顷": 0.0001,
    "公里_to_米": 1000,
    "米_to_公里": 0.001,
    "亩_to_公顷": 0.0667,
    "公顷_to_亩": 15,
}

# 单位格式化规则
UNIT_FORMAT_RULES = {
    "公顷": {"decimal_places": 2, "suffix": "公顷"},
    "平方米": {"decimal_places": 0, "suffix": "平方米", "thousands_separator": True},
    "公里": {"decimal_places": 2, "suffix": "公里"},
    "米": {"decimal_places": 1, "suffix": "米"},
    "%": {"decimal_places": 2, "suffix": "%"},
    "人": {"decimal_places": 0, "suffix": "人"},
    "万元": {"decimal_places": 0, "suffix": "万元", "thousands_separator": True},
}


# ==========================================
# 目标文档结构 (22条)
# ==========================================

TARGET_DOCUMENT_STRUCTURE = {
    "第一章 总则": {
        "article_range": (1, 6),
        "articles": [
            "第1条 规划编制背景",
            "第2条 规划依据",
            "第3条 规划指导思想",
            "第4条 规划原则",
            "第5条 规划范围",
            "第6条 规划期限",
        ]
    },
    "第二章 村庄发展目标": {
        "article_range": (7, 8),
        "articles": [
            "第7条 村庄发展定位",
            "第8条 村庄发展目标",
        ]
    },
    "第三章 规划内容": {
        "article_range": (9, 17),
        "articles": [
            "第9条 用地布局规划",
            "第10条 道路交通规划",
            "第11条 公共服务设施规划",
            "第12条 基础设施规划",
            "第13条 生态绿地规划",
            "第14条 防灾减灾规划",
            "第15条 历史文化传承与保护",
            "第16条 村庄风貌引导",
            "第17条 近期建设行动",
        ]
    },
    "第四章 实施计划": {
        "article_range": (18, 18),
        "articles": [
            "第18条 建设项目库",
        ]
    },
    "第五章 实施保障": {
        "article_range": (19, 22),
        "articles": [
            "第19条 组织保障",
            "第20条 资金保障",
            "第21条 制度保障",
            "第22条 监督保障",
        ]
    },
}


# ==========================================
# 章节Schema（按输出组织）
# ==========================================

CHAPTER_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "第1条_规划编制背景": {
        "type": "object",
        "properties": {
            "背景描述": {"type": "string", "description": "规划编制的背景说明"},
            "编制必要性": {"type": "string", "description": "为何需要编制此规划"},
            "来源": {"type": "string", "description": "数据来源：layer1/layer2"},
        }
    },

    "第2条_规划依据": {
        "type": "object",
        "properties": {
            "法律法规": {"type": "array", "items": {"type": "string"}},
            "政策文件": {"type": "array", "items": {"type": "string"}},
            "技术标准": {"type": "array", "items": {"type": "string"}},
            "上位规划": {"type": "array", "items": {"type": "string"}},
        }
    },

    "第3条_规划指导思想": {
        "type": "object",
        "properties": {
            "指导思想": {"type": "string"},
        }
    },

    "第4条_规划原则": {
        "type": "object",
        "properties": {
            "原则列表": {"type": "array", "items": {"type": "string"}},
        }
    },

    "第5条_规划范围": {
        "type": "object",
        "properties": {
            "村域面积": {"type": "number", "unit": "公顷"},
            "边界描述": {"type": "string"},
            "行政村名称": {"type": "string"},
        }
    },

    "第6条_规划期限": {
        "type": "object",
        "properties": {
            "基准年": {"type": "number"},
            "目标年": {"type": "number"},
            "近期": {"type": "string"},
            "远期": {"type": "string"},
        }
    },

    "第7条_村庄发展定位": {
        "type": "object",
        "properties": {
            "定位描述": {"type": "string"},
            "发展类型": {"type": "string"},
            "特色标签": {"type": "array", "items": {"type": "string"}},
        }
    },

    "第8条_村庄发展目标": {
        "type": "object",
        "properties": {
            "人口目标": {"type": "object", "properties": {"现状": {"type": "number"}, "规划": {"type": "number"}}},
            "用地目标": {"type": "object", "properties": {"现状": {"type": "number"}, "规划": {"type": "number"}}},
            "产业目标": {"type": "string"},
            "生态目标": {"type": "string"},
            "社会目标": {"type": "string"},
        }
    },

    "第9条_用地布局规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string", "description": "从Layer3直接复用"},
            "用地结构调整": {"type": "array", "items": {"type": "object"}},
            "关键指标": {"type": "object"},
        }
    },

    "第10条_道路交通规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "道路等级": {"type": "array", "items": {"type": "object"}},
            "交通设施": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第11条_公共服务设施规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "设施列表": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第12条_基础设施规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "给水工程": {"type": "object"},
            "排水工程": {"type": "object"},
            "电力工程": {"type": "object"},
            "通信工程": {"type": "object"},
        }
    },

    "第13条_生态绿地规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "生态格局": {"type": "string"},
            "绿地系统": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第14条_防灾减灾规划": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "主要灾害": {"type": "array", "items": {"type": "string"}},
            "防灾设施": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第15条_历史文化传承与保护": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "保护范围": {"type": "string"},
            "保护名录": {"type": "array", "items": {"type": "object"}},
            "活化措施": {"type": "array", "items": {"type": "string"}},
        }
    },

    "第16条_村庄风貌引导": {
        "type": "object",
        "properties": {
            "预制文本": {"type": "string"},
            "风貌定位": {"type": "string"},
            "建筑控制": {"type": "object"},
            "整治项目": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第17条_近期建设行动": {
        "type": "object",
        "properties": {
            "近期项目": {"type": "array", "items": {"type": "object"}},
            "投资估算": {"type": "string"},
        }
    },

    "第18条_建设项目库": {
        "type": "object",
        "properties": {
            "近期项目": {"type": "array", "items": {"type": "object"}},
            "中期项目": {"type": "array", "items": {"type": "object"}},
            "远期项目": {"type": "array", "items": {"type": "object"}},
        }
    },

    "第19条_组织保障": {
        "type": "object",
        "properties": {
            "保障措施": {"type": "string"},
        }
    },

    "第20条_资金保障": {
        "type": "object",
        "properties": {
            "保障措施": {"type": "string"},
        }
    },

    "第21条_制度保障": {
        "type": "object",
        "properties": {
            "保障措施": {"type": "string"},
        }
    },

    "第22条_监督保障": {
        "type": "object",
        "properties": {
            "保障措施": {"type": "string"},
        }
    },
}


# ==========================================
# 章节上下文脚本（核心配置）
# ==========================================

CHAPTER_SCRIPTS: Dict[str, Dict[str, Any]] = {
    # ========== 第一章 总则 ==========

    "第1条_规划编制背景": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": """第1条 规划编制背景
为深入贯彻落实乡村振兴战略，推动村庄规划编制工作，优化村庄生产生活生态空间，促进金田村经济社会全面协调可持续发展，根据《中华人民共和国城乡规划法》《广东省村庄规划编制指引》等法律法规要求，结合金田村实际情况，编制《平远县泗水镇金田村村庄规划（2022-2035年）》。""",
        "生成策略": "S-TEMPLATE"
    },

    "第2条_规划依据": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": """第2条 规划依据
（1）法律法规。《中华人民共和国城乡规划法》《中华人民共和国土地管理法》《中华人民共和国环境保护法》《中华人民共和国乡村振兴促进法》等。
（2）政策文件。《中共中央 国务院关于实施乡村振兴战略的意见》《广东省乡村振兴战略规划（2018-2022年）》《梅州市乡村振兴战略规划》等。
（3）技术标准。《村庄规划编制规程》（TD/T 1022-2009）《广东省村庄规划编制指引》《梅州市村庄规划编制技术指引》等。
（4）上位规划。《平远县国土空间总体规划（2021-2035年）》《泗水镇总体规划》等。""",
        "生成策略": "S-TEMPLATE"
    },

    "第3条_规划指导思想": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": """第3条 规划指导思想
以习近平新时代中国特色社会主义思想为指导，全面贯彻党的二十大精神，深入落实乡村振兴战略总体要求，坚持农业农村优先发展，按照产业兴旺、生态宜居、乡风文明、治理有效、生活富裕的总要求，以保护耕地和生态环境为前提，以促进村庄经济发展和改善村民生活条件为目标，统筹安排村庄各项建设活动，推动金田村实现高质量发展。""",
        "生成策略": "S-TEMPLATE"
    },

    "第4条_规划原则": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": """第4条 规划原则
（1）生态优先、绿色发展。坚持生态保护优先，严守生态保护红线和永久基本农田保护红线，推动村庄绿色发展。
（2）因地制宜、突出特色。立足金田村资源禀赋和发展实际，突出南药产业特色，打造特色村庄。
（3）统筹兼顾、协调发展。统筹村庄产业发展、基础设施、公共服务等各项建设，促进村庄全面协调发展。
（4）村民参与、共建共享。充分尊重村民意愿，保障村民参与规划编制和实施的权利，实现共建共享。""",
        "生成策略": "S-TEMPLATE"
    },

    "第5条_规划范围": {
        "知识来源": ["layer1.location"],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": None,  # S-ASSEMBLE策略会动态生成
        "生成策略": "S-ASSEMBLE"
    },

    "第6条_规划期限": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": "第6条 规划期限\n规划期限为2022-2035年，近期到2025年，规划基期年为2022年，与基本实现社会主义现代化期限保持一致。",
        "生成策略": "S-TEMPLATE"
    },

    # ========== 第二章 村庄发展目标 ==========

    "第7条_村庄发展定位": {
        "知识来源": ["layer2.planning_positioning"],
        "预制件路径": None,
        "背景信息路径": "layer2.规划定位分析",
        "LLM任务": [],
        "条文模板": "第7条 村庄发展定位\n根据上位规划以及村庄未来发展需求，确定金田村为集聚提升类村庄，应立足现有农田、生态、村落等乡村资源，依托现有特色种植业和良好的生态环境，按照上位规划要求，保持金田村的生态空间保持总量不减，耕地质量有所提升，永久基本农田总量不变。村庄以生态保护为基底，南药产业为抓手，林下经济为推手，乡村风貌改善为补充，将金田村建设成以特色南药为核心，集林下经济、乡村农旅等功能于一体的特色南药综合开发示范村。",
        "生成策略": "S-TEMPLATE"
    },

    "第8条_村庄发展目标": {
        "知识来源": ["layer1.socio_economic", "layer1.land_use"],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": [],
        "条文模板": None,  # S-ASSEMBLE策略会动态生成表格
        "生成策略": "S-ASSEMBLE"
    },

    # ========== 第三章 规划内容 ==========

    "第9条_用地布局规划": {
        "知识来源": ["layer3.land_use_planning", "layer3.spatial_structure"],
        "预制件路径": "layer3.土地利用规划",
        "背景信息路径": "layer1.土地利用分析",
        "LLM任务": ["转译功能分区、边界管控为法规条文"],
        "条文模板": "第9条 用地布局规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第10条_道路交通规划": {
        "知识来源": ["layer3.traffic_planning"],
        "预制件路径": "layer3.道路交通规划",
        "背景信息路径": "layer1.道路交通分析",
        "LLM任务": ["转译路网格局、道路等级表为法规条文"],
        "条文模板": "第10条 道路交通规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第11条_公共服务设施规划": {
        "知识来源": ["layer3.public_service"],
        "预制件路径": "layer3.公共服务设施规划",
        "背景信息路径": "layer1.公共服务设施分析",
        "LLM任务": ["转译设施配置清单为法规条文"],
        "条文模板": "第11条 公共服务设施规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第12条_基础设施规划": {
        "知识来源": ["layer3.infrastructure_planning"],
        "预制件路径": "layer3.基础设施规划",
        "背景信息路径": "layer1.基础设施分析",
        "LLM任务": ["转译给排水、电力、通信工程为法规条文"],
        "条文模板": "第12条 基础设施规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第13条_生态绿地规划": {
        "知识来源": ["layer3.ecological"],
        "预制件路径": "layer3.生态绿地规划",
        "背景信息路径": "layer1.生态绿地分析",
        "LLM任务": ["转译生态格局、绿地系统为法规条文"],
        "条文模板": "第13条 生态绿地规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第14条_防灾减灾规划": {
        "知识来源": ["layer3.disaster_prevention"],
        "预制件路径": "layer3.防震减灾规划",
        "背景信息路径": "layer1.自然环境分析",
        "LLM任务": ["转译地灾治理、应急体系为法规条文"],
        "条文模板": "第14条 防灾减灾规划\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第15条_历史文化传承与保护": {
        "知识来源": ["layer3.heritage", "layer1.historical_culture"],
        "预制件路径": "layer3.历史文保规划",
        "背景信息路径": "layer1.历史文化与乡愁保护分析",
        "LLM任务": ["转译遗产清单、活化方案为法规条文"],
        "条文模板": "第15条 历史文化传承与保护\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第16条_村庄风貌引导": {
        "知识来源": ["layer3.landscape"],
        "预制件路径": "layer3.村庄风貌指引",
        "背景信息路径": "layer1.建筑分析",
        "LLM任务": ["转译风貌定位、建筑控制导则为法规条文"],
        "条文模板": "第16条 村庄风貌引导\n{预制文本}",
        "生成策略": "S-TRANSLATE"
    },

    "第17条_近期建设行动": {
        "知识来源": ["layer3.project_bank"],
        "预制件路径": "layer3.建设项目库",
        "背景信息路径": None,
        "LLM任务": ["提取近期项目表格"],
        "条文模板": None,  # S-ASSEMBLE策略会动态生成
        "生成策略": "S-ASSEMBLE"
    },

    # ========== 第四章 实施计划 ==========

    "第18条_建设项目库": {
        "知识来源": ["layer3.project_bank"],
        "预制件路径": "layer3.建设项目库",
        "背景信息路径": None,
        "LLM任务": ["直接复用项目库表格"],
        "条文模板": None,  # S-ASSEMBLE策略会动态生成
        "生成策略": "S-ASSEMBLE"
    },

    # ========== 第五章 实施保障 ==========

    "第19条_组织保障": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": ["生成通用组织保障措施"],
        "条文模板": "第19条 组织保障\n{保障措施}",
        "生成策略": "S-GENERATE"
    },

    "第20条_资金保障": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": ["生成通用资金保障措施"],
        "条文模板": "第20条 资金保障\n{保障措施}",
        "生成策略": "S-GENERATE"
    },

    "第21条_制度保障": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": ["生成通用制度保障措施"],
        "条文模板": "第21条 制度保障\n{保障措施}",
        "生成策略": "S-GENERATE"
    },

    "第22条_监督保障": {
        "知识来源": [],
        "预制件路径": None,
        "背景信息路径": None,
        "LLM任务": ["生成通用监督保障措施"],
        "条文模板": "第22条 监督保障\n{保障措施}",
        "生成策略": "S-GENERATE"
    },
}


# ==========================================
# Layer3预制件映射
# ==========================================

LAYER3_PREFAB_MAPPING = {
    # 核心规划章节
    "空间结构规划": "第9条_用地布局规划",
    "空间布局": "第9条_用地布局规划",
    "功能分区表": "第9条_用地布局规划",
    "边界管控": "第9条_用地布局规划",
    "土地利用规划": "第8条_村庄发展目标",
    "土地利用结构调整表": "第8条_村庄发展目标",
    "土地用途分区表": "第9条_用地布局规划",

    # 道路交通
    "道路交通规划": "第10条_道路交通规划",
    "交通设施清单": "第10条_道路交通规划",

    # 公共服务
    "公共服务设施规划": "第11条_公共服务设施规划",
    "公共设施配置": "第11条_公共服务设施规划",
    "功能节点规划": "第11条_公共服务设施规划",

    # 基础设施
    "基础设施规划": "第12条_基础设施规划",

    # 生态绿地
    "生态绿地规划": "第13条_生态绿地规划",
    "绿地系统": "第13条_生态绿地规划",
    "生态防护工程": "第13条_生态绿地规划",
    "历史资源保护绿化": "第13条_生态绿地规划",
    "基础设施配套": "第13条_生态绿地规划",

    # 防灾减灾
    "防震减灾规划": "第14条_防灾减灾规划",
    "防灾避险规划": "第14条_防灾减灾规划",
    "防灾设施清单": "第14条_防灾减灾规划",

    # 历史文化
    "历史文保规划": "第15条_历史文化传承与保护",
    "历史文化保护规划": "第15条_历史文化传承与保护",
    "文化遗产清单": "第15条_历史文化传承与保护",
    "分类保护措施": "第15条_历史文化传承与保护",
    "活化利用方案": "第15条_历史文化传承与保护",
    "保障机制": "第15条_历史文化传承与保护",

    # 村庄风貌
    "村庄风貌指引": "第16条_村庄风貌引导",
    "建筑风貌管控": "第16条_村庄风貌引导",
    "人居环境整治": "第16条_村庄风貌引导",
    "人居环境整治指引": "第16条_村庄风貌引导",
    "核心景观节点设计指引": "第16条_村庄风貌引导",

    # 项目库
    "建设项目库": ["第17条_近期建设行动", "第18条_建设项目库"],
    "近期项目": "第17条_近期建设行动",
    "中期项目": "第18条_建设项目库",
    "远期项目": "第18条_建设项目库",
    "重点建设项目清单": "第18条_建设项目库",

    # 产业规划（新增）
    "产业规划": "第9条_用地布局规划",
    "产业项目清单": "第18条_建设项目库",
    "产业发展定位": "第7条_村庄发展定位",
    "产业发展思路": "第7条_村庄发展定位",

    # 居民点规划（新增）
    "居民点规划": "第9条_用地布局规划",
    "居民点布局模式": "第9条_用地布局规划",
    "宅基地规划表": "第9条_用地布局规划",
}


# ==========================================
# 质量核验规则
# ==========================================

QUALITY_RULES = {
    "占位符清理": {
        "检测模式": r"【[^】]+】",
        "处理方式": "warn"
    },
    "数字核对": {
        "关键指标": [
            "耕地保有量", "基本农田", "生态红线",
            "建设用地", "人口规模", "村域总面积"
        ],
        "容差": 0.01
    },
    "重复检测": {
        "检测范围": "相邻条文",
        "相似度阈值": 0.8
    },
    "完整性检查": {
        "必需条目": ["规划依据", "规划范围", "规划期限"],
        "必需章节": 5,
        "必需条文数": 22
    }
}


# V1.0 兼容
VALIDATION_RULES: Dict[str, Dict[str, Any]] = {
    "耕地保有量": {"min": 0, "max": 1000, "unit": "公顷"},
    "林地覆盖率": {"min": 0, "max": 100, "unit": "%"},
    "道路宽度": {"min": 2.5, "max": 20, "unit": "米"},
    "人均建设用地": {"min": 50, "max": 150, "unit": "平方米"},
    "绿地率": {"min": 0, "max": 100, "unit": "%"},
    "建筑层数": {"min": 1, "max": 6, "unit": "层"},
}

SOURCE_PRIORITY = {
    "法定规划文本": 1,
    "layer3": 2,
    "layer2": 3,
    "layer1": 4,
    "rag_reference": 5,
}


# ==========================================
# 辅助函数
# ==========================================

def get_chapter_schema(article_key: str) -> Dict[str, Any]:
    """获取指定条文的Schema"""
    return CHAPTER_SCHEMAS.get(article_key, {})


def get_chapter_script(article_key: str) -> Dict[str, Any]:
    """获取指定条文的上下文脚本"""
    return CHAPTER_SCRIPTS.get(article_key, {})


def get_generation_strategy(article_key: str) -> str:
    """获取生成策略"""
    script = CHAPTER_SCRIPTS.get(article_key, {})
    return script.get("生成策略", "LLM生成")


def get_prefab_target(layer3_chapter: str) -> Optional[str]:
    """获取Layer3章节对应的目标条文"""
    mapping = LAYER3_PREFAB_MAPPING.get(layer3_chapter)
    if isinstance(mapping, list):
        return mapping[0]
    return mapping


def get_all_article_keys() -> List[str]:
    """获取所有条文key列表"""
    return list(CHAPTER_SCRIPTS.keys())


def get_articles_by_chapter(chapter_name: str) -> List[str]:
    """获取指定章节的所有条文key"""
    chapter_info = TARGET_DOCUMENT_STRUCTURE.get(chapter_name, {})
    articles = chapter_info.get("articles", [])
    return [a.replace(" ", "_") for a in articles]


# ==========================================
# 兼容函数（供旧模块 generator.py 使用）
# ==========================================

DIMENSION_NAMES = {
    "location": "区位与对外交通分析",
    "socio_economic": "社会经济分析",
    "villager_wishes": "村民意愿与诉求分析",
    "superior_planning": "上位规划与政策导向分析",
    "natural_environment": "自然环境分析",
    "land_use": "土地利用分析",
    "traffic": "道路交通分析",
    "public_services": "公共服务设施分析",
    "infrastructure": "基础设施分析",
    "ecological_green": "生态绿地分析",
    "architecture": "建筑分析",
    "historical_culture": "历史文化与乡愁保护分析",
}

DIMENSION_SCHEMAS: Dict[str, Dict[str, Any]] = {}


def get_dimension_name(dimension_key: str) -> str:
    """获取维度的中文名称"""
    return DIMENSION_NAMES.get(dimension_key, dimension_key)


def get_generation_prompt(chapter_name: str, knowledge_data: Dict[str, Any]) -> str:
    """生成内容生成Prompt（兼容旧模块）"""
    import json
    data_str = json.dumps(knowledge_data, ensure_ascii=False, indent=2)
    return f"请根据以下信息生成《{chapter_name}》的法规条文：\n{data_str}"


def get_schema(dimension_key: str) -> Dict[str, Any]:
    """获取指定维度的Schema（兼容旧模块）"""
    return {}


def get_extraction_prompt(dimension_key: str, markdown_content: str) -> str:
    """生成提取Prompt（兼容旧模块）"""
    return f"请从以下文本中提取{dimension_key}相关信息：\n{markdown_content}"


__all__ = [
    "TARGET_DOCUMENT_STRUCTURE",
    "CRITICAL_NUMBERS",
    "DEFAULT_VALUES",
    "UNIT_CONVERSION",
    "UNIT_FORMAT_RULES",
    "CHAPTER_SCHEMAS",
    "CHAPTER_SCRIPTS",
    "LAYER3_PREFAB_MAPPING",
    "QUALITY_RULES",
    "VALIDATION_RULES",
    "SOURCE_PRIORITY",
    "get_chapter_schema",
    "get_chapter_script",
    "get_generation_strategy",
    "get_prefab_target",
    "get_all_article_keys",
    "get_articles_by_chapter",
    # 兼容旧模块
    "DIMENSION_NAMES",
    "DIMENSION_SCHEMAS",
    "get_dimension_name",
    "get_generation_prompt",
    "get_schema",
    "get_extraction_prompt",
]
