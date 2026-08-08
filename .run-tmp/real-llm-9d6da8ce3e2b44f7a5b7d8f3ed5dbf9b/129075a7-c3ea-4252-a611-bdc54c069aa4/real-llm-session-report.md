# GIS 全链阶段报告

- **Session**: 129075a7-c3ea-4252-a611-bdc54c069aa4
- **Feasible**: False

## Fact lineage（KG → L1 → L2）

以下内容来自实际 session 的 KG、L1Snapshot 和 L2 输入审计；不是测试占位数据。

- **L1 / l1_aggregate**
  - producer: L1 report compiler + session KG evidence promotion
  - facts_produced: {
  "items": 9,
  "sample": [
    "[infrastructure] 模型观察: [供水系统]：金田村现有供水设施干管长度约6000m，基本覆盖全村用水家庭。村内设有5个供水点，分别位于肩丰、长塘、营仔、田坑、黄竹，总用地面积约300㎡，其中4个为饮水工程。",
    "[infrastructure] 模型观察: [排水系统]：金田村各家屋前自设排水设施，主要为污水管和雨水排水沟，由每户自行设置，覆盖全村，但缺乏集中统一的污水处理设施。",
    "[infrastructure] 模型观察: [供电系统]：金田村现有变压器9个，主要分布在营仔、社前、田坑、塘笃、黄竹等自然村。村内现有3个水电站，主要沿石窟河布置。全村大部分道路设有路灯照明设施。"
  ]
}
  - location_facts: {
  "items": 46,
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
      "mention": "园寨",
      "normalized_name": "金田村中部",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 园寨 | 金田村中部 | 建筑集中分布区，新旧建筑穿插建造",
      "spatial_hint": "金田村中部"
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
      "mention": "马头段",
      "normalized_name": "金田村东南部",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 马头段 | 金田村东南部 | 建筑集中分布区，新建筑大多位于此",
      "spatial_hint": "金田村东南部"
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
      "source_span": "现状项目 | 祠堂 | 社前村、黄竹村、田坑村 | 具浓厚客家文化元素的传统风貌建筑",
      "spatial_hint": "社前村、黄竹村、田坑村"
    }
  ]
}
- **L2 / l2_aggregate**
  - consumer: L2 dimension prompts via EXPLORE evidence service

