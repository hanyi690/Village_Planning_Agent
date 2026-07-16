# Agent 改造架构设计 — 适配 DESIGN_GOALS v5.0 统一操作引擎

## Context

当前 GIS Agent 采用"PARSE ReAct + LAYOUT 混合管线"架构，管线步骤为：
`parse → fetch → KG → conflicts → allocate_and_generate(ReAct) → validate → export → render`

设计文档 (DESIGN_GOALS v5.0 / GENERATION_REFACTOR_PLAN v3.0 / OUTPUT_ARCHITECTURE v3.0) 要求：
1. **统一生产路径**：所有规划文本解析为 OperationSequence + ConstraintSet，通过 EXECUTE_OPERATIONS 逐条执行
2. **5种原子操作**：create/split/merge/modify/reclassify 作为统一指令集
3. **MIP 降级为辅助 tool**：optimize_allocation，由执行引擎按需调用
4. **删除 planning_zone 独立层**：6类分区信息保留在 ParcelReclass 的 assigned_zone 字段
5. **操作执行引擎**：OperationEngine + 变更日志 + 人工确认

**核心问题**：当前 `allocate_and_generate` 节点是一个 ReAct 子图，内部调用 11 个 tool，但 LLM 决策空间过大（gen/plan 结果趋同），且缺少 OperationSequence 概念。需要将"LLM 自由决策分配策略"改为"LLM 解析文本→生成操作序列→确定性执行引擎逐条执行"。

---

## 一、Agent 图重构

### 1.1 新管线拓扑

```
START
  → parse_intent          (确定性节点，直接从 state 取 PARSE Agent 的输出，不再二次解析)
  → fetch_gis_data        (确定性节点，同现有)
  → build_kg              (确定性节点，ConstraintSet → KG 约束三元组)
  → detect_conflicts      (确定性节点，跨维度冲突检测)
  → execute_operations    (ReAct 子图，LLM 自适应执行操作序列)
  → validate_layout       (Evaluator Gate，强制验证，最多3轮)
  → export_gdb            (确定性节点)
  → render_map            (确定性节点)
  → END
```

**关键变更**：
- `allocate_and_generate` → `execute_operations`：从"LLM 自由调用11个tool"改为"LLM 在操作序列约束下执行5种原子操作"
- ReAct 子图的 tool 从 11 个缩减为 6 个（5种原子操作 + 1个MIP辅助工具）
- 新增 `operation_sequence` 和 `constraint_set` 状态字段

### 1.2 execute_operations ReAct 子图设计

```
execute_operations 节点内部：
  LLM 接收 OperationSequence + ConstraintSet + KG约束
  LLM 逐条决策：
    1. 对每个 operation，先调用 check_compliance 合规预检
    2. 批量场景(660 reclassify) → 调用 optimize_allocation 辅助工具
    3. 逐条场景(1-5 操作) → 直接调用 edit_parcel 执行
    4. 需要空间定位 → 调用 resolve_place_name
    5. 需要编码查表 → 调用 lookup_land_use_code
  输出：updated_layers (06/10/11/13层) + changelog
```

### 1.3 主图 gis_agent_node 变更

当前 `gis_agent_node` (graph.py:52-146) 依次调用 PARSE Agent + LAYOUT Pipeline。
改造后保持双子图架构，但 PARSE Agent 和 LAYOUT Pipeline 各自升级：

**双 Agent 架构设计理由**：

| 维度 | PARSE Agent（文本领域） | LAYOUT Pipeline（空间领域） |
|------|------------------------|---------------------------|
| 领域 | 自然语言理解，规划文本解析 | 空间操作执行，GIS 图层生成 |
| LLM 使用 | 半结构化 ReAct（classify→route→extract→validate） | 确定性骨架 + ReAct 子图（execute_operations） |
| 可用 Tool | parse_planning_text, extract_structured_text, lookup_land_use_code | edit_parcel, optimize_allocation, resolve_place_name, check_compliance, query_knowledge_graph |
| GIS 数据 | 注入 GIS 现状摘要（统计信息，不含几何） | 使用完整 GIS 数据（含几何） |
| 输出 | OperationSequence + ConstraintSet + IntentJSON（Pydantic 严格 Schema） | allocated_geojson + layout_configs + changelog |
| 通信方式 | state 注入（Pydantic 输出 → LAYOUT Pipeline 输入） | 管线内部 state 流转 |

