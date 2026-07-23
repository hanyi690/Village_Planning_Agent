# GIS 村庄规划系统 — 设计目标

> **Status: [CURRENT]** | **Type: Design Specification** | **Version: 5.3** | **Updated: 2026-07-23**
> **Scope**: 权威设计规范 — Trinity架构、编码体系、技术决策
> **References**: BIBLIOGRAPHY.md §A1-4, §B1-2,5-7, §F1-11
> **Related**: 02_OUTPUT_ARCHITECTURE.md, design-log/01_DECISION_LOG.md
>
> **本文档为设计目标/思路文档**。具体的代码实现可能与设计有差异。各节标注了实现状态: ✅已实现 / ⚠️部分实现 / ❌未实现(设计阶段)。
> 输出架构的权威参考见 `02_OUTPUT_ARCHITECTURE.md`。

## 1. 问题定义

传统村庄规划编制依赖人工在 ArcGIS/QGIS 中逐层叠加分析：

- **图数分离**：规划图与指标表各自维护，边界修改后需手动重新量算面积
- **冲突滞后**：建设用地是否侵占基本农田，需人工多次叠加比对，容易遗漏
- **规则依赖经验**：规划条款以自然语言存在于报告中，执行正确性取决于规划师个人理解
- **文本无法落地**：管制规则、建设项目表、村民决议等规划文本停留在文档层面，无法直接转化为空间数据

以金田村为例：660 个地块 × 12 个维度报告 × 6 类规划分区 × 3 重约束（建设用地 ≤21.66ha / 农田 ≥98.54ha / 生态保护红线 ≥367.68ha），人工核查一遍约需 4-6 小时，且无法保证无遗漏。

**目标**：输入规划报告文本 + GIS 现状数据 → 自动输出符合 GB/T 21010 和 DB22/T 3407-2022 标准的 14 层规划成果包。所有规划文本（管制规则/建设项目表/村民决议/规划报告）统一解析为 OperationSequence + ConstraintSet，通过 EXECUTE_OPERATIONS 逐条执行，实现文本到空间数据的闭环落地。

## 2. 目标输出

参考金田村 GDB 实测数据（`docs/金田村村庄规划工程文件.zip`）和国家标准：

```
output/{village_name}/
├── 01_boundary.geojson                   # 行政区划面 (MultiPolygon, 5字段)
├── 02_admin_boundary_line.geojson        # 行政区划界线 (MultiLineString)
├── 03_current_landuse.geojson            # 现状地类图斑 DLBM编码 (MultiPolygon)
├── 04_current_road.geojson               # 现状道路 (MultiLineString)
├── 05_current_annotation.geojson         # 现状注记 (Point)
├── 06_planned_landuse.geojson            # 期末地类图斑 QMDLTB (20+字段) ★
├── 07_farmland_protection.geojson        # 永久基本农田红线 (MultiPolygon)
├── 08_ecological_protection.geojson      # 生态保护红线 (MultiPolygon)
├── 09_historical_protection.geojson      # 历史文化保护线 (MultiPolygon)
├── 10_space_control_zone.geojson         # 建设用地管制区 JSYDGZQ (9字段) ★
├── 11_land_use_zone.geojson              # 土地用途分区 TDYT (9字段) ★
├── 12_geological_hazard_points.geojson   # 地质灾害点 (Point)
├── 13_planned_road.geojson               # 规划道路 (MultiLineString)
├── 14_planned_annotation.geojson         # 规划注记 (Point)
├── tables/
│   ├── planning_targets.json             # 规划目标表（附表1）
│   ├── land_balance.json                 # 用地平衡表
│   └── land_use_structure.json           # 土地利用结构调整表（附表2）
├── changelog.jsonl                       # 操作变更日志 ★
└── layout.json                           # 布局配置
```

**字段标准**参照 `backend/app/modules/gis/schema/gdb.py` 中的 `GDB_LAYER_REGISTRY`（12 层完整字段定义），编码值域参照 `schema/dicts/*.yaml`（DictionaryCenter 单一真相源）。

## 3. 架构设计

### 3.1 Trinity 三层模型

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 1: PLANNING KG (规划知识图谱)                             │
│  将规划报告文本 + GIS 地块属性 → RDF 三元组                      │
│  提供 SPARQL 查询接口，让 LLM 动态获取约束值                      │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: AGENTIC PIPELINE (智能体流水线)                        │
│  PARSE Agent (3 tools, 半结构化 ReAct) → LAYOUT Pipeline (8 nodes)│
│  文本领域：classify → route → extract → validate                  │
│  空间领域：确定性骨架 + execute_operations ReAct 子图              │
│  通过 state 注入通信（PARSE 输出 → LAYOUT 输入）                  │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: SPATIAL GENERATOR (空间生成器)                         │
│  MIP 优化 + CA 细化 → 程序化几何生成                              │
│  硬约束保证（保护地块变量锁定）+ 软约束松弛（面积偏差最小化）       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 统一生产路径

