# Planning Knowledge Graph (KG) 模块

> **定位**: 村庄规划系统的**语义与空间桥接层** -- PARSE 与 EXECUTE 之间的唯一语义中间态
> **层级**: 四层架构 `Schema ← Data ← KG ← Agent` 中的 KG 层
> **依赖**: 仅依赖 `app.modules.schema`；不依赖 Data/Agent/Tools
> **Updated: 2026-07-25 (v4.3)** -- 项目级 `ProjectKG` + ConstraintCompiler + 对接 `ProjectDataView`

---

## 一、模块定位

KG 是独立于 GIS 子包的桥接模块（`app/modules/kg/`）。其职责是**将空间数据与规划语义统一编码为 RDF 三元组**，使下游 Agent 能通过 SPARQL 查询获取语义理解结果，而非直接处理原始 GeoJSON 或自然语言。

**核心定位**（对接 `00_SYSTEM_DESIGN.md` §三）：
- KG 是 PARSE 与 EXECUTE 之间的**唯一语义中间态**：PARSE 写入（Layer 3），EXECUTE 读取
- KG 不存储原始几何坐标（Data 层职责），只存储实体 URI + 属性 + 关系 + 约束 + 意图
- KG 通过 `ConstraintCompiler` 将语义约束编译为 MIP 数值矩阵，供 EXECUTE 的 MIP 求解器消费

### 系统位置（PARSE ↔ KG ↔ EXECUTE）

