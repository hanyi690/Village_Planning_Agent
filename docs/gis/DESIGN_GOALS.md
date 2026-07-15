





# GIS 村庄规划系统 — 设计目标

> 版本: 3.2 | 日期: 2026-07-15 | 混合架构：确定性骨架 + ReAct 自适应循环

## 1. 问题定义

传统村庄规划编制依赖人工在 ArcGIS/QGIS 中逐层叠加分析：

- **图数分离**：规划图与指标表各自维护，边界修改后需手动重新量算面积
- **冲突滞后**：建设用地是否侵占基本农田，需人工多次叠加比对，容易遗漏
- **规则依赖经验**：规划条款以自然语言存在于报告中，执行正确性取决于规划师个人理解

以金田村为例：660 个地块 × 12 个维度报告 × 6 类规划分区 × 3 重约束（建设用地 ≤21.66ha / 农田 ≥98.54ha / 生态保护红线 ≥367.68ha），人工核查一遍约需 4-6 小时，且无法保证无遗漏。

目标：**输入规划报告文本 + GIS 现状数据 → 自动输出符合 GB/T 21010 和 DB22/T 3407-2022 标准的 12 层规划成果包**。

## 2. 目标输出

参考金田村 GDB 实测数据（`docs/金田村村庄规划工程文件.zip`）和国家标准：

```
output/{village_name}/
├── current/                              # 现状 5 层
│   ├── boundary.geojson                  # 行政区划面 (MultiPolygon, 6字段)
│   ├── admin_line.geojson                # 行政区划界线 (MultiLineString, 5字段)
│   ├── landuse.geojson                   # 现状地类图斑 DLBM编码 (MultiPolygon, 9字段)
│   ├── road.geojson                      # 现状道路 (MultiLineString)
│   └── annotation.geojson                # 现状注记 (Point, 注记+分类)
├── planned/                              # 规划 7 层
│   ├── landuse.geojson                   # 规划地类图斑 GHYTBM+GHFLBM双编码 (16字段)
│   ├── farmland_protection.geojson       # 永久基本农田红线 (MultiPolygon)
│   ├── ecological_protection.geojson     # 生态保护红线 (MultiPolygon)
│   ├── historical_protection.geojson     # 历史文化保护线 (MultiPolygon)
│   ├── construction_zone.geojson         # 有条件建设区 (MultiPolygon)
│   ├── hazard_points.geojson             # 地质灾害点 (Point)
│   ├── road.geojson                      # 规划道路 (MultiLineString)
│   └── annotation.geojson                # 规划注记 (Point)
├── tables/
│   └── land_balance.json                 # 用地平衡表 (JSON, 后续→Excel)
└── layout.json                           # 布局配置
```

**字段标准**参照 `backend/app/services/modules/gis/data/gdb_schema.py` 中的 `GDB_LAYER_REGISTRY`（12 层完整字段定义）。

## 3. 架构设计

### 3.1 Trinity 三层模型

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: PLANNING KG (规划知识图谱)                             │
│  将规划报告文本 + GIS 地块属性 → RDF 三元组                      │
│  提供 SPARQL 查询接口，让 LLM 动态获取约束值                      │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: AGENTIC PIPELINE (智能体流水线)                        │
│  PARSE Agent (1 tool) → LAYOUT Agent (11 tools)                  │
│  LLM ReAct 决策，通过 state 注入通信                              │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: SPATIAL GENERATOR (空间生成器)                         │
│  MIP 优化 + CA 细化 → 程序化几何生成                              │
│  硬约束保证（保护地块变量锁定）+ 软约束松弛（面积偏差最小化）       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Agent 子图设计：PARSE ReAct + LAYOUT 混合管线

#### 设计思路来源

传统做法将 LAYOUT Agent 设计为纯 ReAct（LLM 决定每步调用顺序），存在两个问题：

