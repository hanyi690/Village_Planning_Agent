# Schema Layer — 类型契约

> **定位**: 四层架构底层 (`Schema ← Data ← KG ← Agent`)，定义空间要素类型、编码体系、输出规范。
> **零依赖**: 不 import Data / KG / Agent / Tools 中的任何模块。

## 子包结构

```
schema/
├── types/                   # 空间要素类型 (Group A~E)
│   ├── spatial_types.py     # SpatialFeature, CurrentLandUseParcel, PlannedLandUseParcel, ...
│   ├── canonical.py         # BBox, CRS, GeoFeature, GISDataBundle, GISMetadata
│   └── raster_types.py      # DEMInput, DOMInput, TerrainAnalysisResult
│
├── encodings/               # 编码体系
│   ├── classification.py    # EncodingRegistry, LandUseClass, ClassificationSchema, SCHEMA
│   ├── code_sets.py         # DLBM_TO_PLANNING_ZONE, resolve_zone_type_for_dlbm, ...
│   └── dicts/               # YAML 字典数据 + 规则
│       ├── loader.py        # DictionaryCenter, get_center
│       ├── candidate_engine.py  # CandidateEngine (分类候选)
│       ├── rule_loader.py   # PlanningRuleLoader (规划规则)
│       ├── encodings/       # 6套编码 YAML (gbt21010, tugui, appendix5, ghflbm, ydyhfldm, vne)
│       ├── references/      # 参考映射 YAML (element_codes, sddlbm_to_ydyhfldm)
│       └── rules/           # 规划规则 YAML (planning_targets, land_use_structure, ...)
│
├── contracts/               # 跨层数据契约
│   ├── parse_contracts.py   # PARSE 输出: SpatialPlanningIntent, ZoneTarget, SpatialOperation, ...
│   ├── execution_contracts.py # EXECUTE 输入: MIPModel, ExecutionPlan, ChangelogEntry
│   ├── validation_contracts.py # 验证闭环: ValidationCheckItem, ClauseReference
│   └── layout_contracts.py  # LAYOUT 工具契约 (遗留, 逐步迁移)
│
├── output/                  # 输出规范
│   ├── gdb.py               # GDB_LAYER_REGISTRY (12层完整字段定义), enrich_gdb_fields
│   └── colors.py            # ZONE_TYPE_COLORS, PLANNING_ZONE_COLORS, get_zone_color
│
└── utils/                   # 纯计算 (零外部依赖)
    └── metrics.py           # compute_land_use_metrics (用地指标聚合)
```

## 契约文件职责

| 文件 | 角色 | 生产者 | 消费者 |
|------|------|--------|--------|
| `parse_contracts.py` | PARSE 输出契约 (文本→意图) | PARSE Agent | KG, EXECUTE |
| `execution_contracts.py` | EXECUTE 输入契约 (意图→空间) | ConstraintCompiler | MIP solver, EXECUTE |
| `validation_contracts.py` | 验证闭环契约 (结果→合规) | Evaluator | Worker-Evaluator loop |
| `layout_contracts.py` | LAYOUT 工具契约 (遗留) | LAYOUT tools | ZoneGenerator, etc. |

## 关键类型一览

### PARSE 输出 (`parse_contracts.py`)

- **`SpatialPlanningIntent`** — 规划意图 (分区目标 + 设施 + 轴线 + 面积约束 + 三区三线)
- **`ZoneTarget`** — 分区目标 (land_use + area_ratio + vne_code + spatial_preference + adjacency_rules)
- **`FacilityTarget`** — 设施需求 (type + status + location_hint + anchor_village)
- **`AxisTarget`** — 发展轴线 (direction + reference_feature + connects)
- **`SpatialOperation`** — 原子操作 (5 action variants: create/split/merge/modify/reclassify)
- **`SpatialConstraint`** — 空间约束 (6+# categories: area/spatial/building/use/boundary/protection)
- **`SpatialAnchor`** — 双阶段定位 (PARSE预解 + LAYOUT确认)

### EXECUTE 输入 (`execution_contracts.py`)

- **`MIPModel`** — MIP优化模型 (约束编译器输出, KG语义→数值矩阵)
- **`ExecutionPlan`** — 执行计划 (intent + mip_model + operations + constraints)
- **`ConstraintAdjustment`** — 约束调整 (验证失败→重新执行)
- **`ChangelogEntry`** — 变更记录 (操作→图斑变更→溯源)

### 验证闭环 (`validation_contracts.py`)

- **`ValidationCheckItem`** — 单项检查 (8项: 建设上限/耕地下限/农田保护/红线/边界/面积偏差/邻接/三线)
- **`ValidationCheckResult`** — 检查结果 (8项 + 整体pass/fail + 调整建议)
- **`ClauseReference`** — 条款引用 (文档+条款+原文, Phase 5 溯源)

## 依赖规则

| ✅ 允许 | ❌ 禁止 |
|---------|---------|
| 标准库 (typing, dataclasses, functools, ...) | `app.tools` |
| `pydantic` | `app.agent` |
| `yaml` | `app.modules.kg` |
| 内部跨子包引用 (utils→encodings) | `app.modules.data` |
| | `geopandas`, `shapely` |

## 向后兼容

旧路径 `app.modules.gis.schema` 仍可使用 (发出 DeprecationWarning)，通过 shim 文件重导出到新路径。新代码应使用 `app.modules.schema` 路径。

## 设计原则

1. **Schema-First**: 所有空间要素先定义类型再编码，下游只消费类型化模型，禁止 raw dict
2. **零依赖**: Schema 不依赖任何其他层
3. **契约分离**: PARSE/EXECUTE/Validation 契约分文件，职责单一
4. **向后兼容**: 新增字段不破坏旧数据 (所有字段有默认值)
