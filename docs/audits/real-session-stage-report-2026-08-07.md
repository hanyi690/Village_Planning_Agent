# GIS 全链阶段报告

- **Session**: 4e437148-5ed4-46a6-a8d4-1881b717850a
- **Feasible**: False

## Fact lineage（KG → L1 → L2）

以下内容来自实际 session 的 KG、L1Snapshot 和 L2 输入审计；不是测试占位数据。

- **L1 / l1_aggregate**
  - producer: L1 report compiler + session KG evidence promotion
  - facts_produced: {
  "items": 24,
  "sample": [
    "[land_use] 模型观察: 土地总用地面积：金田村土地总用地面积约2352.89公顷。",
    "[land_use] 模型观察: 用地结构：金田村用地以农业用地和生态用地为主，建设用地占比较小。具体用地结构如下表所示，其中水域面积35.99公顷已包含在农业用地与生态用地的统计范畴内。",
    "[land_use] 模型观察: 耕地详情：金田村耕地总面积85.2公顷，其中水田面积78.83公顷，旱地面积数据中未提供。按全村户籍人口1403人计算，人均耕地面积约0.91亩。"
  ]
}
  - location_facts: {
  "items": 48,
  "sample": [
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "建筑集中区",
      "normalized_name": "村中部园寨、马头段",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 建筑集中区 | 村中部园寨、马头段 | 现状建筑分布较分散，主要集中于此",
      "spatial_hint": "村中部园寨、马头段"
    },
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "传统祠堂",
      "normalized_name": "社前村、黄竹村、田坑村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 传统祠堂 | 社前村、黄竹村、田坑村 | 具有浓厚客家文化元素的传统建筑",
      "spatial_hint": "社前村、黄竹村、田坑村"
    },
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "农房外立面整治",
      "normalized_name": "田坑、营仔、园寨等9个自然村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状项目 | 农房外立面整治 | 田坑、营仔、园寨等9个自然村 | 对村内农房外立面进行统一整治",
      "spatial_hint": "田坑、营仔、园寨等9个自然村"
    }
  ]
}
- **L2 / l2_aggregate**
  - consumer: L2 dimension prompts via EXPLORE evidence service

## KG_PREBUILD / kg_prebuild
- timestamp: 2026-08-07T16:42:45.013090
### 产出
- **cache_hit**: False
- **gazetteer_combo_entries**: 0
- **triple_count**: 33266
- **version**: 1
### 诊断
- road_intersects: 365
- sfTouches: 1691
- water_touches: 0