1. **步骤完整性无法保证**：LLM 可能跳步（如跳过 KG 直接分配）或遗漏（如忘记 EXPORT/RENDER）
2. **约束反馈无强制机制**：validate_layout 失败后，LLM 可能不重试而是直接返回

但纯确定性 StateGraph 又丧失了 LLM 自适应能力——智能规划的核心价值恰在于 LLM 能根据约束反馈动态调整分配策略。

参考 LangGraph 官方推荐的 **Plan-and-Execute** 模式 [1] 和 **Worker-Evaluator** 重试循环 [2]，以及智能规划领域实践：

| 参考                                       | 模式                                                                    | 启示                                         |
| ------------------------------------------ | ----------------------------------------------------------------------- | -------------------------------------------- |
| **LangGraph Plan-and-Execute** [1]   | Planner 生成全局计划 → Executor 逐步执行 → Re-planner 评估是否调整    | 确定性骨架保证完整性，LLM 在规划环节提供智能 |
| **Worker-Evaluator Loop** [2]        | Worker 执行 → Evaluator 检查达标 → 不达标则反馈重试                   | 验证必须是强制 gate，不能依赖 LLM "记得"重试 |
| **City-LEO** [3]                     | LLM 生成 MIP 约束 → MIP 确定性求解 → E2E 优化                         | LLM 做约束提取，确定性算法做优化，各司其职   |
| **Participatory Urban Planning** [4] | Planner 提议 → Residents 反馈 → Planner 修订 → 迭代                  | 反馈循环是规划质量的关键，不是可选项         |
| **PlanGEN** [5]                      | ConstraintAgent → SolutionAgent → VerificationAgent → SelectionAgent | 约束提取→方案生成→验证→选择，四阶段流水线 |
| **Intelli-Planner** [6]              | LLM 增强策略网络 + DRL PPO 优化                                         | LLM 提供领域知识先验，优化器做精确搜索       |

**结论**：智能规划 = **确定性骨架**（保证步骤完整性和硬约束） + **ReAct 自适应循环**（LLM 根据约束反馈调整策略）。不是二选一，而是混合。

#### 混合架构设计

```
                    ┌─────────────────────┐
   reports ────────►│    PARSE Agent      │     ← ReAct (文本理解需要 LLM 创造性)
   gis_data         │  1 tool:            │
                    │  parse_planning_text │
                    └──────┬──────────────┘
                           │ intent_json (state 注入)
                           ▼
    ┌────────────── LAYOUT 混合管线 (StateGraph) ──────────────┐
    │                                                          │
    │  ┌─────────┐   ┌──────────┐   ┌──────────────────────┐  │
    │  │build_kg │──►│conflicts │──►│allocate_and_generate │  │  ← ReAct 子图
    │  │(确定节点)│   │(确定节点)│   │  LLM 自适应决策：     │  │     (LLM 决定策略)
    │  └─────────┘   └──────────┘   │  - 查询 KG 约束      │  │
    │                                │  - 调整分配参数      │  │
    │                                │  - 选择布局策略      │  │
    │                                └──────────┬───────────┘  │
    │                                           │              │
    │                                           ▼              │
    │                                ┌──────────────────┐      │
    │                                │ validate_layout  │      │  ← Evaluator Gate
    │                                │ (确定节点 + 条件路由)│  │     (强制验证)
    │                                └──┬───────────┬───┘      │
    │                     通过(→export) │           │ 失败(→retry, 最多3轮)
    │                                   │           │ 反馈注入 messages
    │                                   │           └──────┐
    │                                   │                  │
    │                                   ▼                  │
    │  ┌──────────┐   ┌───────────┐                     │
    │  │export_gdb│──►│render_map │                     │
    │  │(确定节点)│   │(确定节点) │                     │
    │  └──────────┘   └─────┬─────┘                     │
    │                        │                           │
    └────────────────────────┼───────────────────────────┘
                             ▼
                      12-layer output
```