```
规划文本（报告/规则/决议/建设项目表）+ SpatialContext（统计+空间关系）
    ↓                                                         ⚠️ 部分实现
PARSE Agent (半结构化 ReAct)                                   ✅ parse/agent.py 已实现
  ├── classify_sections: 文档结构分类
  ├── route_by_section: 按段落类型路由提取策略
  │   ├── extract_regulations → ConstraintSet
  │   ├── extract_tables → 结构化 JSON
  │   ├── extract_projects → OperationSequence
  │   └── extract_targets → IntentJSON
  └── validate_and_merge: 校验一致性 + 合并
    ↓
OperationSequence(空间锚定) + ConstraintSet(可计算规则) + IntentJSON(空间偏好)
    ↓                                                         ❌ 以下未实现
┌─ ConstraintSet → KG（约束三元组 + 合规规则）
│
└─ OperationSequence → EXECUTE_OPERATIONS
     ├── 空间定位（地名解析 → 候选图斑）
     ├── 用途查表（DictionaryCenter → 编码）
     ├── 合规预检（KG约束 + 冲突检测）
     ├── 人工确认（确认卡片 / 批量确认）
     └── 执行 + 变更日志
    ↓
CONFLICT（跨维度冲突检测）
    ↓
EXECUTE_OPERATIONS（逐条执行操作序列）
    ├── 批量场景 → 按需调用 optimize_allocation (MIP)
    └── 逐条场景 → 直接执行
    ↓
VALIDATE（8 项空间检查 + 合规验证，最多 3 轮）
    ↓
EXPORT（12 层 GeoJSON + 2 表 + 变更日志）
    ↓
RENDER（MapLibre 前端可视化）
```

**操作序列 vs 约束集**：

| 规划文本类型                               | 解析输出                             | 操作规模 | 确认方式      |
| ------------------------------------------ | ------------------------------------ | -------- | ------------- |
| 规划报告（"农田保护区≥98.54ha"）          | OperationSequence（批量 reclassify） | 660 地块 | 批量确认+抽查 |
| 建设项目表（"新建400㎡展销中心"）          | OperationSequence（create/split）    | 1-5 地块 | 逐条确认卡片  |
| 管制规则（"允许建设区内不得安排基本农田"） | ConstraintSet（约束注入）            | 规则级   | 自动生效      |
| 村民决议（"同意搬迁学校"）                 | OperationSequence（modify+create）   | 中等     | 逐条确认      |

**对比测试模式**（非生产路径，仅用于效果验证）：

- gen 模式: 人工规划 markdown → intent → 全管线 → gen layers
- plan 模式: L3 reports → intent → 全管线 → plan layers
- ground truth: planned/ 人工GIS图纸
- 三路对比: gen vs ground, plan vs ground, gen vs plan

### 3.3 Agent 子图设计：混合架构

```
                     ┌─────────────────────────────┐
   reports ─────────►│       PARSE Agent           │  ← 半结构化 ReAct
   spatial_ctx       │  3 tools:                   │     (classify → route → extract → validate)
                     │  parse_planning_text         │
                     │  extract_structured_text     │
                     │  lookup_land_use_code        │
                     │  + classify/validate (LLM节点)│
                     └──────┬──────────────────────┘
                            │ OperationSequence(空间锚定) + ConstraintSet(可计算规则) + intent_json(空间偏好)
                            │ (state 注入，Pydantic 严格 Schema)
                           ▼
    ┌────────────── LAYOUT 混合管线 (StateGraph) ──────────────┐
    │                                                          │
    │  ┌─────────┐   ┌──────────┐   ┌──────────────────────┐  │
    │  │build_kg │──►│conflicts │──►│execute_operations  │  │  ← ReAct 子图
    │  │(确定节点)│   │(确定节点)│   │  LLM 自适应决策：     │  │
    │  └─────────┘   └──────────┘   │  - 查询 KG 约束      │  │
    │                                │  - 调整操作策略            │  │
    │                                │  - 按需调用 MIP            │  │
    │                                └──────────┬───────────┘  │
    │                                           │              │
    │                                           ▼              │
    │                                ┌──────────────────┐      │
    │                                │ validate_layout  │      │  ← Evaluator Gate
    │                                │ (确定节点 + 条件路由)│  │
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
                      14-layer output + changelog
```

**关键设计**：

| 组件                         | 模式           | 理由                                                                       |
| ---------------------------- | -------------- | -------------------------------------------------------------------------- |
| **PARSE Agent**        | 半结构化 ReAct | 文本领域需多步提取/校验，确定性骨架保证步骤完整性，LLM 节点处理异构文档    |
| **KG / CONFLICT**      | 确定性节点     | 步骤顺序不可变，KG 必须在 EXECUTE 之前                                     |
| **EXECUTE_OPERATIONS** | ReAct 子图     | LLM 需根据约束反馈自适应调整操作策略，批量场景按需调用 optimize_allocation |
| **VALIDATE**           | Evaluator Gate | 验证必须是强制 gate，失败则带反馈重试（最多 3 轮）                         |
| **EXPORT / RENDER**    | 确定性节点     | 后处理步骤顺序不可变                                                       |

### 3.4 操作执行引擎设计 ❌ 未实现 (设计阶段)

> **实现状态**: 设计阶段，代码未实现。本节描述的是规划目标，非当前实现状态。

Agent 是**会操作 GIS 的专业绘图员**，不是规划师。所有规划文本统一解析为 OperationSequence + ConstraintSet，通过 EXECUTE_OPERATIONS 逐条执行。操作遵循 **"意图提取 → 方案生成 → 人工确认 → 执行落地"** 的闭环。

**5 种原子操作（统一指令集）**：

| 操作           | 输入               | 输出               | 场景       |
| -------------- | ------------------ | ------------------ | ---------- |
| `create`     | 面积+用途+位置描述 | 新BSM + 属性赋值   | 新增图斑   |
| `split`      | 源BSM+面积比例     | 2+新BSM + 面积守恒 | 分割图斑   |
| `merge`      | 源BSM列表          | 1新BSM             | 合并图斑   |
| `modify`     | 源BSM+字段变更     | 属性更新           | 属性修改   |
| `reclassify` | 源BSM+新QMDLBM     | 编码+属性更新      | 地类重分类 |

