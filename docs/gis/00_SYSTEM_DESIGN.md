# 村庄规划智能系统 — 总体设计文档

> **Status: [CURRENT] | Type: North-Star Design | Version: 4.0 | Updated: 2026-07-25**
> **Scope**: 系统总体架构设计，覆盖 Schema / Data / KG / PARSE / EXECUTE 五层，回答 6 个核心设计问题
> **Audience**: 系统架构师、核心开发者
> **Replaces**: 00_PLANNING_SYSTEM_VISION.md + 01_DESIGN_GOALS.md + 02_OUTPUT_ARCHITECTURE.md (合并、精简、去矛盾)
> **Archived**: 旧文档已迁入 `archive/` 目录
>
> **v4.0 变更摘要（2026-07-25）**：
>
> - Schema 引入 Point/Line/Polygon 几何中间抽象 + RasterDataset 栅格分支（详见 `backend/app/modules/schema/README.md`）
> - `GISDataBundle` 现状/规划地块分离（`current_landuse`/`planned_landuse`），根治"双倍地块"，不保留兼容视图
> - Data 层双轨接入：显式注册 + 智能推断管道（矢量按几何分桶+字段语义匹配，栅格按波段+值域匹配），详见 `backend/app/modules/data/README.md`
> - `backend/app/modules/gis/` 整体删除，无 shim 无兼容层
> - `reference/OPTIMIZATION_TASKS.md` 重写为 parse/kg/layout 大修任务清单
>
> **v4.1 变更摘要（2026-07-25）**：
>
> - 数据视图上移为 `ProjectDataView -> VillageBundle` 两层，取代"一村一包"，支持多村/跨村/项目级组合
> - 新增 `TableDataset` 第四数据形态（矢量/栅格/表格/文档），汇交"一表一规则"有类型化落点
> - 项目配置与数据源配置分离（`projects.yaml` vs `sources.yaml`），智能推断加项目上下文校准
> - `SpatialFeature.layer_type` 嵌入图层身份；`layer_tree` 让图层可发现；三区三线标注引用层
> - KG 同步上移为项目级 `ProjectKG`（多村实体 + 跨村关系），避免数据项目级/KG 村庄级的断层

---

## 第零部分：设计总纲

### 0.1 系统定位

**一句话定义**：

> 给定村庄现状资料（三调数据、三区三线、DEM/DOM、上位规划、村民需求），系统产出
> **可解释、可汇交**的村庄规划成果包（一图一表一规则 + 数据库），过程中文本规划与
> 空间分析双向闭环。

**初期目标（Plan-then-Execute）**：输入村庄规划文本 + 现状 GIS 数据 → 产出整村规划图
（分区着色 + 设施点 + 轴线 + 图层）+ 可解释的 GDB 汇交成果。这是当前可推进的路径。

**终极目标（闭环 ANALYZE/PLAN/DELIVER）**：额外包含栅格分析（DEM/双评价）、文本↔空间闭环迭代、
原子操作落地、具体项目落地、管制规则生成、条款级溯源、5 目录汇交结构。

**核心约束**：系统是规划助手，不做规划决策。不确定性由人消除。

### 0.2 设计原则

| # | 原则                   | 含义                                                                        |
| - | ---------------------- | --------------------------------------------------------------------------- |
| 1 | **Schema-First** | 所有空间要素先定义类型再编码，下游只消费类型化模型，禁止 raw dict           |
| 2 | **单向依赖**     | 依赖方向：Schema ← Data ← KG ← Agent(PARSE/EXECUTE)，Schema 不依赖任何层 |
| 3 | **单一入口**     | 数据进入系统只有一个入口（Data 层），KG 不直接读 GeoJSON 文件               |
| 4 | **语义中间态**   | KG 是 PARSE 与 EXECUTE 之间的唯一语义桥接，PARSE 写入、EXECUTE 读取         |
| 5 | **多策略执行**   | MIP 批量分区 + 约束满足项目落地 + 程序化生成，不是单一策略                  |
| 6 | **闭环反馈**     | 校验失败 → 约束调整 → 重新执行，文本分析结果可回灌空间修订                |
| 7 | **可解释溯源**   | 每个图斑变更可追溯到来源文本，每条管制规则可追溯到上位依据                  |

### 0.3 官方标准对齐

系统设计对齐以下官方标准：

| 标准                  | 全称                                         | 系统对齐                                     |
| --------------------- | -------------------------------------------- | -------------------------------------------- |
| 自然资发〔2023〕234号 | 国土空间调查、规划、用途管制用地用海分类指南 | 用地分类编码体系（YDYHFL）                   |
| GB/T 21010-2017       | 土地利用现状分类                             | 三调国标编码体系（当前数据基准）             |
| GB/T 13923-2022       | 基础地理信息要素分类与代码                   | 10位数字层次码（大类+小类+一至四级类）       |
| DB14/T 2979-2024      | 村庄规划数据库规范                           | 数据库内容、要素分类代码、数学基础、数据分层 |
| 广东省住建厅 (2018)   | 广东省村庄规划编制指引（试行）               | 四阶段工作流、一图一表一规则成果             |
| DB4407/T 105-2023     | 村庄建设规划管制规则                         | 6大类管制规则模板                            |
| 住建部 (2014)         | 村庄规划用地分类指南                         | V/N/E 三分类                                 |
| 三区三线              | 全国国土空间规划                             | 生态/农业/建设空间 + 三线边界                |

### 0.4 文档说明

本文档是系统的**唯一权威设计文档**。旧文档（00_PLANNING_SYSTEM_VISION.md、01_DESIGN_GOALS.md 等）
已迁入 `archive/` 目录，仅作为历史参考。`reference/` 目录保留外部参考资料（人类工作流对标、Exa 发现）。

当本文档与旧文档冲突时，以本文档为准。

---

## 第一部分：分层架构（回答 Q1：data 和 schema 双层设计是否冗余）