## L1 / l1_aggregate
- timestamp: 2026-08-07T16:49:12.919179
### 产出
- **constraint_count**: 0
- **fact_count**: 24
- **facts_by_dimension**: {
  "architecture": {
    "items": 0,
    "sample": []
  },
  "ecological_green": {
    "items": 0,
    "sample": []
  },
  "historical_culture": {
    "items": 0,
    "sample": []
  },
  "infrastructure": {
    "items": 0,
    "sample": []
  },
  "land_use": {
    "items": 8,
    "sample": [
      "[land_use] 模型观察: 土地总用地面积：金田村土地总用地面积约2352.89公顷。",
      "[land_use] 模型观察: 用地结构：金田村用地以农业用地和生态用地为主，建设用地占比较小。具体用地结构如下表所示，其中水域面积35.99公顷已包含在农业用地与生态用地的统计范畴内。",
      "[land_use] 模型观察: 耕地详情：金田村耕地总面积85.2公顷，其中水田面积78.83公顷，旱地面积数据中未提供。按全村户籍人口1403人计算，人均耕地面积约0.91亩。"
    ]
  },
  "location": {
    "items": 0,
    "sample": []
  },
  "natural_environment": {
    "items": 0,
    "sample": []
  },
  "public_services": {
    "items": 0,
    "sample": []
  },
  "socio_economic": {
    "items": 3,
    "sample": [
      "[socio_economic] 模型观察: [行政区划]：金田村隶属广东省梅州市平远县泗水镇，下辖12个自然村，完整名单：园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、黄竹。其中园寨是行政村。",
      "[socio_economic] 模型观察: [人口结构]：金田村全村共有325户人口，户籍人口1403人，常住人口约500人。村内青壮年劳动力大多外出务工求学，常住村民数量较少，多为老人小孩，50岁以下劳动力较少，人口流失与老龄化问题较为严重。",
      "[socio_economic] 模型观察: [产业构成]：第一产业农业是金田村的主导产业，水稻种植是传统种植业，药材与烤烟为新兴种植业，现有林芝种植20亩，烤烟种植60亩，同时有一定规模的养殖业。第二产业依托丰富林木资源发展起杉木家具制造业，但产业规模小且家具产量不足。第三产业缺乏。特色农产品包括林芝与烤烟，年产值数据中未提供。收入水平人均纯收入数据中未提供，主要收入来源分布数据中未提供。劳动力情况中劳动力总数、外出务工人数及本地就业人数均数据中未提供。"
    ]
  },
  "superior_planning": {
    "items": 0,
    "sample": []
  },
  "traffic": {
    "items": 4,
    "sample": [
      "[traffic] 模型观察: [对外交通]：金田村对外交通联系主要依赖乡道和村道。Y122乡道是金田村主要的对外交通道路，也是金田村与泗水镇域相联系的主要通道。此外，X038县道穿过泗水镇，村驻地经Y122乡道与X038县道与泗水镇中心连接。",
      "[traffic] 模型观察: [内部交通]：金田村内交通以村道为主，各村道沿Y122乡道呈梳状南北纵向分布。Y122乡道是村中唯一的东西方向道路，缺乏其他东西向联系通道。目前村内道路已基本实现简单硬化，村道硬化长度达16km，巷道硬化长度达10km。但部分道路仍为砂石路或机耕路，且村庄道路较窄，大部分宽度不足8米，道路两旁景观较差。",
      "[traffic] 模型观察: [交通设施]：金田村现有交通设施相对不足。村内现有停车场1处，位于园寨村村委会，面积不足100㎡，但村内停车基本以路边停车和宅旁停车为主，该停车场未能充分发挥作用。公交站点方面，现状有临时公交站点，分布于社前、园寨、黄竹等自然村，其中仅有一处候车亭位于村庄西南部，其余均为临车上车点。"
    ]
  },
  "villager_wishes": {
    "items": 7,
    "sample": [
      "[villager_wishes] 模型观察: 金田村产业结构单一，经济效益不高，难以支撑村庄建设和发展。第一产业中水稻种植为传统种植业，新兴种植业如林芝和烤烟规模有限，且缺乏第三产业支撑。",
      "[villager_wishes] 模型观察: 村民期望发展经济效益更高的种植产业，如扩大药材种植规模。同时，希望结合本村现有的南粤古驿道、古祠堂、千年古檀等历史文化与生态资源，发展乡村旅游业，实现产业多元化。",
      "[villager_wishes] 模型观察: 金田村村内仍存有部分砂泥路和机耕路尚未硬化，且村内景观缺乏系统建设，整体景观较差，影响村容村貌。"
    ]
  }
}
- **facts_produced**: {
  "items": 24,
  "sample": [
    "[land_use] 模型观察: 土地总用地面积：金田村土地总用地面积约2352.89公顷。",
    "[land_use] 模型观察: 用地结构：金田村用地以农业用地和生态用地为主，建设用地占比较小。具体用地结构如下表所示，其中水域面积35.99公顷已包含在农业用地与生态用地的统计范畴内。",
    "[land_use] 模型观察: 耕地详情：金田村耕地总面积85.2公顷，其中水田面积78.83公顷，旱地面积数据中未提供。按全村户籍人口1403人计算，人均耕地面积约0.91亩。"
  ]
}
- **gate_route**: PASS
- **location_facts**: {
  "items": 48,
  "sample": [
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "建筑集中区",
      "normalized_name": "村中部园寨、马头段",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 建筑集中区 | 村中部园寨、马头段 | 现状建筑分布较分散，主要集中于此",
      "spatial_hint": "村中部园寨、马头段"
    },
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "传统祠堂",
      "normalized_name": "社前村、黄竹村、田坑村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 传统祠堂 | 社前村、黄竹村、田坑村 | 具有浓厚客家文化元素的传统建筑",
      "spatial_hint": "社前村、黄竹村、田坑村"
    },
    {
      "aliases": {
        "items": 2
      },
      "confidence": 0.95,
      "dimension_key": "architecture",
      "evidence_refs": {
        "items": 0
      },
      "mention": "农房外立面整治",
      "normalized_name": "田坑、营仔、园寨等9个自然村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状项目 | 农房外立面整治 | 田坑、营仔、园寨等9个自然村 | 对村内农房外立面进行统一整治",
      "spatial_hint": "田坑、营仔、园寨等9个自然村"
    }
  ]
}
- **source_refs**: {
  "items": 15,
  "sample": [
    "l1_observe",
    "L1:architecture",
    "L1:ecological_green"
  ]
}
### 产物摘要（ArtifactStore）
#### l1_snapshot
```json
{
  "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
  "classification_refs": {
    "items": 0,
    "sample": []
  },
  "constraints": {
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:49:12.838904Z",
  "dimension_provenance": {
    "items": 12,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      }
    ]
  },
  "evidence_gaps": {
    "items": 0,
    "sample": []
  },
  "facts": {
    "items": 24,
    "sample": [
      "[land_use] 模型观察: 土地总用地面积：金田村土地总用地面积约2352.89公顷。",
      "[land_use] 模型观察: 用地结构：金田村用地以农业用地和生态用地为主，建设用地占比较小。具体用地结构如下表所示，其中水域面积35.99公顷已包含在农业用地与生态用地的统计范畴内。",
      "[land_use] 模型观察: 耕地详情：金田村耕地总面积85.2公顷，其中水田面积78.83公顷，旱地面积数据中未提供。按全村户籍人口1403人计算，人均耕地面积约0.91亩。"
    ]
  },
  "facts_by_dimension": {
    "architecture": {
      "items": 0
    },
    "ecological_green": {
      "items": 0
    },
    "historical_culture": {
      "items": 0
    },
    "infrastructure": {
      "items": 0
    },
    "land_use": {
      "items": 8
    },
    "location": {
      "items": 0
    },
    "natural_environment": {
      "items": 0
    },
    "public_services": {
      "items": 0
    },
    "socio_economic": {
      "items": 3
    },
    "superior_planning": {
      "items": 0
    },
    "traffic": {
      "items": 4
    },
    "villager_wishes": {
      "items": 7
    }
  },
  "issues": {
    "items": 0,
    "sample": []
  },
  "location_facts": {
    "items": 48,
    "sample": [
      {
        "key_count": 11,
        "keys": [
          "aliases",
          "confidence",
          "dimension_key",
          "evidence_refs",
          "mention",
          "normalized_name",
          "related_mentions",
          "role",
          "source_report_ref",
          "source_span",
          "spatial_hint"
        ]
      },
      {
        "key_count": 11,
        "keys": [
          "aliases",
          "confidence",
          "dimension_key",
          "evidence_refs",
          "mention",
          "normalized_name",
          "related_mentions",
          "role",
          "source_report_ref",
          "source_span",
          "spatial_hint"
        ]
      },
      {
        "key_count": 11,
        "keys": [
          "aliases",
          "confidence",
          "dimension_key",
          "evidence_refs",
          "mention",
          "normalized_name",
          "related_mentions",
          "role",
          "source_report_ref",
          "source_span",
          "spatial_hint"
        ]
      }
    ]
  },
  "opportunities": {
    "items": 0,
    "sample": []
  },
  "provenance": {
    "module": "l1_observe",
    "natural_language_description": "L1 OBSERVE aggregated snapshot from compiled dimension fragments.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "l1_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:49:12.911218Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "sources": {
    "items": 15,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "confidence",
          "reference",
          "retrieved_at",
          "source_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "confidence",
          "reference",
          "retrieved_at",
          "source_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "confidence",
          "reference",
          "retrieved_at",
          "source_type"
        ]
      }
    ]
  }
}
```
### 诊断
- fact_producer: L1 report compiler + session KG evidence promotion
- kg_fact_count: 2
### 产物
- **l1_snapshot**: `l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1` (type=L1Snapshot, revision=v1)