```
┌──────────────────────────────────────────────────────────────┐
│  Agent Layer                                                  │
│  ┌────────────────┐              ┌────────────────┐          │
│  │  PARSE Agent   │  writes      │  EXECUTE Agent │          │
│  │  (PLAN)        │ ───────────► │  (DELIVER)     │          │
│  │  intent/ops/   │              │  MIP+facility+ │          │
│  │  constraints   │              │  axis+road     │          │
│  └────────┬───────┘              └───────▲────────┘          │
│           │ writes Layer 3              │ reads              │
├───────────┼─────────────────────────────┼────────────────────┤
│           ▼                             │                    │
│  ┌──────────────────────────────────────┴────────────────┐   │
│  │  KG Layer (本模块) -- ProjectKG (项目级)               │   │
│  │  Layer1 静态(本体+编码) | Layer2 语义(关系+约束)       │   │
│  │  Layer3 易失(意图+操作)                                │   │
│  │  ConstraintCompiler: KG -> MIPModel                    │   │
│  └────────────────────────▲────────────────────────────────┘  │
│                           │ typed models                       │
│  ┌────────────────────────┴────────────────────────────────┐  │
│  │  Schema Layer (app.modules.schema)                       │  │
│  │  ProjectDataView -> VillageBundle (四形态类型化要素)      │  │
│  │  parse_contracts: SpatialPlanningIntent/Operation/...    │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、设计原则

| 原则 | 含义 | 当前符合度 |
|---|---|---|
| **Schema-First** | KG 只通过 `app.modules.schema` 的类型化模型读取空间要素，不直接解析 GeoJSON dict | ⚠️ 部分（K2 待改，见 §九） |
| **项目级** | KG 为 `ProjectKG`，含多村实体 + 跨村关系（村间邻接/共享水系/道路连通），与 `ProjectDataView` 对齐 | ❌ 待 K2 实现 |
| **单向依赖** | KG 仅依赖 schema 层，不依赖 Agent/Tools | ⚠️ 部分（K5 待清理反向依赖） |
| **三层分离** | Layer1 静态缓存复用 / Layer2 语义按意图重建 / Layer3 易失闭环迭代 | ✅ 已实现 |
| **PARSE 结果落库** | PARSE 产出的意图/操作/约束/空间关系写入 KG Layer 3 | ❌ 待 K3（add_intent/add_operations/add_constraints） |
| **ConstraintCompiler** | KG 语义约束 -> MIP 数值矩阵，EXECUTE 不直接查 KG 优化 | ❌ 待 K3 |
| **LAYOUT 查询驱动** | EXECUTE 通过 SPARQL 模板 + ConstraintCompiler 获取约束，非直接读 GeoJSON | ⚠️ 部分 |

---

## 三、模块结构

```
backend/app/modules/kg/
├── __init__.py               # 公开 API 导出
├── ontology.py               # 本体定义: 23 实体类型 + 14 关系类型 + 规则常量
├── builder/                  # [K1 待拆] PlanningKG 构建器子包 (按实体组分文件)
│   ├── base.py               # PlanningKG 骨架 + 三层 build
│   ├── parcels.py            # 地块实体 (收 List[CurrentLandUseParcel/PlannedLandUseParcel])
│   ├── protection.py         # 保护边界 + 控制线
│   ├── infrastructure.py     # 道路 + 注记 + 设施
│   ├── planning.py           # 规划要素 (LandUseZone/ConstructionCtrlZone)
│   ├── natural.py            # 自然要素 + 地形
│   └── intent.py             # [K3] PARSE 意图/操作/约束写入
├── constraint_compiler.py    # [K3 待建] KG -> MIPModel 编译器
├── query.py                  # 28 SPARQL 查询模板 + query_kg()
└── manager.py                # KGManager: 项目级缓存 + 会话管理
```

> 当前 `builder.py` 为 2124 行单文件巨石，K1 任务将其拆为 `builder/` 子包。

| 文件 | 核心导出 | 职责 |
|---|---|---|
| `ontology.py` | `PLN`, `GEO`, `EntityTypes`, `Relations`, `FACILITY_TYPES` | 命名空间 + 实体/关系 URI + 规则映射 |
| `builder.py` (待拆) | `PlanningKG`, `KGInputParcels` | RDF 图构建（三层 build + Phase 1~4 入库） |
| `constraint_compiler.py` (待建) | `ConstraintCompiler`, `MIPModel` | KG 语义约束 -> MIP 数值矩阵 |
| `query.py` | `QUERY_TEMPLATES`, `query_kg()`, `TOOL_META` | SPARQL 模板字典 + 参数化查询 |
| `manager.py` | `KGManager`, `get_kg_manager` | 项目级缓存 + LRU + 版本失效 |

---

## 四、本体设计（ontology.py）

### 实体类型（23 类，对接 schema Group A-F）

| 阶段 | 实体 | 对应 schema 类型 |
|---|---|---|
| Phase 0 | `Parcel`, `Zone`, `Constraint`, `Indicator` | `BaseLandUseParcel`, `BaseControlZone`, `SpatialConstraint`, `PlanningIndicatorTable` |
| Phase 1 | `Project`, `Village`, `Regulation`, `LandUsePlan`, `Facility`, `Axis`, `Road`, `WaterBody`, `BuildingGroup` | `ConstructionProjectTable`, `AdminArea`, `ControlRuleTable`, `BaseFacility`/设施子类型(v4.3), `AxisTarget`, `BaseRoad`, `WaterLine`/`WaterArea`, `CurrentBuilding` |
| Phase 2 | `LandConservationPlan`, `ReforestationPlan`, `GridRegulation` | 整治规划 |
| Phase 3 | `ControlRule`, `LandUseCategory`, `PlanningIndicator`, `ThreeZone`, `ThreeLine` | `ControlRuleTable`, `ThreeZoneItem`(v4.2), `ControlLine` 子类 |
| Phase 6 | `AdministrativeVillage`, `NaturalSettlement` | `AdminArea`(admin_level) |

> **v4.3 对接**：设施实体扩展为 `BaseFacility` 的 8 子类型（WaterSupply/Drainage/Waste/Sanitary/Fire/EvacuationShelter/Energy/Lighting Facility）；`ThreeZone`/`ThreeLine` 对接 schema 的 `ThreeZoneItem` + `ControlLine` 子类（矢量引用层，非 KG 独有）。

### 关系类型（14 类）

- **空间**：`adjacent_to`（邻接，MIP 邻接规则）、`within_zone`（包含于分区）、`located_in`（位于）、`designated_as`（被指定为）、`connects`（连接）
- **管制**：`constrained_by`（受约束）、`protects`（保护）、`delineates`（划定）、`controls_use`（管制用途）
- **语义**：`achieves`（达成）、`conflicts_with`（冲突）、`derived_from`（源于，溯源）、`serves`（服务，设施覆盖）、`conducted_from`（上位传导）

---

## 五、三层模型

```
┌──────────────────────────────────────────────────┐
│  Layer 3: 易失层 (Volatile) -- PARSE 写入, EXECUTE 读 │
│  - SpatialPlanningIntent (zone_targets/facilities/axes) │
│  - SpatialOperation (create/split/merge/modify/reclassify) │
│  - SpatialConstraint (area/spatial/building/...) │
│  - 校验反馈 (adjustments)                        │
│  生命周期: 单次 pipeline 运行                      │
├──────────────────────────────────────────────────┤
│  Layer 2: 语义层 (Semantic) -- 空间关系+约束       │
│  - adjacent_to (地块邻接, 几何 sjoin 计算)        │
│  - within_zone / located_in (包含/定位)          │
│  - protects / constrained_by (保护/约束)         │
│  - construction_cap / farmland_min (规划约束)    │
│  - 村组间语义关系 (east_of/contains, PARSE 计算)  │
│  生命周期: 村级 (不变更, 除非数据更新)             │
├──────────────────────────────────────────────────┤
│  Layer 1: 静态层 (Static) -- 本体+编码 (不可变)    │
│  - EntityTypes (23) + Relations (14)             │
│  - 编码体系 (6 套: gbt21010/tugui/appendix5/...) │
│  - 规则模板 (规划目标/空间管制规则)               │
│  生命周期: 应用级 (启动时加载)                    │
└──────────────────────────────────────────────────┘
```

---

## 六、与 schema 对接（ProjectDataView 类型化摄入）

### 6.1 KG 只消费类型化模型，禁止 raw dict

```python
# ✅ 正确 (K2 目标): 从 ProjectDataView 类型化摄入
class ProjectKG:
    def build_from_project(self, project: ProjectDataView) -> "ProjectKG":
        """从项目级数据视图构建 KG (多村 + 跨村关系)."""
        for village_name, village in project.villages.items():
            self.add_parcels(village.current_landuse)      # List[CurrentLandUseParcel]
            self.add_parcels(village.planned_landuse)      # List[PlannedLandUseParcel]
            self.add_roads(village.roads)                  # List[LineFeature]
            self.add_facilities(village.annotations)       # 设施子类型
            self.add_protection_zones(village.protection_zones)  # List[ControlLine]
        self.add_cross_village_relations(project.cross_village_layers)
        self.add_raster_context(project.rasters)           # DEM/DOM 元数据

