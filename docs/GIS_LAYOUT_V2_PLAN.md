# Gz  "returns": "ConstraintResult"

# 
    },

# 
    "detect_zone_conflict": {

# 
    "description": "检测分区间的空间和指标冲突",

# 
    "params": {"zone_a": "str", "zone_b": "str"},

# 
    "returns": "ConflictReport"

# 
    },

# 
    "query_kg": {

# 
    "description": "SPARQL查询知识图谱",

# 
    "params": {"sparql": "str"},

# 
    "returns": "QueryResult"

# 
    },

# 
    # -- 生成工具 --

# ReAct 循环示例

# ￼

# Plain Text

# User: "生成金田村规划布局，目标：建设用地≤30.5ha, 新增0.33ha"

# Planner LLM:

#   Thought: 需要先解析报告获取约束值，再构建KG，然后在约束下分配地块

#   Action: extract_metrics("land_use_planning", schema=CONSTRUCTION_SCHEMA)

#   Observation: {planned_construction_ha: 30.5, new_construction_ha: 0.33}

#   Thought: 建设用地上限已获取。现在需要检查哪些地块可以转为建设用地

#   Action: query_kg("SELECT ?parcel WHERE { ?parcel :dlbm ?dlbm . FILTER(?dlbm IN ('2121','2122','2124')) }")

#   Observation: [132 residential parcels, 23 public service, 28 industrial]

#   Thought: 当前建设用地30.17ha，目标30.50ha，需要新增0.33ha。检查约束

#   Action: check_constraint("construction_cap", {"current": 30.17, "planned": 30.50})

#   Observation: {satisfied: True, margin: 0.33}

#   Thought: 约束满足。现在生成分区分配

#   Action: allocate_zones(targets=ZONE_TARGETS, constraints=CONSTRAINTS, parcels=landuse_current)

#   Observation: {zones: [...], unassigned: 12, conflicts: 0}

#   Thought: 分区已分配。验证整体布局

#   Action: validate_layout(layout=result, kg=kg)

#   Observation: {passed: True, warnings: ["12 parcels unassigned → 归入一般农地区"]}

#   Final Answer: 规划布局生成完成。7个分区 + 3个约束层 + 空间结构。

# 参考文献:

# MapAgent (2025) "A Hierarchical Agent for Geospatial Reasoning with Dynamic Map Tool Integration"

# DemoLand (2024) "Land Use Demonstrator" — The Alan Turing Institute + Geospatial Commission

# OpenEarthAgent (2026) "A Unified Framework for Tool-Augmented Geospatial Agents"

# ThinkGeo (2025) "Evaluating Tool-Augmented Agents for Remote Sensing Tasks"

# 2.3 Layer 3: Spatial Generator (空间生成器)

# 核心理念: 不直接从文本生成几何，而是通过约束求解 + 程序化生成产生可解释、可验证的空间布局。

# 创新点: 借鉴 DemoLand 的 Inverse Planning + CGAN 的像素级布局生成 + 传统MIP优化。

# 三阶段生成流程

# ￼

# Plain Text

# Stage A: 约束分配 (MIP Optimization)

#   输入: 现状地类面积 + 规划目标指标 + 约束规则 (from KG)

#   方法: 混合整数规划 (Mixed Integer Programming)

#   输出: 每个地块的规划用途分配方案

# Stage B: 空间细化 (Procedural Refinement)

#   输入: Stage A 的分配 + 空间邻接关系 (from KG)

#   方法: Cellular Automata + 邻域规则

#   输出: 合并/拆分后的规划图斑几何

# Stage C: 设施与轴线 (Rule-based Placement)

#   输入: Stage B 的图斑 + 项目列表 + 空间结构描述

#   方法: 基于规则的设施选址 + 最短路径轴线生成

#   输出: facility_point + development_axis GeoJSON

# Stage A 具体算法: 规划用地分配MIP

# ￼

# python

# """

# 目标函数:

#   minimize Σ |assigned_area_i - target_area_i|  (面积偏差最小化)

#   + λ * Σ change_penalty_j                      (保持现状的偏好)

#   + μ * Σ spatial_compactness_k                 (空间紧凑性)

# 约束:

#   1. 每个地块只能分配一种规划用途

#   2. 建设用地总量 ≤ 30.5 ha