**关键设计**：

| 组件                          | 模式           | 理由                                               |
| ----------------------------- | -------------- | -------------------------------------------------- |
| **KG / CONFLICT**       | 确定性节点     | 步骤顺序不可变，KG 必须在 ALLOCATE 之前            |
| **ALLOCATE + GENERATE** | ReAct 子图     | LLM 需根据约束反馈自适应调整分配策略和布局参数     |
| **VALIDATE**            | Evaluator Gate | 验证必须是强制 gate，失败则带反馈重试（最多 3 轮） |
| **EXPORT / RENDER**     | 确定性节点     | 后处理步骤顺序不可变                               |

#### 设计理由（更新）

| 决策                                          | 理由                                                                                                                                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **为什么混合架构？**                    | 纯 ReAct 无法保证步骤完整性（LLM 可能跳步/遗漏）；纯 StateGraph 丧失 LLM 自适应能力（无法根据约束反馈调整策略）。混合架构兼得两者优势：确定性骨架保证完整流程，ReAct 子图保留智能决策 |
| **为什么 ALLOCATE+GENERATE 用 ReAct？** | 分配和布局是规划核心环节，各村约束差异大。LLM 需要查询 KG 约束、判断冲突优先级、调整面积比例——这些决策依赖上下文推理，不是固定规则能覆盖的                                          |
| **为什么 VALIDATE 是 Evaluator Gate？** | 参考Worker-Evaluator模式 [2]：验证通过/失败不能由 LLM "决定是否重试"，而必须是系统强制行为。验证失败时反馈注入 messages，LLM 在重试轮看到具体违规信息                                 |
| **为什么保留双 Agent？**                | 文本理解（温度 0.2，需要创造性提取意图）与空间推理（温度 0，确定性操作）的可靠性要求不同。Intent schema 变更时 LAYOUT 零影响                                                          |
| **通信协议**                            | 通过 LangGraph TypedDict state 注入：`ParseAgentState.intent_json → LayoutPipelineState.intent`，类型安全、可追踪                                                                  |
| **fallback**                            | 保留`create_gis_agent_graph()` 单一 Agent（全部 13 工具），用于简单场景和测试                                                                                                       |

#### 参考文献

│
     │ 智能规划领域参考：                                                                         │
     │ - City-LEO (2024)：LLM 生成 MIP 优化模型 + E2E 框架，LLM 做约束提取，MIP 做确定性优化      │
     │ - Intelli-Planner (AAAI 2026)：LLM 增强策略网络 + DRL 优化，LLM 提供领域知识先验           │
     │ - Participatory Urban Planning (清华)：Planner 提出→Residents 讨论→Planner                 │
     │ 修订，反馈迭代循环                                                                         │
     │ - PlanGEN (Google)：ConstraintAgent→SolutionAgent→VerificationAgent→SelectionAgent         │
     │ 四阶段，验证驱动迭代                                                                       │
     │ - GenPlanner (PyPI)：MILP + relation_matrix + Voronoi，纯确定性分区引擎

1. LangGraph Blog: "Planning Agents" — Plan-and-Execute, ReWOO, LLMCompiler 三种规划架构对比. https://www.langchain.com/blog/planning-agents (2024)
2. Dev.to: "Building a worker-evaluator retry loop in LangGraph" — Worker 执行 + Evaluator 评估 + 反馈重试模式. https://dev.to/akashpersetti/ (2026)
3. City-LEO: "Toward Transparent City Management Using LLM with End-to-End Optimization" — LLM 生成 MIP 约束 + RF 目标函数 E2E 优化. arXiv:2406.10958 (2024)
4. Participatory Urban Planning: "LLM for Participatory Urban Planning" — Planner→Residents讨论→Planner修订反馈迭代. arXiv:2402.17161 (2024)
5. PlanGEN: "Generative Planning with Large Language Models" — ConstraintAgent→SolutionAgent→VerificationAgent→SelectionAgent 四阶段. Google Research (2025)
6. Intelli-Planner: "Towards Customized Urban Planning via LLM Empowered Reinforcement Learning" — LLM 增强策略网络 + PPO 优化. AAAI 2026