### 1.1 四层架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent Layer (理解 + 执行)                                        │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐ │
│  │ PARSE Agent  │  │ EXECUTE Agent                            │ │
│  │ 文本→意图    │  │ 意图→空间 (layout/facility/axis/road/ops)│ │
│  │ Think-Format │  │ Worker-Evaluator retry loop              │ │
│  └──────┬───────┘  └───────────────┬──────────────────────────┘ │
│         │ writes/depends           │ reads/depends              │
├─────────┼──────────────────────────┼────────────────────────────┤
│         ▼                          ▼                            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ KG Layer (语义桥接)                                        │ │
│  │ Layer1 静态 (Ontology + 编码) | Layer2 语义 (关系+约束)     │ │
│  │ Layer3 易失 (Intent + Operations)                          │ │
│  │ RDFLib Graph + SPARQL 查询                                 │ │
│  └──────────────────────────────┬─────────────────────────────┘ │
│                                 │ depends                       │
│         ┌───────────────────────┼───────────────────────┐       │
│         ▼                       ▼                       ▼       │
│  ┌──────────────┐  ┌──────────────────────┐  ┌──────────────┐ │
│  │ Schema Layer │  │ Data Layer           │  │ Spatial Ops  │ │
│  │ 类型契约     │  │ 数据生命周期         │  │ 空间计算     │ │
│  │ 编码体系     │  │ 获取→校验→类型化     │  │ 几何运算     │ │
│  │ 输出规范     │  │  →缓存→持久化        │  │ 关系计算     │ │
│  │ 零依赖       │  │ depends: Schema      │  │ depends:     │ │
│  │              │  │                      │  │ Schema+Data  │ │
│  └──────────────┘  └──────────────────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Schema 层：类型契约

**位置**：`app/modules/schema/`（已从 `gis/schema/` 提升为顶层共享契约，5 子包结构）

**职责**：定义"空间要素是什么"、"编码体系有哪些"、"输出 GDB 长什么样"。
**不做**：数据的读取、校验、转换——那是 Data 层的职责。

**核心模块**：

| 子包           | 职责                                 | 关键内容                                                                                                                                                                                      |
| -------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types/`     | 空间要素类型 + 规范化容器 + 栅格类型 | `spatial_types.py`(SpatialFeature, CurrentLandUseParcel, PlannedLandUseParcel, ...), `canonical.py`(GeoFeature, GISDataBundle, BBox), `raster_types.py`(DEMInput, DOMInput)             |
| `encodings/` | 编码体系 + 值域 + 字典               | `classification.py`(6套: GB/T21010/TUGUI/APPENDIX5/GHFLBM/YDYHFL/VNE), `code_sets.py`, `dicts/`(6 YAML + references + rules)                                                            |
| `contracts/` | 跨层契约（分文件）                   | `parse_contracts.py`(SpatialPlanningIntent, SpatialOperation, SpatialConstraint), `execution_contracts.py`(MIPModel, ExecutionPlan), `validation_contracts.py`, `layout_contracts.py` |
| `output/`    | 输出规范                             | `gdb.py`(GDB_LAYER_REGISTRY 12层), `colors.py`(国标着色)                                                                                                                                  |
| `utils/`     | 纯计算（零外部依赖）                 | `metrics.py`(用地指标聚合)                                                                                                                                                                  |

**类型层级**（详见 `backend/app/modules/schema/README.md`）：

- 矢量三层层级：`SpatialFeature -> PointFeature/LineFeature/PolygonFeature -> 语义子类`，几何中间层在 `geometry` field 上加 validator，类型层面约束几何
- 栅格分支：`RasterDataset -> DEMInput/DOMInput/SlopeRaster/AspectRaster/SuitabilityRaster`
- `GISDataBundle` 现状/规划地块分离（`current_landuse`/`planned_landuse`），不混装，根治"双倍地块"，不保留兼容视图

**依赖规则**：Schema 层**不 import** Data / KG / Agent 中的任何模块。

### 1.3 Data 层：数据生命周期

**位置**：`app/modules/data/`

**职责**：数据的获取、校验、类型化、缓存、持久化。是 raw 数据进入类型化模型的**唯一端口**。

**核心概念**：

| 概念                      | 职责                                                                  | 类比               |
| ------------------------- | --------------------------------------------------------------------- | ------------------ |
| **Connection**      | API/DB 连接管理：端点、凭据、rate limit、重试、健康检查               | QGIS Data Source   |
| **Source (Driver)** | 知道"如何从某类源读取原始字节"：本地文件/WFS/MapServer REST/WMTS/栅格 | QGIS Data Provider |
| **Layer**           | 语义化图层：绑定 Source，声明 layer_type、CRS、字段映射               | QGIS Layer         |
| **Catalog**         | 声明式图层目录：YAML 配置注册所有 Layer，按名/按 layer_type 查询      | QGIS Browser       |
| **Ingest Port**     | raw 数据 → 类型化模型：编码校验 + 类型转换                           | ETL Gateway        |

**数据流**：

```
DataCatalog.fetch(layer_type)
  → Connection (获取凭据/端点)
  → Source/Driver (读取原始字节)
  → DataResult(raw geojson/tiles/raster)
  → Ingest Port (编码校验 + 类型转换)
  → Schema 模型 (SpatialFeature / BaseLandUseParcel / ...)
  → 下游消费 (KG / Agent)
```

**关键设计**：

- 统一 `DataResult` 封装：`success` 为假时携带 `error`，不抛异常
- CRS 统一：所有输出 WGS84 (EPSG:4326)，转换在 Source 层完成
- 编码校验前置：`ingest.py` 在端口校验所有编码，脏数据不进管道
- 双轨接入：已注册 layer_type 走严格 `ingest`，未注册走 `ingest_inference.py` 智能推断管道（矢量按几何分桶+字段语义匹配+动态模型生成，栅格按波段+值域匹配）
- 结构优先：先按数据形态（Point/Line/Polygon/Raster）分桶，再按语义分类
- 栅格/表格一等公民：DEM/DOM/坡度有 RasterDataset，人口/管制规则表有 TableDataset（第四形态），独立类型层级与数据视图字段
- 项目级数据视图：`ProjectDataView -> VillageBundle` 两层，取代"一村一包"，支持多村/跨村/共享栅格/表格/文档聚合（详见 `data/README.md`）
- 文档也是数据：规划文本、L3 报告纳入 `documents/` 子模块，走同样抽象

### 1.4 为什么不冗余

Schema 和 Data 的分离遵循 **"定义 vs. 操作"** 原则，类似于 Pydantic 模型（定义）与 Repository（操作）的关系：

| 维度               | Schema 层                    | Data 层                          |
| ------------------ | ---------------------------- | -------------------------------- |
| **关注点**   | 是什么（What）               | 怎么来（How）                    |
| **内容**     | 类型定义、编码体系、输出规范 | 获取、校验、类型化、缓存、持久化 |
| **变更频率** | 低（标准驱动）               | 中（数据源变更）                 |
| **依赖方向** | 零依赖                       | 依赖 Schema                      |
| **测试方式** | 类型正确性                   | 集成测试                         |

**如果合并**：每次新增数据源（如加一个 WFS 服务）会修改"类型定义"模块，导致下游所有消费者
重新评估兼容性。分离后，Schema 变更只发生在标准更新时，Data 变更不影响类型契约。

**已解决**：Schema 原位于 `gis/schema/`（暗示属于 GIS 子包），已提升为 `app/modules/schema/`
顶层共享契约（5 子包：types/encodings/contracts/output/utils），被 data/、kg/、agent/ 共同消费。
`gis/` 目录已整体删除，所有引用走 `app.modules.schema`，无 shim 无兼容层。

### 1.5 依赖规则

```
                    ┌─────────────┐
                    │   Schema    │  ← 零依赖，所有层的公共契约
                    └──────┬──────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   Data   │ │ Spatial  │ │   KG     │
        │          │ │   Ops    │ │          │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
             └────────────┼────────────┘
                          ▼
                   ┌──────────────┐
                   │    Agent     │
                   │ PARSE+EXECUTE│
                   └──────────────┘