#   3. 永久基本农田 ≥ 78.83 ha

#   4. 生态红线内禁止建设用途

#   5. 邻接地块应尽量同类 (compactness)

#   6. 设施用地需在建设区内

# """

# 参考文献:

# Wang et al. (2025) "Evaluation and optimization simulation of land suitability for village construction" — Scientific Reports

# Liu et al. (2025) "CGAN-based rural plan generation" — Frontiers of Architectural Research 14(3):739-758

# DemoLand (2024) "Land Use Demonstrator: Deep Q-Network RL for land use optimization"

# 三、实施路线图

# Phase 1: Knowledge Graph Foundation (2-3 天)

# ￼

# Plain Text

# 目标: 将一份完整的L3报告转化为可查询的规划知识图谱

# 步骤:

#   1.1 定义 OWL 本体 (entities + relations)

#   1.2 实现 report → RDF 转换器

# 
    - 解析 metrics → Indicator 实体

# 
    - 解析表格 → Zone + Constraint 实体

# 
    - 解析空间结构 → Structure 实体

#   1.3 实现 SPARQL 查询接口

#   1.4 验证: 对金田村 session dc2a2e0e 构建KG并查询

# 交付:

#   - planning_ontology.py (本体定义)

#   - kg_builder.py (报告→KG转换)

#   - kg_query.py (SPARQL工具)

#   - 金田村 planning_kg.ttl (完整知识图谱文件)

# Phase 2: Agentic Tools (2-3 天)

# ￼

# Plain Text

# 目标: 将现有功能封装为LLM可调用的工具

# 步骤:

#   2.1 定义 Tool 注册表 (ToolRegistry)

#   2.2 封装现有模块为工具:

# 
    - ConflictDetector → check_constraint / detect_conflict

# 
    - ZoneGenerator → allocate_zones

# 
    - MapRenderer → render_layer

# 
    - ContentExtractor → extract_metrics / parse_tables

#   2.3 实现 KG 查询工具 (query_kg)

#   2.4 实现 validate_layout 工具

#   2.5 构建 ReAct Planner (LangGraph Agent)

# 交付:

#   - tool_registry.py (工具注册表)

#   - tools/*.py (各工具实现)  

#   - agent_planner.py (ReAct Agent)

# Phase 3: Spatial Optimization Engine (3-4 天)

# ￼

# Plain Text

# 目标: 实现约束驱动的空间分配优化

# 步骤:

#   3.1 实现 MIP 地块分配 (pulp/ortools)

#   3.2 实现邻域合并规则 (Cellular Automata)

#   3.3 实现设施选址 (基于距离+覆盖的贪心算法)

#   3.4 实现轴线生成 (最短路径沿道路/水系)

#   3.5 实现验证-反馈-优化循环

# 交付:

#   - spatial_optimizer.py (MIP求解器)

#   - procedural_generator.py (程序化几何生成)

#   - facility_placer.py (设施选址)

#   - axis_builder.py (轴线生成)

# Phase 4: Integration & Evaluation (2 天)

# ￼

# Plain Text

# 目标: 全管道集成，与CAD参考图对比评估

# 步骤:

#   4.1 端到端管道集成

#   4.2 与 project_layout_clean.svg 做定量对比

#   4.3 生成对比报告 (覆盖率/准确率/差异度)

#   4.4 前端集成准备 (GISLayerConfig 输出)

# 交付:

#   - 完整管道脚本

#   - 对比评估报告

#   - 更新的前端数据结构

# 四、关键技术决策

# 4.1 为什么用 Knowledge Graph 而不是纯向量数据库？

# 需求	KG (RDF/SPARQL)	向量DB (如Chroma)

# 精确约束查询 ("永久基本农田 ≥ 78.83ha")	✅ SPARQL FILTER	❌ 近似匹配

# 空间拓扑推理 ("地块A邻接地块B")	✅ 显式关系边	❌ 无图结构

# 法规追溯 ("这条约束来自哪个报告?")	✅ 来源标注	❌ 无追溯

# 与LLM集成	✅ Tool: query_kg(sparql)	✅ 语义搜索

# 增量更新 (新报告→新规则)	✅ add triples	✅ add vectors