**5 步闭环流程**：

```
① 结构化提取
   输入: "同意在刘村小组东侧、晒谷场北边空地，新建400㎡农产品展销中心，用途为经营性建设用地"
   输出: OperationSequence([{action: "create", location_desc: "刘村小组东侧、晒谷场北边", area: 400, land_use_name: "经营性建设用地"}])

② 空间定位 → 候选图斑
   ① 地名解析 → 找到"刘村小组"点位 → 向东偏移
   ② 在搜索区寻找"晒谷场"图斑 → 分析其北侧相邻地块
   ③ 找到空闲地图斑 XG-005（面积≥400㎡）→ 作为操作对象
   ④ 若多个候选 → 生成列表要求规划师点击确认

③ 方案生成与合规预检
   ① 用途字典 → "经营性建设用地" = GHYTBM 2124（从 encodings/appendix5.yaml 查表）
   ② 冲突检测 → 检查图斑是否在建设边界内 ✅，不占基本农田 ✅，不在生态红线内 ✅
   ③ 生成操作预览方案：分割 XG-005 → 新图斑 400㎡ + QMDLBM=2124

④ 人工确认界面
   呈现确认卡片：
   > 拟执行操作：
   > - 在刘村小组东侧、晒谷场北侧空地，新增一块 400㎡ 的经营性建设用地
   > - 图斑编号：待定，将从现状空闲地图斑 XG-005 中分割
   > - 合规检查：✅位于村庄建设边界内 ✅不涉及三线 ✅现状为空闲地无需转用
   > 是否确认执行？

⑤ 执行与留痕
   确认后执行图斑分割 + 属性赋值，记录变更日志（操作人/时间/来源文本/前后快照）
```

**批量 vs 逐条执行**：

- **批量场景**（整村 660 reclassify）：执行引擎检测到大规模操作 → 按需调用 `optimize_allocation` (MIP) 辅助工具 → 批量确认+抽查
- **逐条场景**（1-5 操作）：直接执行 → 逐条确认卡片

**不确定性处理**：若文本未指定规划用途（如"闲置地利用"），Agent 提供候选项列表（如：可转为宅基地/停车场/绿地），由规划师选取，**绝不自动赋值**。

### 3.5 执行粒度：批量操作 vs 逐条操作

"整村生成"和"增量编辑"不是两种模式，而是**同一操作引擎的不同执行粒度**：

| 执行粒度           | 场景              | 操作规模                   | MIP 调用                        | 确认方式      |
| ------------------ | ----------------- | -------------------------- | ------------------------------- | ------------- |
| **批量操作** | 首次编制/全面修编 | 660 地块 reclassify        | 按需调用`optimize_allocation` | 批量确认+抽查 |
| **逐条操作** | 日常调整/单项落地 | 1-5 个 create/split/modify | 不调用 MIP                      | 逐条确认卡片  |

两种粒度共享同一套 5 种原子操作、编码体系（DictionaryCenter）和合规检查（conflict/detector）。区别仅在于：

- 批量操作时，执行引擎自动检测操作规模，按需调用 MIP 辅助工具优化分配
- 逐条操作时，直接执行，不经过 MIP

### 3.6 设计理由

| 决策                                           | 理由                                                                                                                    |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **为什么统一路径？**                     | gen/plan 双路径仅用于对比测试，生产环境只需一条路径。所有规划文本统一解析为操作序列，减少维护成本，避免路径间行为不一致 |
| **为什么混合架构？**                     | 纯 ReAct 无法保证步骤完整性；纯 StateGraph 丧失 LLM 自适应能力。混合架构兼得两者优势                                    |
| **为什么 EXECUTE_OPERATIONS 用 ReAct？** | 操作执行是规划核心环节，各村约束差异大，LLM 需要查询 KG、判断冲突优先级、决定是否调用 MIP                               |
| **为什么 VALIDATE 是 Evaluator Gate？**  | 验证通过/失败不能由 LLM "决定是否重试"，必须是系统强制行为                                                              |
| **为什么操作需要人工确认？**             | GIS 数据修改不可逆，任何操作必须经规划师确认后执行。这是人机协同的底线                                                  |
| **为什么 MIP 降级为辅助工具？**          | MIP 仅在批量操作场景下有用（整村 660 reclassify），逐条操作不需要 MIP。作为辅助工具按需调用，比独立管道步骤更灵活       |
| **为什么编码不做自动映射？**             | 现状→规划用途的映射存在多对多歧义，自动映射会引入规划师未授权的决策。只做字典查找 + 候选项建议                         |
| **为什么分区不来自地类？**             | 规划分区不能由现状地类单一决定——同一 DLBM 的图斑可能因空间位置不同归属不同分区（如 1350 生态林在红线内→生态保护区，红线外→林业发展区）。所有分区计算必须经过 `DynamicZoningEngine` 规则引擎，DLBM 仅为输入之一，绝非输出。无规则匹配时返回低置信度兜底并标记 `needs_decision=True` |

#### 参考文献