# ❌ 禁止: KG 直接读 GeoJSON dict
class ProjectKG:
    def build_from_geojson(self, landuse: dict, gis_data: dict): ...  # K2 删除
```

### 6.2 PARSE 写入（Layer 3）

```python
class ProjectKG:
    def add_intent(self, intent: SpatialPlanningIntent) -> None:
        """PARSE 产出的分区目标/设施/轴线写入 Layer 3."""
    def add_operations(self, ops: List[SpatialOperation]) -> None:
        """原子操作序列写入, 支持 derived_from 溯源."""
    def add_constraints(self, cons: List[SpatialConstraint]) -> None:
        """空间约束写入 (source='parse')."""
    def add_spatial_relations(self, relations: List[SpatialRelation]) -> None:
        """PARSE 计算的村组间语义关系 (east_of/adjacent_to/contains)."""
```

### 6.3 EXECUTE 读取（经 ConstraintCompiler）

```python
class ProjectKG:
    # Layer 2+3 读 API (K3 补齐)
    def get_protected_parcels(self) -> List[str]: ...      # 保护地块 BSM
    def get_zone_restrictions(self) -> Dict: ...           # 分区容量
    def get_adjacency_map(self) -> Dict[str, List[str]]: ...  # 邻接关系
    def get_three_lines(self) -> List[Dict]: ...           # 三线边界
    def get_intent(self) -> SpatialPlanningIntent: ...     # PARSE 意图
    def get_facility_locations(self) -> List[Dict]: ...    # 设施位置
    def get_vne_summary(self) -> Dict: ...                 # VNE 汇总
```

---

## 七、ConstraintCompiler（KG -> MIP，K3 待建）

KG 不能直接被 MIP 求解器查询（抽象层次错误，太慢）。`ConstraintCompiler` 在优化前一次性从 KG 提取所有约束，编译为数值矩阵：

```
KG (语义层)            ConstraintCompiler            MIP (数学优化层)
─────────────         ──────────────────           ─────────────────
protected_parcels ──-> 变量锁定            ──->   x[i][construction] = 0
zone_restrictions ──-> 容量约束            ──->   Σ x[i][zone]*a[i] ≤ max
adjacency_map    ──-> 邻接偏好            ──->   cost_matrix[i][j]
area_targets     ──-> 目标约束            ──->   Σ x[i][zone]*a[i] ≈ target
three_lines      ──-> 空间边界约束        ──->   x[i][zone] = 0 for i outside
```

```python
class ConstraintCompiler:
    def compile(self, intent: SpatialPlanningIntent,
                project: ProjectDataView, kg: ProjectKG) -> MIPModel:
        """一次性编译所有约束为 MIPModel."""
        # Step1 硬约束: kg.get_protected_parcels() -> 变量锁定; kg.get_three_lines() -> 边界
        # Step2 软约束: intent.zone_targets -> 目标; intent.adjacency_rules -> 邻接偏好
        # Step3 ground 成 MIPModel(variables, hard_constraints, soft_goals, cost_matrix)