### 3.3 代码位置

```
app/agent/gis/           # Agent 编排层 (4 文件)
  agent.py               # create_parse/layout/gis_agent_graph()
  layout_pipeline.py     # ★ LAYOUT 混合管线 (StateGraph: 确定性骨架 + ReAct 子图 + Evaluator Gate)
  state.py               # ParseAgentState / LayoutAgentState / LayoutPipelineState / GISAgentState
  prompts.py             # PARSE / LAYOUT / GIS system prompts

app/tools/gis/           # @tool 层 (11 文件, 13 工具)
  parse.py               # parse_planning_text
  kg.py                  # build/query_knowledge_graph
  conflict.py            # detect_conflicts
  allocate.py            # allocate_zones (MIP + greedy)
  generate.py            # generate_layout (CA + facility + axis)
  validate.py            # validate_layout (8 checks)
  export.py              # export_gdb (12层 + 用地平衡表)
  render.py              # render_map (MapLibre 图层)
  data.py                # fetch_gis_data + search_poi
  analytics.py           # calculate_gis_coverage + analyze_accessibility

app/services/modules/gis/ # 纯服务层 (无 @tool)
  zone_schema/           # 编码体系
    schema.py            # ★ 统一分类 Schema — 全部 DLBM 定义的单一真相源
    encodings.py         # 编码映射（从 schema 派生）
    code_sets.py         # 编码集合（从 schema 派生）
    colors.py            # GB/T 21010 国标色卡
  layout/                # 布局生成
    data_loader.py       # 数据加载 + intent 解析（委派到 tool 层）
    intent_cache.py      # 解析因子感知缓存（PARSE_VERSION + LLM_MODEL + 内容hash）
    metrics_calculator.py # GIS 实测面积约束计算
    compare_layouts.py   # 三路对比引擎
    zone_generator.py    # 功能分区生成
    facility_placer.py   # 设施布点（4 策略）
    axis_builder.py      # 发展轴生成（一核一带三区）
    map_renderer.py      # 地图渲染配置
  providers/             # 天地图/高德/OSM
  data/                  # 数据获取 + GDB schema
  analysis/              # 空间分析
  kg/                    # RDF 知识图谱
  conflict/              # 冲突检测-消解
  optimizer/             # MIP + CA 优化器
  validation/            # 布局验证
  utils/                 # 坐标/面积/GeoJSON 工具
```

**已清理的死代码**（Phase 1）：

| 文件                                | 状态   | 原因                                          |
| ----------------------------------- | ------ | --------------------------------------------- |
| `service.py` (GisService)         | 已删除 | 零生产调用，功能与 fetcher.py 重复            |
| `engine.py` (SpatialLayoutEngine) | 已删除 | 只跑 4/8 步，被 layout_pipeline.py 完全取代   |
| `optimizer/procedural.py` 导出    | 已移除 | 4 个函数零生产调用，函数体保留待 Phase 4 集成 |
| `providers/amap/traffic.py` 导出  | 已移除 | TrafficService 从未实例化                     |

## 4. 编码体系

三套正交编码，统一定义在 `zone_schema/schema.py`（**单一真相源**；`encodings.py` 和 `code_sets.py` 均从中自动派生）：

| 体系                    | 来源                      | 用途                        | 示例                              |
| ----------------------- | ------------------------- | --------------------------- | --------------------------------- |
| **DLBM / GHYTBM** | 三调工作分类 (GB/T 21010) | 现状/规划地类 → 8 功能分区 | `2121`=宅基地 → `居住用地`   |
| **YDYHFLDM**      | 自然资发〔2023〕234 号    | 基数转换上报                | `2121` → `0702` (农村宅基地) |
| **V/N/E**         | 住建部村庄规划用地分类    | 前端统计口径                | `2121` → `V11` (住宅用地)    |