1. LangGraph Blog: "Planning Agents" — Plan-and-Execute, ReWOO, LLMCompiler 三种规划架构对比. https://www.langchain.com/blog/planning-agents (2024)
2. Dev.to: "Building a worker-evaluator retry loop in LangGraph" — Worker 执行 + Evaluator 评估 + 反馈重试模式. https://dev.to/akashpersetti/ (2026)
3. City-LEO: "Toward Transparent City Management Using LLM with End-to-End Optimization" — LLM 生成 MIP 约束 + RF 目标函数 E2E 优化. arXiv:2406.10958 (2024)
4. Participatory Urban Planning: "LLM for Participatory Urban Planning" — Planner→Residents讨论→Planner修订反馈迭代. arXiv:2402.17161 (2024)
5. PlanGEN: "Generative Planning with Large Language Models" — ConstraintAgent→SolutionAgent→VerificationAgent→SelectionAgent 四阶段. Google Research (2025)
6. Intelli-Planner: "Towards Customized Urban Planning via LLM Empowered Reinforcement Learning" — LLM 增强策略网络 + PPO 优化. AAAI 2026
7. JackDaw (PoliRural+): "Bridging Global Language Models and Local Spatial Data" — 工具预过滤 + RAG + 值工程模型编排. (2026)
8. Spatial Text-to-SQL: "From questions to queries: an AI-powered multi-agent framework for spatial Text-to-SQL" — 多Agent分阶段解释+审查. Taylor & Francis (2026)
9. Municipal GIS Compliance Framework — versioned rule catalog + per-parcel compliance state machine + immutable audit record. 规则版本化（catalog_version + effective_from），每次判定记录 rule_snapshot，规则变更只需数据更新+重新评估. https://www.municipalgis.org/municipal-zoning-data-architecture-compliance-frameworks/ (2026) **[未执行]**
10. DLSZM (Dual-Logic Spatial Zoning Model) — 规则引擎 + ML 双路径对比，识别"稳定决策区"和"分歧敏感区". Frontiers in Environmental Science 2026. https://www.frontiersin.org/journals/environmental-science/articles/10.3389/fenvs.2026.1791582/full **[未执行]**
11. OZFS (Open Zoning Feed Specification) — overlay district 概念（restrict/relax/replace），条件约束（Python 表达式）. https://github.com/vibe-lab-gsd/ozfs-standard **[未执行]**

### 3.7 代码位置 (当前实际结构, v5.3)

> ✅ **Tool-First 架构已实施** (Phase A/B/C, 2026-07-22~23)。详见 `proposals/03_TOOL_FIRST_ARCHITECTURE.md`。
> modules/gis/ 精简为 schema + data + spatial_context；generation/analysis/rendering 迁入 tools/gis/ 作为内部模块（`_` 前缀）；
> KG 独立为 modules/kg/；utils 提升至 app/utils/；tool 层统一 make_result() Schema 约束。

```
app/agent/gis/              # Agent 编排层
├── agent.py                # create_*_graph() 入口 (GIS_PIPELINE_TOOLS + GIS_DATA_TOOLS)
├── state.py                # GISPipelineState (Pydantic BaseModel)
├── prompts.py              # GIS Agent system prompt
├── layout_pipeline.py      # ★ LAYOUT 管线 (StateGraph) [⚠️部分实现]
├── parse/                  # ★ PARSE 子包 [✅已实现]
│   ├── __init__.py
│   ├── state.py             # ParseAgentState + SpatialOperation + SpatialConstraint
│   └── agent.py             # PARSE Agent 子图 (ReAct + Think-Then-Format)
└── execute/                # ★ EXECUTE_OPS Agent 子包 (Phase 2.5 预留)
    └── __init__.py

app/modules/gis/            # ★ GIS 模块 — 精简为 schema + data + context
├── spatial_context.py      # compute_spatial_context() — GIS → SpatialContext 转换
├── trace.py                # MIPTrace
├── schema/                 # ✅ 单一真相源 (如下)
└── data/                   # ✅ 数据获取/加载/providers

app/modules/kg/             # ★ 独立 KG 模块 (Phase A2)
├── builder.py              # PlanningKG 构建器
├── query.py                # SPARQL 查询模板 + query_kg()
└── ontology.py             # PLN, GEO, EntityTypes, Relations

app/utils/                  # ★ 通用工具 (Phase A3)
├── coord_transform.py      # GCJ-02 ↔ WGS-84 ↔ CGCS2000
├── crs_engine.py           # 投影引擎
├── area_engine.py          # 面积计算
├── geojson_utils.py        # GeoJSON ↔ GeoDataFrame
├── geo_utils.py            # Haversine, safe union
└── coord_utils.py          # 坐标工具

app/tools/helpers.py        # ★ make_result() / to_tool_message() (Phase A1)

app/tools/gis/              # ★ 管线 tools (11) + 内部实现模块 (5)
├── __init__.py              # GIS_PIPELINE_TOOLS
├── parse.py                 # parse_planning_text @tool (PARSE Agent 入口)
├── extract.py               # extract_structured_text @tool
├── lookup.py                # lookup_land_use_code @tool
├── kg.py                    # build/query_knowledge_graph @tool
├── conflict.py              # detect_conflicts @tool (→ ._conflict)
├── allocate.py              # allocate_zones @tool (→ ._generation.optimizer)
├── generate.py              # generate_layout @tool (→ ._generation)
├── validate.py              # validate_layout @tool (→ ._validation)
├── export.py                # export_gdb @tool
├── render.py                # render_map @tool (→ ._rendering)
├── _conflict/               # ← analysis/conflict/
├── _validation/             # ← analysis/validation/
├── _analytics/              # ← analysis/ 其余 + dynamic_zoning
├── _generation/             # ← generation/ (zone/facility/axis/optimizer/pipeline)
└── _rendering/              # ← rendering/

app/tools/gis_data/          # ★ 数据获取 tools (4, make_result 统一约束)
├── fetch.py                 # fetch_gis_data
├── search_poi.py            # search_poi
└── analytics.py             # calculate_gis_coverage + analyze_accessibility

app/tools/gis_execute/       # ★ Phase 2.5 预留
app/tools/gis_query/         # ★ Phase 2.5 预留
```

