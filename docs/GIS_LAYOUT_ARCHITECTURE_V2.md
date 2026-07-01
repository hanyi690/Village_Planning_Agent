# Village Planning Agent — GIS 布局引擎创新架构设计

> 版本: 2.0 | 日期: 2026-06-24 | 基于 DemoLand + MapAgent + PlanGPT-VL + Knowledge Graph 的融合创新

---

## 一、问题诊断：当前架构的根本缺陷

### 1.1 当前架构

```
L3报告文本 → LLM解析 → UnifiedSpatialIntent → ZoneGenerator(DLBM重分类) → MapRenderer → 图层
```

### 1.2 致命缺陷

| 缺陷                         | 表现                                 | 根因                                     |
| ---------------------------- | ------------------------------------ | ---------------------------------------- |
| **文本→几何直接跳跃** | 规划图=现状图的DLBM换色              | 缺少从"语义意图"到"空间布局"的中间层     |
| **单向pipeline**       | 无反馈循环，无法迭代优化             | 生成器与约束验证器独立运行               |
| **无视规划法规**       | 不检查"永久基本农田禁止非农化"等规则 | 规划规则以自然语言存在于报告中，未结构化 |
| **缺少空间推理**       | 1核1带3区的"核"位置是centroid近似    | LLM不理解空间拓扑关系                    |
| **单层输出**           | 6层数据, 但本质是分类标签            | 缺少真正的多层级空间层级(Hierarchy)      |

### 1.3 学术界已验证的方向（15+ 篇论文支撑）

| 方向                          | 代表工作                                                       | 与我们的关联                       |
| ----------------------------- | -------------------------------------------------------------- | ---------------------------------- |
| **Agent + 工具编排**    | MapAgent (2025), OpenEarthAgent (2026), ThinkGeo (2025)        | LLM作为调度器，动态调用GIS工具     |
| **RL + 空间优化**       | DemoLand (Turing, 2024), SWRL-UPOM (2025)                      | 逆向规划：给定目标指标→求土地配置 |
| **知识图谱 + 规划法规** | OntoPlanningRegulations (2025), Ecological Networks OWL (2018) | 将规划规则结构化编码为KG           |
| **GAN生成村庄布局**     | CGAN Rural Plan (FoAR 2025)                                    | 从传统村庄学习布局模式             |
| **领域VLM**             | PlanGPT-VL (2025)                                              | 专门理解规划图的视觉语言模型       |
| **多模态融合**          | SpatialLLM (2025), CUGUV (2025)                                | 遥感+文本+GIS多源融合              |

---

## 二、创新架构：三体模型 (Trinity Model)

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRINITY ARCHITECTURE                          │
│                                                                  │
│  ┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐ │
│  │ Layer 1:        │   │ Layer 2:         │   │ Layer 3:      │ │
│  │ PLANNING KG     │◄──│ AGENTIC          │──►│ SPATIAL       │ │
│  │ 规划知识图谱     │   │ PIPELINE         │   │ GENERATOR     │ │
│  │                 │   │ 智能体管道        │   │ 空间生成器     │ │
│  └────────┬────────┘   └────────┬─────────┘   └───────┬───────┘ │
│           │                     │                      │         │
│           ▼                     ▼                      ▼         │
│     结构化规则+约束        推理+规划+优化         程序化几何生成  │
│     (OWL/RDF triples)     (ReAct + RL)          (MIP + Rules)   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Layer 1: Planning Knowledge Graph (规划知识图谱)

**核心理念**: 将自然语言规划报告转化为机器可推理的结构化知识。

**创新点**: 不是简单的实体-关系抽取，而是构建一个**可执行约束的知识图谱**。

#### 实体类型 (Entity Types)

```
┌──────────────────────────────────────────────────────────────┐
│ ENTITIES                                                     │
├──────────────┬───────────────────────────────────────────────┤
│ Parcel       │ 地块: {bsm, dlbm, dlmc, area, geometry}      │
│ Zone         │ 分区: {zone_id, zone_type, area_target, ...} │
│ Constraint   │ 约束: {type, field, operator, value, source} │
│ Project      │ 项目: {name, location_hint, area, type}      │
│ Village      │ 自然村: {name, population, centroid}         │
│ Regulation   │ 法规: {name, article, condition, action}     │
│ Indicator    │ 指标: {name, current_value, target_value}    │
└──────────────┴───────────────────────────────────────────────┘
```