# 结论: KG 做结构化规则存储和精确推理，向量DB做报告文本的语义搜索 → 两者互补。

# 4.2 为什么用 Agent 而不是端到端模型？

# 维度	Agent + Tools	端到端 (如CGAN生成像素)

# 可解释性	✅ 每步ReAct轨迹可见	❌ 黑盒

# 约束保证	✅ 验证器强制执行	❌ 需后处理

# 法规变更	✅ 改KG即可	❌ 需重新训练

# 数据需求	✅ 一本报告可运行	❌ 需千级样本

# 精度	✅ 图斑级	⚠️ 像素级(需后处理)

# 结论: 村庄规划场景中，规则明确、数据稀缺、需要可解释性 → Agent方案更适合。未来可引入CGAN做布局风格优化。

# 4.3 为什么用 MIP 而不是 LLM 直接生成？

# LLM 直接生成 "地块 #372 → 居住用地" 有两个问题:

# 幻觉: LLM可能将耕地划为建设 (违反基本农田约束)

# 不可验证: 无法保证总面积约束精确满足

# MIP求解器能保证:

# 所有硬约束 100% 满足

# 目标函数最优化

# 结果可复现

# LLM的角色: 不直接生成分配方案，而是:

# 解析报告 → 提取目标值和约束

# 定义优化目标 (如"优先保障粮食安全" → 调整ω权重)

# 解释结果 (自然语言说明为什么这样分配)

# 五、与现有代码的关系

# 保留并增强的模块

# 现有模块	新架构中的角色	改动

# ConflictDetector	→ Tool:check_constraint	改为从KG读取约束

# ConflictResolver	→ Tool:resolve_priority	改为KG推理

# ZoneGenerator	→ Tool:allocate_zones	核心算法改为MIP

# MapRenderer	→ Tool:render_layer	保持现有

# planning_intent.py	→ KG的ZoneDefinition实体	字段对齐KG schema

# semantics.py	→ KG的Indicator实体 + 语义映射	融入本体定义

# colors.py	→ 保持	无需改动

# content_extractor.py	→ Tool:extract_metrics / parse_tables	增强表格解析

# 新增模块

# 新模块	说明

# gis/layout/kg/ontology.py	OWL本体定义

# gis/layout/kg/builder.py	报告→KG构建器

# gis/layout/kg/query.py	SPARQL查询工具

# gis/layout/agent/planner.py	ReAct Agent (LangGraph)

# gis/layout/agent/tools.py	Tool Registry + 工具实现IS 布局引擎 V2 实施计划

> 基于 `docs/GIS_LAYOUT_ARCHITECTURE_V2.md` + 现有 2184 行代码，渐进式重构

---

## 一、现有代码资产（全部保留）

### 不改动的模块

| 文件                     | 行数 | 原因                                              |
| ------------------------ | ---- | ------------------------------------------------- |
| `colors.py`            | 241  | 颜色映射已完整 (现状DLBM + 规划DLBM + GHYTMC)     |
| `conflict_detector.py` | 345  | 三维冲突检测已完成                                |
| `conflict_resolver.py` | 299  | 优先级消解已完成                                  |
| `map_renderer.py`      | 186  | GISLayerConfig 渲染已完成                         |
| `planning_intent.py`   | 128  | ZoneIntent/FacilityIntent/AxisIntent 数据模型正确 |
| `__init__.py`          | 57   | 导出定义                                          |

### 需要改造的模块

| 文件                  | 行数 | 改造原因                                           |
| --------------------- | ---- | -------------------------------------------------- |
| `zone_generator.py` | 554  | 核心算法: DLBM重分类 →**约束驱动的MIP分配** |
| `engine.py`         | 374  | 编排逻辑: 直线管道 →**ReAct Agent循环**     |

### 新增模块

| 文件                               | 预计行数 | 功能                      |
| ---------------------------------- | -------- | ------------------------- |
| `layout/kg/builder.py`           | ~150     | 报告文本 → RDF知识图谱   |
| `layout/kg/query.py`             | ~80      | SPARQL查询 + LLM Tool接口 |
| `layout/optimizer/mip_solver.py` | ~200     | 地块分配MIP求解           |
| `layout/optimizer/procedural.py` | ~120     | 合并/拆分/简化几何        |
| `layout/agent/tool_registry.py`  | ~100     | 工具注册表 (10+ tools)    |
| `layout/agent/planner.py`        | ~150     | ReAct Agent (LangGraph)   |