两套分区体系（互不混用，均从 schema 派生）：

| 分区体系                     | 类别数 | 来源                     | 使用者                             |
| ---------------------------- | ------ | ------------------------ | ---------------------------------- |
| **功能分区 (Layer 1)** | 8 类   | DLBM →`zone_type`     | function_zone 图层 + LLM intent    |
| **规划分区 (Layer 2)** | 6 类   | DLBM →`planning_zone` | MIP allocator + planning_zone 图层 |
| **三区 (Layer 3)**     | 3 类   | DLBM →`primary_zone`  | 三区三线对照                       |

6 类规划分区详情（广东省扩展，含林业发展区）：

| 规划分区             | 归属三区 | 颜色        | 来源                              |
| -------------------- | -------- | ----------- | --------------------------------- |
| 生态保护区           | 生态空间 | `#2E8B57` | GB/T 21010 林地 + 水域            |
| 生态控制区           | 生态空间 | `#90EE90` | 草地（非红线生态空间）            |
| 农田保护区           | 农业空间 | `#FFE4B5` | 永久基本农田                      |
| 一般农业区           | 农业空间 | `#98FB98` | 耕地 + 园地 + 设施农用地          |
| **林业发展区** | 农业空间 | `#3CB371` | 广东省特色分区（商品林 + 生态林） |
| 村庄建设区           | 建设空间 | `#FF6347` | 商服/工矿/住宅/公服/交通          |

关键分类决策（GB/T 21010 合规）：

| DLBM     | 名称   | 功能分区           | 规划分区   | GB/T 21010 依据                |
| -------- | ------ | ------------------ | ---------- | ------------------------------ |
| `1340` | 商品林 | **农业用地** | 林业发展区 | 三大类对照表：全部林地→农用地 |
| `1350` | 生态林 | 生态绿地           | 林业发展区 | 生态功能：水源涵养、生物多样性 |

编码覆盖：金田村实测 660 地块 100% 可映射。新增/修改分类只需改 `schema.py` 一处，LLM prompt 自动注入结构化分类表格。

## 5. 工具流水线

```
PARSE ──► KG ──► CONFLICT ──► ALLOCATE ──► GENERATE ──► VALIDATE ──► EXPORT ──► RENDER
```

双路径架构（设计文档 P1-C 实现）：

```
规划 markdown (人工规划文本) ──→ gen intent ──→ KG→CONFLICT→ALLOCATE→GENERATE ──→ gen layers
L3 reports (系统L3报告)        ──→ plan intent ──→ KG→CONFLICT→ALLOCATE→GENERATE ──→ plan layers
planned/ (人工绘制GIS图纸)      ───────────────────────────────────────────────────────→ ground truth

三路对比:
  gen layers  vs planned/  = 「AI 解读人工规划文本」 vs 「人工绘制图纸」
  plan layers vs planned/  = 「AI 基于 L3 报告」   vs 「人工绘制图纸」
  gen layers  vs plan layers = 「人工文本路径」    vs 「L3 报告路径」
```

