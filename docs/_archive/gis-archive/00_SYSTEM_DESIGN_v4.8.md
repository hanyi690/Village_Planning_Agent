# 村庄规划智能系统 — 总体设计文档

> **Status: [CURRENT] | Type: North-Star Design | Version: 4.8 | Updated: 2026-07-29**
> **Scope**: 系统总体架构设计，覆盖 Schema / Data / KG / PARSE / EXECUTE 五层，回答 6 个核心设计问题
> **Audience**: 系统架构师、核心开发者
> **Replaces**: 00_PLANNING_SYSTEM_VISION.md + 01_DESIGN_GOALS.md + 02_OUTPUT_ARCHITECTURE.md (合并、精简、去矛盾)
> **Archived**: 旧文档已迁入 `archive/` 目录
>
> **v4.8 变更摘要（2026-07-29）**：
>
> - **02_EXECUTION_PLAN reconciliation 回填**：02 中推翻 00 的四个条款（§3.2/§3.5/§3.6/§5.1）已全部回填到本文档，消除双文档矛盾
> - §3.2 更新：L1/L2 保留为 LLM 空间语义基础设施（对齐 02 认知修正 #2）
> - §3.5 确认：ConstraintCompiler 废弃，MIP 直接消费 KG 查询结果
> - §3.6 确认：ThreeZone/ThreeLine 保持 v4.7 移出 KG，改 ConstraintIndex
> - §5.1 确认：MIP 先图斑后校核（图斑级操作优先，MIP 配额校核辅助）
> - 归档重组：`docs/architecture/` 和 `docs/gis/` 按主题模块重组，旧文档统一添加 deprecated 横幅
> - 权威链修正：模块 README > 本文档 > audit > proposals > archive
>
> **v4.7 变更摘要（2026-07-26）**：
>
> - EXECUTE 范式修正：图斑级操作（reclassify/modify/split/merge）为主策略，MIP 降级为配额测算与校核（对齐 03_GAP_ANALYSIS 缺陷1、05_MODULE_BOUNDARY_AUDIT §2）
> - 清理 v4.5 编辑残留：删除重复的旧版 §3.5/§3.6 与孤儿代码片段
> - 清理 ConstraintCompiler 矛盾：迁移路线图与术语表同步标注废弃
> - 新增第七部分"成果合规与协同"：汇交坐标系/椭球面积、管制规则闭环、村民参与、编制模式分支、上位指标分解
> - 基数转换纳入主数据流（Data 层 ingest 阶段）
>
> **v4.6 变更摘要（2026-07-26）**：
>
> - KG 重构：只存有几何的空间实体，删除非空间类型（ControlRule, PlanningIndicator, Constraint, PlanIntent）
> - 删除 8 个关系类型（constrained_by, achieves, conflicts_with, conducted_from, controls_use, protects, adjacent_to, location_constraint）
> - 新增 SemanticMemoryStore：实体 + 关系注解，替代 _semantic_store
> - 新增 L3 意图虚拟实体：Intent → 粗糙几何 + 空间关系
> - 新增 L4 PlannedState：规划成果增量聚合，形态对齐 bundle
> - KG builder 从 bundle 形态分组直连，不依赖 ContextBlock
> - ContextBlock 和 PlanBlock 对称——都是 Agent 的"工作记忆"，不进 KG
> - ConstraintCompiler 废弃——MIP 直接消费 SPARQL 结果
> - 删除 `queries/llm.py`（死代码）、`_semantic_store` 字段
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