## 4. 编码体系 ✅ 已实现

六套独立编码，统一定义在 `schema/dicts/encodings/*.yaml`（**DictionaryCenter 单一真相源**；`schema/code_sets.py` 从中自动派生运行时字典）：

| 体系 | 来源 | 用途 | 文件 |
|------|------|------|------|
| **gbt21010** | GB/T 21010-2017 | 三调输入 (现状地类) | `encodings/gbt21010.yaml` |
| **tugui** | 粤国土资规保发〔2009〕67号 | QMDLTB.DLBM/QMDLBM | `encodings/tugui.yaml` |
| **appendix5** | 广东省技术指南(2019) 附录5 | QMDLTB.GHYTBM | `encodings/appendix5.yaml` |
| **ghflbm** | 广东省土规数据库标准 | QMDLTB.GHFLBM | `encodings/ghflbm.yaml` |
| **ydyhfldm** | 自然资发〔2023〕234号 | 基数转换目标 (新标准方向) | `encodings/ydyhfldm.yaml` |
| **vne** | 住建部村庄规划用地分类指南 | 统计口径 (从appendix5派生) | `encodings/vne.yaml` |

**DLBM 默认分区倾向**（仅供参考，非最终分区）：

DLBM 编码在 `encodings/gbt21010.yaml`、`encodings/tugui.yaml`、`encodings/appendix5.yaml` 中携带 `zone_type`、`planning_zone`、`primary_zone` 等属性，仅为无其他空间约束时的初步参考。**最终分区由 `DynamicZoningEngine` 根据 `rules/planning_zone_rules.yaml` 结合三线、建设边界、灾害因子等动态计算**，规则引擎未覆盖或存在冲突时标记 `needs_decision=True`，由人工确认。

6 类规划分区详情（广东省扩展，含林业发展区）——**分区归属由规则引擎判定，下表仅为 DLBM 默认倾向**：

| 规划分区             | 默认倾向来源           | 归属三区 | 规则引擎判定依据                                           |
| -------------------- | ---------------------- | -------- | ---------------------------------------------------------- |
| 生态保护区           | 生态红线重叠           | 生态空间 | 规则1：图斑与生态红线重叠                                  |
| 生态控制区           | 草地/非红线生态空间    | 生态空间 | 规则3：地质灾害缓冲区，或规则引擎降级                      |
| 农田保护区           | 基本农田重叠           | 农业空间 | 规则2：图斑与永久基本农田重叠                              |
| 一般农业区           | 耕地+园地+设施农用地   | 农业空间 | 默认倾向（DLBM 0101/0201/0202/0203），规则引擎兜底        |
| **林业发展区** | 商品林/生态林(1340/1350) | 农业空间 | DLBM 1340→农业空间(GB/T 21010)，1350→生态功能倾向，规则引擎判定最终分区 |
| 村庄建设区           | 商服/工矿/住宅/公服/交通 | 建设空间 | 默认倾向（DLBM 21xx），但需通过建设边界约束检查            |

**关键分类决策**（GB/T 21010 合规）：

| DLBM     | 名称   | 默认功能分区倾向   | 规则引擎备注                               |
| -------- | ------ | ------------------ | ------------------------------------------ |
| `1340` | 商品林 | 农业用地           | 三大类对照表：全部林地→农用地，规则引擎通常保留 |
| `1350` | 生态林 | 生态绿地（倾向）   | 生态功能强：水源涵养、生物多样性，规则引擎可能升级为生态保护区 |

编码覆盖：金田村实测 660 地块 100% 可映射。新增/修改分类只需改 `dicts/encodings/*.yaml`，无需改代码。

### 候选项建议引擎

系统内**不存在"映射"概念**，只有"候选项建议"：

- `resolve_mapping` → `propose_classification_candidates`：输出是"建议"，不是"结果"
- `MappingResult` → `ClassificationProposal`：返回候选项列表，由规划师选取
- Agent 禁止在文本无明确用途时自动调用 `propose()`，只在用户主动问"这块地能做什么"时才返回候选项

三种置信度：

- `exact`：一一对应，`needs_human_decision=False`
- `conditional`：一对多 + context 匹配，可缩小范围
- `ambiguous`：无明确候选，`needs_human_decision=True`

## 5. 工具流水线

> ✅ 所有 tool 已统一 make_result() Schema 约束（Phase C3）。parse.py/parse_tools.py 已拆分为 parse/extract/lookup（Phase C2）。_helpers.py 已提升为 tools/helpers.py（Phase A1）。data.py/analytics.py 已迁入 tools/gis_data/（Phase C3）。gis_execute/、gis_query/ 空壳已创建（Phase C4）。

```
PARSE ──► KG ──► CONFLICT ──► EXECUTE_OPERATIONS ──► VALIDATE ──► EXPORT ──► RENDER
```