| # | 步骤               | 功能                                                                                                                                                                              | 设计理由                                             | 外部参考                                                   |
| - | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------- |
| 1 | **PARSE**    | LLM 解析规划文本 →`UnifiedSpatialIntent`。Gen 路径：人工规划 markdown；Plan 路径：12 维度 L3 reports。LLM prompt 注入 `SCHEMA.to_prompt_table()` 结构化分类表 + GIS 实测约束 | 自然语言约束提取，结构化 taxonomy 注入比文本补丁准确 | EMNLP 2025 HTC: 结构化的 per-parent prompting 优于扁平列表 |
| 2 | **KG**       | 构建 RDF 图谱 (660 parcels × ~10 triples = 8462 triples) + GIS 实测约束三元组 + SPARQL 查询                                                                                      | 结构化约束后 LLM 可动态查询                          | OntoPlanningRegulations (2025) KG 模式                     |
| 3 | **CONFLICT** | 跨维度指标冲突检测（metric/constraint/spatial 三类）                                                                                                                              | 13 维度独立规划必然出现冲突，需在分配前统一          | 专利 CN202511326944                                        |
| 4 | **ALLOCATE** | MIP 分配 **6 规划分区** + 硬约束锁定保护地块。**targets 必须使用规划分区名**（非功能分区名），通过 `map_zone_type_to_planning_zone` 映射。 | MILP 保证全局最优解（村级 <1000 地块 30s 内）        | GenPlanner (PyPI) 的 MILP + relation_matrix                |
| 5 | **GENERATE** | 5 内部生成层（对齐 OUTPUT_ARCHITECTURE.md）：① ParcelReclass (16字段重分类) → ② SpaceControl (4类管制) → ③ UseZone (V/N/E) → ④ FacilityPlan (8类设施) → ⑤ RoadPlan (规划道路) | 分层解耦，每层输入输出明确                          | GenPlanner 的 Voronoi 细化                                 |
| 6 | **VALIDATE** | 8 项空间检查 + 合规验证（最多 3 轮）                                                                                                                                              | 独立验证确保输出质量                                 | BlocksNet                                                  |
| 7 | **EXPORT**   | 标准 **14 层** GeoJSON + 用地平衡表（对齐广东汇交标准）                                                                                                                            | 与 GDB 标准和 ArcGIS 入库规范对齐                    | bxgis 的 Arcpy GDB                                         |
| 8 | **RENDER**   | Python/matplotlib + MapLibre 前端图层（GB/T 21010 配色，从 PLANNING_ZONE_COLORS 导入，不重复定义）                                                                                | 数据驱动渲染，三路并排对比图 PNG                     | —                                                         |

## 6. 技术决策记录

| 决策               | 选择                                                  | 不选                               | 理由                                                                                                                                                                                                                                                                |
| ------------------ | ----------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **优化算法** | MIP (PuLP)                                            | DRL / GA / 模拟退火                | 村级 <1000 地块，MIP 30s 内最优解，无需启发式                                                                                                                                                                                                                       |
| **知识表示** | RDF / SPARQL                                          | SQL / JSON Schema / Prolog         | RDF 无 schema 变更即可添加约束类型；SPARQL 可被 LLM 生成                                                                                                                                                                                                            |
| **编排**     | 混合架构：确定性骨架 + ReAct 子图                     | 纯 ReAct / 纯 StateGraph / Airflow | 纯 ReAct 无法保证步骤完整性（LLM 可能跳步）；纯 StateGraph 丧失 LLM 自适应能力。混合架构：确定性边保证 KG→CONFLICT→VALIDATE 顺序，ReAct 子图在 ALLOCATE+GENERATE 提供 LLM 策略决策，Evaluator Gate 强制验证重试。参考 [1] Plan-and-Execute + [2] Worker-Evaluator |
| **约束力度** | 硬约束（保护地块 MIP 变量锁定）+ 软约束（面积 slack） | 全软约束                           | 生态红线/基本农田是法律红线，不可违反                                                                                                                                                                                                                               |
| **空间细化** | CA (Cellular Automata)                                | Voronoi / GAN                      | CA 简单可解释，GAN 需要大量训练样本且输出不可控                                                                                                                                                                                                                     |
| **坐标系**   | WGS-84 (内部) + GCJ-02 (高德) + CGCS2000 (天地图)     | 单一坐标系                         | 三个数据源使用不同坐标系，坐标转换为已知算法                                                                                                                                                                                                                        |
| **地图渲染** | MapLibre GL JS                                        | Leaflet / OpenLayers               | 国产化兼容（不含 Google 服务）、矢量瓦片性能、GL JSON 样式规范                                                                                                                                                                                                      |