| 标准                  | 全称                                         | 系统对齐                                                                       |
| --------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| 自然资发〔2023〕234号 | 国土空间调查、规划、用途管制用地用海分类指南 | 用地分类编码体系（YDYHFL）                                                     |
| GB/T 21010-2017       | 土地利用现状分类                             | 三调国标编码体系（注意：金田村现状层实际为附录5编码，见 02_DATA_SOURCE §2.3） |
| GB/T 13923-2022       | 基础地理信息要素分类与代码                   | 10位数字层次码（大类+小类+一至四级类）                                         |
| DB14/T 2979-2024      | 村庄规划数据库规范                           | 数据库内容、要素分类代码、数学基础、数据分层                                   |
| 广东省住建厅 (2018)   | 广东省村庄规划编制指引（试行）               | 四阶段工作流、一图一表一规则成果                                               |
| DB4407/T 105-2023     | 村庄建设规划管制规则                         | 6大类管制规则模板                                                              |
| 住建部 (2014)         | 村庄规划用地分类指南                         | V/N/E 三分类                                                                   |
| 三区三线              | 全国国土空间规划                             | 生态/农业/建设空间 + 三线边界                                                  |

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
│  ┌────op──────────┐  ┌──────────────────────────────────────────┐ │
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
│  │ Layer3 易失 (Intent ) |Layer planblock 规划增量                         │ │
│  │ RDFLib Graph + SPARQL 查询    +面对LLM的语义查询+json的实体附带的语义文件                             │ │
│  └──────────────────────────────┬─────────────────────────────┘ │
│                                 │ depends                       │
│         ┌───────────────────────┼───────────────────────┐       │bundle
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

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: Catalog (声明式编排)                           │
│  sources.yaml -> DataCatalog.load_village_bundle()       │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Source / Driver (形态驱动读取)                  │
│  file_vector | api_vector | wmts_tile | local_raster    │
│  | remote_raster | document                              │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Connection (连接管理)                          │
│  tianditu | amap | osm | gd_tianditu                     │
└─────────────────────────────────────────────────────────┘
         │
         ▼  (DataResult -> ingest -> typed models)
         ▼  (_assign_to_bundle: isinstance dispatch -> morphology groups)
┌─────────────────────────────────────────────────────────┐
│  VillageBundle (v4.3 形态优先 dataclass)                 │
│  ├── points:   PointLayerGroup (设施/建筑/注记/高程/灾害)│
│  ├── lines:    LineLayerGroup (道路/等高线/行政界线)     │
│  ├── polygons: PolygonLayerGroup (地块/保护/管控/水系)   │
│  ├── rasters:  RasterLayerGroup (DEM/DOM/坡度/坡向)     │
│  ├── tables:   TableLayerGroup (人口/管制规则/指标)      │
│  ├── documents: DocumentGroup (规划文本/L3 报告)          │
│  └── compute_context_blocks(bundle) -> List[ContextBlock] │
└─────────────────────────────────────────────────────────┘
```

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
**语义索引层**——只存储有几何的空间实体及其关系，不存储非空间要素。

**核心原则**：KG 只存"有几何的空间要素"。非空间要素（规则、指标、约束数值）通过
`bundle.tables` 或 `ContextBlock` 传递。

**KG 存储什么**（不存储什么）：

- ✅ 实体 URI + 属性 + 空间关系（语义层）
- ✅ 空间关系（touches、nearby、within_zone）
- ✅ 意图虚拟实体（L3 易失层，粗糙几何）
- ✅ 规划成果实体（L4 版本化，精确几何）
- ❌ 原始几何坐标（Data 层负责存储和查询，KG 只存 centroid）
- ❌ 规划约束数值（由 ContextBlock 承载）
- ❌ 管制规则（由 `bundle.tables.control_rules` 承载）
- ❌ 规划指标（由 `bundle.tables.planning_indicators` 承载）
- ❌ 语义注解（由 `SemanticMemoryStore` 承载，非 RDF）

### 3.2 四层模型

```
┌──────────────────────────────────────────────┐
│ Layer 4: 规划成果层 (PlannedState)             │
│ EXECUTE 产出 → 版本化规划实体                  │
│ - PlannedParcel (规划地块)                     │
│ - PlannedRoad (规划道路)                       │
│ - PlannedFacility (规划设施点)                 │
│ 生命周期: 会话持久（可多版并存）                │
├──────────────────────────────────────────────┤
│ Layer 3: 意图易失层 (Intent Virtual Entities)  │
│ PARSE 意图 → 粗糙几何 + 空间关系               │
│ - ZoneTarget (分区目标, 粗糙bbox)              │
│ - FacilityTarget (设施目标, 点+缓冲区)         │
│ - RoadTarget (道路目标, 线+缓冲区)             │
│ 生命周期: 单次规划会话，结束后清除              │
├──────────────────────────────────────────────┤
│ Layer 2: 空间关系层 (Spatial Relations)        │
│ 由 spatial_ops 计算，KG 存储索引               │
│ - touches, nearby, connected_via_road          │
│ - within_zone, located_in, delineates          │
│ - designated_as, derived_from, serves          │
│ 生命周期: 村级持久（不变更，除非数据更新）      │
├──────────────────────────────────────────────┤
│ Layer 1: 现状实体层 (Static Entities)          │
│ 本体 + 空间实体（从 bundle 形态分组直连）       │
│ - Parcel, Road, WaterBody, Facility            │
│ - Zone, ThreeZone, ThreeLine                   │
│ - FarmlandProtection, EcologicalRedline, ...   │
│ 生命周期: 应用级（数据更新时重建）              │
└──────────────────────────────────────────────┘
```

### 3.3 KG 消费 Schema

KG 的 Builder 直接从 `VillageBundle` 的形态分组读取类型化数据，不依赖 ContextBlock。
ContextBlock 只作为 PARSE 的 prompt 上下文（agent 记忆），不进入 KG 构建路径。

```python
# ✅ 正确：通过类型化模型 + bundle 形态分组直连
kg.build_from_bundle(
    bundle=bundle,              # VillageBundle — 类型化形态视图
    parcel_relations=relations, # ParcelRelations — 三层空间关系（外部计算）
    intent=intent,              # SpatialPlanningIntent → L3 虚拟实体（可选）
    planned_state=planned,      # PlannedState → L4 规划成果（可选）
)