| # | 步骤                         | 功能                                                                                                                                                                                                                           | 设计理由                                                                   |
| - | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| 1 | **PARSE**              | 半结构化 ReAct：classify → route → extract → validate →`OperationSequence(空间锚定)` + `ConstraintSet(可计算规则)` + `IntentJSON(空间偏好)`。SpatialContext 注入（统计+空间锚点+邻接关系+约束概要，~2KB），`DictionaryCenter.to_prompt_table()` 编码参考表注入 | 文本领域需多步提取/校验，SpatialContext 提供空间语义防止 LLM 盲写位置描述，编码参考表保证标准名称 |
| 2 | **KG**                 | 构建 RDF 图谱 (660 parcels × ~10 triples = 8462 triples) + GIS 实测约束三元组 + SPARQL 查询                                                                                                                                   | 结构化约束后 LLM 可动态查询                                                |
| 3 | **CONFLICT**           | 跨维度指标冲突检测（metric/constraint/spatial 三类）                                                                                                                                                                           | 13 维度独立规划必然出现冲突，需在执行前统一                                |
| 4 | **EXECUTE_OPERATIONS** | 逐条执行操作序列（5 种原子操作），批量场景按需调用`optimize_allocation` 辅助工具                                                                                                                                             | 统一指令集，批量/逐条共享同一执行逻辑                                      |
| 5 | **VALIDATE**           | 8 项空间检查 + 合规验证（最多 3 轮）                                                                                                                                                                                           | 独立验证确保输出质量                                                       |
| 6 | **EXPORT**             | 标准**14 层** GeoJSON + 2 表 + 变更日志（对齐广东汇交标准）                                                                                                                                                              | 与 GDB 标准和 ArcGIS 入库规范对齐                                          |
| 7 | **RENDER**             | Python/matplotlib + MapLibre 前端图层（GB/T 21010 配色）                                                                                                                                                                       | 数据驱动渲染                                                               |

### 5.5 操作工具集（5 个专业工具 + 1 个辅助工具）

| 工具                        | 功能                                                | 复用                           | 说明                                         |
| --------------------------- | --------------------------------------------------- | ------------------------------ | -------------------------------------------- |
| `resolve_place_name`      | 空间地名解析：自然语言描述 → 候选图斑列表          | Amap POI + OSM + 本地别名库    | 模糊匹配 + 空间关系推理（东侧/沿河/北侧）    |
| `lookup_land_use_code`    | 规划用途字典：用途名称 → 标准编码 + 约束规则       | DictionaryCenter (encodings/appendix5.yaml) | 不做自动映射，返回候选项                     |
| `check_compliance`        | 冲突检测：拟操作图斑 → 实时合规检查                | conflict/detector.py           | 三区三线/建设边界/现状地类                   |
| `edit_parcel`             | GIS 编辑：执行 create/split/merge/modify/reclassify | Shapely + GeoPandas            | 原子操作 + 变更日志                          |
| `extract_structured_text` | 表格结构提取：表格类文本 → 结构化 JSON             | LLM                            | 近期建设项目表/用地指标表                    |
| `optimize_allocation`     | **辅助工具**：MIP 分配 6 规划分区             | MIP allocator (PuLP)           | 仅批量场景由执行引擎按需调用，非独立管道步骤 |

## 6. 技术决策记录

| 决策                   | 选择                                                                            | 不选                       | 理由                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------- |
| **优化算法**     | MIP (PuLP)                                                                      | DRL / GA / 模拟退火        | 村级 <1000 地块，MIP 30s 内最优解                                                                  |
| **知识表示**     | RDF / SPARQL                                                                    | SQL / JSON Schema / Prolog | RDF 无 schema 变更即可添加约束类型                                                                 |
| **编排**         | 混合架构：确定性骨架 + ReAct 子图                                               | 纯 ReAct / 纯 StateGraph   | 纯 ReAct 无法保证步骤完整性；纯 StateGraph 丧失 LLM 自适应能力                                     |
| **约束力度**     | 硬约束（保护地块 MIP 变量锁定）+ 软约束（面积 slack）                           | 全软约束                   | 生态红线/基本农田是法律红线，不可违反                                                              |
| **空间细化**     | CA (Cellular Automata)                                                          | Voronoi / GAN              | CA 简单可解释，GAN 需要大量训练样本且输出不可控                                                    |
| **坐标系**       | WGS-84 (内部) + GCJ-02 (高德) + CGCS2000 (天地图)                               | 单一坐标系                 | 三个数据源使用不同坐标系，坐标转换为已知算法                                                       |
| **地图渲染**     | MapLibre GL JS                                                                  | Leaflet / OpenLayers       | 国产化兼容、矢量瓦片性能、GL JSON 样式规范                                                         |
| **MIP 定位**     | 辅助工具（按需调用）                                                            | 独立管道步骤               | MIP 仅批量场景有用，逐条操作不需要；作为辅助工具更灵活                                             |
| **操作确认**     | 人工确认卡片                                                                    | 自动执行                   | GIS 数据修改不可逆，必须经规划师确认                                                               |
| **PARSE 架构**   | 半结构化 ReAct（确定性骨架 + LLM 节点内可调用 tool）                            | 纯 ReAct / 纯 StateGraph   | 纯 ReAct 无法保证步骤完整性（LLM 可能跳过校验）；纯 StateGraph 无法处理异构文档（需 LLM 判断路由） |
| **PARSE 工具数** | 3 tools（parse_planning_text + extract_structured_text + lookup_land_use_code） | 1 tool                     | 规划文本不是一次 LLM 能解析完的——需要多步提取（表格→JSON、名称→编码、多次校验）                |
| **PARSE 输出**   | Pydantic 严格模型（OperationItem + ConstraintItem + PlanningIntent）            | 自由格式 Dict              | 严格 Schema 保证 PARSE → LAYOUT 边界可靠性                                                        |
| **GIS 数据注入** | PARSE 阶段注入 SpatialContext（统计信息 + 空间关系摘要，~2KB，不含原始几何） | 统计信息，不含几何 | 统计信息无法支撑空间推理（LLM 不知"刘村小组"在村庄哪个方位）；空间关系摘要（锚点/邻接/方向）可在 ~2KB 内提供空间语义，不含原始几何数据 |
| **PARSE 空间输出** | OperationItem 携带 SpatialAnchor（空间锚定），ConstraintItem 携带 SpatialRule（可计算空间规则） | 自由文本 location_desc / rule | SpatialAnchor 预判候选图斑但不执行（遵守"Agent 是绘图员"原则）；SpatialRule 可直接映射 Shapely 操作，避免 KG 重复编码自由文本 |