**为什么 PARSE Agent 采用半结构化 ReAct**：
- 规划文本解析不是一次 LLM 调用能完成的——可能需要先 `extract_structured_text` 处理表格，再 `lookup_land_use_code` 查编码，多次调整
- 纯 ReAct 无法保证步骤完整性（LLM 可能跳过校验或遗漏某类提取）
- 半结构化 ReAct（classify → route → extract → validate）保证步骤完整性，同时允许 LLM 判断路由
- 文本领域和空间领域是正交关注点，不应合并

**改造后架构**：

```
主图 (graph.py)
  └── gis_agent_node
        ├── Step 1: PARSE Agent (半结构化 ReAct, 3 tools)
        │     子图: classify_sections → route_by_section → extract_* → validate_and_merge
        │     tools: parse_planning_text, extract_structured_text, lookup_land_use_code
        │     输入: planning_text + gis_data_summary (GIS 现状摘要)
        │     输出: operation_sequence + constraint_set + intent_json (Pydantic 严格 Schema)
        │
        └── Step 2: LAYOUT Pipeline (StateGraph, 8 nodes)
              ├── parse_intent        ← 纯透传节点（直接从 state 取 PARSE 结果，零逻辑）
              ├── fetch_gis_data
              ├── build_kg
              ├── detect_conflicts
              ├── execute_operations   ← ReAct 子图（5 tools）
              ├── validate_layout
              ├── export_gdb
              └── render_map
```

### 1.4 PARSE Agent 子图拓扑

PARSE Agent 采用半结构化 ReAct（确定性骨架 + LLM 节点内可调用 tool）：

```
START
  → classify_sections    (LLM 节点：文档结构分类 → section_map)
  → route_by_section     (条件边：按 section_type 路由)
     ├── extract_regulations   (LLM 节点 → ConstraintSet)
     ├── extract_tables        (LLM 节点 + extract_structured_text → 结构化 JSON)
     ├── extract_projects      (LLM 节点 + lookup_land_use_code → OperationSequence)
     └── extract_targets       (LLM 节点 → IntentJSON)
  → validate_and_merge   (LLM 节点：校验一致性 + 合并结果)
  → should_retry         (条件边：通过→END，失败→retry，最多2轮)
  → END
```

**设计理由**：
- 纯 ReAct 无法保证步骤完整性（LLM 可能跳过校验）
- 纯 StateGraph 无法处理异构文档（需 LLM 判断路由）
- 半结构化兼得两者优势
- GIS 现状摘要注入 classify 和 extract 节点，锚定自然村名/地类面积，防止 LLM 幻觉
- DictionaryCenter 编码表注入 extract_projects 节点，保证用途名称标准性

**PARSE Agent 工具集（3个）**：

| Tool | 作用 |
|------|------|
| `parse_planning_text` | 主解析：规划文本 → IntentJSON + OperationSequence + ConstraintSet（GIS-aware，注入现状摘要+DictionaryCenter） |
| `extract_structured_text` | 辅助：表格类文本（建设项目表/用地指标表/经营性指标表）→ 结构化 JSON（6种表格类型） |
| `lookup_land_use_code` | 辅助：用途名称 → GHYTBM 标准编码 + VNE 编码 + 规划分区映射（DictionaryCenter 查表，不做自动映射） |

**主图 gis_agent_node 改造**：