# ❌ 禁止：KG 从 ContextBlock 读取
class PlanningKG:
    def build_from_blocks(self, blocks, ...)  # 禁止 — ContextBlock 是 agent 记忆，不进 KG
```

**关键**：KG 的 geometry 操作（如计算邻接关系、质心坐标）不应在 KG 内部实现。
`SpatialRelation` 的计算由 `SpatialOps` 模块完成，KG 只负责存储和索引。

### 3.4 KG 对接 PARSE（写入）

PARSE 产出写入 KG 的 Layer 3（易失层）：

```
PARSE Agent
  → SpatialPlanningIntent  → KG.build_intent_layer(intent)
                              → ZoneTarget/FacilityTarget/RoadTarget 虚拟实体
                              → spatial_ops 计算虚拟实体与 L1 的空间关系
```

**写入接口**：

```python
class PlanningKG:
    # Layer 3 写入 (PARSE → KG)
    def build_intent_layer(self, intent: SpatialPlanningIntent) -> None:
        """写入意图虚拟实体 + 粗糙几何 + 空间关系"""
        for zt in intent.zone_targets:
            self._add_zone_target_virtual(zt)  # pln:Intent/zone_target_1 (粗糙 bbox)
        for ft in intent.facilities:
            self._add_facility_target_virtual(ft)  # pln:Intent/facility_1 (点+缓冲区)
        for at in intent.development_axes:
            self._add_axis_target_virtual(at)  # pln:Intent/axis_1 (线+缓冲区)
        # 触发 spatial_ops 计算虚拟实体与 L1 的空间关系

    def clear_intent_layer(self) -> None:
        """清除 Layer 3 临时实体"""
```

### 3.5 KG 对接 EXECUTE（读取）

EXECUTE 从 KG 读取约束和语义信息。MIP 求解器直接消费 SPARQL 结果，不经过 ConstraintCompiler：

```
EXECUTE Agent
  ← KG.query("get_constraints")          # 所有约束 → MIP 软约束 (slack)
  ← KG.query("get_adjacent_parcels")     # 邻接关系 → MIP 邻接成本矩阵
  ← KG.query("get_protected_parcels")    # 保护地块 → MIP 变量锁定
  ← KG.query("get_three_lines")          # 三线 → MIP 硬约束
  ← KG.query("get_facility_locations")   # 设施位置 → 设施布局
  ← KG.query("count_by_vne")             # VNE 汇总 → 验证参考
  ← intent.zone_targets                  # 分区目标 → 目标面积 (直接从 intent 对象)
```

**读取接口**：

```python
class PlanningKG:
    # Layer 2+3 读取 (KG → EXECUTE)
    def get_constraints(self) -> List[Dict]:
        """获取所有约束（SPARQL → MIP 软约束）"""
        return self.query("get_constraints")

    def get_adjacency_map(self) -> Dict[str, List[str]]:
        """获取地块邻接关系"""
        return self.query("get_adjacent_parcels")

    def get_protected_parcels(self) -> List[str]:
        """获取受保护地块 BSM 列表"""
        return self.query("check_protected_parcels")

    def get_three_lines(self) -> List[Dict]:
        """获取三线边界"""
        return self.query("get_three_lines")