#### 关系类型 (Relation Types)

```
┌────────────────────────────────────────────────────────────┐
│ RELATIONS                                                  │
├────────────────────┬───────────────────────────────────────┤
│ adjacent_to        │ Parcel → Parcel (空间邻接)            │
│ within_zone        │ Parcel → Zone (地块归属)              │
│ constrained_by     │ Parcel → Constraint (受约束)          │
│ designated_as      │ Parcel → LandUseType (规划用途)       │
│ protects           │ Constraint → Zone (保护关系)          │
│ located_in         │ Project → Village (项目选址)          │
│ achieves           │ Project → Indicator (项目达标)       │
│ conflicts_with     │ Zone → Constraint (冲突检测)          │
│ derived_from       │ Indicator → Regulation (指标来源)     │
└────────────────────┴───────────────────────────────────────┘
```

#### 约束编码示例

```turtle
# 永久基本农田保护规则
:permanent_farmland_constraint rdf:type :SpatialConstraint ;
  :applies_to :parcel_with_dlbm_1100 ;
  :prohibits :non_agricultural_use ;
  :min_area_ha 78.83 ;
  :source_report "land_use_planning_v13" ;
  :legal_basis "国土空间用途管制制度" .

# 建设用地规模上限
:construction_cap rdf:type :NumericConstraint ;
  :field :construction_area_ha ;
  :operator "<=" ;
  :value 30.5 ;
  :enforced_by :superior_planning .

# 生态红线禁止开发
:ecological_redline rdf:type :SpatialConstraint ;
  :applies_to :ecological_redline_zone ;
  :prohibits :industrial_development ;
  :prohibits :urbanization ;
  :area_ha 362.02 .
```

**关键技术选型**:

- 存储: RDFLib + SQLite backend (轻量级，不需要独立的图数据库)
- 查询: SPARQL (符合W3C标准，可集成到LLM tool calling)
- 与LLM集成: `kg_query(sparql)` → 结构化结果 → LLM推理上下文

**参考文献**:

- Grisiute et al. (2025) "3D Land Use Planning: Making Future Cities Measurable with Ontology-Driven Representations" — AGILE GIScience
- Belussi et al. (2018) "Ontological Representation of Constraints for Geographical Reasoning" — SciTePress
- UrbanKGent (2024) "A Unified LLM Agent Framework for Urban Knowledge Graph Construction" — arXiv:2402.06861

---

### 2.2 Layer 2: Agentic Pipeline (智能体管道)

**核心理念**: LLM不作为直接生成器，而是作为**规划调度器** (Orchestrator)，协调多个专用工具完成空间推理。

**创新点**: 借鉴 MapAgent 的"hierarchical planning + tool execution"模式 + DemoLand 的"inverse planning"思路。

#### 架构

```
                    ┌──────────────────┐
                    │   PLANNER LLM    │  ← 高层规划: "需要生成7个分区, 3个约束层"
                    │  (GPT/DeepSeek)  │
                    └────────┬─────────┘
                             │ 分解为 sub-goals
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │ PARSE       │ │ REASON      │ │ GENERATE    │
    │ 解析Agent   │ │ 推理Agent   │ │ 生成Agent   │
    │             │ │             │ │             │
    │ 工具:       │ │ 工具:       │ │ 工具:       │
    │ - extract_  │ │ - check_    │ │ - allocate_ │
    │   metrics   │ │   constraint│ │   zones     │
    │ - parse_    │ │ - detect_   │ │ - place_    │
    │   tables    │ │   conflict  │ │   facilities │
    │ - build_kg  │ │ - resolve_  │ │ - generate_ │
    │             │ │   priority  │ │   geometry  │
    └─────────────┘ └─────────────┘ └─────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  VALIDATOR       │  ← 验证循环: 是否符合约束？
                    │  验证器           │     NO → 反馈给 REASON
                    │                  │     YES → 输出
                    └──────────────────┘
```

#### 工具注册表 (Tool Registry)

