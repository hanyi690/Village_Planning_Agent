# GIS 全链阶段报告

- **Session**: d2ba8855-ecd5-4f83-9d4d-3330d1830259
- **Feasible**: False

## Fact lineage（KG → L1 → L2）

以下内容来自实际 session 的 KG、L1Snapshot 和 L2 输入审计；不是测试占位数据。

- **L1 / l1_aggregate**
  - producer: L1 report compiler + session KG evidence promotion
  - facts_produced: {
  "items": 12,
  "sample": [
    "[ecological_green] 模型观察: 村内古树名木资源突出，营仔村分布有100余株古树名木，主要为古檀木且已挂牌保护，构成了重要的现状生态斑块。",
    "[ecological_green] 模型观察: 这形成了村域内重要的生态廊道与水系空间，为村庄提供了良好的生态基底。",
    "[ecological_green] 模型观察: 金田村村委会门前的广场面积最大，广场内设有篮球场，闲时也可起晒场的作用，具备多功能复合使用特征。"
  ]
}
  - location_facts: {
  "items": 60,
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
      "mention": "现状建筑",
      "normalized_name": "金田村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 现状建筑 | 金田村 | 主体和局部结构质量分四类",
      "spatial_hint": "金田村"
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
      "mention": "祠堂",
      "normalized_name": "社前村、黄竹村、田坑村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 祠堂 | 社前村、黄竹村、田坑村 | 具有浓厚客家文化元素",
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
      "normalized_name": "田坑、营仔、园寨等9村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状项目 | 农房外立面整治 | 田坑、营仔、园寨等9村 | 农房外立面整治工程",
      "spatial_hint": "田坑、营仔、园寨等9村"
    }
  ]
}
- **L2 / l2_aggregate**
  - consumer: L2 dimension prompts via EXPLORE evidence service

## KG_PREBUILD / kg_prebuild
- timestamp: 2026-08-08T16:08:22.343907
### 产出
- **cache_hit**: False
- **gazetteer_combo_entries**: 0
- **triple_count**: 33301
- **version**: 1
### 诊断
- road_intersects: 365
- sfTouches: 1708
- water_touches: 0