```

### 3.6 本体设计

**实体类型**：只包含有几何的空间实体。非空间要素（ControlRule、PlanningIndicator、Constraint）
从 KG 移出，由 `bundle.tables` 或 ContextBlock 承载。

| 形态 | 实体                        | 对应 Schema 类型             | KG 层 |
| ---- | --------------------------- | ---------------------------- | ----- |
| 面   | Parcel                      | CurrentLandUseParcel         | L1    |
| 面   | WaterBody                   | WaterFeature                 | L1    |
| 面   | BuildingGroup               | CurrentBuilding              | L1    |
| 面   | Zone                        | —                           | L1    |
| 面   | ThreeZone                   | ThreeZoneItem                | L1    |
| 面   | ThreeLine                   | ThreeLineItem                | L1    |
| 面   | FarmlandProtection          | FarmlandProtection           | L1    |
| 面   | EcologicalRedline           | EcologicalRedline            | L1    |
| 面   | HistoricalProtection        | HistoricalProtection         | L1    |
| 面   | VillageDevBoundary          | VillageDevBoundary           | L1    |
| 面   | HazardControlLine           | HazardControlLine            | L1    |
| 面   | FloodControlLine            | FloodControlLine             | L1    |
| 面   | ConditionalConstructionZone | ConditionalConstructionZone  | L1    |
| 面   | LandUseZone                 | LandUseZone                  | L1    |
| 面   | ConstructionCtrlZone        | ConstructionCtrlZone         | L1    |
| 面   | PlanningScope               | PlanningScope                | L1    |
| 面   | AdministrativeVillage       | AdminArea                    | L1    |
| 面   | NaturalSettlement           | (从用地聚类)                 | L1    |
| 点   | Facility                    | CurrentFacility              | L1    |
| 线   | Road                        | CurrentRoad                  | L1    |
| 面   | ZoneTarget                  | ZoneTarget (parse_contracts) | L3    |
| 点   | FacilityTarget              | FacilityTarget               | L3    |
| 线   | RoadTarget                  | RoadTarget                   | L3    |
| 线   | AxisTarget                  | AxisTarget                   | L3    |
| 面   | PlannedParcel               | PlannedLandUseParcel         | L4    |
| 点   | PlannedFacility             | PlannedFacility              | L4    |
| 线   | PlannedRoad                 | PlannedRoad                  | L4    |

**关系类型**：

| 关系                   | 含义               | 类别     | 用于                   |
| ---------------------- | ------------------ | -------- | ---------------------- |
| `touches`            | 拓扑邻接           | 空间拓扑 | MIP 邻接规则、地块合并 |
| `nearby`             | 近邻关系（≤200m） | 空间拓扑 | 设施选址               |
| `connected_via_road` | 路网连通           | 空间拓扑 | 交通可达性             |
| `within_zone`        | 包含于分区         | 空间拓扑 | 分区查询               |
| `located_in`         | 位于               | 空间拓扑 | 村名→地块映射         |
| `delineates`         | 划定               | 空间拓扑 | 三线划定               |
| `designated_as`      | 被指定为           | 规划语义 | 用地分类               |
| `derived_from`       | 源于               | 规划语义 | 溯源                   |
| `serves`             | 服务               | 规划语义 | 设施覆盖               |

**已删除的关系**（不再属于 KG）：
`constrained_by`, `achieves`, `conflicts_with`, `conducted_from`, `controls_use`,
`protects`, `adjacent_to` ([@deprecated]), `location_constraint`

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

**核心范式（v4.7 修正）**：规划不是"白纸分区分配"，而是"对现状图斑的操作"
（见 `03_GAP_ANALYSIS.md` 缺陷1、`05_MODULE_BOUNDARY_AUDIT.md` §2）。人类规划师的
实际操作以字段计算器式属性重赋值为主、几何裁剪为辅：大部分图斑"规划地类 = 基期现状
地类"批量保持，少数图斑 modify/split。EXECUTE 以图斑级操作为主策略，MIP 降级为
配额测算与校核工具，不直接生成规划几何。

**输入**：PARSE 意图 + KG 约束 + 基数转换后的现状图斑（Data 层）
**输出**：PlannedLandUseParcel[]（derived_from 关联现状图斑）+ layout_configs

+ validation_result + 用地平衡表

### 5.2 执行策略（按优先序）

| # | 子任务                         | 输入                           | 策略                                               | 输出                    |
| - | ------------------------------ | ------------------------------ | -------------------------------------------------- | ----------------------- |
| 0 | 基数转换（Data 层前置）        | 三调 DLBM                      | DLBM -> 规划用途编码映射                           | 基期现状图斑            |
| 1 | **operations**（主策略） | SpatialOperation[] + 现状图斑  | reclassify(批量保持)/modify/split/merge/create     | QMDLTB 期末地类图斑     |
| 2 | **layout**（配额校核）   | ZoneTarget[] + operations 结果 | MIP 测算配额并校核偏差                             | 配额偏差报告 + 调整建议 |
| 3 | **facility**             | FacilityTarget[] + 设施锚点    | 约束满足 + 最近邻                                  | 设施点图层              |
| 4 | **axis**                 | AxisTarget[] + 现状轴线        | 程序化生成 + 缓冲区                                | 轴线 + 空间控制区       |
| 5 | **road**                 | 现状道路 + 规划意图            | 图搜索 + 最短路径                                  | 规划道路网络            |
| 6 | 聚合派生                       | QMDLTB                         | dissolve by GHFLBM -> TDYT；unary_union -> JSYDGZQ | TDYT/JSYDGZQ 图层       |

### 5.3 MIP 与 KG 的协作模式（回答 Q5）

> **定位（v4.7）**：MIP 的角色是配额测算与校核——输出是各类用地的配额建议与偏差报告，
> 最终落地必须映射回图斑级 operations（reclassify/modify/split），MIP 不直接生成规划几何。

**核心结论**：MIP 不能直接查询 KG 进行优化（太慢，抽象层次错误），但可以通过
**一次性 SPARQL 查询**在优化前从 KG 提取所有约束。MIP 求解器直接消费 SPARQL 结果
（flat dict list），不经过 ConstraintCompiler。

```
KG (语义层)             SPARQL 查询               MIP (数学优化层)
─────────────        ──────────────           ─────────────────
protected_parcels ──→ query_protected_parcels ──→  x[i][construction] = 0
zone_restrictions ──→ query_constraints        ──→  Σ x[i][zone] * a[i] ≤ max (软约束)
adjacency_map    ──→ query_adjacent_parcels   ──→  cost_matrix[i][j]
area_targets     ──→ intent.zone_targets       ──→  Σ x[i][zone] * a[i] ≈ target
three_lines      ──→ query_three_lines         ──→  x[i][zone] = 0 for i outside (硬约束)
vne_summary      ──→ query_count_by_vne        ──→  V/E/N 面积下限 (硬约束)
```

**MIP 的数据流**：

```
1. 从 KG 提取约束 (一次性 SPARQL 查询)
   - get_constraints()           → List[Dict] → 软约束 (slack 变量, weight=5)
   - get_protected_parcels()     → BSM list   → 硬变量锁定
   - get_three_lines()           → List[Dict] → 硬约束 (DLBM 关键字匹配)
   - count_by_vne()              → List[Dict] → 硬约束 (VNE 编码前缀匹配)