```python
TOOLS = {
    # -- 解析工具 --
    "extract_metrics": {
        "description": "从报告文本中提取数值指标",
        "params": {"report_content": "str", "metric_schema": "dict"},
        "returns": "Dict[str, float]"
    },
    "parse_zoning_table": {
        "description": "解析土地用途分区表",
        "params": {"report_content": "str"},
        "returns": "List[ZoneDefinition]"
    },
    "build_knowledge_graph": {
        "description": "将解析结果构建为RDF知识图谱",
        "params": {"entities": "list", "relations": "list"},
        "returns": "Graph"
    },
  
    # -- 推理工具 --
    "check_constraint": {
        "description": "检查单个约束是否满足",
        "params": {"constraint_id": "str", "current_state": "dict"},
        "returns": "ConstraintResult"
    },
    "detect_zone_conflict": {
        "description": "检测分区间的空间和指标冲突",
        "params": {"zone_a": "str", "zone_b": "str"},
        "returns": "ConflictReport"
    },
    "query_kg": {
        "description": "SPARQL查询知识图谱",
        "params": {"sparql": "str"},
        "returns": "QueryResult"
    },
  
    # -- 生成工具 --
    "allocate_zones": {
        "description": "基于约束和指标分配功能区",
        "params": {"targets": "dict", "constraints": "list", "parcels": "GeoDataFrame"},
        "returns": "GeoDataFrame with zone assignments"
    },
    "place_facility": {
        "description": "依据选址规则放置设施点",
        "params": {"facility": "FacilityIntent", "candidate_zones": "list"},
        "returns": "Point geometry"
    },
    "generate_axis": {
        "description": "生成发展轴线几何",
        "params": {"axis_type": "str", "anchor_points": "list"},
        "returns": "LineString geometry"
    },
  
    # -- 验证工具 --
    "validate_layout": {
        "description": "全面验证生成结果是否满足所有约束",
        "params": {"layout": "dict", "kg": "Graph"},
        "returns": "ValidationReport"
    },
    "measure_divergence": {
        "description": "计算规划布局与现状的差异度",
        "params": {"current": "GeoDataFrame", "planned": "GeoDataFrame"},
        "returns": "DivergenceMetrics"
    },
}
```

#### ReAct 循环示例

```
User: "生成金田村规划布局，目标：建设用地≤30.5ha, 新增0.33ha"

Planner LLM:
  Thought: 需要先解析报告获取约束值，再构建KG，然后在约束下分配地块
  Action: extract_metrics("land_use_planning", schema=CONSTRUCTION_SCHEMA)
  Observation: {planned_construction_ha: 30.5, new_construction_ha: 0.33}

  Thought: 建设用地上限已获取。现在需要检查哪些地块可以转为建设用地
  Action: query_kg("SELECT ?parcel WHERE { ?parcel :dlbm ?dlbm . FILTER(?dlbm IN ('2121','2122','2124')) }")
  Observation: [132 residential parcels, 23 public service, 28 industrial]

  Thought: 当前建设用地30.17ha，目标30.50ha，需要新增0.33ha。检查约束
  Action: check_constraint("construction_cap", {"current": 30.17, "planned": 30.50})
  Observation: {satisfied: True, margin: 0.33}

  Thought: 约束满足。现在生成分区分配
  Action: allocate_zones(targets=ZONE_TARGETS, constraints=CONSTRAINTS, parcels=landuse_current)
  Observation: {zones: [...], unassigned: 12, conflicts: 0}

  Thought: 分区已分配。验证整体布局
  Action: validate_layout(layout=result, kg=kg)
  Observation: {passed: True, warnings: ["12 parcels unassigned → 归入一般农地区"]}

  Final Answer: 规划布局生成完成。7个分区 + 3个约束层 + 空间结构。
```

**参考文献**:

- MapAgent (2025) "A Hierarchical Agent for Geospatial Reasoning with Dynamic Map Tool Integration"
- DemoLand (2024) "Land Use Demonstrator" — The Alan Turing Institute + Geospatial Commission
- OpenEarthAgent (2026) "A Unified Framework for Tool-Augmented Geospatial Agents"
- ThinkGeo (2025) "Evaluating Tool-Augmented Agents for Remote Sensing Tasks"

---

### 2.3 Layer 3: Spatial Generator (空间生成器)

**核心理念**: 不直接从文本生成几何，而是通过**约束求解 + 程序化生成**产生可解释、可验证的空间布局。

**创新点**: 借鉴 DemoLand 的 Inverse Planning + CGAN 的像素级布局生成 + 传统MIP优化。

#### 三阶段生成流程