## L1 / l1_aggregate
- timestamp: 2026-08-08T16:15:08.650952
### 输入
- **artifact_refs**: {}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: b8df85eb9c62305d01967b83374012ca24f2f810d40335cada59d56423c1fa3b
- **source_refs**: {
  "items": 12,
  "sample": [
    "L1:architecture",
    "L1:ecological_green",
    "L1:historical_culture"
  ]
}
### 产出
- **constraint_count**: 0
- **fact_count**: 12
- **facts_by_dimension**: {
  "architecture": {
    "items": 0,
    "sample": []
  },
  "ecological_green": {
    "items": 3,
    "sample": [
      "[ecological_green] 模型观察: 村内古树名木资源突出，营仔村分布有100余株古树名木，主要为古檀木且已挂牌保护，构成了重要的现状生态斑块。",
      "[ecological_green] 模型观察: 这形成了村域内重要的生态廊道与水系空间，为村庄提供了良好的生态基底。",
      "[ecological_green] 模型观察: 金田村村委会门前的广场面积最大，广场内设有篮球场，闲时也可起晒场的作用，具备多功能复合使用特征。"
    ]
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
    "items": 0,
    "sample": []
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
      "[socio_economic] 模型观察: 第一产业：农业为主导，包含水稻种植，以及药材、烤烟等新兴种植业和一定规模的养殖业，林芝种植20亩，烤烟种植60亩，年产量数据中未提供，年产值数据中未提供。",
      "[socio_economic] 模型观察: 第二产业：杉木家具制造业，企业作坊数量数据中未提供，年产值数据中未提供，带动就业人数数据中未提供。",
      "[socio_economic] 模型观察: 第三产业：数据中未提供。"
    ]
  },
  "superior_planning": {
    "items": 4,
    "sample": [
      "[superior_planning] 模型观察: [规划定位要求]：金田村作为泗水镇最北端的村庄，需落实上位规划中泗水镇“以现代农业为基础，生态旅游为特色的美丽小镇”的发展导向。结合平远县“粤闽赣边宜居山城”的总体定位，金田村应依托其丰富的林业资源与南粤古驿道等历史文化底蕴，定位为生态保育与特色农旅融合发展的村庄，支撑乡村振兴与“百县千镇万村高质量发展工程”。",
      "[superior_planning] 模型观察: [规划约束识别]：上位规划对泗水镇及金田村域内的空间底线提出了严格管控要求。必须严守国土空间安全底线，落实蓝线、绿线、黄线、紫线、历史文化保护线以及洪涝风险控制线等防灾减灾底线。同时，金田村地处丘陵山地，属于地质灾害中易发生区，存在多处崩塌与滑坡隐患点，在村庄建设与选址时必须避开地质灾害隐患区域，确保空间安全。",
      "[superior_planning] 模型观察: [政策背景分析]：在“百县千镇万村高质量发展工程”与乡村振兴政策背景下，上位规划强调因地制宜编制村庄规划，引导村庄分类发展。政策要求强化宅基地与乡村产业项目用地保障，统筹镇村连线成片建设，修复田园生态景观，改善农村人居环境。金田村需结合全域土地综合整治等政策工具，优化村庄建设用地布局，提升基本公共服务水平。"
    ]
  },
  "traffic": {
    "items": 0,
    "sample": []
  },
  "villager_wishes": {
    "items": 0,
    "sample": []
  }
}
- **facts_produced**: {
  "items": 12,
  "sample": [
    "[ecological_green] 模型观察: 村内古树名木资源突出，营仔村分布有100余株古树名木，主要为古檀木且已挂牌保护，构成了重要的现状生态斑块。",
    "[ecological_green] 模型观察: 这形成了村域内重要的生态廊道与水系空间，为村庄提供了良好的生态基底。",
    "[ecological_green] 模型观察: 金田村村委会门前的广场面积最大，广场内设有篮球场，闲时也可起晒场的作用，具备多功能复合使用特征。"
  ]
}
- **gate_route**: PASS
- **kg_evidence_produced**: {
  "fact_count": 2,
  "fact_statements": {
    "items": 2,
    "sample": [
      "村域概况: 金田村，总面积2352.86公顷，共660个地块，692条道路，60个设施，0处水域。",
      "annotations_current: 34个要素（current_annotation×34）"
    ]
  },
  "source_refs": {
    "items": 14,
    "sample": [
      "L1:architecture",
      "L1:ecological_green",
      "L1:historical_culture"
    ]
  }
}
- **location_facts**: {
  "items": 60,
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
      "mention": "现状建筑",
      "normalized_name": "金田村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 现状建筑 | 金田村 | 主体和局部结构质量分四类",
      "spatial_hint": "金田村"
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
      "mention": "祠堂",
      "normalized_name": "社前村、黄竹村、田坑村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状设施 | 祠堂 | 社前村、黄竹村、田坑村 | 具有浓厚客家文化元素",
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
      "normalized_name": "田坑、营仔、园寨等9村",
      "related_mentions": {
        "items": 0
      },
      "role": "village",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状项目 | 农房外立面整治 | 田坑、营仔、园寨等9村 | 农房外立面整治工程",
      "spatial_hint": "田坑、营仔、园寨等9村"
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
  "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "classification_refs": {
    "items": 0,
    "sample": []
  },
  "constraints": {
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T08:15:08.500764Z",
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
    "items": 12,
    "sample": [
      "[ecological_green] 模型观察: 村内古树名木资源突出，营仔村分布有100余株古树名木，主要为古檀木且已挂牌保护，构成了重要的现状生态斑块。",
      "[ecological_green] 模型观察: 这形成了村域内重要的生态廊道与水系空间，为村庄提供了良好的生态基底。",
      "[ecological_green] 模型观察: 金田村村委会门前的广场面积最大，广场内设有篮球场，闲时也可起晒场的作用，具备多功能复合使用特征。"
    ]
  },
  "facts_by_dimension": {
    "architecture": {
      "items": 0
    },
    "ecological_green": {
      "items": 3
    },
    "historical_culture": {
      "items": 0
    },
    "infrastructure": {
      "items": 0
    },
    "land_use": {
      "items": 0
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
      "items": 4
    },
    "traffic": {
      "items": 0
    },
    "villager_wishes": {
      "items": 0
    }
  },
  "issues": {
    "items": 0,
    "sample": []
  },
  "location_facts": {
    "items": 60,
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
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "l1_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:15:08.628950Z",
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
- **l1_snapshot**: `l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1` (type=L1Snapshot, revision=v1, checksum=641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42)

## L2 / l2_aggregate
- timestamp: 2026-08-08T16:18:45.510240
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: c880438a77632de3577a591b49812a89b801ed5bb66f827fd2a34a1b9eff4a93
- **source_refs**: {
  "items": 5,
  "sample": [
    "artifact:l1_snapshot",
    "L2:development_goals",
    "L2:planning_positioning"
  ]
}
### 产出
- **development_goals**: {
  "items": 15,
  "sample": [
    "[总体目标：粤闽赣边古驿道文化传承与生态农旅融合发展示范村]",
    "耕地保有量：85.20公顷（约束性）",
    "永久基本农田保护面积：78.83公顷（约束性）"
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
    "生态优先——生态保护网格化（针对40处地质灾害隐患与生态林保护需求，实施35处滑坡和5处崩塌工程治理，划定325.92公顷生态林严格保护区，覆盖40处隐患点及325.92公顷生态林）",
    "产业振兴——主导产业特色化（针对产业规模小与三产缺乏问题，整合85.2公顷耕地推进水田流转，扩大灵芝与烤烟种植规模，升级杉木家具制造，预期带动新增就业150人及人均收入提升20%）",
    "设施完善——基础设施标准化（针对污水直排与垃圾收集不规范问题，新建1座集中污水处理设施及管网，规范设置12个标准化垃圾收集点，拓宽16千米村道，覆盖12个自然村）"
  ]
}
### 产物摘要（ArtifactStore）
#### l2_strategy
```json
{
  "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T08:18:45.498356Z",
  "development_goals": {
    "items": 15,
    "sample": [
      "[总体目标：粤闽赣边古驿道文化传承与生态农旅融合发展示范村]",
      "耕地保有量：85.20公顷（约束性）",
      "永久基本农田保护面积：78.83公顷（约束性）"
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
      "生态优先——生态保护网格化（针对40处地质灾害隐患与生态林保护需求，实施35处滑坡和5处崩塌工程治理，划定325.92公顷生态林严格保护区，覆盖40处隐患点及325.92公顷生态林）",
      "产业振兴——主导产业特色化（针对产业规模小与三产缺乏问题，整合85.2公顷耕地推进水田流转，扩大灵芝与烤烟种植规模，升级杉木家具制造，预期带动新增就业150人及人均收入提升20%）",
      "设施完善——基础设施标准化（针对污水直排与垃圾收集不规范问题，新建1座集中污水处理设施及管网，规范设置12个标准化垃圾收集点，拓宽16千米村道，覆盖12个自然村）"
    ]
  },
  "provenance": {
    "module": "l2_observe",
    "natural_language_description": "L2 STRATEGIZE aggregated strategy from compiled dimension fragments.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "l2_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:18:45.498395Z",
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
- **l2_strategy**: `l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1` (type=L2Strategy, revision=v1, checksum=14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619)

## L3 / l3_aggregate
- timestamp: 2026-08-08T16:23:34.583460
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 79b0e851de44c8ce7923b632e7198df10564d92f85dd83c4220ea39c479ebc36
- **source_refs**: {
  "items": 14,
  "sample": [
    "artifact:l1_snapshot",
    "artifact:l2_strategy",
    "L3:disaster_prevention"
  ]
}
### 产出
- **gate_route**: PASS
- **intervention_count**: 38
- **program_issue_count**: 1
- **spatial_instruction_count**: 0
### 产物摘要（ArtifactStore）
#### planning_program
```json
{
  "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T08:23:34.550703Z",
  "dependencies": {
    "items": 0,
    "sample": []
  },
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
  "interventions": {
    "items": 38,
    "sample": [
      {
        "key_count": 13,
        "keys": [
          "area_range_ha",
          "category",
          "constraints",
          "derives_from_strategy",
          "evidence_refs",
          "functions",
          "implementation_phase",
          "intervention_id",
          "name",
          "problem_addressed",
          "scale",
          "service_population",
          "spatial_requirements"
        ]
      },
      {
        "key_count": 13,
        "keys": [
          "area_range_ha",
          "category",
          "constraints",
          "derives_from_strategy",
          "evidence_refs",
          "functions",
          "implementation_phase",
          "intervention_id",
          "name",
          "problem_addressed",
          "scale",
          "service_population",
          "spatial_requirements"
        ]
      },
      {
        "key_count": 13,
        "keys": [
          "area_range_ha",
          "category",
          "constraints",
          "derives_from_strategy",
          "evidence_refs",
          "functions",
          "implementation_phase",
          "intervention_id",
          "name",
          "problem_addressed",
          "scale",
          "service_population",
          "spatial_requirements"
        ]
      }
    ]
  },
  "l1_snapshot_ref": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "l2_strategy_ref": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "omissions": {
    "items": 0,
    "sample": []
  },
  "program_issues": {
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
  },
  "provenance": {
    "module": "l3_plan",
    "natural_language_description": "L3 PLAN aggregated program from compiled dimension fragments.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "l3_plan",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:34.550748Z",
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
  }
}
```
### 诊断
- fact_consumer: L1Snapshot + L2Strategy + L3 dimension reports
### 产物
- **planning_program**: `l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1` (type=PlanningProgram, revision=v1, checksum=647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b)

## PARSE / parse_node
- timestamp: 2026-08-08T16:23:37.635252
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 25d211a70bc88ac1d5ca28d72e261fbf498c92d04ad0021d2873191db4f6e2e7
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## PARSE / parse_node
- timestamp: 2026-08-08T16:23:39.479956
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 25d211a70bc88ac1d5ca28d72e261fbf498c92d04ad0021d2873191db4f6e2e7
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  }
}
- **output_checksum**: 7994c9a5e4a3f6ff498d9e72cc6db0f8bb8225a13f724ed032ae747dfdc8aa9c
- **output_keys**: {
  "items": 7,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
- **output_summary**: {
  "artifact_refs": {
    "intent_compilation": {
      "key_count": 2,
      "keys": [
        "keys",
        "key_count"
      ]
    }
  },
  "context_fingerprint": "sha256:fbc7ca040e97883d",
  "context_ref": {
    "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "version": "1"
  },
  "context_version": "1",
  "parse_gate": {
    "artifact_id": "gate-parse-0",
    "context_fingerprint": "",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470299Z",
    "evidence_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "feedback_route": null,
    "passed": true,
    "pending_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "schema_version": "1.0",
    "stage": "parse"
  },
  "specs": {
    "items": 10,
    "sample": {
      "items": 3
    }
  },
  "upstream_gates": {
    "items": 1,
    "sample": {
      "items": 1
    }
  }
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
  "created_at": "2026-08-08T08:23:39.470264Z",
  "diagnostics": {
    "items": 30,
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
      "items": 0
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 38
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
  "program_ref": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
  "project_requirements": {
    "items": 38,
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
    "natural_language_description": "Deterministic compile of PlanningProgram l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1 into SpatialPlanningIntent",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "parse",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:39.470250Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_reference_specs": {
    "items": 10,
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
    "finished_at": "2026-08-08T08:23:39.470217+00:00",
    "mode": "compile",
    "started_at": "2026-08-08T08:23:39.470217+00:00",
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
      "items": 0
    },
    "farmland_area_ha": null,
    "indicator_table": null,
    "planning_period": "",
    "population": null,
    "project_targets": {
      "items": 38
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
- duration_ms: 1845.02
- gate_route: PASS
- status: stage_completed
### 产物
- **intent_compilation**: `intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2` (type=IntentCompilationResult, revision=v1, checksum=92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47)

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:39.505667
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: fd7482a836a3f1fa8fdb4670bfb91867604358beed575e182b77cef48c6803b4
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:43.019288
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: fd7482a836a3f1fa8fdb4670bfb91867604358beed575e182b77cef48c6803b4
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-8b1c32f527ebb092",
    "artifact_type": "GroundingResult",
    "checksum": "b5c47533cc03f989a40f59da8b59ec920a7008020eeca37ea7fae432b8a8c2a2",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:43.013951Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:43.013954Z"
  }
}
- **output_checksum**: 57c1312bc8b58089e4cbb0eb09df630d1ccadf6af7e81dca9ffe5d9ad655788e
- **output_keys**: {
  "items": 6,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
- **output_summary**: {
  "artifact_refs": {
    "grounding_result": {
      "key_count": 2,
      "keys": [
        "keys",
        "key_count"
      ]
    }
  },
  "context_fingerprint": "sha256:fbc7ca040e97883d",
  "context_ref": {
    "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "version": "1"
  },
  "context_version": "1",
  "ground_gate": {
    "artifact_id": "gate-ground-0",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-08T08:23:43.013832Z",
    "evidence_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "feedback_route": "EXPLORE",
    "passed": false,
    "pending_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "schema_version": "1.0",
    "stage": "ground"
  },
  "upstream_gates": {
    "items": 2,
    "sample": {
      "items": 2
    }
  }
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 8,
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
  "created_at": "2026-08-08T08:23:53.288686Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:53.288672Z",
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
    "items": 2,
    "sample": [
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 3513.82
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-8b1c32f527ebb092` (type=GroundingResult, revision=v1, checksum=b5c47533cc03f989a40f59da8b59ec920a7008020eeca37ea7fae432b8a8c2a2)

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:43.031576
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-8b1c32f527ebb092",
    "artifact_type": "GroundingResult",
    "checksum": "b5c47533cc03f989a40f59da8b59ec920a7008020eeca37ea7fae432b8a8c2a2",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:43.013951Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:43.013954Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: ab467d30a089c739cff8063d6a32835b09b718a1958a5010a7ed1ce653803cf8
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:46.520373
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-8b1c32f527ebb092",
    "artifact_type": "GroundingResult",
    "checksum": "b5c47533cc03f989a40f59da8b59ec920a7008020eeca37ea7fae432b8a8c2a2",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:43.013951Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:43.013954Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: ab467d30a089c739cff8063d6a32835b09b718a1958a5010a7ed1ce653803cf8
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-1a595b14b9dd9323",
    "artifact_type": "GroundingResult",
    "checksum": "0a350aa4de65d339df1ce236b732490de34b8a351308f83a4e86460dbd05d7de",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:46.512243Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:46.512245Z"
  }
}
- **output_checksum**: be74f7bcf174bddf30a062a4e995ffe417704d924b5e85d88412c833f95236f9
- **output_keys**: {
  "items": 8,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
- **output_summary**: {
  "artifact_refs": {
    "grounding_result": {
      "key_count": 2,
      "keys": [
        "keys",
        "key_count"
      ]
    }
  },
  "context_fingerprint": "sha256:fbc7ca040e97883d",
  "context_ref": {
    "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "version": "1"
  },
  "context_version": "1",
  "error_feedback": {
    "ground": "unresolved spec: no candidates resolved for type=topological"
  },
  "ground_gate": {
    "artifact_id": "gate-ground-0",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-08T08:23:46.512119Z",
    "evidence_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "feedback_route": "EXPLORE",
    "passed": false,
    "pending_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "schema_version": "1.0",
    "stage": "ground"
  },
  "retry_counts": {
    "ground": 1
  },
  "upstream_gates": {
    "items": 3,
    "sample": {
      "items": 3
    }
  }
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 8,
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
  "created_at": "2026-08-08T08:23:53.288686Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:53.288672Z",
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
    "items": 2,
    "sample": [
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 1
- duration_ms: 3488.93
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-1a595b14b9dd9323` (type=GroundingResult, revision=v1, checksum=0a350aa4de65d339df1ce236b732490de34b8a351308f83a4e86460dbd05d7de)

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:46.532839
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-1a595b14b9dd9323",
    "artifact_type": "GroundingResult",
    "checksum": "0a350aa4de65d339df1ce236b732490de34b8a351308f83a4e86460dbd05d7de",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:46.512243Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:46.512245Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 34350b4c8f9f7bee4247da8599f80962d98992d1f6e28cc11962c975150f10a8
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 2
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:49.922852
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-1a595b14b9dd9323",
    "artifact_type": "GroundingResult",
    "checksum": "0a350aa4de65d339df1ce236b732490de34b8a351308f83a4e86460dbd05d7de",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:46.512243Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:46.512245Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 34350b4c8f9f7bee4247da8599f80962d98992d1f6e28cc11962c975150f10a8
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-e754a0c35caad9cc",
    "artifact_type": "GroundingResult",
    "checksum": "d22a5e89cb161a085bdab66ebf98c4bb925791411d13db602ebaa90eeb1f63cc",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:49.915387Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:49.915389Z"
  }
}
- **output_checksum**: 46870c1d8d53637e330107bc194089f010fa76272e38ceb5c3e31c3c19e8449f
- **output_keys**: {
  "items": 8,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
- **output_summary**: {
  "artifact_refs": {
    "grounding_result": {
      "key_count": 2,
      "keys": [
        "keys",
        "key_count"
      ]
    }
  },
  "context_fingerprint": "sha256:fbc7ca040e97883d",
  "context_ref": {
    "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "version": "1"
  },
  "context_version": "1",
  "error_feedback": {
    "ground": "unresolved spec: no candidates resolved for type=topological"
  },
  "ground_gate": {
    "artifact_id": "gate-ground-0",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-08T08:23:49.915264Z",
    "evidence_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "feedback_route": "EXPLORE",
    "passed": false,
    "pending_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "schema_version": "1.0",
    "stage": "ground"
  },
  "retry_counts": {
    "ground": 2
  },
  "upstream_gates": {
    "items": 4,
    "sample": {
      "items": 3
    }
  }
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 8,
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
  "created_at": "2026-08-08T08:23:53.288686Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:53.288672Z",
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
    "items": 2,
    "sample": [
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 2
- duration_ms: 3390.23
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-e754a0c35caad9cc` (type=GroundingResult, revision=v1, checksum=d22a5e89cb161a085bdab66ebf98c4bb925791411d13db602ebaa90eeb1f63cc)

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:49.963303
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-e754a0c35caad9cc",
    "artifact_type": "GroundingResult",
    "checksum": "d22a5e89cb161a085bdab66ebf98c4bb925791411d13db602ebaa90eeb1f63cc",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:49.915387Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:49.915389Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 99be8349f78e9980d32a028c98003617acb23982f5f627c614453ead215c0c33
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 3
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T16:23:53.295959
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-e754a0c35caad9cc",
    "artifact_type": "GroundingResult",
    "checksum": "d22a5e89cb161a085bdab66ebf98c4bb925791411d13db602ebaa90eeb1f63cc",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:49.915387Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:49.915389Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-d2ba8855-ecd5-4f83-9d4d-3330d1830259-82a07ab45c69b0e2",
    "artifact_type": "IntentCompilationResult",
    "checksum": "92f0de2a4ec6cde7ff1d1840640257fae9669635d89f0c881b2fe1bdb0820a47",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:39.470772Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:39.470775Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "641814cceb4e751ae813244b1f3eb4e35e76cfb9ba2e09602d77d7d654a07b42",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "l2_strategy": {
    "artifact_id": "l2-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "L2Strategy",
    "checksum": "14c0fa7b29be80e78fe979ff4b11287b2ffaf7a8575e51aa43e0f9acb190a619",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259"
  },
  "planning_program": {
    "artifact_id": "l3-d2ba8855-ecd5-4f83-9d4d-3330d1830259-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "647a936e39a23f6199be8a39c8901b54f5b3d750d89e4b36bbffdd89f5ac384b",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:34.571121Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:34.571138Z"
  }
}
- **context_ref**: {
  "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
  "version": "1"
}
- **input_checksum**: 99be8349f78e9980d32a028c98003617acb23982f5f627c614453ead215c0c33
- **source_refs**: {
  "items": 10,
  "sample": [
    {
      "checksum": "546340f566e59f0c43af960e9b1c6bda0f3894ba6b5a7ca04d4bc0b973c82dcf",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "admin_boundary_line.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 9,
      "parse_status": "success",
      "size_bytes": 7242376
    },
    {
      "checksum": "31fba31eff26f5041a34b6039411b010e04027de7316dbcdd1e5670ca16c4ab6",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "annotation.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 1,
      "parse_status": "success",
      "size_bytes": 6257
    },
    {
      "checksum": "1a16521f850391167d60f0c1a948fb6f96e4bbc15d58622aeb138d735a03ec07",
      "file_category": "village_data",
      "file_type": "geojson",
      "filename": "boundary.geojson",
      "geometry_audit": {
        "key_count": 5,
        "keys": [
          "feature_count",
          "invalid_count",
          "null_geometry_count",
          "samples",
          "status"
        ]
      },
      "id": 2,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-06ac8162f348fad1",
    "artifact_type": "GroundingResult",
    "checksum": "bf3ce3efbef41f4d004f078a1b48d1fcca885b72f2ac1faa5a9d486d1a024fdb",
    "context_fingerprint": "sha256:fbc7ca040e97883d",
    "context_version": "1",
    "created_at": "2026-08-08T08:23:53.288888Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T08:23:53.288890Z"
  }
}
- **output_checksum**: d84bc32adb98a04c7b09ff239dc2b8c24ffeea0197367947af8a28fe29834a22
- **output_keys**: {
  "items": 8,
  "sample": [
    "artifact_refs",
    "context_fingerprint",
    "context_ref"
  ]
}
- **output_summary**: {
  "artifact_refs": {
    "grounding_result": {
      "key_count": 2,
      "keys": [
        "keys",
        "key_count"
      ]
    }
  },
  "context_fingerprint": "sha256:fbc7ca040e97883d",
  "context_ref": {
    "session_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "version": "1"
  },
  "context_version": "1",
  "error_feedback": {
    "ground": "unresolved spec: no candidates resolved for type=topological"
  },
  "ground_gate": {
    "artifact_id": "gate-ground-0",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-08T08:23:53.288755Z",
    "evidence_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "feedback_route": "EXPLORE",
    "passed": false,
    "pending_requests": {
      "key_count": 1,
      "keys": [
        "items"
      ]
    },
    "schema_version": "1.0",
    "stage": "ground"
  },
  "retry_counts": {
    "ground": 3
  },
  "upstream_gates": {
    "items": 5,
    "sample": {
      "items": 3
    }
  }
}
### 产物摘要（ArtifactStore）
#### grounding_result
```json
{
  "artifact_id": "",
  "candidates": {
    "items": 8,
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
  "created_at": "2026-08-08T08:23:53.288686Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "d2ba8855-ecd5-4f83-9d4d-3330d1830259",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T08:23:53.288672Z",
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
    "items": 2,
    "sample": [
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      },
      {
        "key_count": 6,
        "keys": [
          "code",
          "detail",
          "message",
          "related_artifact_id",
          "severity",
          "stage"
        ]
      }
    ]
  }
}
```
### 诊断
- attempt: 3
- duration_ms: 3332.86
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-d2ba8855-ecd5-4f83-9d4d-3330d1830259-06ac8162f348fad1` (type=GroundingResult, revision=v1, checksum=bf3ce3efbef41f4d004f078a1b48d1fcca885b72f2ac1faa5a9d486d1a024fdb)