## L2 / l2_aggregate
- timestamp: 2026-08-07T16:52:32.815980
### 产出
- **development_goals**: {
  "items": 15,
  "sample": [
    "[总体目标：梅州市平远县绿美生态与古驿客家文化特色保护示范村]",
    "耕地保有量：85.2公顷（约束性）",
    "永久基本农田保护面积：80.0公顷（约束性）"
  ]
}
- **evidence_gap_count**: 1
- **evidence_refs**: {
  "items": 0,
  "sample": []
}
- **gate_route**: PASS
- **implementation_priorities**: {
  "items": 7,
  "sample": [
    "生态优先——生态保护网格化（针对地质灾害中易发与生态林管护问题，实施40处地灾隐患点工程治理与生物防护，建立三级生态林巡护机制，覆盖40处隐患点及325.9公顷生态公益林）",
    "产业振兴——主导产业特色化（针对产业规模小与耕地破碎问题，扩大灵芝与烤烟林下种植，整合耕地发展规模化水稻种植，开发农文旅融合项目，预期带动150人就业与人均收入提升20%）",
    "设施完善——基础设施标准化（针对排水分散与交通设施不足问题，建设集中式雨污分流管网与微型污水处理设施，拓宽瓶颈路段并增设生态停车场与公交候车亭，覆盖12个自然村）"
  ]
}
### 产物摘要（ArtifactStore）
#### l2_strategy
```json
{
  "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:52:32.810652Z",
  "development_goals": {
    "items": 15,
    "sample": [
      "[总体目标：梅州市平远县绿美生态与古驿客家文化特色保护示范村]",
      "耕地保有量：85.2公顷（约束性）",
      "永久基本农田保护面积：80.0公顷（约束性）"
    ]
  },
  "dimension_provenance": {
    "items": 4,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "module",
          "natural_language_description",
          "raw_text",
          "reasoning_trace",
          "run_id",
          "source",
          "spatial_hint",
          "timestamp",
          "trace"
        ]
      }
    ]
  },
  "evidence_gaps": {
    "items": 1,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "description",
          "dimension",
          "gap_id",
          "required_fact",
          "severity"
        ]
      }
    ]
  },
  "evidence_refs": {
    "items": 0,
    "sample": []
  },
  "implementation_priorities": {
    "items": 7,
    "sample": [
      "生态优先——生态保护网格化（针对地质灾害中易发与生态林管护问题，实施40处地灾隐患点工程治理与生物防护，建立三级生态林巡护机制，覆盖40处隐患点及325.9公顷生态公益林）",
      "产业振兴——主导产业特色化（针对产业规模小与耕地破碎问题，扩大灵芝与烤烟林下种植，整合耕地发展规模化水稻种植，开发农文旅融合项目，预期带动150人就业与人均收入提升20%）",
      "设施完善——基础设施标准化（针对排水分散与交通设施不足问题，建设集中式雨污分流管网与微型污水处理设施，拓宽瓶颈路段并增设生态停车场与公交候车亭，覆盖12个自然村）"
    ]
  },
  "provenance": {
    "module": "l2_observe",
    "natural_language_description": "L2 STRATEGIZE aggregated strategy from compiled dimension fragments.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "l2_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:52:32.810686Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "sources": {
    "items": 1,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "confidence",
          "reference",
          "retrieved_at",
          "source_type"
        ]
      }
    ]
  },
  "spatial_structure": "特色保护类",
  "strategy_conflicts": {
    "items": 0,
    "sample": []
  },
  "strategy_issues": {
    "items": 1,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "code",
          "detail",
          "message",
          "severity",
          "stage"
        ]
      }
    ]
  }
}
```
### 诊断
- fact_consumer: L2 dimension prompts via EXPLORE evidence service
### 产物
- **l2_strategy**: `l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1` (type=L2Strategy, revision=v1)