## KG_PREBUILD / kg_prebuild
- timestamp: 2026-08-08T15:14:59.005767
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
- timestamp: 2026-08-08T15:21:30.727331
### 输入
- **artifact_refs**: {}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: 3d4937fc31fadb8c364fee31d1de60d27e6f62e5fee8de6913c260a0ddee4e58
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
- **fact_count**: 9
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
    "items": 5,
    "sample": [
      "[infrastructure] 模型观察: [供水系统]：金田村现有供水设施干管长度约6000m，基本覆盖全村用水家庭。村内设有5个供水点，分别位于肩丰、长塘、营仔、田坑、黄竹，总用地面积约300㎡，其中4个为饮水工程。",
      "[infrastructure] 模型观察: [排水系统]：金田村各家屋前自设排水设施，主要为污水管和雨水排水沟，由每户自行设置，覆盖全村，但缺乏集中统一的污水处理设施。",
      "[infrastructure] 模型观察: [供电系统]：金田村现有变压器9个，主要分布在营仔、社前、田坑、塘笃、黄竹等自然村。村内现有3个水电站，主要沿石窟河布置。全村大部分道路设有路灯照明设施。"
    ]
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
    "items": 1,
    "sample": [
      "[natural_environment] 模型观察: 地质灾害隐患点情况如下："
    ]
  },
  "public_services": {
    "items": 0,
    "sample": []
  },
  "socio_economic": {
    "items": 0,
    "sample": []
  },
  "superior_planning": {
    "items": 0,
    "sample": []
  },
  "traffic": {
    "items": 0,
    "sample": []
  },
  "villager_wishes": {
    "items": 1,
    "sample": [
      "[villager_wishes] 模型观察: 诉求迫切性排序：生活保障→环境改善→增收致富→公共服务。村民首先关注基本生活条件的保障与改善，其次期望提升人居环境，进而追求产业增收，最后完善公共服务体系。"
    ]
  }
}
- **facts_produced**: {
  "items": 9,
  "sample": [
    "[infrastructure] 模型观察: [供水系统]：金田村现有供水设施干管长度约6000m，基本覆盖全村用水家庭。村内设有5个供水点，分别位于肩丰、长塘、营仔、田坑、黄竹，总用地面积约300㎡，其中4个为饮水工程。",
    "[infrastructure] 模型观察: [排水系统]：金田村各家屋前自设排水设施，主要为污水管和雨水排水沟，由每户自行设置，覆盖全村，但缺乏集中统一的污水处理设施。",
    "[infrastructure] 模型观察: [供电系统]：金田村现有变压器9个，主要分布在营仔、社前、田坑、塘笃、黄竹等自然村。村内现有3个水电站，主要沿石窟河布置。全村大部分道路设有路灯照明设施。"
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
  "items": 46,
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
      "mention": "园寨",
      "normalized_name": "金田村中部",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 园寨 | 金田村中部 | 建筑集中分布区，新旧建筑穿插建造",
      "spatial_hint": "金田村中部"
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
      "mention": "马头段",
      "normalized_name": "金田村东南部",
      "related_mentions": {
        "items": 0
      },
      "role": "area",
      "source_report_ref": "rpt-architecture-v1",
      "source_span": "现状分区 | 马头段 | 金田村东南部 | 建筑集中分布区，新建筑大多位于此",
      "spatial_hint": "金田村东南部"
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
      "source_span": "现状项目 | 祠堂 | 社前村、黄竹村、田坑村 | 具浓厚客家文化元素的传统风貌建筑",
      "spatial_hint": "社前村、黄竹村、田坑村"
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
  "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
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
  "created_at": "2026-08-08T07:21:30.540120Z",
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
    "items": 9,
    "sample": [
      "[infrastructure] 模型观察: [供水系统]：金田村现有供水设施干管长度约6000m，基本覆盖全村用水家庭。村内设有5个供水点，分别位于肩丰、长塘、营仔、田坑、黄竹，总用地面积约300㎡，其中4个为饮水工程。",
      "[infrastructure] 模型观察: [排水系统]：金田村各家屋前自设排水设施，主要为污水管和雨水排水沟，由每户自行设置，覆盖全村，但缺乏集中统一的污水处理设施。",
      "[infrastructure] 模型观察: [供电系统]：金田村现有变压器9个，主要分布在营仔、社前、田坑、塘笃、黄竹等自然村。村内现有3个水电站，主要沿石窟河布置。全村大部分道路设有路灯照明设施。"
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
      "items": 5
    },
    "land_use": {
      "items": 0
    },
    "location": {
      "items": 0
    },
    "natural_environment": {
      "items": 1
    },
    "public_services": {
      "items": 0
    },
    "socio_economic": {
      "items": 0
    },
    "superior_planning": {
      "items": 0
    },
    "traffic": {
      "items": 0
    },
    "villager_wishes": {
      "items": 1
    }
  },
  "issues": {
    "items": 0,
    "sample": []
  },
  "location_facts": {
    "items": 46,
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
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "l1_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:21:30.703454Z",
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
- **l1_snapshot**: `l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1` (type=L1Snapshot, revision=v1, checksum=b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858)

## L2 / l2_aggregate
- timestamp: 2026-08-08T15:24:23.530618
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: 7f8aa4db1c6c87141fcc952b7817c0cb036949fea2ab17c9ee54c84cb000e410
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
    "[总体目标：梅州市特色生态农林与客家驿道文旅综合发展示范村]",
    "耕地保有量：85.20公顷（约束性）",
    "永久基本农田保护面积：80.00公顷（约束性）"
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
    "生态优先——生态保护网格化（针对地质灾害中易发及生态林保护问题，实施35处滑坡和5处崩塌隐患点工程治理与监测，划定362.02公顷生态用地网格化管护，覆盖全村90%林地范围）",
    "产业振兴——主导产业特色化（针对产业规模小及三产缺乏问题，扩大灵芝与烤烟种植规模并升级杉木家具制造业，引入林下经济与农林文旅融合项目，预期带动150人就业与村民年均收入增长15%）",
    "设施完善——基础设施标准化（针对污水直排及垃圾收集不规范问题，新建集中式污水处理设施及管网并增设标准化垃圾收集点，覆盖12个自然村）"
  ]
}
### 产物摘要（ArtifactStore）
#### l2_strategy
```json
{
  "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T07:24:23.517770Z",
  "development_goals": {
    "items": 15,
    "sample": [
      "[总体目标：梅州市特色生态农林与客家驿道文旅综合发展示范村]",
      "耕地保有量：85.20公顷（约束性）",
      "永久基本农田保护面积：80.00公顷（约束性）"
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
      "生态优先——生态保护网格化（针对地质灾害中易发及生态林保护问题，实施35处滑坡和5处崩塌隐患点工程治理与监测，划定362.02公顷生态用地网格化管护，覆盖全村90%林地范围）",
      "产业振兴——主导产业特色化（针对产业规模小及三产缺乏问题，扩大灵芝与烤烟种植规模并升级杉木家具制造业，引入林下经济与农林文旅融合项目，预期带动150人就业与村民年均收入增长15%）",
      "设施完善——基础设施标准化（针对污水直排及垃圾收集不规范问题，新建集中式污水处理设施及管网并增设标准化垃圾收集点，覆盖12个自然村）"
    ]
  },
  "provenance": {
    "module": "l2_observe",
    "natural_language_description": "L2 STRATEGIZE aggregated strategy from compiled dimension fragments.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "l2_observe",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:24:23.517813Z",
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
- **l2_strategy**: `l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1` (type=L2Strategy, revision=v1, checksum=b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1)

## L3 / l3_aggregate
- timestamp: 2026-08-08T15:29:45.573657
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: feaa11b53aeaab896816bdb7a3337a7e257cc43a58f2873d4f67ac6aef0bbf8a
- **source_refs**: {
  "items": 14,
  "sample": [
    "artifact:l1_snapshot",
    "artifact:l2_strategy",
    "L3:disaster_prevention"
  ]
}
### 产出
- **gate_route**: EXPLORE
- **intervention_count**: 27
- **program_issue_count**: 0
- **spatial_instruction_count**: 0
### 产物摘要（ArtifactStore）
#### planning_program
```json
{
  "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T07:32:55.406945Z",
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
    "items": 32,
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
  "l1_snapshot_ref": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "l2_strategy_ref": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
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
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "l3_plan",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:32:55.406966Z",
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
- **planning_program**: `l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1` (type=PlanningProgram, revision=v1, checksum=636d93be7d4df9263bceeb578de876e01f029b4075f552df5302086dfd55ba51)

## L3 / l3_aggregate
- timestamp: 2026-08-08T15:32:55.424927
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: feaa11b53aeaab896816bdb7a3337a7e257cc43a58f2873d4f67ac6aef0bbf8a
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
- **intervention_count**: 32
- **program_issue_count**: 1
- **spatial_instruction_count**: 0
### 产物摘要（ArtifactStore）
#### planning_program
```json
{
  "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "context_fingerprint": "",
  "context_version": "1",
  "created_at": "2026-08-08T07:32:55.406945Z",
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
    "items": 32,
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
  "l1_snapshot_ref": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "l2_strategy_ref": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
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
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "l3_plan",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:32:55.406966Z",
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
- **planning_program**: `l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1` (type=PlanningProgram, revision=v1, checksum=3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7)

## PARSE / parse_node
- timestamp: 2026-08-08T15:32:55.448169
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: e410f6517f2554a0457cec3d5f25c83c319b8819c5e30d62e09b3a5e03115bd1
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## PARSE / parse_node
- timestamp: 2026-08-08T15:32:55.502152
### 输入
- **artifact_refs**: {
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: e410f6517f2554a0457cec3d5f25c83c319b8819c5e30d62e09b3a5e03115bd1
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  }
}
- **output_checksum**: fc3510d56405fd1b74066cbc11ad946c616810104474bf57b0d8a220bcd69da5
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
  "context_fingerprint": "sha256:9e31fd220384084f",
  "context_ref": {
    "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "version": "1"
  },
  "context_version": "1",
  "parse_gate": {
    "artifact_id": "gate-parse-0",
    "context_fingerprint": "",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.493527Z",
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
    "items": 5,
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
  "created_at": "2026-08-08T07:32:55.493486Z",
  "diagnostics": {
    "items": 32,
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
      "items": 32
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
  "program_ref": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
  "project_requirements": {
    "items": 32,
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
    "natural_language_description": "Deterministic compile of PlanningProgram l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1 into SpatialPlanningIntent",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "parse",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:32:55.493471Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_reference_specs": {
    "items": 5,
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
    "finished_at": "2026-08-08T07:32:55.493441+00:00",
    "mode": "compile",
    "started_at": "2026-08-08T07:32:55.493441+00:00",
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
      "items": 32
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
- duration_ms: 54.18
- gate_route: PASS
- status: stage_completed
### 产物
- **intent_compilation**: `intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467` (type=IntentCompilationResult, revision=v1, checksum=c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f)

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:55.516082
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: fabd6199db70cbcc921356ee41e224512b589c9afab53f82f78f4ee5077ec407
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:56.699180
### 输入
- **artifact_refs**: {
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: fabd6199db70cbcc921356ee41e224512b589c9afab53f82f78f4ee5077ec407
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-644e55ea6c4370b7",
    "artifact_type": "GroundingResult",
    "checksum": "e700512682a1ad6320cc9ad167b4c2ea94134ea8c5b86931ac54b5cc7a138a1e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:56.692701Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:56.692703Z"
  }
}
- **output_checksum**: f62df16d1364af488b01b22b4386968b95d19d23f3af9add9d911be656b7db9e
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
  "context_fingerprint": "sha256:9e31fd220384084f",
  "context_ref": {
    "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "version": "1"
  },
  "context_version": "1",
  "ground_gate": {
    "artifact_id": "gate-ground-0",
    "context_fingerprint": "",
    "context_version": "",
    "created_at": "2026-08-08T07:32:56.692557Z",
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
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-08T07:33:00.820418Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:33:00.820398Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 8,
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
    "items": 5,
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
- duration_ms: 1183.36
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-644e55ea6c4370b7` (type=GroundingResult, revision=v1, checksum=e700512682a1ad6320cc9ad167b4c2ea94134ea8c5b86931ac54b5cc7a138a1e)

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:56.712144
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-644e55ea6c4370b7",
    "artifact_type": "GroundingResult",
    "checksum": "e700512682a1ad6320cc9ad167b4c2ea94134ea8c5b86931ac54b5cc7a138a1e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:56.692701Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:56.692703Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: b4485c02b2c442d39a532d630b34ef42510247cfbc488620ef6e68583cd9a09d
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 1
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:58.045782
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-644e55ea6c4370b7",
    "artifact_type": "GroundingResult",
    "checksum": "e700512682a1ad6320cc9ad167b4c2ea94134ea8c5b86931ac54b5cc7a138a1e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:56.692701Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:56.692703Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: b4485c02b2c442d39a532d630b34ef42510247cfbc488620ef6e68583cd9a09d
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-838e8a61d8f69bcb",
    "artifact_type": "GroundingResult",
    "checksum": "6976bcb86c228a16250c702182c034fa2290cc9db383ca5ef13bb27ef46d128e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:58.039563Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:58.039568Z"
  }
}
- **output_checksum**: ab15a772a1a521635868748d8b3036ad066504b439251efb44aead36bbd4d9cd
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
  "context_fingerprint": "sha256:9e31fd220384084f",
  "context_ref": {
    "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
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
    "created_at": "2026-08-08T07:32:58.039320Z",
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
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-08T07:33:00.820418Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:33:00.820398Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 8,
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
    "items": 5,
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
- duration_ms: 1333.98
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-838e8a61d8f69bcb` (type=GroundingResult, revision=v1, checksum=6976bcb86c228a16250c702182c034fa2290cc9db383ca5ef13bb27ef46d128e)

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:58.079807
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-838e8a61d8f69bcb",
    "artifact_type": "GroundingResult",
    "checksum": "6976bcb86c228a16250c702182c034fa2290cc9db383ca5ef13bb27ef46d128e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:58.039563Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:58.039568Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: c5dbbeb3f48a8e2fe53d80e17fc5859420a076753e975c3e461a7695d57a2a50
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 2
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:59.482544
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-838e8a61d8f69bcb",
    "artifact_type": "GroundingResult",
    "checksum": "6976bcb86c228a16250c702182c034fa2290cc9db383ca5ef13bb27ef46d128e",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:58.039563Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:58.039568Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: c5dbbeb3f48a8e2fe53d80e17fc5859420a076753e975c3e461a7695d57a2a50
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-7adee92e734d67ea",
    "artifact_type": "GroundingResult",
    "checksum": "019a1c7bdc42af25359c45c7635d2f515303f1015cbb09f4ed4e897e5ab3de43",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:59.474132Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:59.474137Z"
  }
}
- **output_checksum**: c7bef4b52440362502032d772b87a76544a63c61274703008ccc5575d6a9c120
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
  "context_fingerprint": "sha256:9e31fd220384084f",
  "context_ref": {
    "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
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
    "created_at": "2026-08-08T07:32:59.473781Z",
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
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-08T07:33:00.820418Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:33:00.820398Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 8,
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
    "items": 5,
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
- duration_ms: 1403.1
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-7adee92e734d67ea` (type=GroundingResult, revision=v1, checksum=019a1c7bdc42af25359c45c7635d2f515303f1015cbb09f4ed4e897e5ab3de43)

## GROUND / ground_node
- timestamp: 2026-08-08T15:32:59.527054
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-7adee92e734d67ea",
    "artifact_type": "GroundingResult",
    "checksum": "019a1c7bdc42af25359c45c7635d2f515303f1015cbb09f4ed4e897e5ab3de43",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:59.474132Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:59.474137Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: b004865116694906671e7d93bee7a9d85a830dd36981503555a19235b86cbed1
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 诊断
- attempt: 3
- status: stage_started

## GROUND / ground_node
- timestamp: 2026-08-08T15:33:00.827304
### 输入
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-7adee92e734d67ea",
    "artifact_type": "GroundingResult",
    "checksum": "019a1c7bdc42af25359c45c7635d2f515303f1015cbb09f4ed4e897e5ab3de43",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:59.474132Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:59.474137Z"
  },
  "intent_compilation": {
    "artifact_id": "intent_compilation-129075a7-c3ea-4252-a611-bdc54c069aa4-692b64c6ef65b467",
    "artifact_type": "IntentCompilationResult",
    "checksum": "c117f201c06d55152ed3604b41419581e13e64e081e07a1b97901840e0aa6d1f",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.494003Z",
    "module": "parse",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.494006Z"
  },
  "l1_snapshot": {
    "artifact_id": "l1-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L1Snapshot",
    "checksum": "b24fcb61d8fcdd23928786a49e45e62f7b055c85158c38fdf56fbf6efd6c6858",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l1_observe",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "l2_strategy": {
    "artifact_id": "l2-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "L2Strategy",
    "checksum": "b7dca6cf8d7efe1916c66b26a462a9844ecc4f3dd262292a9ac61a2f5b6d60c1",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "module": "l2_strategize",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4"
  },
  "planning_program": {
    "artifact_id": "l3-129075a7-c3ea-4252-a611-bdc54c069aa4-v1",
    "artifact_type": "PlanningProgram",
    "checksum": "3571d64860b4f8717a87f164a0be627e2034ccb67474d91921b0573ea68524a7",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:32:55.411353Z",
    "module": "l3_plan",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:32:55.411357Z"
  }
}
- **context_ref**: {
  "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
  "version": "1"
}
- **input_checksum**: b004865116694906671e7d93bee7a9d85a830dd36981503555a19235b86cbed1
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
      "id": 5,
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
      "id": 7,
      "parse_status": "success",
      "size_bytes": 58455
    }
  ]
}
### 产出
- **artifact_refs**: {
  "grounding_result": {
    "artifact_id": "grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-155cfdf67846dbd4",
    "artifact_type": "GroundingResult",
    "checksum": "21465cfdf8a16919c72c21a010ac446faec8287992a03896d9f3b871496102fc",
    "context_fingerprint": "sha256:9e31fd220384084f",
    "context_version": "1",
    "created_at": "2026-08-08T07:33:00.820669Z",
    "module": "ground",
    "revision": "v1",
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "schema_version": "1.0",
    "stored_at": "2026-08-08T07:33:00.820673Z"
  }
}
- **output_checksum**: 7cbda683d3c1b7198866f29b99c83187f4a029cce201be91c8424178e4612f88
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
  "context_fingerprint": "sha256:9e31fd220384084f",
  "context_ref": {
    "session_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
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
    "created_at": "2026-08-08T07:33:00.820475Z",
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
    "items": 0,
    "sample": []
  },
  "context_fingerprint": "",
  "context_version": "",
  "created_at": "2026-08-08T07:33:00.820418Z",
  "provenance": {
    "module": "ground",
    "natural_language_description": "GROUND grounding result produced by ground_aggregate via SpatialResolver.",
    "raw_text": null,
    "reasoning_trace": null,
    "run_id": "129075a7-c3ea-4252-a611-bdc54c069aa4",
    "source": "ground_aggregate",
    "spatial_hint": null,
    "timestamp": "2026-08-08T07:33:00.820398Z",
    "trace": {
      "items": 1
    }
  },
  "schema_version": "1.0",
  "spatial_query_evidence": {
    "items": 8,
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
    "items": 5,
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
- duration_ms: 1300.57
- gate_route: EXPLORE
- status: stage_completed
### 产物
- **grounding_result**: `grounding_result-129075a7-c3ea-4252-a611-bdc54c069aa4-155cfdf67846dbd4` (type=GroundingResult, revision=v1, checksum=21465cfdf8a16919c72c21a010ac446faec8287992a03896d9f3b871496102fc)