```
Stage A: 约束分配 (MIP Optimization)
  输入: 现状地类面积 + 规划目标指标 + 约束规则 (from KG)
  方法: 混合整数规划 (Mixed Integer Programming)
  输出: 每个地块的规划用途分配方案

Stage B: 空间细化 (Procedural Refinement)
  输入: Stage A 的分配 + 空间邻接关系 (from KG)
  方法: Cellular Automata + 邻域规则
  输出: 合并/拆分后的规划图斑几何

Stage C: 设施与轴线 (Rule-based Placement)
  输入: Stage B 的图斑 + 项目列表 + 空间结构描述
  方法: 基于规则的设施选址 + 最短路径轴线生成
  输出: facility_point + development_axis GeoJSON
```

#### Stage A 具体算法: 规划用地分配MIP

```python
"""
目标函数:
  minimize Σ |assigned_area_i - target_area_i|  (面积偏差最小化)
  + λ * Σ change_penalty_j                      (保持现状的偏好)
  + μ * Σ spatial_compactness_k                 (空间紧凑性)

约束:
  1. 每个地块只能分配一种规划用途
  2. 建设用地总量 ≤ 30.5 ha
  3. 永久基本农田 ≥ 78.83 ha
  4. 生态红线内禁止建设用途
  5. 邻接地块应尽量同类 (compactness)
  6. 设施用地需在建设区内
"""
```

**参考文献**:

- Wang et al. (2025) "Evaluation and optimization simulation of land suitability for village construction" — Scientific Reports
- Liu et al. (2025) "CGAN-based rural plan generation" — Frontiers of Architectural Research 14(3):739-758
- DemoLand (2024) "Land Use Demonstrator: Deep Q-Network RL for land use optimization"

---

## 三、实施路线图

### Phase 1: Knowledge Graph Foundation (2-3 天)

```
目标: 将一份完整的L3报告转化为可查询的规划知识图谱

步骤:
  1.1 定义 OWL 本体 (entities + relations)
  1.2 实现 report → RDF 转换器
       - 解析 metrics → Indicator 实体
       - 解析表格 → Zone + Constraint 实体  
       - 解析空间结构 → Structure 实体
  1.3 实现 SPARQL 查询接口
  1.4 验证: 对金田村 session dc2a2e0e 构建KG并查询

交付:
  - planning_ontology.py (本体定义)
  - kg_builder.py (报告→KG转换)
  - kg_query.py (SPARQL工具)
  - 金田村 planning_kg.ttl (完整知识图谱文件)
```

### Phase 2: Agentic Tools (2-3 天)

```
目标: 将现有功能封装为LLM可调用的工具

步骤:
  2.1 定义 Tool 注册表 (ToolRegistry)
  2.2 封装现有模块为工具:
       - ConflictDetector → check_constraint / detect_conflict
       - ZoneGenerator → allocate_zones
       - MapRenderer → render_layer
       - ContentExtractor → extract_metrics / parse_tables
  2.3 实现 KG 查询工具 (query_kg)
  2.4 实现 validate_layout 工具
  2.5 构建 ReAct Planner (LangGraph Agent)

交付:
  - tool_registry.py (工具注册表)
  - tools/*.py (各工具实现)  
  - agent_planner.py (ReAct Agent)
```

### Phase 3: Spatial Optimization Engine (3-4 天)

```
目标: 实现约束驱动的空间分配优化

步骤:
  3.1 实现 MIP 地块分配 (pulp/ortools)
  3.2 实现邻域合并规则 (Cellular Automata)
  3.3 实现设施选址 (基于距离+覆盖的贪心算法)
  3.4 实现轴线生成 (最短路径沿道路/水系)
  3.5 实现验证-反馈-优化循环

交付:
  - spatial_optimizer.py (MIP求解器)
  - procedural_generator.py (程序化几何生成)
  - facility_placer.py (设施选址)
  - axis_builder.py (轴线生成)
```

### Phase 4: Integration & Evaluation (2 天)

```
目标: 全管道集成，与CAD参考图对比评估

步骤:
  4.1 端到端管道集成
  4.2 与 project_layout_clean.svg 做定量对比
  4.3 生成对比报告 (覆盖率/准确率/差异度)
  4.4 前端集成准备 (GISLayerConfig 输出)

交付:
  - 完整管道脚本
  - 对比评估报告
  - 更新的前端数据结构
```

---

## 四、关键技术决策

### 4.1 为什么用 Knowledge Graph 而不是纯向量数据库？