```python
# 改造后：双子图，全新接口（不兼容旧构造）
async def gis_agent_node(state):
    # Step 0: 构建 GIS 现状摘要（只统计，不传几何）
    gis_summary = _build_gis_summary(gis_data)  # {parcel_count, current_landuse_stats, natural_villages, ...}

    # Step 1: PARSE Agent (半结构化 ReAct — 文本领域)
    parse_graph = create_parse_agent_graph()  # classify→route→extract→validate
    parse_result = await parse_graph.ainvoke({
        "session_id": session_id,
        "village_name": village_name,
        "planning_text": reports_text,
        "gis_data_summary": gis_summary,  # GIS 现状注入
        "messages": [],
    })

    operation_sequence = parse_result.get("operation_sequence", [])
    constraint_set = parse_result.get("constraint_set", [])
    intent_json = parse_result.get("intent_json", {})
    
    if not intent_json and not operation_sequence:
        return {"messages": [AIMessage(content="规划意图解析失败")]}

    # Step 2: LAYOUT Pipeline (空间领域)
    pipeline = build_layout_pipeline()
    layout_result = await pipeline.ainvoke({
        "session_id": session_id,
        "village_name": village_name,
        "gis_data": gis_data,
        "intent": intent_json,
        "operation_sequence": operation_sequence,  # 新增
        "constraint_set": constraint_set,            # 新增
        ...
    })
```

---

## 二、State 扩展

### 2.1 GISPipelineState 新增字段

```python
class GISPipelineState(BaseModel):
    # ── 现有字段保持不变 ──
    session_id: str = ""
    village_name: str = ""
    reports: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    gis_data: Dict[str, Optional[Dict[str, Any]]] = Field(default_factory=dict)
    intent: Dict[str, Any] = Field(default_factory=dict)
    intent_json: Dict[str, Any] = Field(default_factory=dict)
    kg_turtle: str = ""
    kg_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    validation_round: int = 0
    export_result: Dict[str, Any] = Field(default_factory=dict)
    render_result: List[Dict[str, Any]] = Field(default_factory=list)
    messages: List[Any] = Field(default_factory=list)

    # ── 新增字段 ──
    # 操作序列（PARSE 输出）
    operation_sequence: List[Dict[str, Any]] = Field(default_factory=list)
    # 约束集（PARSE 输出）
    constraint_set: List[Dict[str, Any]] = Field(default_factory=list)
    # 变更日志（EXECUTE_OPERATIONS 输出）
    changelog: List[Dict[str, Any]] = Field(default_factory=list)
    # 待确认操作队列（人工确认机制）
    pending_confirmations: List[Dict[str, Any]] = Field(default_factory=list)
    # 规划文本（新增输入）
    planning_text: str = ""
    l3_reports: Dict[str, Any] = Field(default_factory=dict)
```

### 2.2 GISPipelineInput 新增字段