---

## 二、创新点与可行性论证

### 创新 1: 规划知识图谱 (Planning KG)

**做什么**: 将报告的"永久基本农田 ≥ 78.83ha"这种自然语言约束，转化为:

```python
# KG Triple (RDF):
parcel_372 → constrained_by → permanent_farmland_rule
permanent_farmland_rule → min_area_ha → 78.83
permanent_farmland_rule → prohibits → "非农化建设"
```

**为什么创新**: 现有方法把约束藏在代码的 `if` 语句里；KG 让 LLM 可以通过 `query_kg(sparql)` 动态查询约束

**为什么可行**:

- RDFLib 是 Python 标准库 (`pip install rdflib`)，不需要独立图数据库
- SPARQL 查询可以直接作为 ReAct Agent 的 Tool
- 一本报告约产生 200-500 个 triple，SQLite 完全够用

### 创新 2: MIP 地块分配

**做什么**: 将"660个地块 → 7种规划用途"转化为优化问题:

```
目标: minimize Σ|分配面积_i - 目标面积_i|
约束: 建设用地 ≤ 30.5ha (from KG)
      永久基本农田 ≥ 78.83ha (from KG)
      生态红线内禁止建设 (spatial join)
      每个地块只能一种用途 (assignment)
```

**为什么创新**: 现有 ZoneGenerator 只是按 DLBM 归类 + union；MIP 求解器在约束下重新分配地块用途，输出自然不同于现状

**为什么可行**:

- `pulp` (Python MIP库) 对于 660个地块 × 7种用途的分配问题，求解时间 < 5秒
- 约束来自 KG，可追溯可修改
- LLM 不直接输出分配方案（避免幻觉），只定义优化目标权重

### 创新 3: ReAct Agent 编排

**做什么**: 用 LLM 的推理能力分解决策，用工具的确定性执行保证正确性

```
Planner LLM (推理):                     Tools (执行):
  "需要先查询永久基本农田约束"  →    query_kg("永久基本农田") 
  "当前耕地 85.2ha，满足约束"   →    check_constraint(...)
  "现在运行MIP分配"            →    solve_mip(targets, constraints)
  "验证结果"                  →    validate_layout(...)
  "建设用地 30.50ha ✓"        →    (done)
```

**为什么创新**: LLM 扮演规划师角色（分析报告、设定目标），MIP 扮演工程师角色（精确求解约束）

**为什么可行**: DemoLand (Turing Institute) 已验证了这个模式；MapAgent 验证了 LLM+GIS工具编排

---

## 三、迭代实施（4 个 Phase，共 6-8 天）

### Phase 1: Planning KG (1-2 天) — 最小可行

**目标**: 将 1 份 L3 报告构建为可查询的 KG

```
新增文件:
  layout/kg/__init__.py
  layout/kg/builder.py        # 报告→KG构建器
  layout/kg/query.py           # SPARQL工具

修改文件:
  无 (纯新增)
```

**具体实现**:

```python
# layout/kg/builder.py

class PlanningKnowledgeGraph:
    """基于 RDFLib 的规划知识图谱"""
  
    def __init__(self):
        from rdflib import Graph, Namespace
        self.g = Graph()
        self.PLN = Namespace("http://village-planning.org/")
  
    def add_parcel(self, bsm, dlbm, dlmc, area_ha, geometry_wkt):
        """添加地块实体"""
        parcel = self.PLN[f"parcel_{bsm}"]
        self.g.add((parcel, RDf.type, self.PLN.Parcel))
        self.g.add((parcel, self.PLN.dlbm, Literal(dlbm)))
        self.g.add((parcel, self.PLN.dlmc, Literal(dlmc)))
        self.g.add((parcel, self.PLN.area_ha, Literal(area_ha)))
  
    def add_constraint(self, name, field, operator, value, source_report):
        """添加约束实体 (从报告提取)"""
        c = self.PLN[f"constraint_{name}"]
        self.g.add((c, RDF.type, self.PLN.Constraint))
        self.g.add((c, self.PLN.constrains_field, Literal(field)))
        self.g.add((c, self.PLN.operator, Literal(operator)))
        self.g.add((c, self.PLN.target_value, Literal(value)))
        self.g.add((c, self.PLN.source, Literal(source_report)))
  
    def build_from_reports(self, reports, landuse_geojson):
        """一键构建: 从DB报告 + GIS数据构建完整KG"""
        # 1. 添加660个地块
        for feat in landuse_geojson['features']:
            self.add_parcel(...)
      
        # 2. 从报告提取约束
        for dk, report in reports.items():
            metrics = report['summary'].get('metrics', {})
            for key, val in metrics.items():
                if '建设用地' in key:
                    self.add_constraint('construction_cap', key, '<=', val, dk)
                elif '基本农田' in key:
                    self.add_constraint('farmland_min', key, '>=', val, dk)
                # ... more patterns
      
        # 3. 添加空间关系 (adjacent_to from GeoDataFrame)
        # spatial join to find neighboring parcels
  
    def query(self, sparql):
        """执行SPARQL查询，返回字典"""
        results = self.g.query(sparql)
        return [dict(row) for row in results]
```