| 需求                                     | KG (RDF/SPARQL)           | 向量DB (如Chroma) |
| ---------------------------------------- | ------------------------- | ----------------- |
| 精确约束查询 ("永久基本农田 ≥ 78.83ha") | ✅ SPARQL FILTER          | ❌ 近似匹配       |
| 空间拓扑推理 ("地块A邻接地块B")          | ✅ 显式关系边             | ❌ 无图结构       |
| 法规追溯 ("这条约束来自哪个报告?")       | ✅ 来源标注               | ❌ 无追溯         |
| 与LLM集成                                | ✅ Tool: query_kg(sparql) | ✅ 语义搜索       |
| 增量更新 (新报告→新规则)                | ✅ add triples            | ✅ add vectors    |

**结论**: KG 做结构化规则存储和精确推理，向量DB做报告文本的语义搜索 → **两者互补**。

### 4.2 为什么用 Agent 而不是端到端模型？

| 维度     | Agent + Tools        | 端到端 (如CGAN生成像素) |
| -------- | -------------------- | ----------------------- |
| 可解释性 | ✅ 每步ReAct轨迹可见 | ❌ 黑盒                 |
| 约束保证 | ✅ 验证器强制执行    | ❌ 需后处理             |
| 法规变更 | ✅ 改KG即可          | ❌ 需重新训练           |
| 数据需求 | ✅ 一本报告可运行    | ❌ 需千级样本           |
| 精度     | ✅ 图斑级            | ⚠️ 像素级(需后处理)   |

**结论**: 村庄规划场景中，规则明确、数据稀缺、需要可解释性 → Agent方案更适合。未来可引入CGAN做布局风格优化。

### 4.3 为什么用 MIP 而不是 LLM 直接生成？

LLM 直接生成 "地块 #372 → 居住用地" 有两个问题:

1. **幻觉**: LLM可能将耕地划为建设 (违反基本农田约束)
2. **不可验证**: 无法保证总面积约束精确满足

MIP求解器能保证:

1. 所有硬约束 100% 满足
2. 目标函数最优化
3. 结果可复现

**LLM的角色**: 不直接生成分配方案，而是:

- 解析报告 → 提取目标值和约束
- 定义优化目标 (如"优先保障粮食安全" → 调整ω权重)
- 解释结果 (自然语言说明为什么这样分配)

---

## 五、与现有代码的关系

### 三层架构实际落地

```
app/agent/gis/          ← ReAct Agent 子图（Layer 2）
  graph.py              create_react_agent(state_schema=GISAgentState)
  state.py              GISAgentState (kg_turtle, kg_constraints, layout_configs, ...)
  prompts.py            ReAct system prompt
app/tools/gis/          ← Tool 层（Layer 2 ↔ Layer 3 桥接）
  layout_tools.py       6 个 @tool: InjectedState + Command + ToolMessage
  data_tools.py         4 个数据工具（fetch/coverage/accessibility/poi）
app/services/modules/gis/layout/  ← Service 层（Layer 1 + Layer 3）
  kg/                  PlanningKG (rdflib.Graph) + SPARQL 查询
  optimizer/           MIPZoneAllocator (PuLP) + procedural 几何工具
  engine.py            SpatialLayoutEngine 编排器
  validator.py         LayoutValidator 5 类验证
  facility_placer.py   设施选址
  axis_builder.py      发展轴构建
  conflict_detector.py 跨维度冲突检测
  zone_generator.py    DLBM 重分类
  map_renderer.py      图层渲染
```

### 保留并增强的模块

| 现有模块                 | 新架构中的角色                               | 改动                            |
| ------------------------ | -------------------------------------------- | ------------------------------- |
| `ConflictDetector`     | → Tool:`detect_conflicts`                 | summaries 从 InjectedState 注入 |
| `ConflictResolver`     | Phase 0 内部调用（非独立工具）               | 保持现有                        |
| `ZoneGenerator`        | → Tool:`allocate_zones` (function_zone层) | 保留 DLBM 重分类路径            |
| `MapRenderer`          | → engine.generate_layout() 内部调用         | 保持现有                        |
| `planning_intent.py`   | Tool 参数 schema                             | 字段对齐 KG schema              |
| `semantics.py`         | KG 构建时消费                                | 融入 builder                    |
| `colors.py`            | 保持                                         | 无需改动                        |
| `content_extractor.py` | KG 构建前预处理                              | 保持现有                        |




### 新增模块