```

**禁止的依赖**：

- Agent 不直接 import Data（通过 KG 间接访问数据）
- KG 不 import Agent（Agent 通过 KG 的公共 API 读写）
- Schema 不 import 任何其他层

---

## 第二部分：数据持久化（回答 Q2：怎么迁入数据库）

### 2.1 持久化分层

不是"把所有数据迁入一个数据库"，而是**按数据类型选择正确的持久化方式**：

| 数据类型                                           | 存储方式               | 原因                                                       |
| -------------------------------------------------- | ---------------------- | ---------------------------------------------------------- |
| **空间数据**（矢量/栅格）                    | GeoPackage (.gpkg)     | SQLite 扩展 + 空间索引，标准 GIS 交换格式，QGIS 可直接打开 |
| **元数据/目录**（数据源、图层、连接配置）    | SQLite                 | 关系型适合结构化查询，ORM 友好                             |
| **KG（知识图谱）**                           | RDFLib + SQLite 后端   | 三元组可通过 SQLite 持久化，生产环境可升级到 Apache Jena   |
| **会话状态**（pipeline state、parse result） | SQLite                 | 当前方案，保持                                             |
| **规划文档**（规划文本、L3 报告）            | 文件系统 + SQLite 索引 | 文本内容大，存文件；元数据存 DB                            |
| **输出成果**（GeoJSON、GDB）                 | 文件系统               | 标准输出格式，便于分发和汇交                               |

### 2.2 空间数据：GeoPackage (.gpkg)

GeoPackage 是 OGC 标准，本质是 SQLite + 空间扩展（SpatiaLite），天然支持：

- 多图层（一个 .gpkg 文件包含多个矢量图层）
- 空间索引（R-Tree）
- CRS 转换
- 属性查询 + 空间查询

**迁移路径**：

```
当前: data/gis/jintian/current/landuse.geojson
            planned/landuse.geojson
            boundary.geojson → 散落 GeoJSON 文件

目标: data/gis/jintian.gpkg
      ├── current_landuse    (现状地类图斑)
      ├── current_road       (现状道路)
      ├── current_annotation (现状注记)
      ├── planned_landuse    (规划地类图斑)
      ├── boundary           (村界)
      ├── farmland_protection (永久基本农田)
      ├── ecological_redline (生态保护红线)
      └── ...                (其他图层)