```python
# layout/kg/query.py

# 预定义常用查询模板
QUERY_TEMPLATES = {
    "get_constraints": """
        SELECT ?name ?field ?op ?value 
        WHERE { ?c a pln:Constraint ; pln:name ?name ; 
                pln:constrains_field ?field ; pln:operator ?op ; 
                pln:target_value ?value }
    """,
    "get_parcels_by_type": """
        SELECT ?parcel ?area 
        WHERE { ?parcel a pln:Parcel ; pln:dlbm ?dlbm ; pln:area_ha ?area .
                FILTER(?dlbm = '{dlbm}') }
    """,
    "count_protected_parcels": """
        SELECT (COUNT(?p) as ?count) (SUM(?area) as ?total_area)
        WHERE { ?p pln:constrained_by ?c . ?c pln:prohibits ?action . 
                ?p pln:area_ha ?area . }
    """,
}

def query_kg(sparql: str, kg=None):
    """Tool: 查询规划知识图谱"""
    if kg is None:
        raise ValueError("KG not initialized")
    return kg.query(sparql)
```

**验证**: 运行 `test_kg_builder.py` → SPARQL 查询返回正确约束值

### Phase 2: MIP Optimizer (2 天) — 核心突破

**目标**: 替代 ZoneGenerator 的 DLBM重分类，用约束求解分配地块

```
新增文件:
  layout/optimizer/__init__.py
  layout/optimizer/mip_solver.py    # MIP求解器

修改文件:
  zone_generator.py → 调用 MIP solver 替代 _classify_parcels + _build_zone_feature
```

**具体实现**:

```python
# layout/optimizer/mip_solver.py

from pulp import LpProblem, LpMinimize, LpVariable, lpSum, value, PULP_CBC_CMD

class MIPZoneAllocator:
    """MIP-based zone allocation optimizing land use assignment."""
  
    def solve(self, parcels, targets, constraints, kg=None):
        """
        Args:
            parcels: GeoDataFrame (660 features)
            targets: {zone_type: target_area_ha}  (7 types)
            constraints: list of Constraint objects from KG
            kg: PlanningKnowledgeGraph
      
        Returns:
            GeoDataFrame with 'assigned_zone' column
        """
        prob = LpProblem("ZoneAllocation", LpMinimize)
      
        # Decision vars: x[i][j] = 1 if parcel i assigned to zone j
        x = {}
        for i in parcels.index:
            for j, zone_type in enumerate(targets.keys()):
                x[(i, zone_type)] = LpVariable(f"x_{i}_{j}", cat='Binary')
      
        # Constraint 1: each parcel → exactly one zone
        for i in parcels.index:
            prob += lpSum(x[(i, zone_type)] for zone_type in targets) == 1
      
        # Constraint 2: zone area ≈ target (soft)
        area_vars = {}
        for zone_type, target_area in targets.items():
            actual = lpSum(
                parcels.loc[i, 'area_ha'] * x[(i, zone_type)]
                for i in parcels.index
            )
            # Slack variables for deviation
            over = LpVariable(f"over_{zone_type}", lowBound=0)
            under = LpVariable(f"under_{zone_type}", lowBound=0)
            prob += actual - target_area == over - under
            area_vars[zone_type] = (over, under)
      
        # Objective: minimize total deviation
        prob += lpSum(over + under for over, under in area_vars.values())
      
        # Constraint 3: hard constraints from KG
        for c in constraints:
            if c.type == 'construction_cap':
                construction_area = lpSum(
                    parcels.loc[i, 'area_ha'] * x[(i, '居住用地')]
                    + parcels.loc[i, 'area_ha'] * x[(i, '产业用地')]
                    + ...
                )
                prob += construction_area <= c.value
      
        # Solve
        prob.solve(PULP_CBC_CMD(msg=False))
      
        # Assign results
        parcels['assigned_zone'] = parcels.index.map(
            lambda i: next(
                zone_type for zone_type in targets
                if value(x[(i, zone_type)]) > 0.5
            )
        )
        return parcels
```