| 新模块                                    | 说明                                           |
| ----------------------------------------- | ---------------------------------------------- |
| `gis/layout/kg/ontology.py`             | OWL 本体定义 (RDF/OWL)                         |
| `gis/layout/kg/builder.py`              | 报告→KG 构建器 + to_turtle/from_turtle        |
| `gis/layout/kg/query.py`                | SPARQL 查询模板 + query_kg                     |
| `agent/gis/graph.py`                    | create_react_agent + state_schema              |
| `agent/gis/state.py`                    | GISAgentState TypedDict                        |
| `tools/gis/layout_tools.py`             | 6 个 @tool（InjectedState + Command）          |
| `gis/layout/optimizer/mip_allocator.py` | PuLP 混合整数规划求解器                        |
| `gis/layout/optimizer/mip_solver.py`    | ConstraintDrivenAllocator (greedy + MIP 路由)  |
| `gis/layout/optimizer/procedural.py`    | merge/split/simplify/buffer 几何工具           |
| `gis/layout/facility_placer.py`         | 4 种设施选址策略                               |
| `gis/layout/axis_builder.py`            | 一核一带三区 + AxisIntent                      |
| `gis/layout/validator.py`               | 5 类验证（面积/完整性/重叠/保护地块/最小面积） |

---

## 五-B、LangGraph 1.2 数据流（关键 API）

### 5-B.1 state_schema 是必需的

```python
# app/agent/gis/graph.py
graph = create_react_agent(
    llm,
    GIS_TOOLS,
    state_schema=GISAgentState,   # ← 关键：自定义字段才能被 Command.update 写入
    prompt=GIS_AGENT_SYSTEM_PROMPT,
)
```

**没有 `state_schema`，`Command(update={"layout_configs": ...})` 会被静默丢弃**——这是 V1 的致命 bug。

### 5-B.2 工具签名：InjectedState + InjectedToolCallId

```python
@tool
def build_knowledge_graph(
    reports: Annotated[Dict, InjectedState("reports")],        # LLM 不可见
    gis_data: Annotated[Dict, InjectedState("gis_data")],      # LLM 不可见
    village_name: Annotated[str, InjectedState("village_name")],# LLM 不可见
    tool_call_id: Annotated[str, InjectedToolCallId],          # LLM 不可见
) -> Command:
    """无需参数，数据自动从状态注入。"""  # ← LLM 只看到这个 docstring
    ...
```

LLM 看到的 tool schema 只有无注入参数（如 `query_knowledge_graph` 的 `template_name`），大对象（1-2MB GeoJSON）通过 InjectedState 注入，避免上下文膨胀。

### 5-B.3 Command 返回模式（LangGraph 1.2 实际 API）

```python
from langchain_core.messages import ToolMessage
from langgraph.types import Command

@tool
def generate_layout(intent: dict, ...) -> Command:
    configs = engine.generate_layout(...)
    result = {"success": True, "data": {"layer_count": len(configs), ...}}
    return Command(
        update={
            "layout_configs": configs,                          # 写 state
            "messages": [ToolMessage(                            # LLM 可见
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
            )],
        },
    )
```

**关键约束**：

- `Command` 没有 `result=` 参数（V1 计划设计错误，V2 已修正）
- LLM 可见内容必须通过 `update["messages"]` 里的 `ToolMessage` 传递
- `ToolMessage.tool_call_id` 必须匹配调用 id（由 `InjectedToolCallId` 注入）
- `update` 中的其他字段（如 `layout_configs`、`kg_turtle`）会被合并到 graph state

### 5-B.4 KG Turtle 序列化（跨工具调用持久化）

`PlanningKG` 内部是 `rdflib.Graph`，无法直接放入 TypedDict state。用 Turtle 字符串序列化：

```python
# build_knowledge_graph 工具
kg = PlanningKG(village_name=village_name)
kg.build_from_reports(reports, landuse_geojson)
return Command(update={
    "kg_turtle": kg.to_turtle(),         # 序列化字符串存入 state
    "kg_constraints": kg.get_constraints(),
    "messages": [ToolMessage(...)],
})

# query_knowledge_graph 工具
kg = PlanningKG.from_turtle(kg_turtle)   # 反序列化
results = query_kg(kg, template_name, ...)
```

优势：支持 checkpointing、符合 LangGraph 官方模式；劣势：每次查询反序列化约 100ms（ReAct 循环内可接受）。

---

## 六、验证指标

### 量化指标