> **⚡ 已知争议**: `proposals/01_PARSE_SPATIAL_ENHANCEMENT.md` 认为当前 SpatialContext 的"统计信息+空间关系"粒度仍不足以支撑 LLM 的空间心智模型，主张进一步升级为 SpatialContext(含225条parcel级空间关系+15个自然村锚点)。详见 `design-log/01_DECISION_LOG.md §Decision-001`。争议的教材依据：李巍等《实用性村庄规划编制手册》(BIBLIOGRAPHY §A3) — GIS实验操作纳入村庄规划流程需要空间认知；高宜程《实用性村庄规划：理论与实践》(BIBLIOGRAPHY §A4) — 村庄形态设计需要空间关系认知。

## 7. 外部可行性验证

| 功能维度         | 本项目实现        | GenPlanner | BlocksNet | DRL-urban-planning | JackDaw (PoliRural+) | GISDataAgent      |
| ---------------- | ----------------- | ---------- | --------- | ------------------ | -------------------- | ----------------- |
| MILP 分区分配    | ✅                | ✅         | ❌        | ❌                 | ❌                   | ❌                |
| 邻接约束矩阵     | ✅                | ✅         | ❌        | ❌                 | ❌                   | ❌                |
| 规则引擎冲突检测 | ✅                | ❌         | ❌        | ❌                 | ❌                   | ❌                |
| 知识图谱         | ✅ (RDF)          | ❌         | ❌        | ❌                 | ❌                   | ✅ (networkx)     |
| Text-to-GIS 操作 | ★ (统一操作引擎) | ❌         | ❌        | ❌                 | ✅ (RAG+工具)        | ✅ (NL2SQL)       |
| 人机协同确认     | ★ (设计)         | ❌         | ❌        | ❌                 | ❌                   | ✅ (HITLApproval) |
| GDB 标准输出     | ⚠️ (GeoJSON)    | ❌         | ❌        | ❌                 | ❌                   | ❌                |
| 14 层完整输出    | ⚠️ (7/14)       | ❌         | ❌        | ❌                 | ❌                   | ❌                |

**结论**：我们以 MIP + KG + Conflict 三个独特组合覆盖了现有开源方案的盲区。统一操作执行引擎（5 种原子操作 + MIP 辅助工具）参考 JackDaw 的工具预过滤和 GISDataAgent 的 HITLApproval 人机审批模式，但面向村庄规划场景做了专门设计——所有规划文本统一解析为操作序列，批量/逐条共享同一执行逻辑。

## 8. 路线图

### Phase 0 — 架构重构 ✅ 已完成 (2026-07-22~23, commits 415dbf5/2006d30/c8a76d4)

> ✅ Tool-First 架构已建立。Phase 2/2.5 的实现基础已就绪。

- [x] Tool-First 架构迁移（详见 `proposals/03_TOOL_FIRST_ARCHITECTURE.md`）
  - [x] KG 独立：`modules/gis/kg/` → `modules/kg/` (Phase A2)
  - [x] Utils 通用化：`modules/gis/utils/` → `app/utils/` (Phase A3)
  - [x] generation/analysis/rendering 迁入 `tools/gis/_*` 作为 tool 内部模块 (Phase B)
  - [x] Tool 层统一 Schema 约束（禁止裸 json.dumps，统一 make_result()）(Phase C3)
  - [x] 预留 `tools/gis_execute/`、`tools/gis_query/`、`agent/gis/execute/` 空壳 (Phase C4)
- [x] 设计文档同步（§3.7 代码位置更新，§5 实现差距消除）

### Phase 1 — 已完成 (2026-07) ✅

- [X] 六套编码体系分离 (encodings/gbt21010, tugui, appendix5, ghflbm, ydyhfldm, vne)
- [X] 输入边界层 GISIngestionLayer (ingestion.py: SpatialFeature + 20种空间要素类型)
- [X] DictionaryCenter YAML 驱动 (dicts/encodings/ + rules/ + references/)
- [X] 通用空间要素摄入器 (ingest_feature(), 21种feature type注册)
- [X] 编码体系代码集派生 (code_sets.py: DLBM_TO_* dicts + lookup functions)
- [X] 数据契约模型统一 (contracts.py: intent + pipeline 合并)
- [X] Schema 文件精简 (14→11 .py, -3 files)
- [X] Canonical Data Model（Pydantic BaseModel，WGS84 归一化）
- [X] Provider 适配层（Tianditu/Amap/OSM，CRS 归一化）
- [X] DynamicZoningEngine 动态分区引擎
- [X] ClassificationSchema 懒加载
- [X] EncodingRegistry (merged into classification.py)
- [X] GDB_LAYER_REGISTRY (12 层完整字段定义)
- [X] 颜色集中化（colors.py，6 套色卡）
- [X] PARSE Agent (parse/agent.py, parse/state.py)
- [X] 金田村实测数据全覆盖验证 (14/14文件 100%覆盖)