2. 从 PARSE intent 提取目标
   - zone_targets                → target_map {zone: area_ha}
   - density_hints               → zone → density
   - adjacency_rules             → prefer/avoid lists

3. 从 PARSE constraint_set 提取语义约束
   - SpatialConstraint[]         → 硬变量排除 (x[i][construction] = 0)

4. MIP 求解 (PuLP CBC)
   - 变量: x[i][zone] ∈ {0,1}
   - 硬约束: 保护地块锁定、三线边界、VNE 容量、PARSE 语义排除
   - 软约束: 面积目标偏差最小化 (slack)、KG 约束 (slack)
   - 目标: minimize Σ|actual - target| + slack_cost + preference_cost
```

**为什么不需要 ConstraintCompiler**：

- MIP 求解器直接消费 SPARQL 返回的 flat dict 列表，通过字符串匹配（`"construction" in cid`、
  `"farmland" in cid`）识别约束类型
- 3 种 KG 约束（construction cap / farmland min / ecological min）全部作为软约束
  （slack 变量），不产生不可行解
- 3 种硬约束（三线 / VNE / PARSE 语义）各自有独立的处理函数，不需要统一编译层
- 当前 4 种数据源（KG SPARQL / intent / constraint_set / three_line）各自格式不同，
  统一编译层的收益不足以覆盖其复杂度

### 5.4 意图落地路径（回答 Q6）

**图斑级操作是主路径**（v4.7）。具体项目落地与小规模变更使用约束满足策略：

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

### 5.5 验证闭环

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
│   │   ├── ontology.py             # 本体定义
│   │   ├── memory.py               # [v4.6] SemanticMemoryStore
│   │   ├── builder/                # 四层构建器子包
│   │   │   ├── base.py             # PlanningKG: build_from_bundle
│   │   │   ├── layer1.py           # L1 现状实体
│   │   │   ├── layer2.py           # L2 空间关系
│   │   │   ├── layer3.py           # L3 意图虚拟实体
│   │   │   ├── layer4.py           # L4 规划成果
│   │   │   └── mixins.py           # [v4.6] Mixin 类
│   │   └── queries/
│   │       ├── __init__.py
│   │       ├── sparql.py           # SPARQL 模板注册表 + 实例方法 (merged)
│   │       └── semantic.py         # LLM 友好语义查询
│   │
│   └── spatial_ops/                # 空间计算工具
│       ├── __init__.py
│       ├── relations.py            # 空间关系计算
│       ├── geometry.py             # 几何操作
│       ├── context.py              # ContextBlock 计算 (compute_context_blocks)
│       ├── grounding.py            # [v4.7] PARSE 空间接地
│       ├── constraint_compiler.py  # [v5.0] 约束编译
│       ├── parcel_ops.py           # [v5.0] 地块原子操作
│       ├── road_planner.py         # [v5.0] 规划道路网络
│       └── land_balance.py         # [v5.0] 用地平衡表
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
2. Data Layer: 加载 VillageBundle（GeoPackage + 远程 API）+ 基数转换（DLBM -> 规划用途编码）
3. Spatial Ops: 计算 ParcelRelations（三层空间关系）+ ContextBlock（PARSE 记忆）
4. KG Builder: 从 bundle 形态分组 + ParcelRelations 构建 KG Layer 1-2
5. PARSE: 文本 + ContextBlock（agent 记忆）+ KG 工具 → SpatialPlanningIntent
6. KG: PARSE 意图写入 Layer 3（虚拟实体 + 粗糙几何 + 空间关系）
7. EXECUTE: SPARQL 直查 KG + intent 对象 → MIP 约束矩阵
8. MIP 求解: 一次性 SPARQL 结果 → PuLP 模型
9. PlanBlock: EXECUTE 单次增量变更（agent 记忆）
10. PlannedState: PlanBlock 累积 → 写入 KG Layer 4
11. KG: 清除 Layer 3 临时实体
12. Export: 图层 → GeoPackage / GeoJSON
13. Render: 图层 → 前端可视化
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
| 2.1 | ~~Constraint Compiler~~ | 已废弃（v4.6）——MIP 直接消费 SPARQL 结果，不设编译层                          |
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

## 第七部分：成果合规与协同（v4.7 新增）

本部分补齐"非空间但必需"的成果环节与协同机制，均为汇交/审批的硬要求。
背景与依据见 `reference/HUMAN_PLANNING_WORKFLOW.md` §1/§3/§7/§13。

### 7.1 汇交坐标系与面积基准

系统内部统一 WGS84（见 §1.3），但汇交要求不同，须在 export 层做出口转换：

| 项       | 内部              | 汇交要求                            | 出口转换             |
| -------- | ----------------- | ----------------------------------- | -------------------- |
| 坐标系   | WGS84 (EPSG:4326) | CGCS2000，三度分带高斯投影          | export 层统一重投影  |
| 高程基准 | —                | 1985 国家高程基准                   | 栅格/高程数据标注    |
| 面积     | 平面近似          | TBMJ 椭球面积                       | 导出前按椭球面积重算 |
| 容差     | —                | Tolerance 0.001 / Resolution 0.0001 | .mdb 建库参数        |

**红线**：GCJ-02 及其纠偏产物（即使偏移 <5m）不得进入汇交链路；商业底图瓦片
（天地图/高德）仅用于可视化，不参与几何运算与成果导出。

### 7.2 管制规则生成闭环

"一规则"是基本成果三件套之一。闭环三层：

```
规则提取（PARSE）          规则编码（Schema）            规则验证（validate）
文本+上位规划+地方规定  ->  ControlRule 结构化（6大类）  ->  与图斑/分区 overlay 校验
```

- 量化值来源：地方规定（如宅基地面积上限、层数≤3/总高≤10m）+ 案例基准 + 村民协商；
  系统只提供模板与候选值，**最终量化值由人确认**
- 双形态输出：村规民约语体（村民可理解）+ 结构化编码（机器可验证）
- 每条规则可追溯：规则 ↔ 上位依据条款 ↔ 受控图斑集合

### 7.3 村民参与（输入与输出）

法定程序要求村民会议或村民代表会议 **2/3 以上**同意，成果必含"村民参与报告"附件
（参照金田村规划文本附件 1-5：前期征询/方案征询/批前公示/村民代表大会/镇政府意见）。

- **输入侧**：村民意愿数据（宅基地需求、搬迁意愿、产业诉求、意见征询表）作为
  `bundle.tables` / `bundle.documents` 的一等数据源，PARSE 纳入意图提取
- **输出侧**："村民版成果"——总图简化版 + 项目表通俗版 + 管制规则村规民约版
- **过程侧**：意见征询 -> 方案修改记录进入 changelog，支撑"村民参与报告"生成

### 7.4 编制模式分支

2024-2025 政策转向后须支持三种模式（详见 HUMAN_PLANNING_WORKFLOW §7）：

| 模式       | 成果                                        | 系统行为                                  |
| ---------- | ------------------------------------------- | ----------------------------------------- |
| 完整编制   | 一图一表一规则 + 数据库汇交                 | 全流程（当前默认）                        |
| 通则式管理 | 一图一表（底线管控图+管控要求表）+ 附加图层 | 裁剪输出：仅底线层+负面清单，跳过详细布局 |
| 不编制     | —                                          | 仅现状分析报告                            |

### 7.5 上位指标分解

上位批复指标为**镇级总量**（如泗水镇耕地保有量 5.33 km²），到村需要指标分解。
分解本质是与乡镇政府的协商过程，不是算术均摊。系统职责边界：

- 提供分解建议（按现状占比/适宜性加权）+ 敏感性分析
- `SpatialPlanningIntent` 指标字段标注来源：`上位传导（镇级分解，需人工确认）` vs `本级确定`
- 未经人工确认的分解值不得作为 MIP 硬约束

---

## 附录 A：术语表

| 术语                | 全称                                                    | 说明                                 |
| ------------------- | ------------------------------------------------------- | ------------------------------------ |
| PARSE               | Plan Agent for Report Spatial Extraction                | 规划文本 → 空间意图                 |
| EXECUTE             | Execution Agent                                         | 空间意图 → 空间几何成果             |
| KG                  | Knowledge Graph                                         | 语义桥接层                           |
| MIP                 | Mixed Integer Programming                               | 混合整数规划（批量分区优化）         |
| GDB                 | GeoDatabase                                             | 空间数据库格式                       |
| DLBM                | 地类编码                                                | 土地利用分类编码                     |
| GHYTBM              | 规划用途编码                                            | 附录5编码                            |
| BSM                 | 标识码                                                  | 地块唯一标识                         |
| VNE                 | V=村庄建设用地, N=非村庄建设用地, E=非建设用地          | 住建部三分类                         |
| 三区三线            | 生态/农业/建设空间 + 生态红线/永久基本农田/城镇开发边界 | 全国国土空间规划                     |
| 一图一表一规则      | 村庄规划总图 + 近期建设项目表 + 管制规则                | 广东省基本成果                       |
| SpatialContext      | 空间上下文                                              | 约2KB的空间摘要，注入PARSE prompt    |
| Constraint Compiler | 约束编译器（已废弃 v4.6）                               | MIP 直接消费 SPARQL 结果，不设编译层 |

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