| 指标              | 计算方式                           | 目标值              |
| ----------------- | ---------------------------------- | ------------------- |
| 约束满足率        | satisfied / total_constraints      | 100% (硬约束)       |
| 面积偏差          | Σ                                 | actual_i - target_i |
| 空间紧凑度        | Σ perimeter_i / (2√(π·area_i)) | 越低越好            |
| 变化检测率        | changed_parcels / total_parcels    | > 5% (要有可见差异) |
| 项目覆盖率        | located_projects / total_projects  | > 80%               |
| 与CAD参考图相似度 | IoU of zone boundaries             | > 60% (定性参考)    |

### 与 CAD 参考图的对齐检查

- [ ] 一核(服务中心)位置是否在园寨
- [ ] 一带是否沿金田河走向
- [ ] 三区划分是否与报告描述一致
- [ ] 永久基本农田边界是否被尊重
- [ ] 项目标注是否在合理位置
- [ ] 指北针、比例尺、图例是否完整

---

## 七、参考文献

1. **CGAN Rural Plan**: Liu et al. (2025) "The study of high-performance generation methods for rural plan based on generative adversarial network." *Frontiers of Architectural Research* 14(3):739-758.
2. **PlanGPT-VL**: (2025) "PlanGPT-VL: Enhancing Urban Planning with Domain-Specific Vision-Language Models." *EMNLP 2025 Industry Track*.
3. **DemoLand**: The Alan Turing Institute + Geospatial Commission (2024) "Geospatial AI for Land Use." GOV.UK Publications.
4. **MapAgent**: (2025) "MapAgent: A Hierarchical Agent for Geospatial Reasoning with Dynamic Map Tool Integration." arXiv:2509.05933.
5. **SpatialLLM**: (2025) "SpatialLLM: From Multi-modality Data to Urban Spatial Intelligence." arXiv:2505.12703.
6. **OntoPlanningRegulations**: Grisiute et al. (2025) "3D Land Use Planning: Making Future Cities Measurable with Ontology-Driven Representations." *AGILE GIScience Ser.* 6:3.
7. **UrbanKGent**: (2024) "UrbanKGent: A Unified LLM Agent Framework for Urban Knowledge Graph Construction." arXiv:2402.06861.
8. **OpenEarthAgent**: (2026) "OpenEarthAgent: A Unified Framework for Tool-Augmented Geospatial Agents." arXiv:2602.17665.
9. **ThinkGeo**: (2025) "ThinkGeo: Evaluating Tool-Augmented Agents for Remote Sensing Tasks." arXiv:2505.23752.
10. **SWRL-UPOM**: (2025) "Semantic Web-Enhanced Reinforcement Learning Model for Urban Planning Optimization." ScienceDirect.
11. **Belussi et al.**: (2018) "Ontological Representation of Constraints for Geographical Reasoning." SciTePress.
12. **LLM + GIS**: (2025) "On the Use of LLMs for GIS-Based Spatial Analysis." *IJGI* 14(10):401.
13. **CUGUV**: Wang et al. (2025) "CUGUV: A Benchmark Dataset for Promoting Large-Scale Urban Village Mapping." *Scientific Data* 12:390.
14. **MPLNet**: (2026) "Mamba Prompt Learning Network for semantic segmentation of remote sensing images of traditional villages." *PLOS One*.
15. **HGNN Villages**: (2025) "Multi-Modal Feature Fusion for Spatial Morphology Analysis of Traditional Villages via Hierarchical Graph Neural Networks." arXiv:2510.27208.
16. **Village Suitability**: (2025) "Evaluation and optimization simulation of land suitability for village construction." *Scientific Reports*.
17. **Knowledge Graph + Bayesian**: Wang et al. (2026) "Integrating Knowledge Graphs and Bayesian Inference to Balance Ecological Security, Carbon Sinks, and Development." *Land* 15(4):636.
18. **CityGenAgent**: (2025) "Imagine a City: CityGenAgent for Procedural 3D City Generation." arXiv:2602.05362.

---

## 八、附录：数据流示意图（LangGraph 1.2 实际实现）