```

对标：RLP / Graph-Grounded / Scimitar / Ontology-to-tools T-Box hard locks（见 `EXA_FINDINGS.md`）。

---

## 八、三层缓存架构（manager.py）

| 层 | 内容 | 缓存键 | 生命周期 |
|---|---|---|---|
| **Layer 1 静态** | 地块/邻接/VNE/基础设施/GIS 约束 | `project_id + villages_hash(SHA256)` | 进程级 LRU(50)，同项目同数据命中 |
| **Layer 2 语义** | 约束/指标/分区/规制（来自 intent/reports） | 无（按意图重建） | 每次 PARSE 输出重建 |
| **Layer 3 易失** | `designated_as`/分区指派/操作结果 | 无 | 闭环迭代变更，`bump_version` 失效查询缓存 |

- `get_or_build_layer1()`：命中时 `clone_static_layer()` 复制三元组，避免 O(n²) 邻接重算
- `query_with_cache()`：SPARQL 结果按 `session_id + template + params` 缓存
- **v4.3 改动**：缓存键从 `village_name + landuse_hash` 升级为 `project_id + villages_hash`（项目级）

---

## 九、当前差距与改进路线（对接 OPTIMIZATION_TASKS）

| 差距 | 现状 | 任务 | 优先级 |
|---|---|---|---|
| KG 仍读 raw dict | `builder.py` 两套入口，生产走 dict 路径 | K2: `build_from_project(ProjectDataView)` | P0 |
| KG 村庄级，非项目级 | 无多村/跨村关系 | K2: `ProjectKG` + 项目级缓存 | P0 |
| KG 反向依赖 Tools | `builder.py` import `_analytics`/`_generation` | K5: 改用 schema 层函数 | P0 |
| PARSE 结果未落库 | intent/operations/constraints/relations 不入 KG | K3: `add_intent`/`add_operations`/`add_constraints`/`add_spatial_relations` | P1 |
| 无 ConstraintCompiler | EXECUTE 直接从 state 读 flat dict | K3: `ConstraintCompiler.compile -> MIPModel` | P1 |
| builder 巨石 | 2124 行单文件 | K1: 拆 `builder/` 子包 | P1 |
| KG 入库率低 | 4/29 实体类型 | K4: 补保护/规划/自然要素入库（含 v4.3 设施子类型） | P1 |
| 查询模板未用 | 12/28 未被调用 | 治理：补消费者或废弃 | P2 |

---

## 十、对外 API

### 构建入口（K2 目标）

```python
from app.modules.kg import ProjectKG, get_kg_manager

manager = get_kg_manager()
kg = manager.build_from_project(project_data_view)  # 项目级构建
kg.add_intent(intent)                                # PARSE 写入 Layer 3
kg.add_operations(ops)
kg.add_constraints(cons)
```

### 编译入口（K3 目标）

```python
from app.modules.kg import ConstraintCompiler

mip_model = ConstraintCompiler(kg).compile(intent, project, kg)
# EXECUTE 的 MIP 求解器从 mip_model 取约束
```

### 查询入口

```python
from app.modules.kg import query_kg

results = query_kg(kg, "get_constraint_by_field", field_name="construction")
results = query_kg(kg, "get_parcel_neighbors", bsm="12345_0101_5600")
```

### 持久化

```python
kg.to_turtle()                  # 序列化为 Turtle (state 持久化)
ProjectKG.from_turtle(t, ...)   # 从 Turtle 重建
```

---

## 十一、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` §三 - KG 桥接层设计（本模块的设计依据）
- `docs/gis/reference/OPTIMIZATION_TASKS.md` - K1-K5 任务（KG 大修）
- `backend/app/modules/schema/README.md` - Schema v4.3 类型定义（KG 消费的类型化模型）
- `backend/app/modules/schema/contracts/parse_contracts.py` - PARSE 契约（KG Layer 3 写入类型）
- `backend/app/modules/schema/contracts/execution_contracts.py` - EXECUTE 契约（MIPModel 等）
- `backend/app/modules/spatial_ops/context.py` - SpatialContext 计算（KG 应接收的村组关系输入）
- `docs/gis/schema对接kg，parse.md` - Schema->KG 入库覆盖率审计
