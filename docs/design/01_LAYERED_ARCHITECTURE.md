# 分层架构与模块边界

> **目标：让目录结构、依赖方向和业务职责一致。** 目录名不是边界；契约和依赖规则才是边界。

## 1. 目标分层

```text
API / UI adapters
        ↓
Application workflow subgraphs
        ↓
Planning domain services
        ↓
Spatial query / KG services
        ↓
Data repositories and adapters
        ↓
Schema contracts and encodings
```

## 2. 各层职责

### 2.1 Schema contracts

位置：`backend/app/modules/schema/`

只定义类型、枚举、编码、规则描述和 provenance。典型契约包括：

- `PlanningContext`
- `L1Snapshot`
- `L2Strategy`
- `L3PlanningIntent`
- `SpatialReferenceSpec`
- `GroundingResult`
- `PlacementDecision`
- `ExecutionPlan`
- `ValidationReport`
- `DeliveryGate`

Schema 不读取数据库、文件、KG 或 LLM。

### 2.2 Data repositories

位置：`backend/app/modules/data/` 与会话存储适配器。

负责数据摄取、类型化、缓存、版本和外部数据源。`DataCatalog` 只生产 `VillageBundle` 或其版本化引用；外部锚点不得在每次业务读取时隐式重新抓取。

### 2.3 Spatial query services

位置：`backend/app/modules/spatial_ops/`。

负责几何、空间索引、候选集精化、距离、拓扑和约束计算。它不解析自然语言，也不决定规划策略。

### 2.4 KG semantic services

位置：`backend/app/modules/kg/`。

负责实体、语义关系、来源和可查询的空间认知。KG 不替代完整几何引擎；需要多边形精确计算时，通过 Spatial Query Service 组合完成。

### 2.5 Planning domain services

目标位置：`backend/app/modules/planning/`（迁移期间可由现有 `agent/gis`、`spatial_ops` 和 `tools/gis/_generation` 分批承接）。

包含：

- `intent_compiler`：报告/规划文本 → 类型化意图
- `grounding_service`：空间引用 → 候选及证据
- `selection_service`：候选 → 选址决定
- `execution_service`：决定 → 规划图层
- `reconciliation_service`：意图与成果对账

这些服务必须是可独立测试的纯领域入口，不能依赖 LangGraph State。

### 2.6 Application workflow subgraphs

位置：`backend/app/agent/`。

只负责节点编排、并行调度、Gate、重试和人工中断。它不应该直接拼接 GeoJSON、加载 Gazetteer、选择 BSM 或实现道路算法。

### 2.7 Adapters

位置：`backend/app/api/`、`backend/app/services/`、`backend/app/tools/`。

适配数据库、LLM、外部地图、SSE 和文件输出。适配器可以调用领域服务，但不能反向把领域服务绑定到某个 Agent State。

## 3. 允许与禁止的依赖

| 来源 | 可依赖 | 禁止依赖 |
|---|---|---|
| Schema | 标准库、Pydantic | Data、KG、Agent、Service、API |
| Data | Schema、外部 Provider | Agent、LangGraph |
| Spatial Query | Schema、Data read port | Agent、LLM、API |
| KG | Schema、Spatial Query port | Agent State、API |
| Planning domain | Schema、KG port、Spatial port | LangGraph、SSE、ReportStore 实现 |
| Workflow | Planning domain、ports、adapters | 直接实现领域算法 |
| Tools | ports、外部 SDK | 反向导入 Agent 作为业务依赖 |

## 4. 单一上下文原则

所有子图接收同一个版本化的 `PlanningContext`：

```text
PlanningContext
├── session_id
├── village_bundle_ref + version
├── kg_snapshot_ref + version
├── report_snapshot_ref
├── evidence_bundle_ref
├── planning_artifacts
├── provenance
└── active_gate
```

子图之间传递 artifact 引用和版本，不复制完整 GIS 数据、报告文本和 KG 缓存。

## 5. 迁移规则

1. 先建立 contracts 和 ports，再移动实现。
2. 同一能力只保留一个正式入口；旧入口只能转发并标记 `[DEPRECATED]`。
3. 新增 import 边界检查，禁止出现 `modules → agent/services/api`。
4. 每迁移一个子图，保留输入/输出快照测试。
5. 目录重命名晚于职责切分，避免“换目录但耦合不变”。