## PARSE / parse_node
- timestamp: 2026-08-07T16:57:31.552221
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": ""
}
- **input_checksum**: f780be7408b70774890dcdf7552ce713f8575dcb08f31acf9c10f7e5c2348757
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## PARSE / parse_node
- timestamp: 2026-08-07T16:57:33.048082
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": ""
}
- **input_checksum**: f780be7408b70774890dcdf7552ce713f8575dcb08f31acf9c10f7e5c2348757
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  }
}
- **output_checksum**: d19548e1578f96f0602bf4aa3bbb7a412d610e4827c543669aabc6ae21e91901
- **output_keys**: {
  "items": 7,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### intent_compilation
```json
{
  "artifact_id": "",
  "base_revision_ref": "",
  "compilation_errors": {
    "items": 0,
    "sample": []
  },
  "compilation_status": "validated",
  "confidence": 0.0,
  "constraint_set": null,
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-07T08:57:33.038136Z",
  "diagnostics": {
    "items": 44,
    "sample": [
      {
        "key_count": 6,
        "keys": [
          "code",
          "diagnostic_id",
          "field_path",
          "message",
          "severity",
          "source_text_loc"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "diagnostic_id",
          "field_path",
          "message",
          "severity",
          "source_text_loc"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "diagnostic_id",
          "field_path",
          "message",
          "severity",
          "source_text_loc"
        ]
      }
    ]
  },
  "intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  },
  "patches": {
    "items": 0,
    "sample": []
  },
  "program_ref": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
  "project_requirements": {
    "items": 56,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "area_range",
          "constraints",
          "functions",
          "project_ref",
          "spatial_requirements"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "area_range",
          "constraints",
          "functions",
          "project_ref",
          "spatial_requirements"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "area_range",
          "constraints",
          "functions",
          "project_ref",
          "spatial_requirements"
        ]
      }
    ]
  },
  "provenance": {
    "module": "parse",
    "natural_language_description": "Deterministic compile of PlanningProgram l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1 into SpatialPlanningIntent",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "parse",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:57:33.038125Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_reference_specs": {
    "items": 13,
    "sample": [
      {
        "key_count": 11,
        "keys": [
          "attr_filter",
          "children",
          "direction",
          "distance_m",
          "intervention_id",
          "op",
          "project_ref",
          "reference",
          "relation",
          "topo",
          "type"
        ],
        "type": "topological"
      },
      {
        "key_count": 11,
        "keys": [
          "attr_filter",
          "children",
          "direction",
          "distance_m",
          "intervention_id",
          "op",
          "project_ref",
          "reference",
          "relation",
          "topo",
          "type"
        ],
        "type": "topological"
      },
      {
        "key_count": 11,
        "keys": [
          "attr_filter",
          "children",
          "direction",
          "distance_m",
          "intervention_id",
          "op",
          "project_ref",
          "reference",
          "relation",
          "topo",
          "type"
        ],
        "type": "topological"
      }
    ]
  },
  "trace": {
    "finished_at": "2026-08-07T08:57:33.038098+00:00",
    "mode": "compile",
    "started_at": "2026-08-07T08:57:33.038098+00:00",
    "steps": {
      "items": 3
    }
  },
  "typed_intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 1495.94
- gate_route: PASS
- status: stage_completed
### 产物
- **intent_compilation**: `intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe` (type=IntentCompilationResult, revision=v1)

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:33.079844
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 4441e2b5a4f2573c283da26defa4ec28f86c149bab6be2aa155ce13570d9d5f0
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:37.677371
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 4441e2b5a4f2573c283da26defa4ec28f86c149bab6be2aa155ce13570d9d5f0
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:37.671316Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:37.671318Z"
  }
}
- **output_checksum**: 732f92a644217dfa4985f0489723b7ff2c910cea13d7a5addd60e56cbe45ca92
- **output_keys**: {
  "items": 6,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 13,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      }
    ]
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:11.109902Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:11.109887Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 13,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      }
    ]
  },
  "unresolved": {
    "items": 0,
    "sample": []
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 4597.59
- gate_route: PASS
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba` (type=GroundingResult, revision=v1)

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:43.659396
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.632835Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.632840Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:37.671316Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:37.671318Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.627569Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.627571Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: c24b28e02d71392b521edf8a219d6ac4a78b964ed02b85f20a538dae5f63b3f7
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:48.662687
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.632835Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.632840Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:37.671316Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:37.671318Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.627569Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.627571Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: c24b28e02d71392b521edf8a219d6ac4a78b964ed02b85f20a538dae5f63b3f7
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:48.658222Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:48.658224Z"
  }
}
- **output_checksum**: 2ba330426c30b301574ffed473a9fc0e9fee8db95293196f9c2acbd178b29ac0
- **output_keys**: {
  "items": 6,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 13,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      }
    ]
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:11.109902Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:11.109887Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 13,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      }
    ]
  },
  "unresolved": {
    "items": 0,
    "sample": []
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 5003.37
- gate_route: PASS
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28` (type=GroundingResult, revision=v1)

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:55.534079
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.513031Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.513034Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:48.658222Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:48.658224Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.509113Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.509116Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: a9f68215b4b891787bf99f05c65d1723b21368bf02f326774f618c0b78e14cae
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-07T16:57:59.818880
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.513031Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.513034Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:48.658222Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:48.658224Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.509113Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.509116Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: a9f68215b4b891787bf99f05c65d1723b21368bf02f326774f618c0b78e14cae
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:59.813451Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:59.813453Z"
  }
}
- **output_checksum**: b7040d02f8404e9b4040d19b3cbb0b194ee2d335ba1726fb08a70f7726986f52
- **output_keys**: {
  "items": 6,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 13,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      }
    ]
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:11.109902Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:11.109887Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 13,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      }
    ]
  },
  "unresolved": {
    "items": 0,
    "sample": []
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 4284.87
- gate_route: PASS
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a` (type=GroundingResult, revision=v1)

## GROUND / ground_node
- timestamp: 2026-08-07T16:58:06.721823
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.694830Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.694834Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:59.813451Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:59.813453Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.689743Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.689745Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 385c15f0626ed01eecc0841c9f35472fbf3933d132d3fcd8b9d201aeb47f06b6
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-07T16:58:11.119438
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.694830Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.694834Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:59.813451Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:59.813453Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.689743Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.689745Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 385c15f0626ed01eecc0841c9f35472fbf3933d132d3fcd8b9d201aeb47f06b6
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-57934d35ba36d122",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:11.110116Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:11.110119Z"
  }
}
- **output_checksum**: 0596693253a743830cd6d0f999969e369dd1c1e638723bc205ac50fa440a135c
- **output_keys**: {
  "items": 6,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 13,
    "sample": [
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      },
      {
        "key_count": 9,
        "keys": [
          "available_area_ha",
          "available_geometry_wkt",
          "evidence_refs",
          "hard_constraint_result",
          "metrics",
          "project_ref",
          "site_id",
          "source_parcels",
          "target_ref"
        ]
      }
    ]
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:11.109902Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:11.109887Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 13,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "query_params",
          "query_type",
          "result_count",
          "result_refs"
        ]
      }
    ]
  },
  "unresolved": {
    "items": 0,
    "sample": []
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 4397.7
- gate_route: PASS
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-57934d35ba36d122` (type=GroundingResult, revision=v1)

## SELECT / select_node
- timestamp: 2026-08-07T16:57:37.696737
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:37.671316Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:37.671318Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 4e1a08261fb9214f96c3145f02e67d00656810dae6bd5e25f9ed24249a8210f2
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## SELECT / select_node
- timestamp: 2026-08-07T16:57:43.640055
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-80468a8d5f4d61ba",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:37.671316Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:37.671318Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 4e1a08261fb9214f96c3145f02e67d00656810dae6bd5e25f9ed24249a8210f2
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.632835Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.632840Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.627569Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.627571Z"
  }
}
- **output_checksum**: b1b3fd00accdaff8d3516841b659331f40777527e860595b23221f982a5f7e33
- **output_keys**: {
  "items": 7,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### site_selection
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:14.713192Z",
  "decision_factors": {
    "best_score_by_target": {
      "key_count": 16,
      "keys": [
        "heritage-int-1",
        "industry-int-0",
        "industry-int-12",
        "industry-int-13",
        "industry-int-14",
        "industry-int-17",
        "industry-int-18",
        "industry-int-19",
        "industry-int-2",
        "industry-int-8",
        "infrastructure_planning-int-1",
        "project_bank-int-10",
        "project_bank-int-3",
        "public_service-int-0",
        "settlement_planning-int-1",
        "traffic_planning-int-2"
      ]
    },
    "facility_count": 1,
    "facility_placements": {
      "key_count": 1,
      "keys": [
        "facility_0"
      ]
    },
    "placed_count": 13,
    "target_count": 16,
    "unplaced_count": 3
  },
  "eliminated": {
    "items": 349,
    "sample": [
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      }
    ]
  },
  "full_ranking": {
    "items": 14,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      }
    ]
  },
  "provenance": {
    "module": "app.agent.select.aggregate",
    "natural_language_description": "SELECT aggregate for 16 targets",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "select_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:14.713176Z",
    "trace": {
      "items": 1
    }
  },
  "review_status": "auto",
  "schema_version": "1.0",
  "selected_combination": {
    "items": 14,
    "sample": [
      "00000000000000001093",
      "00000000000000001064",
      "00000000000000001120"
    ]
  }
}
```
#### execution_plan
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-07T08:58:17.970692Z",
  "dependencies": {
    "items": 0,
    "sample": []
  },
  "intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  },
  "land_design_briefs": {
    "items": 13,
    "sample": [
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      }
    ]
  },
  "plan_id": "execute-4e437148-5ed4-46a6-a8d4-1881b717850a",
  "provenance": null,
  "schema_version": "1.0",
  "site_selection": {
    "artifact_id": "",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:58:14.713192Z",
    "decision_factors": {
      "key_count": 6,
      "keys": [
        "best_score_by_target",
        "facility_count",
        "facility_placements",
        "placed_count",
        "target_count",
        "unplaced_count"
      ]
    },
    "eliminated": {
      "items": 349
    },
    "full_ranking": {
      "items": 14
    },
    "provenance": {
      "key_count": 9,
      "keys": [
        "module",
        "natural_language_description",
        "raw_text",
        "reasoning_trace",
        "run_id",
        "source",
        "spatial_hint",
        "timestamp",
        "trace"
      ]
    },
    "review_status": "auto",
    "schema_version": "1.0",
    "selected_combination": {
      "items": 14
    }
  },
  "worker_tasks": {
    "items": 57,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 5943.41
- gate_route: RETRY_GROUND
- status: stage_completed
### 产物
- **site_selection**: `site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81` (type=SiteSelectionDecision, revision=v1)
- **execution_plan**: `execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad` (type=ExecutionPlan, revision=v1)

## SELECT / select_node
- timestamp: 2026-08-07T16:57:48.675651
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.632835Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.632840Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:48.658222Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:48.658224Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.627569Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.627571Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 65c32510648ff39ad3c4ec49b610fd4138274a38a6f830b506b15dd871394d43
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 1
- status: stage_started

## SELECT / select_node
- timestamp: 2026-08-07T16:57:55.519749
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-58d09462bfe416ad",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.632835Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.632840Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-8e1592fab4b06c28",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:48.658222Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:48.658224Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-da85d2c1cfd36e81",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:43.627569Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:43.627571Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 65c32510648ff39ad3c4ec49b610fd4138274a38a6f830b506b15dd871394d43
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.513031Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.513034Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.509113Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.509116Z"
  }
}
- **output_checksum**: 221e36b2dfac45a1c6b26b7203468ad29f191b241335c367942b46015d038e51
- **output_keys**: {
  "items": 9,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### site_selection
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:14.713192Z",
  "decision_factors": {
    "best_score_by_target": {
      "key_count": 16,
      "keys": [
        "heritage-int-1",
        "industry-int-0",
        "industry-int-12",
        "industry-int-13",
        "industry-int-14",
        "industry-int-17",
        "industry-int-18",
        "industry-int-19",
        "industry-int-2",
        "industry-int-8",
        "infrastructure_planning-int-1",
        "project_bank-int-10",
        "project_bank-int-3",
        "public_service-int-0",
        "settlement_planning-int-1",
        "traffic_planning-int-2"
      ]
    },
    "facility_count": 1,
    "facility_placements": {
      "key_count": 1,
      "keys": [
        "facility_0"
      ]
    },
    "placed_count": 13,
    "target_count": 16,
    "unplaced_count": 3
  },
  "eliminated": {
    "items": 349,
    "sample": [
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      }
    ]
  },
  "full_ranking": {
    "items": 14,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      }
    ]
  },
  "provenance": {
    "module": "app.agent.select.aggregate",
    "natural_language_description": "SELECT aggregate for 16 targets",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "select_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:14.713176Z",
    "trace": {
      "items": 1
    }
  },
  "review_status": "auto",
  "schema_version": "1.0",
  "selected_combination": {
    "items": 14,
    "sample": [
      "00000000000000001093",
      "00000000000000001064",
      "00000000000000001120"
    ]
  }
}
```
#### execution_plan
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-07T08:58:17.970692Z",
  "dependencies": {
    "items": 0,
    "sample": []
  },
  "intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  },
  "land_design_briefs": {
    "items": 13,
    "sample": [
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      }
    ]
  },
  "plan_id": "execute-4e437148-5ed4-46a6-a8d4-1881b717850a",
  "provenance": null,
  "schema_version": "1.0",
  "site_selection": {
    "artifact_id": "",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:58:14.713192Z",
    "decision_factors": {
      "key_count": 6,
      "keys": [
        "best_score_by_target",
        "facility_count",
        "facility_placements",
        "placed_count",
        "target_count",
        "unplaced_count"
      ]
    },
    "eliminated": {
      "items": 349
    },
    "full_ranking": {
      "items": 14
    },
    "provenance": {
      "key_count": 9,
      "keys": [
        "module",
        "natural_language_description",
        "raw_text",
        "reasoning_trace",
        "run_id",
        "source",
        "spatial_hint",
        "timestamp",
        "trace"
      ]
    },
    "review_status": "auto",
    "schema_version": "1.0",
    "selected_combination": {
      "items": 14
    }
  },
  "worker_tasks": {
    "items": 57,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 6844.18
- gate_route: RETRY_GROUND
- status: stage_completed
### 产物
- **site_selection**: `site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9` (type=SiteSelectionDecision, revision=v1)
- **execution_plan**: `execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034` (type=ExecutionPlan, revision=v1)

## SELECT / select_node
- timestamp: 2026-08-07T16:57:59.844644
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.513031Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.513034Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:59.813451Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:59.813453Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.509113Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.509116Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 6ef69d0b268f6f8bbbf9e3ba223c8f57a30dce9e1db626ee8a751c8b9cde21b6
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 2
- status: stage_started

## SELECT / select_node
- timestamp: 2026-08-07T16:58:06.700800
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-666618a30bc8e034",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.513031Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.513034Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-b8df8f0b3263009a",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:59.813451Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:59.813453Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-659d2d7cad5f52d9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:55.509113Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:55.509116Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 6ef69d0b268f6f8bbbf9e3ba223c8f57a30dce9e1db626ee8a751c8b9cde21b6
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.694830Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.694834Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.689743Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.689745Z"
  }
}
- **output_checksum**: ad4c1bb6aec4d2d56079c4cbe78a934b322d8173e37c2343aae1aedb68b9ea45
- **output_keys**: {
  "items": 9,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### site_selection
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:14.713192Z",
  "decision_factors": {
    "best_score_by_target": {
      "key_count": 16,
      "keys": [
        "heritage-int-1",
        "industry-int-0",
        "industry-int-12",
        "industry-int-13",
        "industry-int-14",
        "industry-int-17",
        "industry-int-18",
        "industry-int-19",
        "industry-int-2",
        "industry-int-8",
        "infrastructure_planning-int-1",
        "project_bank-int-10",
        "project_bank-int-3",
        "public_service-int-0",
        "settlement_planning-int-1",
        "traffic_planning-int-2"
      ]
    },
    "facility_count": 1,
    "facility_placements": {
      "key_count": 1,
      "keys": [
        "facility_0"
      ]
    },
    "placed_count": 13,
    "target_count": 16,
    "unplaced_count": 3
  },
  "eliminated": {
    "items": 349,
    "sample": [
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      }
    ]
  },
  "full_ranking": {
    "items": 14,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      }
    ]
  },
  "provenance": {
    "module": "app.agent.select.aggregate",
    "natural_language_description": "SELECT aggregate for 16 targets",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "select_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:14.713176Z",
    "trace": {
      "items": 1
    }
  },
  "review_status": "auto",
  "schema_version": "1.0",
  "selected_combination": {
    "items": 14,
    "sample": [
      "00000000000000001093",
      "00000000000000001064",
      "00000000000000001120"
    ]
  }
}
```
#### execution_plan
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-07T08:58:17.970692Z",
  "dependencies": {
    "items": 0,
    "sample": []
  },
  "intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  },
  "land_design_briefs": {
    "items": 13,
    "sample": [
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      }
    ]
  },
  "plan_id": "execute-4e437148-5ed4-46a6-a8d4-1881b717850a",
  "provenance": null,
  "schema_version": "1.0",
  "site_selection": {
    "artifact_id": "",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:58:14.713192Z",
    "decision_factors": {
      "key_count": 6,
      "keys": [
        "best_score_by_target",
        "facility_count",
        "facility_placements",
        "placed_count",
        "target_count",
        "unplaced_count"
      ]
    },
    "eliminated": {
      "items": 349
    },
    "full_ranking": {
      "items": 14
    },
    "provenance": {
      "key_count": 9,
      "keys": [
        "module",
        "natural_language_description",
        "raw_text",
        "reasoning_trace",
        "run_id",
        "source",
        "spatial_hint",
        "timestamp",
        "trace"
      ]
    },
    "review_status": "auto",
    "schema_version": "1.0",
    "selected_combination": {
      "items": 14
    }
  },
  "worker_tasks": {
    "items": 57,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 2
- duration_ms: 6856.3
- gate_route: RETRY_GROUND
- status: stage_completed
### 产物
- **site_selection**: `site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9` (type=SiteSelectionDecision, revision=v1)
- **execution_plan**: `execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e` (type=ExecutionPlan, revision=v1)

## SELECT / select_node
- timestamp: 2026-08-07T16:58:11.140388
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.694830Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.694834Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-57934d35ba36d122",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:11.110116Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:11.110119Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.689743Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.689745Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 999844ec8b6a6c895d961b0e6ce2c53303f0d0c62e687c336868bead2d3b2af5
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 诊断
- attempt: 3
- status: stage_started

## SELECT / select_node
- timestamp: 2026-08-07T16:58:17.983059
### 输入
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-6e80c5067402a27e",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.694830Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.694834Z"
  },
  "grounding_result": {
    "artifact_id": "grounding_result-4e437148-5ed4-46a6-a8d4-1881b717850a-57934d35ba36d122",
    "artifact_type": "GroundingResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:11.110116Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:11.110119Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-4e437148-5ed4-46a6-a8d4-1881b717850a-2f77808c9501dabe",
    "artifact_type": "IntentCompilationResult",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:57:33.038729Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:33.038733Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L1Snapshot",
    "context_version": "",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "l2_strategy": {
    "artifact_id": "l2-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "L2Strategy",
    "context_version": "",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a"
  },
  "planning_program": {
    "artifact_id": "l3-4e437148-5ed4-46a6-a8d4-1881b717850a-v1",
    "artifact_type": "PlanningProgram",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:57:31.536534Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:57:31.536540Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-14b49775d6b757c9",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:06.689743Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:06.689745Z"
  }
}
- **context_ref**: {
  "session_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
  "version": "1"
}
- **input_checksum**: 999844ec8b6a6c895d961b0e6ce2c53303f0d0c62e687c336868bead2d3b2af5
- **source_refs**: {
  "items": 0,
  "sample": []
}
### 产出
- **artifact_refs**: {
  "execution_plan": {
    "artifact_id": "execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-8f2332c807bf2e93",
    "artifact_type": "ExecutionPlan",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:17.974363Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:17.974366Z"
  },
  "site_selection": {
    "artifact_id": "site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-b617217613ec854d",
    "artifact_type": "SiteSelectionDecision",
    "context_fingerprint": "sha256:fb83f135404ccc40",
    "context_version": "1",
    "created_at": "2026-08-07T08:58:17.970790Z",
    "module": "select",
    "revision": "v1",
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "schema_version": "1.0",
    "stored_at": "2026-08-07T08:58:17.970791Z"
  }
}
- **output_checksum**: b9350f57c7ad83f90f82a8d97ec2263463e5210da2a99f5dd7fe8af196471b06
- **output_keys**: {
  "items": 9,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
### 产物摘要（ArtifactStore）
#### site_selection
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-07T08:58:14.713192Z",
  "decision_factors": {
    "best_score_by_target": {
      "key_count": 16,
      "keys": [
        "heritage-int-1",
        "industry-int-0",
        "industry-int-12",
        "industry-int-13",
        "industry-int-14",
        "industry-int-17",
        "industry-int-18",
        "industry-int-19",
        "industry-int-2",
        "industry-int-8",
        "infrastructure_planning-int-1",
        "project_bank-int-10",
        "project_bank-int-3",
        "public_service-int-0",
        "settlement_planning-int-1",
        "traffic_planning-int-2"
      ]
    },
    "facility_count": 1,
    "facility_placements": {
      "key_count": 1,
      "keys": [
        "facility_0"
      ]
    },
    "placed_count": 13,
    "target_count": 16,
    "unplaced_count": 3
  },
  "eliminated": {
    "items": 349,
    "sample": [
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      },
      {
        "key_count": 3,
        "keys": [
          "candidate_id",
          "eliminated_by_constraint",
          "elimination_reason"
        ]
      }
    ]
  },
  "full_ranking": {
    "items": 14,
    "sample": [
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      },
      {
        "key_count": 5,
        "keys": [
          "candidate_id",
          "project_ref",
          "rank",
          "score",
          "score_breakdown"
        ]
      }
    ]
  },
  "provenance": {
    "module": "app.agent.select.aggregate",
    "natural_language_description": "SELECT aggregate for 16 targets",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "4e437148-5ed4-46a6-a8d4-1881b717850a",
    "source": "select_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-07T08:58:14.713176Z",
    "trace": {
      "items": 1
    }
  },
  "review_status": "auto",
  "schema_version": "1.0",
  "selected_combination": {
    "items": 14,
    "sample": [
      "00000000000000001093",
      "00000000000000001064",
      "00000000000000001120"
    ]
  }
}
```
#### execution_plan
```json
{
  "artifact_id": "",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-07T08:58:17.970692Z",
  "dependencies": {
    "items": 0,
    "sample": []
  },
  "intent": {
    "construction_area_ha": null,
    "custom_zone_targets": {
      "items": 0
    },
    "development_axes": {
      "items": 0
    },
    "ecological_area_ha": null,
    "facilities": {
      "items": 1
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 56
    },
    "raw_text": "",
    "reasoning_trace": "",
    "road_targets": {
      "items": 0
    },
    "three_zones_three_lines": null,
    "total_area_ha": null,
    "village_name": "",
    "vocabulary_name": "",
    "zone_targets": {
      "items": 0
    }
  },
  "land_design_briefs": {
    "items": 13,
    "sample": [
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      },
      {
        "key_count": 7,
        "keys": [
          "access_requirements",
          "adjacency_requirements",
          "area_tolerance_pct",
          "footprint_conditions",
          "preservation_requirements",
          "project_ref",
          "setback_requirements"
        ]
      }
    ]
  },
  "plan_id": "execute-4e437148-5ed4-46a6-a8d4-1881b717850a",
  "provenance": null,
  "schema_version": "1.0",
  "site_selection": {
    "artifact_id": "",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-07T08:58:14.713192Z",
    "decision_factors": {
      "key_count": 6,
      "keys": [
        "best_score_by_target",
        "facility_count",
        "facility_placements",
        "placed_count",
        "target_count",
        "unplaced_count"
      ]
    },
    "eliminated": {
      "items": 349
    },
    "full_ranking": {
      "items": 14
    },
    "provenance": {
      "key_count": 9,
      "keys": [
        "module",
        "natural_language_description",
        "raw_text",
        "reasoning_trace",
        "run_id",
        "source",
        "spatial_hint",
        "timestamp",
        "trace"
      ]
    },
    "review_status": "auto",
    "schema_version": "1.0",
    "selected_combination": {
      "items": 14
    }
  },
  "worker_tasks": {
    "items": 57,
    "sample": [
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      },
      {
        "key_count": 4,
        "keys": [
          "depends_on",
          "payload",
          "task_id",
          "worker_type"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 3
- duration_ms: 6842.8
- gate_route: RETRY_GROUND
- status: stage_completed
### 产物
- **site_selection**: `site_selection-4e437148-5ed4-46a6-a8d4-1881b717850a-b617217613ec854d` (type=SiteSelectionDecision, revision=v1)
- **execution_plan**: `execution_plan-4e437148-5ed4-46a6-a8d4-1881b717850a-8f2332c807bf2e93` (type=ExecutionPlan, revision=v1)