## 7. 外部可行性验证

| 功能维度         | 本项目实现       | GenPlanner (PyPI) | BlocksNet (40★) | DRL-urban-planning (清华,Nature) | 专利 CN202511326944 | bxgis           |
| ---------------- | ---------------- | ----------------- | ---------------- | -------------------------------- | ------------------- | --------------- |
| MILP 分区分配    | ✅               | ✅                | ❌ (模拟退火)    | ❌ (DRL)                         | ❌                  | ❌              |
| 邻接约束矩阵     | ✅ (zone_schema) | ✅                | ❌               | ❌                               | ❌                  | ❌              |
| 规则引擎冲突检测 | ✅ (conflict.py) | ❌                | ❌               | ❌                               | ✅                  | ✅              |
| 用地平衡表       | ⚠️ (JSON)      | ❌                | ✅               | ❌                               | ✅                  | ✅ (Excel)      |
| 可达性分析       | ✅               | ❌                | ✅               | ❌                               | ❌                  | ❌              |
| 道路网络生成     | ❌               | ✅                | ❌               | ✅                               | ❌                  | ❌              |
| 知识图谱         | ✅ (RDF)         | ❌                | ❌               | ❌                               | ❌                  | ❌              |
| GDB 标准输出     | ⚠️ (GeoJSON)   | ❌                | ❌               | ❌                               | ❌                  | ✅ (Arcpy .gdb) |
| 12 层完整输出    | ⚠️ (7/14)      | ❌                | ❌               | ❌                               | ❌                  | ✅              |
| DRL 优化         | ❌ (Phase 3)     | ❌                | ❌               | ✅                               | ❌                  | ❌              |

**结论**：我们以 MIP + KG + Conflict 三个独特组合覆盖了现有开源方案的盲区。GenPlanner 最接近但缺 KG 和冲突检测；DRL-urban-planning 专注土地利用但缺规划约束和标准输出。

## 8. 路线图

### Phase 1 — 当前 (2026-07) ✅ 已完成

- [X] Trinity 架构 + 双 Agent
- [X] 13 个 @tool 流水线
- [X] MIP 分配 + 硬约束保护地块锁定（6 规划分区）
- [X] 8 项空间验证
- [X] 统一分类 Schema（`zone_schema/schema.py`，83 条 DLBM 定义）
- [X] 双路径 pipeline（gen/plan）+ 三路对比
- [X] GIS 约束注入 LLM prompt（GB/T 21010 三大类合规）
- [X] Intent 缓存（解析因子感知：PARSE_VERSION + LLM_MODEL + 内容hash）
- [X] 死代码清理：删除 GisService、SpatialLayoutEngine，移除 procedural/traffic 未用导出
- [X] Canonical Data Model（Pydantic BaseModel，WGS84 归一化）
- [X] Provider 适配层（Tianditu/Amap/OSM，CRS 归一化）
- [X] EncodingRegistry（从 schema.py 自动派生编码映射）
- [X] OutputProfile 省份可扩展机制（广东 14 层 + 约束常量）
- [X] 空间管制区生成器 SpaceControlZoneGenerator (510/520/530/540)
- [X] 土地用途分区生成器 LandUseZoneGenerator (V/N/E)
- [X] 颜色集中化（zone_schema/colors.py，6 套色卡）

### Phase 2 — 架构对齐（2026-07，进行中）

**目标**：对齐 OUTPUT_ARCHITECTURE.md 的 5 内部生成层 + 14 层输出标准

#### 已知缺陷（P0 — 必须修复）