```python
class GISPipelineInput(BaseModel):
    session_id: str = ""
    village_name: str = ""
    planning_text: str = ""           # 规划报告文本
    l3_reports: Dict[str, Any] = Field(default_factory=dict)  # L3报告
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

---

## 三、Tool 迁移方案

### 3.1 迁移原则

| 层级 | 职责 | 是否迁移为 @tool |
|------|------|-----------------|
| **Agent 编排层** (`agent/gis/`) | 图构建、节点定义、路由 | 保持，重构内容 |
| **Tool 层** (`tools/gis/`) | LLM 可调用的原子操作 | 新增6个tool，删除2个 |
| **服务层** (`modules/gis/`) | 纯计算逻辑，LLM不可直接调用 | 保留，部分提取为tool的内部实现 |

### 3.2 原 14 Tool → 新架构完整迁移映射

| # | 原 Tool | 作用 | 迁移方案 | 新 Tool / 去向 |
|---|---------|------|---------|---------------|
| 1 | `fetch_gis_data` | 获取天地图/OSM/高德 GIS 数据 | **保留**，管线确定性节点调用 | `fetch_gis_data` |
| 2 | `search_poi` | POI 兴趣点搜索 | **保留**，被 `resolve_place_name` 内部复用 | `search_poi` |
| 3 | `calculate_gis_coverage` | GIS 数据覆盖率计算 | **保留**，分析类辅助工具 | `calculate_gis_coverage` |
| 4 | `analyze_accessibility` | 空间可达性分析 | **保留**，分析类辅助工具 | `analyze_accessibility` |
| 5 | `parse_planning_text` | LLM 解析规划文本 → intent | **改造**：输出增加 `operation_sequence` + `constraint_set` | `parse_planning_text`（扩展输出） |
| 6 | `build_knowledge_graph` | 构建 RDF 知识图谱 | **保留**，管线确定性节点 | `build_knowledge_graph` |
| 7 | `query_knowledge_graph` | SPARQL 查询 KG 约束 | **保留**，execute_operations ReAct 内可调用 | `query_knowledge_graph` |
| 8 | `detect_conflicts` | 跨维度冲突检测 | **保留**，管线确定性节点 | `detect_conflicts` |
| 9 | `allocate_zones` | MIP 分配 6 规划分区 | **降级改造**：去掉 InjectedState，改为显式参数 | → `optimize_allocation`（辅助工具） |
| 10 | `generate_layout` | 6 层一次性生成 | **删除**：6 层生成逻辑拆散到操作引擎 + 各 generator | → `edit_parcel` + 各 generator |
| 11 | `validate_layout` | 8 项空间验证 | **保留**，Evaluator Gate 节点 | `validate_layout` |
| 12 | `export_gdb` | 导出 12 层 GeoJSON + 用地平衡表 | **保留**，管线确定性节点 | `export_gdb` |
| 13 | `render_map` | 渲染 MapLibre 图层 | **保留**，管线确定性节点 | `render_map` |

**generate_layout 6 层逻辑拆解**：

| 原 generate_layout 内部层 | 新架构归属 |
|--------------------------|-----------|
| `_generate_function_zones` → ZoneGenerator | → `ParcelReclassGenerator`（20 字段升级） |
| `_make_planning_zone_layer` | **删除**，信息保留在 ParcelReclass.assigned_zone |
| `_generate_facilities` → FacilityPlacer | 保留为 `FacilityPlacer`，由 execute_operations 调用 |
| `_generate_axes` → AxisBuilder | 保留为可视化叠加，不独立成层 |
| `_generate_space_control_zone` → SpaceControlZoneGenerator | 保留，由 execute_operations 调用 |
| `_generate_land_use_zone` → LandUseZoneGenerator | 保留，由 execute_operations 调用 |

#### 新增 Tool（5个，替代 generate_layout + allocate_zones）

| # | Tool 名 | 文件 | 功能 | 内部复用 |
|---|---------|------|------|---------|
| 1 | `edit_parcel` | `tools/gis/operations.py` | 5种原子操作(create/split/merge/modify/reclassify) | Shapely + GeoPandas |
| 2 | `optimize_allocation` | `tools/gis/allocate.py` (改造) | MIP辅助工具，批量场景按需调用 | MIPZoneAllocator |
| 3 | `resolve_place_name` | `tools/gis/place_resolver.py` | 空间地名解析：自然语言→候选图斑 | Amap POI + place_aliases.yaml |
| 4 | `lookup_land_use_code` | `tools/gis/code_lookup.py` | 规划用途字典：名称→编码+约束 | DictionaryCenter |
| 5 | `check_compliance` | `tools/gis/compliance.py` | 合规预检：拟操作图斑→实时检测 | ConflictDetector |

#### 改造 Tool（2个）

| # | Tool 名 | 改动 | 说明 |
|---|---------|------|------|
| 1 | `parse_planning_text` | 输出增加 operation_sequence + constraint_set | 从只输出 intent 扩展为输出 OperationSequence + ConstraintSet |
| 2 | `allocate_zones` → `optimize_allocation` | 降级为辅助工具，去掉 InjectedState 自动注入 | 不再是管线独立步骤，由 execute_operations 按需调用 |

#### 新增独立辅助 Tool（1个）

| # | Tool 名 | 文件 | 功能 | 说明 |
|---|---------|------|------|------|
| 1 | `extract_structured_text` | `tools/gis/extract.py` | 表格文本→结构化JSON | 建设项目表/用地指标表解析，PARSE 阶段使用 |

#### 删除 Tool（2个）

| # | Tool 名 | 原因 |
|---|---------|------|
| 1 | `generate_layout` | 被 execute_operations + edit_parcel + 各 generator 替代 |
| 2 | `allocate_zones` | 重命名为 optimize_allocation，降级为辅助工具 |

#### 保留 Tool（8个，不改动）

`fetch_gis_data`, `search_poi`, `build_knowledge_graph`, `query_knowledge_graph`, `detect_conflicts`, `validate_layout`, `export_gdb`, `render_map`

#### 保留但降级为非管线 Tool（2个，仅按需调用）

`calculate_gis_coverage`, `analyze_accessibility`

### 3.3 新增 Tool 接口签名

#### edit_parcel（核心 — 5种原子操作）

```python
@tool
def edit_parcel(
    action: Literal["create", "split", "merge", "modify", "reclassify"],
    # create 参数
    area_sqm: Optional[float] = None,
    land_use_name: Optional[str] = None,
    location_desc: Optional[str] = None,
    # split 参数
    source_bsm: Optional[str] = None,
    split_ratio: Optional[float] = None,
    # merge 参数
    source_bsms: Optional[List[str]] = None,
    # modify/reclassify 参数
    field_changes: Optional[Dict[str, Any]] = None,
    new_qmdlbm: Optional[str] = None,
    # 通用
    gis_data: Annotated[Dict, InjectedState("gis_data")] = None,
    allocated_geojson: Annotated[Optional[Dict], InjectedState("allocated_geojson")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Execute a parcel edit operation (create/split/merge/modify/reclassify).

    Returns updated layers + changelog entry.
    """
```

#### resolve_place_name

```python
@tool
def resolve_place_name(
    location_desc: str,
    village_name: Annotated[str, InjectedState("village_name")] = "",
    gis_data: Annotated[Dict, InjectedState("gis_data")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Resolve natural language place description to candidate parcel list.

    Uses: local alias DB (place_aliases.yaml) + Amap POI + spatial reasoning.
    """
```

#### lookup_land_use_code

```python
@tool
def lookup_land_use_code(
    land_use_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Look up planning use code from DictionaryCenter.

    Returns: GHYTBM code + GHYTMC name + constraints + candidates.
    Does NOT auto-map; returns proposal list for human selection.
    """
```

#### check_compliance

```python
@tool
def check_compliance(
    parcel_bsm: str,
    proposed_action: str,
    new_qmdlbm: Optional[str] = None,
    gis_data: Annotated[Dict, InjectedState("gis_data")] = None,
    kg_constraints: Annotated[List, InjectedState("kg_constraints")] = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Check compliance before executing a parcel operation.

    Checks: three-zone-three-line, construction boundary, current land use.
    Returns: compliance report (pass/fail + violation details).
    """
```

#### extract_structured_text

```python
@tool
def extract_structured_text(
    text: str,
    text_type: Literal["project_table", "indicator_table", "regulation"] = "project_table",
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Extract structured JSON from tabular planning text.

    For: construction project tables, land use indicator tables, regulations.
    """
```

---

## 四、数据流重构

### 4.1 当前数据流

```
reports → parse_planning_text → intent_json (zones/facilities/axes/constraints)
    ↓
intent → MIPZoneAllocator.solve(targets) → allocated_geojson
    ↓
allocated_geojson + intent → generate_layout → 6层 (function_zone/planning_zone/facility/axis/space_control/land_use_zone)
    ↓
layout_configs → validate → export → render
```

### 4.2 新数据流

```
reports + planning_text → parse_intent → OperationSequence + ConstraintSet + intent_json
    ↓
ConstraintSet → build_kg → kg_constraints (约束三元组)
    ↓
kg_constraints → detect_conflicts → conflict_report
    ↓
OperationSequence + kg_constraints + gis_data → execute_operations (ReAct)
    ├── 批量场景: 660 reclassify → optimize_allocation (MIP) → ParcelReclassGenerator
    ├── 逐条场景: 1-5 create/split → edit_parcel → 直接执行
    ├── 空间定位: resolve_place_name
    ├── 编码查表: lookup_land_use_code
    └── 合规预检: check_compliance
    ↓
输出: allocated_geojson (20字段) + space_control + land_use_zone + facility + road_plan + changelog
    ↓
layout_configs → validate → export (14层) → render
```

### 4.3 关键数据流变更

| 变更点 | 当前 | 新架构 |
|--------|------|--------|
| PARSE 输出 | intent_json (zones/facilities/axes) | OperationSequence + ConstraintSet + IntentJSON（Pydantic 严格 Schema） |
| MIP 角色 | 独立管线步骤 allocate_zones | 辅助工具 optimize_allocation，按需调用 |
| 6层生成 | generate_layout 一次性生成 | execute_operations 逐条执行，层是操作结果 |
| planning_zone | 独立层 _make_planning_zone_layer | 删除，信息在 ParcelReclass.assigned_zone |
| ParcelReclass | 不存在 (ZoneGenerator 仅输出 zone_type/color) | 新增，每地块20必选字段 |
| RoadPlan | 不存在 | 新增，规划道路生成 |
| 变更日志 | 不存在 | changelog.jsonl，每次操作记录 |

---

## 五、文件变更清单

### 5.1 新增文件

| # | 路径 | 说明 |
|---|------|------|
| 1 | `agent/gis/parse_agent.py` | ★ PARSE Agent 子图 (classify → route → extract → validate) |
| 2 | `agent/gis/parse_state.py` | ★ ParseAgentState + GISSummary + OperationItem + ConstraintItem + PlanningIntent |
| 3 | `agent/gis/parse_prompts.py` | ★ PARSE Agent 专用 prompts (GIS 注入 + DictionaryCenter 注入) |
| 4 | `tools/gis/operations.py` | edit_parcel tool (5种原子操作) |
| 5 | `tools/gis/place_resolver.py` | resolve_place_name tool |
| 6 | `tools/gis/code_lookup.py` | lookup_land_use_code tool |
| 7 | `tools/gis/compliance.py` | check_compliance tool |
| 8 | `tools/gis/extract.py` | extract_structured_text tool |
| 9 | `modules/gis/generation/parcel_reclass_generator.py` | ParcelReclass (20字段重分类) |
| 10 | `modules/gis/generation/road_plan_generator.py` | RoadPlan (规划道路) |
| 11 | `modules/gis/generation/operation_engine.py` | OperationEngine (统一操作执行引擎) |
| 12 | `modules/gis/schema/dicts/place_aliases.yaml` | 本地地名别名库 |

### 5.2 修改文件

| # | 路径 | 改动 |
|---|------|------|
| 1 | `agent/gis/agent.py` | 引入 PARSE Agent 子图，重构 gis_agent_node（全新逻辑，不兼容旧构造） |
| 2 | `agent/gis/state.py` | GISPipelineState 新增 operation_sequence/constraint_set/changelog/pending_confirmations/planning_text/l3_reports 字段 + GISSummary 模型 |
| 3 | `agent/gis/layout_pipeline.py` | 替换 allocate_and_generate → execute_operations 节点；parse_intent 改为纯透传节点（零逻辑） |
| 4 | `agent/gis/prompts.py` | 全新 PARSE prompts（GIS 数据注入 + DictionaryCenter 注入）；新增 EXECUTE_OPERATIONS_SYSTEM_PROMPT |
| 5 | `agent/graph.py` | gis_agent_node 重构：构建 GIS 现状摘要 → PARSE Agent → LAYOUT Pipeline |
| 6 | `tools/gis/parse.py` | 全新实现 parse_planning_text（GIS-aware + DictionaryCenter 注入 + Pydantic 输出） |
| 7 | `tools/gis/allocate.py` | allocate_zones → optimize_allocation，去掉 InjectedState，改为显式参数 |
| 8 | `tools/gis/generate.py` | 删除 _make_planning_zone_layer；generate_layout 改为调用 OperationEngine |
| 9 | `tools/gis/__init__.py` | 更新 GIS_TOOLS 列表：新增8个tool，删除 generate_layout/allocate_zones |
| 10 | `modules/gis/generation/pipeline.py` | 删除 _make_planning_zone_layer 调用；串联 ParcelReclass → 下游层 |
| 11 | `modules/gis/generation/optimizer/mip_allocator.py` | solve() 开头添加 targets 映射 (功能分区→规划分区) |
| 12 | `api/gis_test_routes.py` | 新增 /operations/confirm, /operations/preview, /operations/changelog 端点 |

### 5.3 删除

| # | 目标 | 说明 |
|---|------|------|
| 1 | `tools/gis/generate.py::_make_planning_zone_layer()` | planning_zone 层被 ParcelReclass.assigned_zone 替代 |
| 2 | `agent/gis/agent.py::create_parse_agent_graph()` | 废弃，pipeline 内部包含 parse |
| 3 | `agent/gis/agent.py::create_layout_agent_graph()` | 废弃，被 execute_operations 替代 |
| 4 | `agent/gis/agent.py::create_gis_agent_graph()` | 废弃，单Agent回退不再需要 |

---

## 六、实施顺序（4步渐进）

### Step 1: State + Pipeline 骨架改造（不破坏现有功能）

1. 扩展 `GISPipelineState` 新增字段（带默认值，向后兼容）
2. 改造 `layout_pipeline.py`：将 `allocate_and_generate` 重命名为 `execute_operations`，内部仍调用旧 ReAct agent（过渡期）
3. 简化 `gis_agent_node`：去掉外部 PARSE Agent 调用，pipeline 内部包含 parse
4. 更新 `prompts.py`：PARSE prompt 输出增加 OperationSequence 格式

**验证**：现有 API 端点 `/api/dev/gis/layout` 仍正常工作

### Step 2: 新增 Tool 层（6个新tool + OperationEngine）

1. 创建 `tools/gis/operations.py` (edit_parcel)
2. 创建 `tools/gis/place_resolver.py` (resolve_place_name)
3. 创建 `tools/gis/code_lookup.py` (lookup_land_use_code)
4. 创建 `tools/gis/compliance.py` (check_compliance)
5. 创建 `tools/gis/extract.py` (extract_structured_text)
6. 改造 `tools/gis/allocate.py` → optimize_allocation
7. 创建 `modules/gis/generation/operation_engine.py`
8. 更新 `tools/gis/__init__.py` GIS_TOOLS 列表

**验证**：新 tool 可独立调用，单元测试通过

### Step 3: execute_operations 接入新 Tool

1. 改造 `layout_pipeline.py` 的 `execute_operations` 节点：从调用旧 ReAct agent 改为调用新 ReAct agent（6个新tool）
2. 创建 `parcel_reclass_generator.py` (20字段)
3. 删除 `_make_planning_zone_layer`
4. 创建 `road_plan_generator.py`
5. 更新 `generation/pipeline.py` 串联新层
6. 新增 API 端点：/operations/confirm, /operations/preview, /operations/changelog

**验证**：E2E 测试 gen/plan 路径产出不同结果，20字段完整

### Step 4: 清理废弃代码

1. 删除 `agent/gis/agent.py` 中 3 个废弃函数
2. 删除 `tools/gis/generate.py` 中 `_make_planning_zone_layer`
3. 清理 legacy TypedDict aliases (GISAgentState, ParseAgentState, LayoutAgentState, LayoutPipelineState)
4. 更新文档

**验证**：全量测试通过，无 import 错误

---

## 七、验证方案

### 7.1 单元测试

```bash
# 新 tool 单元测试
pytest tests/unit/test_gis_operations.py -v
pytest tests/unit/test_gis_compliance.py -v
pytest tests/unit/test_parcel_reclass.py -v

# 现有测试不回归
pytest tests/unit/test_gis_unit.py -v
```

### 7.2 E2E 测试

```bash
# gen/plan 路径产出不同
pytest tests/e2e/test_gis_e2e.py -v

# API 端点测试
curl -X POST /api/dev/gis/layout -d '{"village_name":"金田村委会","run_path":"gen"}'
curl -X POST /api/dev/gis/operations/preview -d '{"operation_id":"..."}'
```

### 7.3 渲染验证

```bash
python scripts/render_comparison.py
# 预期: gen 和 plan 面板渲染不同
```