```
┌────────────────────────────────────────────────────────────────────┐
│                          INPUT (gis_agent_node)                     │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ L3 Reports   │  │ landuse_current   │  │ Protection Zones     │ │
│  │ (12 dims)    │  │ (660 parcels)     │  │ (farmland/eco/hist)  │ │
│  └──────┬───────┘  └────────┬─────────┘  └──────────┬───────────┘ │
│         │                   │                       │             │
│         ▼                   ▼                       ▼             │
│  gis_input = {                                                   │
│    reports, summaries, gis_data: {boundary, landuse_current,     │
│    protection_zones, road, hazard},                              │
│    kg_turtle: "",  kg_constraints: [],  layout_configs: [],      │
│    messages: []                                                  │
│  }                                                               │
└─────────┬──────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────────────────┐
│          LAYER 2: ReAct Agent (create_react_agent)                  │
│          state_schema=GISAgentState  ← 关键                         │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 1: build_knowledge_graph()                              │  │
│  │   InjectedState: reports, gis_data, village_name (LLM不可见) │  │
│  │   → Command(update={                                          │  │
│  │       "kg_turtle": kg.to_turtle(),      ← 写 state           │  │
│  │       "kg_constraints": [...],          ← 写 state           │  │
│  │       "messages": [ToolMessage(content=JSON, tool_call_id)] │  │
│  │     })                                                       │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 2: query_knowledge_graph(template_name="get_constraints")│  │
│  │   InjectedState: kg_turtle  ← 从 state 读                     │  │
│  │   kg = PlanningKG.from_turtle(kg_turtle)                      │  │
│  │   → Command(update={"messages": [ToolMessage(...)]})         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 3: detect_conflicts()                                   │  │
│  │   InjectedState: summaries  ← 从 state 读                     │  │
│  │   → Command(update={"messages": [ToolMessage(...)]})         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 4: allocate_zones(targets, constraints, mode="mip")    │  │
│  │   InjectedState: gis_data, kg_constraints  ← 从 state 读      │  │
│  │   MIPZoneAllocator.solve() — PuLP CBC 求解                    │  │
│  │   → Command(update={"messages": [ToolMessage(...)]})         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 5: generate_layout(intent)                              │  │
│  │   InjectedState: gis_data  ← 从 state 读                      │  │
│  │   SpatialLayoutEngine.generate_layout()                       │  │
│  │   → Command(update={                                          │  │
│  │       "layout_configs": configs,        ← 写 state           │  │
│  │       "messages": [ToolMessage(content=JSON)]                │  │
│  │     })                                                       │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ Tool 6: validate_layout(layout_configs, constraints)         │  │
│  │   LayoutValidator.validate() — 5 类验证                       │  │
│  │   → Command(update={"messages": [ToolMessage(...)]})         │  │
│  │   失败时 LLM 调整 targets 重试（最多 3 次）                  │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                    LAYER 1+3: SERVICE IMPL                           │
│                                                                     │
│  Layer 1 - PlanningKG (rdflib.Graph):                             │
│    build_from_reports() → 600+ triples, 30+ constraints           │
│    to_turtle()/from_turtle() — 跨工具调用持久化                    │
│    SPARQL 查询模板 (9 个): get_constraints, get_parcels_by_dlbm,  │
│    count_by_zone_type, get_zone_restrictions, ...                 │
│                                                                     │
│  Layer 3 - SpatialLayoutEngine:                                   │
│    Phase 0: ConflictDetector → ConflictResolver                   │
│    Phase 1: ZoneGenerator (DLBM 重分类) → function_zone           │
│             ConstraintDrivenAllocator (greedy/MIP) → planning_zone│
│             FacilityPlacer → facility_point                       │
│             AxisBuilder → development_axis                        │
│             MapRenderer → 6+ 图层配置                              │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                          OUTPUT                                      │
│  gis_agent_node 返回:                                              │
│    {                                                               │
│      "messages": [AIMessage(content=汇总)],                       │
│      "gis_layout_configs": [                                       │
│        {layerType: "boundary", data: {...}},                      │
│        {layerType: "function_zone", data: {...}},                 │
│        {layerType: "planning_zone", data: {...}},  ← KG 驱动      │
│        {layerType: "sensitivity_zone", data: {...}},              │
│        {layerType: "infrastructure", data: {...}},                │
│        {layerType: "facility_point", data: {...}},                │
│        {layerType: "development_axis", data: {...}},              │
│      ]                                                            │
│    }                                                              │
│  → 前端 Leaflet 渲染 7 层规划图                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 八-B、验证测试

- `backend/tests/test_gis_validator.py` — 16 个测试覆盖 5 类验证
- `backend/tests/test_gis_layout_tools.py` — 14 个测试覆盖 Command/ToolMessage/InjectedState
- 全部通过：`pytest tests/ -v` → 30 passed