**改造 zone_generator.py**:

```python
# 旧代码 (Phase 1):
parcel_zones = self._classify_parcels(landuse_gdf)  # DLBM→zone_type
features = [self._build_zone_feature(...)]           # 合并相同类型的几何

# 新代码 (Phase 2):
targets = {z.land_use: z.area_ratio * total_area for z in intent.zones}
allocated = self.mip_solver.solve(parcels, targets, constraints, kg)
features = self._build_from_allocation(allocated)  # 按MIP分配合并
```

**验证**:

- 建设用地 ≤ 30.5ha (硬约束100%满足)
- 面积偏差 < 5%
- 规划图与现状图有明显差异 (assigned_zone ≠ DLBM分类)

### iPhase 3: Agent Layer (1-2 天) — 编排层

**目标**: 用 ReAct Agent 替代硬编码 pipeline

```
新增文件:
  layout/agent/__init__.py
  layout/agent/tools.py           # 10+ tool definitions
  layout/agent/planner.py         # LangGraph ReAct agent

修改文件:
  engine.py → 调用 Agent 替代顺序调用
```

**Tool 定义** (直接包装现有函数):

```python
# layout/agent/tools.py

from langchain.tools import tool

@tool
def query_kg(query_str: str) -> dict:
    """查询规划知识图谱。输入SPARQL查询，返回三元组列表。
    用于：检查约束值、查询地块属性、验证空间关系"""
    from ..kg.query import execute_sparql
    return execute_sparql(query_str)

@tool  
def extract_metrics(report_content: str, metric_names: list) -> dict:
    """从报告文本提取指标值。返回 {指标名: 值} 字典"""
    from ..planning_text.content_extractor import extract_metrics
    return extract_metrics(report_content, metric_names)

@tool
def allocate_zones(parcels_geojson: str, targets: dict, constraints: list) -> str:
    """MIP地块分配。输入地块GeoJSON+目标面积+约束，返回分配方案GeoJSON"""
    from ..optimizer.mip_solver import MIPZoneAllocator
    allocator = MIPZoneAllocator()
    result = allocator.solve(parcels, targets, constraints)
    return json.dumps(geodataframe_to_geojson(result))

@tool
def validate_layout(layout_geojson: str, constraints: list) -> dict:
    """验证生成布局是否满足约束。返回 {通过: bool, 违规: [...]}"""
    # 检查每个约束
    ...

# ... 10+ tools total
```

**Agent 定义**:

```python
# layout/agent/planner.py

from langgraph.prebuilt import create_react_agent

class SpatialPlanningAgent:
    def __init__(self, kg, tools):
        self.kg = kg
        self.agent = create_react_agent(
            model=ChatOpenAI(model="gpt-4o"),
            tools=tools,
            prompt=PLANNER_SYSTEM_PROMPT,
        )
  
    def plan(self, intent: UnifiedSpatialIntent, reports: dict) -> dict:
        """主入口: 给定意图+报告 → 生成规划布局"""
        result = self.agent.invoke({
            "messages": [
                ("system", PLANNER_SYSTEM_PROMPT),
                ("user", f"生成金田村规划布局。目标分区: {intent.zones}。报告摘要: {reports}")
            ]
        })
        return result
```

**改造 engine.py**:

```python
# 旧代码:
def generate_layout(self, intent, ...):
    function_zone = self.zone_generator.generate(intent, ...)
    configs = self.map_renderer.render(function_zone, ...)
    return configs

# 新代码:
def generate_layout(self, intent, reports, ...):
    # 如果没有KG，先构建
    if not self.kg:
        self.kg = build_kg_from_reports(reports, landuse)
  
    # Agent 编排 (替代硬编码顺序调用)
    result = self.agent.plan(intent, reports)
  
    # 渲染输出
    configs = self.map_renderer.render(result['layers'])
    return configs, result['reasoning_trace']
```

### Phase 4: 集成验证 (1 天)

```
目标: 
  1. 全管道对金田村 session dc2a2e0e 运行
  2. 与 project_layout_clean.svg 对比
  3. 验证 6 项量化指标
```

---

## 四、验证指标

| # | 指标         | 计算方式                                     | 目标           |
| - | ------------ | -------------------------------------------- | -------------- |
| 1 | 硬约束满足率 | passed/total                                 | **100%** |
| 2 | 面积偏差     | Σ\|actual-target\|/total                    | < 5%           |
| 3 | 变化可见度   | assigned≠original parcels/total             | > 10%          |
| 4 | MIP求解时间  | wall clock                                   | < 10s          |
| 5 | 现有测试通过 | test_zone_generator + test_semantic_conflict | 10/10          |
| 6 | KG查询正确性 | SPARQL结果 vs 报告原文                       | 100%           |

---

## 五、文件变更清单

```
新增 (6 files):
  layout/kg/__init__.py
  layout/kg/builder.py          (~150 lines)
  layout/kg/query.py            (~80 lines)
  layout/optimizer/__init__.py
  layout/optimizer/mip_solver.py (~200 lines)
  layout/agent/tools.py         (~100 lines)

修改 (2 files):
  zone_generator.py → 调用 MIP solver (约改 50 行)
  engine.py → 集成 KG + Agent (约改 30 行)

不改 (7 files):
  colors.py, conflict_detector.py, conflict_resolver.py,
  map_renderer.py, planning_intent.py, __init__.py, 
  geojson_utils.py

新增依赖:
  rdflib, pulp (pip install)
```

---

## 六、Phase 1 第一步: KG构建器

从现有代码直接起步:

**输入**: `landuse_current.geojson` (660 parcels) + DB reports (12 dimensions × 最新版本)

**输出**: 一个 RDFLib Graph 对象，可通过 `kg.query(sparql)` 查询

**从现有代码复用**:

- `geojson_utils.geojson_to_geodataframe()` → 读取地块
- `colors.py` 的 DLBM/ZONE_TYPE 映射 → 补全实体属性
- `semantics.py` 的 CROSS_DIMENSION_METRICS → 约束概念定义

**从报告提取约束的具体模式**:

| 报告文本模式                                 | → KG约束                              |
| -------------------------------------------- | -------------------------------------- |
| "建设用地规模控制在 30.5 公顷以内"           | construction_cap ≤ 30.5               |
| "耕地保有量 85.2 公顷"                       | farmland_min ≥ 85.2                   |
| "永久基本农田 78.83 公顷保护任务"            | permanent_farmland ≥ 78.83            |
| "生态保护红线面积 362.02 公顷，实行严格管控" | ecological_redline ≥ 362.02; 禁止开发 |
| "森林覆盖率不低于 90%"                       | forest_coverage ≥ 90%                 |
| "新增建设用地 0.33 公顷"                     | construction_expansion = 0.33          |
| "园寨自然村（废弃小学旧址）"                 | project_site = POINT(园寨 centroid)    |

---

## 七、实施状态总结（2026-06-25 更新）

### 7.1 实际完成情况

| Phase | 计划目标 | 实际完成 | 状态 |
|-------|----------|----------|------|
| Phase 1: Planning KG | KG 构建器 + SPARQL 查询 | `kg/builder.py` + `kg/query.py` + 9 个查询模板 + `to_turtle`/`from_turtle` 序列化 | ✅ 完成 |
| Phase 2: MIP Optimizer | PuLP 混合整数规划 | `optimizer/mip_allocator.py` (PuLP CBC, 30s 超时) + `mip_solver.py` 的 `mode="mip"` 路由 | ✅ 完成 |
| Phase 3: 缺失模块 | facility/axis/procedural | `facility_placer.py` (4 策略) + `axis_builder.py` (一核一带三区) + `optimizer/procedural.py` (6 几何工具) | ✅ 完成 |
| Phase 4: Agent 集成 | ReAct Agent + 工具 | `agent/gis/` 子图 + `tools/gis/layout_tools.py` (6 工具) + `validator.py` (5 类验证) | ✅ 完成 |
| Phase 5: 测试 + 文档 | 单元测试 + 文档更新 | `tests/test_gis_validator.py` (16) + `tests/test_gis_layout_tools.py` (14) + 本文档更新 | ✅ 完成 |