- [ ] **MIP allocator 编码体系断裂**：targets 使用功能分区名（农业用地），但 `_get_preference_cost` 用规划分区名（农田保护区），零重叠导致 gen/plan 分配结果完全一致。修复：添加 `map_zone_type_to_planning_zone` 映射。
- [ ] **ParcelReclass 输出缺少 16 字段**：ZoneGenerator 只输出简单 zone_type/color，缺少 QMDLBM/GHFLBM/GHYTBM/GHYTMC。修复：升级 ZoneGenerator 为 ParcelReclassGenerator。
- [ ] **planning_zone (6类) 与 UseZone (V/N/E) 并存**：架构要求 planning_zone 被 UseZone 替代。修复：删除 `_make_planning_zone_layer`，6 类分区信息保留在 ParcelReclass 的 `assigned_zone` 字段中。
- [ ] **RoadPlan 层缺失**：架构要求 ⑤ RoadPlan → 13_planned_road，当前无对应生成器。

#### 混合架构重构

- [ ] 新建 `layout_pipeline.py`：混合 StateGraph（确定性骨架 + ReAct 子图 + Evaluator Gate）
- [ ] 新增 `LayoutPipelineState`（含 `validation_round` 计数器）
- [ ] 确定性节点：build_kg → detect_conflicts → validate_layout → export_gdb → render_map
- [ ] ReAct 子图：allocate_and_generate 节点（LLM 自适应决策分配策略和布局参数）
- [ ] Evaluator Gate：validate_layout 条件路由（通过→export，失败→带反馈重试，最多 3 轮）
- [ ] 修改 `gis_agent_node`：Step 2 改用 `build_layout_pipeline()`
- [ ] 保留 `create_layout_agent_graph()` 作为 ReAct 子图被 pipeline 调用
- [ ] 测试统一通过 layout_pipeline 执行（覆盖完整 8 步，无手动拼接）

#### 5 内部生成层对齐

```
当前 6 层                          →  架构 5 层
─────────────────────────────────────────────────
function_zone (ZoneGenerator)     →  ① ParcelReclass (16字段)
planning_zone (6类规划分区)       →  ❌ 删除（信息保留在 ① assigned_zone 字段）
space_control_zone                →  ② SpaceControl (已有)
land_use_zone                     →  ③ UseZone (V/N/E, 已有)
facility_point                    →  ④ FacilityPlan (已有)
infrastructure (AxisBuilder)      →  可视化叠加（不独立成层）
(无)                              →  ⑤ RoadPlan (待实现)
```

- [ ] 创建 `ParcelReclassGenerator`：每地块输出 16 字段（BSM/YSDM/DLBM/DLMJ/QMDLBM/GHFLBM/GHYTBM/GHYTMC/...）
- [ ] 删除 `_make_planning_zone_layer`，前端从 ParcelReclass 的 `assigned_zone` 字段提取 6 类分区显示
- [ ] MIP allocator：`solve()` 开头添加功能分区→规划分区映射
- [ ] gis_test_routes.py 管线：targets 映射到规划分区
- [ ] 实现 RoadPlan 生成器（或简化为现状道路 + 新增连接段）
- [ ] E2E 测试：验证 gen/plan 差异性 + 16 字段完整性

### Phase 3 — 功能增强

- [ ] 测试覆盖补全：plan 路径 LLM E2E 测试、三路对比集成测试
- [ ] export: 用地平衡表 Excel 输出、标准字段补全
- [ ] allocate: Voronoi 细化参考 GenPlanner
- [ ] 集成 procedural 工具：merge_parcels → zone_generator, simplify_boundary → map_renderer
- [ ] CA 精化模块恢复（当前缺失 `app.services.modules.gis.layout.optimizer`）
- [ ] PuLP → COIN_CMD 迁移
- [ ] GHFLBM ↔ V/N/E 完整映射表（从 planned/landuse 实测数据反推 + 规范校验）

### Phase 4 — 探索方向

- [ ] DRL 土地优化（参考清华 DRL-urban-planning）
- [ ] GAN 村庄布局生成
- [ ] 实时协同编辑 + 移动端预览