```

**使用方式**：

```python
# Data Layer 内部
from app.modules.data import DataCatalog
catalog = DataCatalog("data/gis/jintian.gpkg")
parcels = catalog.get_layer("current_landuse")  # → List[CurrentLandUseParcel]
```

### 2.3 元数据/目录：关系库

`catalog/sources.yaml` → 启动时加载到 SQLite 的 `data_sources` 表：

```sql
CREATE TABLE data_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    driver TEXT NOT NULL,
    layer_type TEXT NOT NULL,
    crs TEXT DEFAULT 'EPSG:4326',
    config_json TEXT,        -- 连接参数
    enabled INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE layer_registry (
    id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES data_sources(id),
    layer_name TEXT NOT NULL,
    feature_count INTEGER,
    bbox_west REAL, bbox_south REAL, bbox_east REAL, bbox_north REAL,
    cached_at TEXT
);
```

### 2.4 KG：RDF 持久化

**当前**：RDFLib 内存图，每次构建，不持久化。Layer1 缓存（相同 village + landuse 跳过 `_add_spatial_relations`）仅做计算跳过，不做存储持久化。

**目标**：

- 开发环境：RDFLib `Sleepycat`（Berkeley DB 后端）或 `SQLite` 后端
- 生产环境：Apache Jena Fuseki（SPARQL endpoint）

**持久化策略**：

- Layer1（静态本体 + 编码）：应用启动时加载一次，不可变
- Layer2（语义关系 + 约束）：每次 pipeline 运行后持久化
- Layer3（意图 + 操作）：每次 pipeline 运行后持久化，可被后续修订覆盖

### 2.5 会话状态

当前 SQLite WAL 方案（`backend/data/*.db`）保持。存储：

- Pipeline 运行状态（`pipeline_runs` 表）
- PARSE 结果（`parse_results` 表，JSON 列存 `SpatialPlanningIntent` 序列化）
- EXECUTE 结果（`execute_results` 表，JSON 列存 `AllocationResult` 序列化）

### 2.6 迁移路线

| 阶段 | 任务                  | 说明                                                     |
| ---- | --------------------- | -------------------------------------------------------- |
| P0   | GeoJSON → GeoPackage | 数据层添加 GeoPackage driver，DataCatalog 自动检测源格式 |
| P1   | 元数据入 SQLite       | catalog/sources.yaml →`data_sources` 表               |
| P2   | KG 持久化             | RDFLib SQLite 后端                                       |
| P3   | 生产级 KG             | Apache Jena Fuseki（可选，取决于规模需求）               |

---

## 第三部分：KG 桥接层（回答 Q3：KG 如何利用 Schema，对接 PARSE 和 EXECUTE）

### 3.1 KG 定位

KG 是 PARSE 与 EXECUTE 之间的**唯一语义中间态**。它不是数据存储（Data 层负责），而是
**语义索引层**——将空间要素、关系、约束、意图统一编码为 RDF 三元组，使下游能通过 SPARQL
获取语义理解结果。

**KG 存储什么**（不存储什么）：

- ✅ 实体 URI + 属性 + 关系（语义层）
- ✅ 规划约束（数值 + 规则）
- ✅ 空间关系（邻接、包含、定位）
- ✅ 规划意图（分区目标、设施布局、轴线）
- ❌ 原始几何坐标（Data 层负责存储和查询）
- ❌ GeoJSON 文件路径（Data 层负责管理）

### 3.2 三层模型

```
┌──────────────────────────────────────────────┐
│ Layer 3: 易失层 (Volatile)                    │
│ PARSE 产出 → 写入 KG → EXECUTE 读取           │
│ - SpatialPlanningIntent (zone_targets, ...)  │
│ - SpatialOperation (create/split/merge/...)  │
│ - SpatialConstraint (area/spatial/building)  │
│ - 校验反馈 (adjustments)                      │
│ 生命周期: 单次 pipeline 运行                   │
├──────────────────────────────────────────────┤
│ Layer 2: 语义层 (Semantic)                     │
│ 空间关系 + 约束 (从 Geometry 计算)              │
│ - 邻接关系 (adjacent_to)                      │
│ - 包含关系 (within_zone, located_in)          │
│ - 保护关系 (protects, constrained_by)         │
│ - 规划约束 (construction_cap, farmland_min)   │
│ 生命周期: 村级 (不变更，除非数据更新)            │
├──────────────────────────────────────────────┤
│ Layer 1: 静态层 (Static)                      │
│ 本体 + 编码字典 (不可变)                        │
│ - EntityTypes (23 实体类型)                    │
│ - Relations (14 关系类型)                      │
│ - 编码体系 (6 套编码)                           │
│ - 规则模板 (规划目标、空间管制规则)              │
│ 生命周期: 应用级 (启动时加载)                    │
└──────────────────────────────────────────────┘
```

### 3.3 KG 消费 Schema

KG 的 Builder 只通过类型化 Schema 模型接收数据，不直接解析 GeoJSON：

```python
# ✅ 正确：通过类型化模型
class PlanningKG:
    def add_parcels(self, parcels: List[CurrentLandUseParcel]) -> None:
        for p in parcels:
            self._add_parcel_entity(p)  # p.bsm, p.dlbm, p.area_ha, p.geometry

    def add_facilities(self, facilities: List[CurrentFacility]) -> None:
        ...

    def add_roads(self, roads: List[CurrentRoad]) -> None:
        ...

    def add_protection_zones(self, zones: List[FarmlandProtection | EcologicalRedline]) -> None:
        ...

# ❌ 禁止：KG 直接读 GeoJSON
class PlanningKG:
    def build_from_geojson(self, landuse: dict, annotations: dict) -> None:  # 禁止
        ...
```

**关键**：KG 的 geometry 操作（如计算邻接关系、质心坐标）不应在 KG 内部实现。
`SpatialRelation` 的计算由 `SpatialOps` 模块完成，KG 只负责存储和索引。

### 3.4 KG 对接 PARSE（写入）

PARSE 产出写入 KG 的 Layer 3（易失层）：

```
PARSE Agent
  → SpatialPlanningIntent  → KG.add_intent(intent)     # 分区目标、设施、轴线
  → SpatialOperation[]     → KG.add_operations(ops)     # 原子操作序列
  → SpatialConstraint[]    → KG.add_constraints(cons)   # 空间约束
  → 编码/地名映射          → KG.add_mappings(mappings)   # lookup_code/resolve_place 结果
```

**写入接口**：

```python
class PlanningKG:
    # Layer 3 写入 (PARSE → KG)
    def add_intent(self, intent: SpatialPlanningIntent) -> None:
        """写入分区目标、设施布局、发展轴线"""
        for zt in intent.zone_targets:
            self._add_zone_target(zt)  # pln:ZoneTarget 实体
        for ft in intent.facilities:
            self._add_facility_target(ft)  # pln:FacilityTarget 实体
        for at in intent.development_axes:
            self._add_axis_target(at)  # pln:AxisTarget 实体

    def add_operations(self, ops: List[SpatialOperation]) -> None:
        """写入原子操作序列"""
        for op in ops:
            self._add_operation(op)  # pln:SpatialOperation 实体

    def add_constraints(self, cons: List[SpatialConstraint]) -> None:
        """写入空间约束 (PARSE 产出 + YAML 规则)"""
        for c in cons:
            self._add_constraint(c)  # pln:Constraint 实体
```

### 3.5 KG 对接 EXECUTE（读取）

EXECUTE 从 KG 读取约束和语义信息：

```
EXECUTE Agent
  ← KG.get_constraints()          # 所有约束 → MIP 约束矩阵
  ← KG.get_adjacency_map()        # 邻接关系 → MIP 邻接规则
  ← KG.get_protected_parcels()    # 保护地块 → MIP 锁定变量
  ← KG.get_zone_restrictions()    # 分区限制 → MIP 容量约束
  ← KG.get_intent()               # 规划意图 → 分配目标
  ← KG.get_three_lines()          # 三线 → 空间约束
  ← KG.get_vne_summary()          # VNE 汇总 → 验证参考
  ← KG.get_facility_locations()   # 设施位置 → 设施布局
```

**读取接口**：

```python
class PlanningKG:
    # Layer 2+3 读取 (KG → EXECUTE)
    def get_constraints(self) -> List[Dict]:
        """获取所有约束（含 PARSE 产出 + YAML 规则）"""
        return self._query("get_constraints")

    def get_adjacency_map(self) -> Dict[str, List[str]]:
        """获取地块邻接关系"""
        return self._query("get_adjacent_parcels")

    def get_protected_parcels(self) -> List[str]:
        """获取受保护地块 BSM 列表"""
        return self._query("check_protected_parcels")

    def get_intent(self) -> SpatialPlanningIntent:
        """获取 PARSE 产出的规划意图"""
        return self._reconstruct_intent()

    def get_three_lines(self) -> List[Dict]:
        """获取三线边界"""
        return self._query("get_three_lines")
```

### 3.6 本体设计

**23 个实体类型**（对齐 Group A~E 空间要素）：

| 分组     | 实体                                                                            | 对应 Schema 类型                                     |
| -------- | ------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 行政区划 | Village, AdministrativeVillage, NaturalSettlement                               | AdminArea                                            |
| 现状地类 | Parcel (CurrentLandUseParcel), BuildingGroup                                    | CurrentLandUseParcel, CurrentBuilding                |
| 现状设施 | Facility, Road, WaterBody                                                       | CurrentFacility, CurrentRoad, WaterFeature           |
| 规划要素 | Zone (PlannedLandUseParcel), PlannedRoad, PlannedAnnotation                     | PlannedLandUseParcel, PlannedRoad, PlannedAnnotation |
| 保护控制 | FarmlandProtection, EcologicalRedline, HistoricalProtection, VillageDevBoundary | 对应 Schema 类型                                     |
| 管控线   | HazardControlLine, ConditionalConstructionZone                                  | 对应 Schema 类型                                     |
| 规划分区 | LandUseZone, ConstructionCtrlZone, PlanningScope                                | 对应 Schema 类型                                     |
| 三区三线 | ThreeZone, ThreeLine                                                            | ThreeZoneItem, ThreeLineItem                         |
| 规划意图 | ZoneTarget, FacilityTarget, AxisTarget                                          | ZoneTarget, FacilityTarget, AxisTarget               |
| 管制规则 | ControlRule, PlanningIndicator                                                  | 对应 Schema 类型                                     |

**14 个关系类型**：

| 关系               | 含义       | 用于           |
| ------------------ | ---------- | -------------- |
| `adjacent_to`    | 空间邻接   | MIP 邻接规则   |
| `within_zone`    | 包含于分区 | 分区查询       |
| `constrained_by` | 受约束于   | 约束检查       |
| `designated_as`  | 被指定为   | 用地分类       |
| `protects`       | 保护       | 保护边界       |
| `located_in`     | 位于       | 村名→地块映射 |
| `achieves`       | 达成       | 指标落地       |
| `conflicts_with` | 冲突       | 冲突检测       |
| `derived_from`   | 源于       | 溯源           |
| `serves`         | 服务       | 设施覆盖       |
| `connects`       | 连接       | 道路网络       |
| `delineates`     | 划定       | 三线划定       |
| `controls_use`   | 管制用途   | 管制规则       |
| `conducted_from` | 上位传导   | 指标传导       |

---

## 第四部分：PARSE 理解层（回答 Q4：PARSE 如何完成空间理解，辅助 EXECUTE）

### 4.1 PARSE 定位

PARSE 是 **理解层**——将自然语言规划文本转化为结构化的空间意图。
它不操作几何，只产出**声明式意图**（declarative intent），由 EXECUTE 落地。

**输入**：规划文本（L3 报告/规划说明）+ SpatialContext（空间上下文摘要）+ KG 查询能力
**输出**：SpatialPlanningIntent + SpatialOperation[] + SpatialConstraint[]

### 4.2 空间理解机制

PARSE 的空间理解通过三个层次实现：

**Level 1: 空间上下文注入（SpatialContext）**

`SpatialContext` 是约 2KB 的压缩空间摘要，从 Data 层获取的 GISDataBundle 计算得出，
在 PARSE 启动时注入 prompt：

```
SpatialContext 包含:
  - 村名锚点 (NaturalVillageAnchor[]) — 精确坐标 + 候选地块 BSM
  - 设施锚点 (FacilityAnchor[]) — 精确坐标 + 设施类型
  - 空间关系 (SpatialRelation[]) — 村组间方向/邻接/包含关系
  - 用地分布 (LanduseEntry[]) — 各类型地块数量+面积
  - 约束摘要 (ConstraintSummary[]) — 保护边界范围
  - 村界 + 建设边界面积
```

**Level 2: KG 工具调用（Think 阶段）**

在 Think 阶段（`explore_*` 节点），LLM 可以调用三个 KG 工具：

| 工具                 | 用途                    | 查询方式                        |
| -------------------- | ----------------------- | ------------------------------- |
| `lookup_code`      | 用地名称 → GHYTBM 编码 | 查 Schema 字典                  |
| `resolve_place`    | 地名 → 空间锚点        | 查 KG entities + SpatialContext |
| `query_village_kg` | 查询 KG 空间上下文      | SPARQL 查询                     |

**Level 3: LLM 推理（Think 阶段自由推理）**

LLM 利用 Level 1（注入的空间上下文）和 Level 2（工具调用结果），在 Think 阶段自由推理
空间布局偏好。例如："金田村北部是生态保护红线，南部分布 3 个自然村，因此产业用地应布局在
南部靠近主干道的位置"。

### 4.3 输出模型

**SpatialPlanningIntent**（规划意图）：

```python
class SpatialPlanningIntent:
    village_name: str
    # 分区目标（核心）
    zone_targets: List[ZoneTarget]  # land_use + area_ratio + vne_code + spatial_preference
    # 设施布局
    facilities: List[FacilityTarget]  # type + location_hint + anchor_village
    # 发展轴线
    development_axes: List[AxisTarget]  # direction + connects
    # 指标表
    indicator_table: Optional[PlanningIndicatorTable]  # 附表1
    # 三区三线
    three_zones_three_lines: Optional[ThreeZonesThreeLines]
```

**SpatialOperation**（原子操作）：

```python
class SpatialOperation:
    action: Literal["create", "split", "merge", "modify", "reclassify"]
    spatial_anchor: SpatialAnchor  # 双阶段定位
    target_parcels: List[str]      # BSM 列表
    # action-specific params
    project_name, area_sqm, land_use_code  # create
    source_bsm, split_ratio                 # split
    source_bsms                            # merge
    field_changes, new_qmdlbm              # modify/reclassify
```

**SpatialConstraint**（空间约束）：

```python
class SpatialConstraint:
    type: Literal["area_constraint", "spatial_constraint", ..., "farmland_protection", ...]
    # 面积约束
    land_use, target_area_ha, operator
    # 空间约束
    spatial_rule: SpatialRule  # no_overlap, buffer_exclusion, contained_by, ...
    # 建筑约束
    max_area_sqm, max_height_m, setback_m
```

### 4.4 辅助 EXECUTE 的路径

PARSE 通过四个路径辅助 EXECUTE：

| 路径               | PARSE 产出              | EXECUTE 消费          | 用途               |
| ------------------ | ----------------------- | --------------------- | ------------------ |
| **分区目标** | `ZoneTarget[]`        | MIP 分配目标          | 决定各分区面积比例 |
| **设施布局** | `FacilityTarget[]`    | 设施放置器            | 决定设施位置和类型 |
| **轴线**     | `AxisTarget[]`        | 轴线生成器            | 决定发展轴线方向   |
| **约束规则** | `SpatialConstraint[]` | MIP 约束矩阵 + 验证器 | 确保合规           |
| **原子操作** | `SpatialOperation[]`  | 操作执行器            | 具体项目落地       |

**关键设计**：PARSE 产出是**声明式**的（"应该在南部靠近主干道的位置布局产业用地"），
不是**命令式**的（"把地块 BSM-001 改为产业用地"）。EXECUTE 负责将声明式意图转化为
具体的空间变更。

---

## 第五部分：EXECUTE 执行层（回答 Q5：MIP 如何利用 KG + Q6：如何实现意图）

### 5.1 EXECUTE 定位

EXECUTE 是**执行层**——将 PARSE 产出的结构化意图转化为空间几何成果。
它是多策略执行器，不是单一的 MIP 求解器。

**输入**：PARSE 意图 + KG 约束 + GIS 数据（通过 Data 层）
**输出**：allocated_geojson + layout_configs（多个图层） + validation_result

### 5.2 四类子任务

| 子任务               | 输入                        | 策略                | 输出                           |
| -------------------- | --------------------------- | ------------------- | ------------------------------ |
| **layout**     | ZoneTarget[] + 现状地块     | MIP 批量分配        | 分区赋色 + 功能分区 + 规划分区 |
| **facility**   | FacilityTarget[] + 设施锚点 | 约束满足 + 最近邻   | 设施点图层                     |
| **axis**       | AxisTarget[] + 现状轴线     | 程序化生成 + 缓冲区 | 轴线 + 空间控制区 + 用途分区   |
| **road**       | 现状道路 + 规划意图         | 图搜索 + 最短路径   | 规划道路网络                   |
| **operations** | SpatialOperation[]          | 原子操作执行        | 具体图斑变更                   |

### 5.3 MIP 与 KG 的协作模式（回答 Q5）

**核心结论**：MIP 不能直接查询 KG 进行优化（太慢，抽象层次错误），但可以通过
**约束编译器（Constraint Compiler）** 在优化前一次性从 KG 提取所有约束。

```
KG (语义层)            约束编译器               MIP (数学优化层)
─────────────        ──────────────           ─────────────────
protected_parcels ──→ 变量锁定          ──→  x[i][construction] = 0
zone_restrictions ──→ 容量约束          ──→  Σ x[i][zone] * a[i] ≤ max
adjacency_map    ──→ 邻接偏好          ──→  cost_matrix[i][j]
area_targets     ──→ 目标约束          ──→  Σ x[i][zone] * a[i] ≈ target
three_lines      ──→ 空间边界约束      ──→  x[i][zone] = 0 for i outside
```

**约束编译器的工作流程**：

```
1. 从 KG 提取约束 (一次性 SPARQL 查询)
   - get_protected_parcels() → BSM list
   - get_zone_restrictions() → zone → capacity
   - get_adjacency_map() → parcel → neighbors
   - get_three_lines() → line boundaries

2. 从 PARSE intent 提取目标
   - zone_targets → target_map {zone: area_ha}
   - density_hints → zone → density
   - adjacency_rules → prefer/avoid lists

3. 编译为 MIP 模型 (PuLP)
   - 变量: x[i][zone] ∈ {0,1}
   - 硬约束: 保护地块锁定、三线边界、容量上限
   - 软约束: 面积目标偏差最小化、邻接偏好
   - 目标: minimize Σ |actual - target| + adjacency_cost
```

**为什么不能直接查询 KG**：

- MIP 求解器（PuLP/CBC）在优化循环中每次评估约束和变量，需要的不是 SPARQL 查询，
  而是数值矩阵（系数矩阵 A, 约束向量 b, 目标向量 c）
- KG 的 RDF 图是符号化的知识表示，不是数值优化模型
- 约束编译器是一次性编译，MIP 求解器是迭代数值优化，分离是正确设计

### 5.4 约束编译器设计

```python
class ConstraintCompiler:
    """将 KG 语义约束编译为 MIP 数值约束矩阵"""

    def __init__(self, kg: PlanningKG):
        self.kg = kg

    def compile(self, intent: SpatialPlanningIntent, landuse: List[CurrentLandUseParcel]) -> MIPModel:
        """一次性编译所有约束"""
        model = MIPModel()

        # Step 1: 创建变量
        parcels = [p.bsm for p in landuse]
        zones = [zt.land_use for zt in intent.zone_targets]
        model.create_variables(parcels, zones)

        # Step 2: 硬约束（从 KG 提取）
        protected = self.kg.get_protected_parcels()
        model.lock_protected(protected)  # x[i][construction] = 0

        three_lines = self.kg.get_three_lines()
        model.apply_spatial_bounds(three_lines, landuse)

        # Step 3: 软约束（从 PARSE intent 提取）
        targets = {zt.land_use: zt.area_ratio for zt in intent.zone_targets}
        model.set_targets(targets)

        adjacency = self.kg.get_adjacency_map()
        model.set_adjacency_cost(adjacency, intent.adjacency_rules)

        # Step 4: 密度约束
        model.set_density_constraints(intent.density_hints, landuse)

        return model
```

### 5.5 意图落地路径（回答 Q6）

**当 MIP 不适用时**（具体项目落地、小规模操作），EXECUTE 使用约束满足策略：

**create 操作**（"新建 400㎡ 展销中心"）：

```
1. 解析 SpatialAnchor → 候选地块列表
2. 约束满足：
   - 合规检查：不在基本农田、不在生态红线、在建设边界内
   - 面积约束：≥400㎡
   - 邻接约束：靠近主干道
3. 选择最优地块 → 创建新图斑
4. 写入 changelog
```

**split/merge 操作**（"合并相邻地块"）：

```
1. 查找 source_bsms
2. 几何操作：union / split
3. 面积重算
4. 写入 changelog
```

**程序化生成**（轴线、道路、分区图层）：

```
1. 从 intent 读取参数
2. 程序化算法（缓冲区/插值/最短路径）
3. 生成图层
4. 写入 changelog
```

### 5.6 验证闭环

EXECUTE 的 Worker-Evaluator 循环：

```
EXECUTE (layout → facility → axis → road)
    ↓
VALIDATE (8 项检查 + 8 条硬约束)
    ├── PASS → END
    └── FAIL → 生成 constraint_adjustments
         ↓
    EXECUTE (重新执行，应用调整)
         ↓
    VALIDATE (再次检查)
         ├── PASS → END
         └── FAIL → ... (最多 3 轮)
```

**验证检查项**：

| # | 检查项           | 输入                                   | 约束来源      |
| - | ---------------- | -------------------------------------- | ------------- |
| 1 | 建设用地不超上限 | allocated_geojson + intent             | KG constraint |
| 2 | 耕地下限         | allocated_geojson + intent             | KG constraint |
| 3 | 不占永久基本农田 | allocated_geojson + protected_parcels  | KG spatial    |
| 4 | 不占生态红线     | allocated_geojson + ecological_redline | KG spatial    |
| 5 | 建设边界内       | allocated_geojson + boundary           | KG spatial    |
| 6 | 面积偏差 ≤ 5%   | allocated_geojson + targets            | intent        |
| 7 | 邻接规则合规     | allocated_geojson + adjacency_rules    | intent        |
| 8 | 三线合规         | allocated_geojson + three_lines        | KG spatial    |

---

## 第六部分：实现规划

### 6.1 模块结构（目标架构）

```
app/
├── modules/
│   ├── schema/                    # [DONE v4.2] 独立 Schema 层（已从 gis/schema/ 提升）
│   │   ├── __init__.py
│   │   ├── types/                # base + spatial_types + canonical + raster_types + table_types + document_types + layer_registry
│   │   ├── encodings/            # classification / code_sets / dicts(6 YAML+rules)
│   │   ├── contracts/            # parse / execution / validation / layout 契约
│   │   ├── output/               # gdb / colors / tables
│   │   ├── utils/                # metrics
│   │   └── README.md
│   │
│   ├── data/                      # Data 层
│   │   ├── __init__.py
│   │   ├── contracts.py           # DataResult, DataSourceMetadata
│   │   ├── catalog/               # 声明式目录
│   │   │   ├── catalog.py         # DataCatalog
│   │   │   ├── config.py          # Pydantic 配置
│   │   │   └── sources.yaml       # 数据源声明
│   │   ├── connections/           # 连接管理
│   │   │   ├── base.py
│   │   │   ├── tianditu.py
│   │   │   ├── amap.py
│   │   │   └── osm.py
│   │   ├── sources/               # 数据源驱动
│   │   │   ├── base.py
│   │   │   ├── file_vector.py
│   │   │   ├── api_vector.py
│   │   │   ├── local_raster.py
│   │   │   ├── remote_raster.py
│   │   │   └── wmts_tile.py
│   │   ├── ingest.py              # 数据型式端口（唯一入口）
│   │   ├── documents/             # 文档数据
│   │   │   ├── loader.py
│   │   │   └── intent_cache.py
│   │   └── README.md
│   │
│   ├── kg/                         # KG 桥接层
│   │   ├── __init__.py
│   │   ├── manager.py              # KGManager (统一入口)
│   │   ├── builder.py              # PlanningKG (构建器)
│   │   ├── ontology.py             # 本体定义
│   │   ├── query.py                # SPARQL 查询模板
│   │   ├── constraint_compiler.py  # [NEW] 约束编译器
│   │   └── README.md
│   │
│   └── spatial_ops/                # [NEW] 空间计算工具
│       ├── __init__.py
│       ├── relations.py            # 空间关系计算
│       ├── geometry.py             # 几何操作
│       └── context.py              # SpatialContext 计算
│
├── agent/
│   └── gis/
│       ├── __init__.py
│       ├── state.py                # GISPipelineState
│       ├── pipeline.py             # [RENAMED] 顶层流水线（原 layout_pipeline.py）
│       ├── parse/                  # PARSE Agent
│       │   ├── __init__.py
│       │   ├── state.py
│       │   ├── agent.py
│       │   └── README.md
│       ├── analyze/               # [NEW] ANALYZE Agent (栅格分析, 见 Phase 5 / T26)
│       │   ├── __init__.py
│       │   ├── state.py
│       │   ├── dem_analysis.py    # DEM -> TerrainAnalysisResult
│       │   └── double_evaluation.py # 双评价
│       └── execute/                # EXECUTE Agent
│           ├── __init__.py
│           ├── state.py
│           ├── agent.py
│           ├── layout/             # 布局子任务
│           ├── facility/           # 设施子任务
│           ├── axis/               # 轴线子任务
│           ├── road/               # 道路子任务
│           └── README.md
│
└── tools/
    └── gis/                        # 工具层（LangGraph @tool 包装）
        ├── parse.py
        ├── generate.py
        ├── allocate.py
        ├── validate.py
        ├── export.py
        ├── render.py
        ├── conflict.py
        ├── kg.py
        └── gis_data/
            ├── fetch.py
            └── search_poi.py
```

### 6.2 数据流

```
1. 用户输入规划文本 + 村庄名称
2. Data Layer: 加载 GISDataBundle（GeoPackage + 远程 API）
3. Spatial Ops: 计算 SpatialContext（从 GISDataBundle）
4. KG Builder: 从 Schema 模型构建 KG Layer 1+2
5. PARSE: 文本 + SpatialContext + KG 工具 → SpatialPlanningIntent + OperationSequence + ConstraintSet
6. KG: PARSE 产出写入 KG Layer 3
7. Constraint Compiler: KG → MIP 约束矩阵
8. EXECUTE: MIP 分配 + 设施放置 + 轴线生成 + 道路生成 + 操作执行
9. VALIDATE: 8 项检查 → PASS 或撤回 EXECUTE
10. Export: 图层 → GeoPackage / GeoJSON
11. Render: 图层 → 前端可视化
```

### 6.3 迁移路线图

> **进度概览（2026-07-25）**：Phase 1.1-1.3 ✅ 已完成；1.4 ❌ 仍 `layout_pipeline.py`；1.5 ⏳ 部分（T5/T6/T23 ✅ shim+注册表+文档，T1-T4 待执行）。
> Phase 2.1 ❌ ConstraintCompiler（T10）；2.2-2.5 ⏳ KG 入库 4/29；2.6 ❌ 持久化。Phase 3 ❌；Phase 4 ⏳ 部分；Phase 5 ❌ 远期（T26 ANALYZE 骨架先行）。
> T27b ✅ GDSpecializedService 断链修复；T27c ✅ trace.py 迁出 gis/。详细任务见 `reference/OPTIMIZATION_TASKS.md`。

**Phase 0: 设计落地（当前）**

| #   | 任务               | 说明                       |
| --- | ------------------ | -------------------------- |
| 0.1 | 编写本设计文档     | ✅ 当前                    |
| 0.2 | 归档旧文档         | 旧设计文档迁入`archive/` |
| 0.3 | 编写新`INDEX.md` | 精简导航                   |

**Phase 1: 架构清理**

| #   | 任务                                      | 说明                                                             |
| --- | ----------------------------------------- | ---------------------------------------------------------------- |
| 1.1 | Schema 层提升                             | `app/modules/gis/schema/` -> `app/modules/schema/` ✅ 已完成 |
| 1.2 | 消除 KG 反向依赖                          | KG 不再 import`tools/gis/_generation` 和 `_analytics`        |
| 1.3 | 提取 Spatial Ops 模块                     | 空间关系计算从 KG 和 agent 中提取到`app/modules/spatial_ops/`  |
| 1.4 | `layout_pipeline.py` → `pipeline.py` | 重命名，消除名不副实                                             |
| 1.5 | 消除 data/ 三套并行抽象                   | 统一到 Catalog + Source 架构                                     |

**Phase 2: KG 完善**

| #   | 任务                     | 说明                                                                            |
| --- | ------------------------ | ------------------------------------------------------------------------------- |
| 2.1 | 实现 Constraint Compiler | KG → MIP 约束矩阵的编译层                                                      |
| 2.2 | 补齐保护边界入库         | FarmlandProtection, EcologicalRedline, HistoricalProtection, VillageDevBoundary |
| 2.3 | 补齐规划要素入库         | LandUseZone, ConstructionCtrlZone, PlanningScope                                |
| 2.4 | 补齐自然地理入库         | WaterFeature, GeologicalHazardPoint, ElevationPoint                             |
| 2.5 | 地块实体增强             | centroid 坐标、VNE 码、规划分区                                                 |
| 2.6 | KG 持久化                | RDFLib SQLite 后端                                                              |

**Phase 3: 数据持久化**

| #   | 任务            | 说明                                       |
| --- | --------------- | ------------------------------------------ |
| 3.1 | GeoPackage 集成 | Data Layer 添加 GeoPackage driver          |
| 3.2 | 元数据入 SQLite | catalog/sources.yaml →`data_sources` 表 |
| 3.3 | 会话状态持久化  | Pipeline 运行结果持久化                    |

**Phase 4: EXECUTE 完善**

| #   | 任务                    | 说明                        |
| --- | ----------------------- | --------------------------- |
| 4.1 | 实现 PlannedRoad 生成器 | 道路网络生成                |
| 4.2 | 实现 create 原子操作    | 具体项目落地                |
| 4.3 | 实现 split/merge 操作   | 地块拆分/合并               |
| 4.4 | 完善验证闭环            | 8 项检查 + 8 条硬约束自动化 |

**Phase 5: 闭环（远期）**

| #   | 任务           | 说明                         |
| --- | -------------- | ---------------------------- |
| 5.1 | ANALYZE 能力   | 栅格摄入 + DEM 分析 + 双评价 |
| 5.2 | 文本↔空间闭环 | 空间分析结果回灌文本修订     |
| 5.3 | 完整汇交成果   | 5 目录 + .mdb + 条款级溯源   |

---

## 附录 A：术语表

| 术语                | 全称                                                    | 说明                              |
| ------------------- | ------------------------------------------------------- | --------------------------------- |
| PARSE               | Plan Agent for Report Spatial Extraction                | 规划文本 → 空间意图              |
| EXECUTE             | Execution Agent                                         | 空间意图 → 空间几何成果          |
| KG                  | Knowledge Graph                                         | 语义桥接层                        |
| MIP                 | Mixed Integer Programming                               | 混合整数规划（批量分区优化）      |
| GDB                 | GeoDatabase                                             | 空间数据库格式                    |
| DLBM                | 地类编码                                                | 土地利用分类编码                  |
| GHYTBM              | 规划用途编码                                            | 附录5编码                         |
| BSM                 | 标识码                                                  | 地块唯一标识                      |
| VNE                 | V=村庄建设用地, N=非村庄建设用地, E=非建设用地          | 住建部三分类                      |
| 三区三线            | 生态/农业/建设空间 + 生态红线/永久基本农田/城镇开发边界 | 全国国土空间规划                  |
| 一图一表一规则      | 村庄规划总图 + 近期建设项目表 + 管制规则                | 广东省基本成果                    |
| SpatialContext      | 空间上下文                                              | 约2KB的空间摘要，注入PARSE prompt |
| Constraint Compiler | 约束编译器                                              | KG语义约束 → MIP数值约束矩阵     |

## 附录 B：与旧文档的对应关系

| 旧文档                                         | 本文档对应部分     | 变更                               |
| ---------------------------------------------- | ------------------ | ---------------------------------- |
| 00_PLANNING_SYSTEM_VISION.md                   | §0.1-0.2, Part 5  | 合并初期/终极目标，去除冗余描述    |
| 01_DESIGN_GOALS.md                             | §1.1-1.5, Part 1  | 简化为四层架构，去除过时技术细节   |
| 02_OUTPUT_ARCHITECTURE.md                      | §1.2 + Appendix A | 输出规范并入 Schema 层，术语表提取 |
| 03_DATA_SOURCE.md                              | §2.2-2.3          | 数据源并入 Data 层持久化方案       |
| 04_DATA_ACQUISITION_PLAN.md                    | §2.6              | 数据获取计划并入迁移路线           |
| schema对接kg，parse.md                         | §3.3-3.5, Part 4  | 整合为 KG+PARSE 对接设计           |
| proposals/03_TOOL_FIRST_ARCHITECTURE.md        | §6.1              | 模块结构已更新为当前目标           |
| proposals/04_MULTI_SOURCE_DATA_ARCHITECTURE.md | §1.3, §2.2       | 数据源架构并入 Data 层             |

---

> **文档结束**。本文档是系统的唯一权威设计文档。旧文档已迁入 `archive/`，仅作为历史参考。
> 当本文档与旧文档冲突时，以本文档为准。