### 7.2 关键技术决策修正

| 计划中的设计 | 实际实现 | 原因 |
|--------------|----------|------|
| `Command(update={...}, result=...)` | `Command(update={..., "messages": [ToolMessage(...)]})` | LangGraph 1.2 的 `Command` **没有 `result` 参数**，LLM 可见内容必须通过 `update["messages"]` 里的 `ToolMessage` 传递 |
| module-level dict 共享 KG | `InjectedState("kg_turtle")` + Turtle 序列化 | LangGraph 官方不推荐 module-level globals（破坏 checkpointing），`InjectedState` 是 1.x 推荐模式 |
| `create_react_agent` 默认 state | `state_schema=GISAgentState` 必需 | 不传 `state_schema`，`Command(update={...})` 的自定义字段会被静默丢弃——这是 V1 最严重的 bug |
| LLM 传 GeoJSON 参数 | `InjectedState` 注入大对象 | 1-2MB GeoJSON 进 LLM 上下文会膨胀，`InjectedState` 让参数对 LLM 不可见 |
| 无 `InjectedToolCallId` | `tool_call_id: Annotated[str, InjectedToolCallId]` | `ToolMessage` 必须匹配 `tool_call_id`，否则 ToolNode 校验失败 |

### 7.3 依赖版本

```
langgraph       1.0.8 → 1.2.6  (升级)
langchain       1.1.0 → 1.3.11 (升级)
langchain-core  → 1.4.8
langchain-openai → 1.3.3
rdflib          (已有)
pulp            (已有)
geopandas/shapely (已有)
```

### 7.4 验证结果

```bash
cd backend && python -m pytest tests/ -v
# 30 passed in 6.35s

# 测试覆盖:
# - LayoutValidator: 5 类验证 × 多场景 = 16 tests
# - layout_tools: Command/ToolMessage/InjectedState/dict_to_intent = 14 tests
```

### 7.5 文件清单（实际）

```
新增 (10 files):
  app/agent/gis/__init__.py
  app/agent/gis/graph.py              # create_react_agent + state_schema
  app/agent/gis/state.py              # GISAgentState TypedDict
  app/agent/gis/prompts.py            # ReAct system prompt
  app/tools/gis/layout_tools.py       # 6 @tool (InjectedState + Command)
  app/services/modules/gis/layout/kg/ (3 files: ontology/builder/query)
  app/services/modules/gis/layout/optimizer/mip_allocator.py   # PuLP MIP
  app/services/modules/gis/layout/optimizer/procedural.py      # 6 几何工具
  app/services/modules/gis/layout/facility_placer.py           # 设施选址
  app/services/modules/gis/layout/axis_builder.py              # 发展轴
  app/services/modules/gis/layout/validator.py                 # 5 类验证
  backend/tests/test_gis_validator.py      (16 tests)
  backend/tests/test_gis_layout_tools.py   (14 tests)

修改:
  app/services/modules/gis/layout/engine.py   # 集成 FacilityPlacer/AxisBuilder，删除死代码
  app/services/modules/gis/layout/optimizer/__init__.py  # 导出 MIPZoneAllocator + procedural
  app/services/modules/gis/layout/kg/builder.py  # 加 to_turtle/from_turtle
  app/services/modules/gis/layout/optimizer/mip_solver.py  # 加 mode="mip" 路由
  app/agent/graph.py                          # gis_agent_node 适配新 state
```

### 7.6 后续工作

- [ ] 端到端集成测试（真实 L3 报告 + 真实 GIS 数据）
- [ ] MIP vs greedy 对比基准（面积偏差、求解时间）
- [ ] 前端 7 层渲染验证
- [ ] validate_layout 失败重试循环测试