### Phase 1.5 — Schema 完整化 (2026-07) ⚠️ 部分完成

- [X] LandUseParcel 三层拆分 (Base → Current / Planned)
- [X] 20种空间要素类型模型 (spatial_types.py: Admin → Control → Planning layers)
- [ ] TDYT / JSYDGZQ / GHCFW ingest函数实现 (类型已定义, 摄入函数待完善)
- [ ] 现有 props.get() 调用迁移到类型化 parcel (Phase 2 迁移)

### Phase 2 — 架构对齐 (2026-07) ❌ 未实现

### Phase 2 — 架构对齐 ❌ 未实现 (设计阶段)

> ✅ **前置依赖 Phase 0 已完成**。generation/ 已迁入 `tools/gis/_generation/`，ZoneGenerator 等类可通过 `from app.tools.gis._generation.xxx import` 引用。

**目标**: 对齐 02_OUTPUT_ARCHITECTURE.md v3.3 的 5+1 内部生成层 + 12 层输出标准

#### 已知缺陷（P0 — 必须修复）

- [ ] **ParcelReclass 输出缺少 20 字段**：ZoneGenerator 只输出简单 zone_type/color，缺少 QMDLBM/GHFLBM/GHYTBM/GHYTMC。修复：升级 ZoneGenerator 为 ParcelReclassGenerator
- [ ] **planning_zone (6类) 与 UseZone (V/N/E) 并存**：架构要求 planning_zone 被 UseZone 替代。修复：删除 `_make_planning_zone_layer`，6 类分区信息保留在 ParcelReclass 的 `assigned_zone` 字段中
- [ ] **RoadPlan 层缺失**：架构要求 ⑤ RoadPlan → 13_planned_road，当前无对应生成器

#### 5+1 内部生成层对齐

```
当前 6 层                          →  架构 5+1 层
─────────────────────────────────────────────────
function_zone (ZoneGenerator)     →  ① ParcelReclass (20字段)
planning_zone (6类规划分区)       →  ❌ 删除（信息保留在 ① assigned_zone 字段）
space_control_zone                →  ② SpaceControl (已有)
land_use_zone                     →  ③ UseZone (V/N/E, 已有)
facility_point                    →  ④ FacilityPlan (已有)
infrastructure (AxisBuilder)      →  可视化叠加（不独立成层）
(无)                              →  ⑤ RoadPlan (待实现)
(无)                              →  ⑥ Text2GIS Ops (Phase D)
```

- [ ] 创建 `ParcelReclassGenerator`：每地块输出 20 必选字段
- [ ] 删除 `_make_planning_zone_layer`，前端从 ParcelReclass 的 `assigned_zone` 字段提取 6 类分区显示
- [ ] MIP allocator：`solve()` 开头添加功能分区→规划分区映射
- [ ] 实现 RoadPlan 生成器
- [ ] E2E 测试：验证 gen/plan 差异性 + 20 字段完整性

### Phase 2.5 — 统一操作执行引擎 ❌ 未实现 (设计阶段, 规划 2026-08)

> ✅ **前置依赖 Phase 0 已完成**。`agent/gis/execute/` 和 `tools/gis_execute/` 空壳已创建（Phase C4）。5 个 tools 待 Phase 2.5 实现。

- [ ] OperationEngine（5 种原子操作 + 变更日志 + 批量/逐条执行）
- [ ] MIP 降级为 `optimize_allocation` 辅助工具（批量场景按需调用）
- [ ] 空间地名解析工具（Amap POI + DLMC 字段聚类 + 地名词典辅助）
- [ ] 合规预检集成（复用 conflict/detector）
- [ ] 人工确认卡片 API（/api/gis/operations/confirm + /preview + /changelog）
- [ ] 前端确认界面（确认/拒绝/修改 + 地图预览）
- [ ] 变更日志与审计追踪（changelog.jsonl）

### Phase 3 — 功能增强 ❌ 未实现 (规划)

- [ ] 测试覆盖补全：plan 路径 LLM E2E 测试、三路对比集成测试
- [ ] export: 用地平衡表 Excel 输出、标准字段补全
- [ ] allocate: Voronoi 细化参考 GenPlanner
- [ ] 集成 procedural 工具：merge_parcels → zone_generator, simplify_boundary → map_renderer
- [ ] CA 精化模块恢复
- [ ] GHFLBM ↔ V/N/E 完整映射表

### Phase 4 — 探索方向 ❌ 未开始 (远期)

- [ ] DRL 土地优化（参考清华 DRL-urban-planning）
- [ ] GAN 村庄布局生成
- [ ] 实时协同编辑 + 移动端预览

## 9. 人机协同原则

1. **Agent 是专业绘图员，不是规划师**：Agent 负责将规划师的文字指令精确转化为 GIS 操作，不做规划决策
2. **不确定性必须由人消除**：文本未指定用途时反问，不自动赋值；空间定位有歧义时列出候选，不自动选择
3. **所有修改留痕待审**：变更日志记录每次操作的来源文本、前后快照、合规检查结果、确认人
4. **编码映射不做自动转换**：只做字典查找（用途名称→编码）+ 候选项建议（多对多时列出选项），不做现状→规划的自动推断
5. **合规检查是前置条件**：任何 GIS 操作执行前必须通过合规检查，违规操作不生成确认卡片
6. **操作可撤销**：变更日志记录 before 快照，支持按 operation_id 回滚
