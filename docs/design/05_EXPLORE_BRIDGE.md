# EXPLORE 桥接层设计

> **EXPLORE 是贯穿规划全周期的空间认知引擎，为 L1/L3 维度分析动态提供 KG 空间认知，并作为 L3 后的文本-空间桥接节点。**
> 对应 `00_SYSTEM_DESIGN` 第四部分展开。

---

## 1. 设计目标：EXPLORE 是可复用能力，不是单次节点

EXPLORE 不应被设计为"L3完成后才触发一次的桥接节点"，而是一种**贯穿规划全周期的可复用能力**，在三个时机发挥作用：

```
L1现状分析(12维并行)
  │ 每个维度分析时: EXPLORE 提供 KG 空间认知
  │ (替代当前 _optimize_semantics 静态 DIM_KG_MAP)
  │
  ▼
L2规划定位(4维波次)
  │ EXPLORE 提供 KG 约束校核认知
  │ (治断点②: 当前 dim_layer!=1 return "" 阻断)
  │
  ▼
L3详细规划(12维波次)
  │ 每个维度分析时: EXPLORE 提供 KG 现状结构认知
  │ (治断点②: L3 同样被阻断)
  │
  ▼
L3完成后的桥接 (EXPLORE 作为主图顶层节点)
  │ 按需读 L1+L2+L3 全量报告
  │ KG 交互查候选实体
  │ 产出: ExplorationInstructionCollection + ReportSummaryIndex
  │ 路由 -> gis_agent -> PARSE -> EXECUTE -> L4回写
  │
  ▼
L3校核轮
  │ EXPLORE 提供 L4 PlannedState 空间认知
  │ (读 L4 对账, 治断点⑥)
```

### 1.1 为什么 EXPLORE 要用于 L1/L3 维度分析

**当前问题**：`analysis/node.py:670-680` 的 `_optimize_semantics` 是一个**静态硬编码映射**（`DIM_KG_MAP`），为每个 L1 维度固定查询特定 KG 模式：

```python
# 当前: 静态硬编码, 不可扩展
DIM_KG_MAP = {
    "land_use": ["land_distribution", "zone_candidates"],
    "natural_environment": ["constraint_coverage"],
    "traffic": ["road_network"],
    ...
}
```

这个方案的缺陷：
1. **不可扩展**：新增维度或调整查询模式需改代码
2. **L2/L3 被阻断**：`node.py:667 if dim_layer != 1: return ""` 一刀切禁了 L2/L3
3. **KG 实例不统一**：`node.py:691 KGManager().get_any_kg()` 用全局 KG，非 session KG
4. **无文本理解**：直接查 KG 模板，不消费维度报告文本中的空间线索
5. **无概要索引**：KG 查询结果直接塞入 prompt，无结构化索引供下游复用

**EXPLORE 替代方案**：将 `_optimize_semantics` 升级为 EXPLORE 能力调用，为每个维度**动态**提供 KG 空间认知：

```python
# 目标: EXPLORE 作为可复用能力, 为维度分析动态提供空间认知
from app.agent.explore import explore_for_dimension

async def _optimize_semantics(dim_key, dim_layer, state, cfg):
    """EXPLORE 为维度分析提供 KG 空间认知."""
    explore_result = await explore_for_dimension(
        session_id=state["session_id"],
        dim_key=dim_key,
        dim_layer=dim_layer,
        report_text=state.get("current_report_text", ""),
        kg=require_session_kg(state["session_id"]),
    )
    return explore_result.spatial_cognition_section  # 结构化空间认知摘要
```

### 1.2 EXPLORE 的三种调用模式

| 模式 | 时机 | 输入 | 产出 | 替代 |
|------|------|------|------|------|
| **维度认知模式** | L1/L2/L3 每个维度分析时 | dim_key + 维度报告文本 + KG | SpatialCognitionSummary（空间认知摘要） | 替代 `_optimize_semantics` 静态 DIM_KG_MAP |
| **桥接模式** | L3 完成后（自动/手动） | L1+L2+L3 全量报告 + KG | ExplorationInstructionCollection + ReportSummaryIndex | 新增 |
| **校核模式** | L3 校核轮 | L4 PlannedState + L3 文本 + KG | ConsistencyReport（文本/几何一致性报告） | 新增（I5改造） |

---

## 2. EXPLORE 作为主图顶层节点（桥接模式）

### 2.1 定位

在桥接模式下，EXPLORE 是主图顶层节点（与 conversation/analyze_dimension/gis_agent 平级），**不是** gis_agent 的子步骤。

### 2.2 触发方式

| 触发 | 条件 | 实现 |
|------|------|------|
| 自动触发 | L3 完成 + 非 step_mode | `[PLANNED]` routing.py `after_analysis` 增加 `explore` 分支 |
| 手动触发 | 用户显式请求空间探索 | `[PLANNED]` 新增 `explore_analysis` tool_call |

### 2.3 输入：按需读取 L1+L2+L3

EXPLORE **不一次性吞掉全量文本**，而是按需读取：

```python
from app.services.report_store import ReportStore

store = ReportStore.get_instance()

# 按需读取各层报告摘要
l1_summaries = await store.get_layer_summaries(session_id, layer=1)  # 12维现状
l2_summaries = await store.get_layer_summaries(session_id, layer=2)  # 4维定位
l3_summaries = await store.get_layer_summaries(session_id, layer=3)  # 12维详细
```

**按需读取策略**：
- L1：只读与空间相关的维度（land_use, natural_environment, traffic, public_services, infrastructure, architecture）
- L2：只读定位相关维度（resource_endowment, planning_positioning, development_goals, planning_strategies）
- L3：读全部 12 维（空间布局的直接输入）
- 完整报告原文通过 `ReportStore.get_latest_report(session_id, dim_key)` 按维度按需获取

### 2.4 KG 交互

```python
from app.modules.kg import require_session_kg, query_session_template

kg = require_session_kg(session_id)  # 统一用 session KG, 治断点⑨

# 查候选实体
candidates = query_session_template(session_id, "entity_candidates", domain="landuse")
# 查规划分区
zones = query_session_template(session_id, "planning_zone")
# 查建设许可
perms = query_session_template(session_id, "construction_permission")
```

### 2.5 产出

#### ExplorationInstructionCollection

来自 `25e24847` 分支的 `explore/contracts.py`：

```python
class ExplorationInstruction(BaseModel):
    instruction_id: str                    # "EXP-0001"
    source_chunk_id: str                   # 文本分块ID
    section_title: str                     # 章节标题
    evidence_text: str                     # 证据原文
    domain: Literal["road", "facility", "landuse", "zone", "regulation", "axis"]
    action: str                            # create/preserve/constrain/widen/repair/...
    entity_mentions: List[str]             # 实体提及（引号短语+中文地名）
    candidate_bsm_list: List[str]          # 候选BSM标识码
    candidate_bbox: Optional[List[float]]  # 候选边界框
    constraints: List[Dict[str, Any]]      # 约束条件
    confidence: float                      # 置信度
    requires_human_confirmation: bool      # 是否需要人工确认
```

#### ReportSummaryIndex（参考 Claude Code 概要模式）

```python
class DimensionSummaryEntry(BaseModel):
    """单个维度的概要索引条目"""
    dimension_key: str                     # "land_use_planning"
    layer: int                             # 1/2/3
    dimension_name: str                    # "土地利用规划"
    spatial_relevance: Literal["high", "medium", "low", "none"]
    key_spatial_findings: List[str]        # ["耕地127.18公顷", "建设用地占比12%"]
    mentioned_entities: List[str]          # ["金田村", "杉木家具产业园"]
    mentioned_bsms: List[str]             # BSM标识码
    spatial_hints: List[str]              # ["沿河布置", "集中建设区北侧"]
    report_available: bool                 # 报告原文是否可获取
    # 若 True, GIS可通过 ReportStore.get_latest_report(session_id, dim_key) 获取原文

class ReportSummaryIndex(BaseModel):
    """EXPLORE产出的概要索引，供GIS按维度导航"""
    session_id: str
    village_name: str
    total_dimensions: int
    spatial_relevant_count: int
    entries: Dict[str, DimensionSummaryEntry]  # dim_key -> entry
    cross_dimension_findings: List[str]    # 跨维度发现
```

**GIS agent 使用概要索引**：

```python
# gis_agent 内的 PARSE 节点
summary_index = state["report_summary_index"]

# 1. 先扫描概要索引，识别空间相关维度
for dim_key, entry in summary_index.entries.items():
    if entry.spatial_relevance == "high":
        # 2. 按需获取该维度的完整 L3 报告原文
        if entry.report_available:
            full_report = await ReportStore.get_instance().get_latest_report(session_id, dim_key)
            # 3. 从完整报告中提取 ZoneTarget/FacilityTarget/...
```

---

## 3. EXPLORE 用于 L1/L3 维度分析（维度认知模式）

### 3.1 替代 `_optimize_semantics`

当前 `_optimize_semantics`（node.py:661-744）的问题：

| 问题 | 当前 | EXPLORE 方案 |
|------|------|-------------|
| 查询模式 | 静态 DIM_KG_MAP 硬编码 | 动态：读维度报告文本 -> 识别空间线索 -> 选择 KG 查询模式 |
| L2/L3 阻断 | `if dim_layer != 1: return ""` | 按层级分派：L1查认知/L2查约束/L3查结构 |
| KG 实例 | `get_any_kg()`（全局） | `require_session_kg(session_id)`（统一） |
| 文本理解 | 无（直接查模板） | 有（EXPLORE 分块+域分类+实体识别） |
| 下游复用 | 无（结果塞入 prompt 消失） | 产出 SpatialCognitionSummary 可复用 |

### 3.2 SpatialCognitionSummary 产出

```python
class SpatialCognitionSummary(BaseModel):
    """EXPLORE 为单个维度分析提供的 KG 空间认知摘要"""
    dimension_key: str
    layer: int
    
    # KG 查询结果摘要
    layer_cards: List[Dict[str, Any]]       # 地块分布卡片
    constraint_coverage: Optional[Dict]      # 约束覆盖统计
    road_network: Optional[Dict]             # 道路网络摘要
    facility_coverage: Optional[Dict]        # 设施覆盖摘要
    village_overview: Optional[Dict]         # 村庄概览
    
    # EXPLORE 从维度报告文本中提取的空间线索
    spatial_findings: List[str]              # ["耕地破碎化严重", "林地占90%"]
    entity_mentions: List[str]              # 文本中提及的空间实体
    candidate_bsms: List[str]               # 候选 BSM 标识码
    
    # 格式化为可直接注入 LLM prompt 的文本
    prompt_section: str                      # 格式化的空间认知段落
    
    # 元数据
    kg_session_ref: str                      # 使用的 session KG 引用
    query_modes: List[str]                   # 实际查询的 KG 模式
```

### 3.3 维度分析中的调用方式

```python
# analysis/node.py 修正后:
async def analyze_dimension(state):
    dim_key = state["dimension_key"]
    dim_layer = get_dimension_layer(dim_key)
    
    # ... RAG 检索 ...
    
    # EXPLORE 提供空间认知 (替代 _optimize_semantics)
    from app.agent.explore import explore_for_dimension
    cognition = await explore_for_dimension(
        session_id=state["session_id"],
        dim_key=dim_key,
        dim_layer=dim_layer,
        report_text=structured_summary_text,  # 当前维度的结构化摘要
    )
    
    # 注入 LLM prompt
    professional_data_section += cognition.prompt_section
    
    # ... LLM 生成 ...
```

### 3.4 L1/L2/L3 的 KG 查询分派

| 层 | EXPLORE 查询模式 | 内容 | 当前状态 |
|----|------------------|------|----------|
| L1 | `analysis_queries`（粗，semantic） | layer_cards, constraint_coverage, road_network, facility_coverage, village_overview | `[IMPLEMENTED]` 但用静态 DIM_KG_MAP |
| L2 | `analysis_queries` + `shared_queries` | 村庄分类校核、三区三线覆盖、资源禀赋 | `[PLANNED]` 当前被阻断 |
| L3 | `execute_queries` + `shared_queries` | get_area_by_type 算现状结构、get_parcel_context 校布局 | `[PLANNED]` 当前被阻断 |

---

## 4. EXPLORE 用于 L3 校核轮（校核模式）

### 4.1 读 L4 PlannedState 对账

L3 校核轮中，EXPLORE 读 L4 PlannedState，为每个维度提供文本/几何一致性校核：

```python
class ConsistencyReport(BaseModel):
    """EXPLORE 校核模式产出"""
    dimension_key: str
    text_claims: List[TextClaim]            # L3 文本中的空间声明
    # 如: {"text": "耕地127.18公顷", "metric": "farmland_ha", "value": 127.18}
    
    kg_l4_values: Dict[str, float]          # L4 PlannedState 的计算值
    # 如: {"farmland_ha": 126.95}
    
    discrepancies: List[Discrepancy]        # 不一致项
    # 如: {"metric": "farmland_ha", "text_value": 127.18, "kg_value": 126.95, "delta": 0.23}
    
    suggested_corrections: List[str]        # 建议修正
```

---

## 5. EXPLORE 的三种模式统一架构

```
┌─────────────────────────────────────────────────────────────┐
│                    EXPLORE 能力引擎                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ 文本分块     │  │ 域分类       │  │ 实体识别     │        │
│  │ (章节/页码)  │  │ (6域关键词)  │  │ (BSM+地名)  │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘        │
│         └────────────────┼────────────────┘                │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  KG 交互 (require_session_kg + query_session_template)│   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              三种调用模式                             │   │
│  ├─────────────┬─────────────┬─────────────────────────┤   │
│  │ 维度认知模式 │ 桥接模式    │ 校核模式                 │   │
│  │ (L1/L2/L3)  │ (L3完成后)  │ (L3校核轮)              │   │
│  │             │             │                         │   │
│  │ 输入:       │ 输入:       │ 输入:                   │   │
│  │  dim_key    │  L1+L2+L3   │  L4 PlannedState        │   │
│  │  维度报告   │  全量报告   │  + L3文本               │   │
│  │             │             │                         │   │
│  │ 产出:       │ 产出:       │ 产出:                   │   │
│  │  SpatialCog │  Exploration│  ConsistencyReport      │   │
│  │  Summary    │  Instr +    │                         │   │
│  │             │  SummaryIdx │                         │   │
│  └─────────────┴─────────────┴─────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 5.1 Flash LLM 独立配置

EXPLORE 使用独立配置的 Flash 模型（快速、低成本），与维度分析的 LLM 独立：

```env
GIS_EXPLORE_LLM_ENABLED=true           # opt-in, 确定性基线优先
GIS_EXPLORE_MODEL=qwen-flash           # Flash 模型
GIS_EXPLORE_TEMPERATURE=0.3            # 低温度，偏确定性
GIS_EXPLORE_MAX_TOKENS=4096
```

### 5.2 ExploreFlashAgent 实现来源

`ExploreFlashAgent` 源码在 `25e24847` 分支（`backend/app/agent/gis/explore/agent.py`），核心逻辑：

1. **文本分块**：按章节/页码分块
2. **域分类**：6域关键词评分（road/facility/landuse/zone/regulation/axis）
3. **实体识别**：引号短语 + 中文地名模式 + BSM 正则
4. **KG 查询**：`SessionKGQuery` -> `require_session_kg` + `query_session_template`
5. **产出**：`ExplorationInstructionCollection`

**待合入部分**：ExploreFlashAgent 主体 + ExplorationInstruction 契约 + Flash LLM 配置
**已合入部分**：SessionKGQuery -> require_session_kg / query_session_template（087cfc6e）

---

## 6. EXPLORE 与 PARSE 的边界

| | EXPLORE (维度认知模式) | EXPLORE (桥接模式) | PARSE | EXECUTE |
|---|---|---|---|---|
| **时机** | L1/L2/L3 每个维度分析时 | L3 完成后 | gis_agent 内 | gis_agent 内 |
| **输入** | dim_key + 维度报告 + KG | L1+L2+L3 全量报告 + KG | ExplorationInstruction + SummaryIndex | SpatialPlanningIntent + KG |
| **产** | SpatialCognitionSummary | ExplorationInstr + ReportSummaryIndex | ZoneTarget/FacilityTarget/... | 布局成果 + L4 回写 |
| **KG** | 查认知（session KG） | 查候选（session KG） | 不直接查 | 查 + 写 L4 |
| **位置** | analysis/node.py 内调用 | 主图顶层节点 | gis_agent 内 | gis_agent 内 |

---

## 7. PARSE Agent 修正方向

### 7.1 当前：纯正则，不查 KG

`parse/agent.py`（214行）是纯规则解析器，不接收 `session_id`，不查询 KG。`ParseAgentState` 的 KG 交互字段全部空置。

### 7.2 目标：消费 ExplorationInstruction + 概要索引

```
PARSE 修正后:
  1. 从 state 读取 ExplorationInstructionCollection + ReportSummaryIndex
  2. 扫描概要索引，识别空间相关维度
  3. 按需获取该维度完整 L3 报告原文 (ReportStore.get_latest_report)
  4. 结合 ExplorationInstruction 的候选BSM + 域分类 + 约束
  5. 产出类型化 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget
  6. 填充 ParseAgentState 的空置字段
```

### 7.3 消除双重 parse

当前：`graph.py:97` + `layout_pipeline.py:123` 双重 parse。
目标：graph.py 移除独立 parse 调用，layout_pipeline 统一消费 EXPLORE 产出。

---

## 8. gis_agent 简化

### 8.1 当前（DEGRADED）

```python
# graph.py:52 gis_agent_node 当前:
reports, summaries = await _get_reports_and_summaries(state)  # 只取L3
parse_graph = create_parse_agent_graph()                        # 双重parse
parse_result = await parse_graph.ainvoke({...})
pipeline = build_layout_pipeline()
layout_result = await pipeline.ainvoke({...})
```

### 8.2 目标（简化后）

```python
# 从 state 读取 EXPLORE 产出
explore_instructions = state.get("explore_instructions", {})
report_summary_index = state.get("report_summary_index", {})

# 直接调 layout_pipeline (不再独立 parse)
pipeline = build_layout_pipeline()
layout_result = await pipeline.ainvoke({
    ...,
    "explore_instructions": explore_instructions,
    "report_summary_index": report_summary_index,
})
```

移除：`_get_reports_and_summaries()`、`create_parse_agent_graph()` 独立调用。

---

## 9. 实现状态总览

| 组件 | 状态 | 证据 |
|------|------|------|
| **维度认知模式** | | |
| L1 KG查询 (静态DIM_KG_MAP) | `[IMPLEMENTED]` | node.py:670-680, 待升级为EXPLORE调用 |
| L2/L3 KG查询 | `[PLANNED]` | node.py:667 阻断, I2改造 |
| _optimize_semantics 升级为 EXPLORE | `[PLANNED]` | 替代静态映射 |
| SpatialCognitionSummary 产出 | `[PLANNED]` | 新设计 |
| KG实例统一 | `[PLANNED]` | get_any_kg -> get_session_kg |
| **桥接模式** | | |
| ExploreFlashAgent | `[PLANNED]` | 25e24847 分支待合入 |
| ExplorationInstruction 契约 | `[PLANNED]` | 25e24847 explore/contracts.py |
| SessionKGQuery | `[IMPLEMENTED]` | 087cfc6e 合入为 require_session_kg |
| ReportSummaryIndex | `[PLANNED]` | 新设计 |
| Flash LLM 配置 | `[PLANNED]` | GIS_EXPLORE_LLM_ENABLED 等 |
| after_analysis L3->explore 自动路由 | `[PLANNED]` | I6 改造 |
| explore_analysis 手动触发 | `[PLANNED]` | 新增 tool_call |
| explore -> gis_agent 边 | `[PLANNED]` | 新增边 |
| **校核模式** | | |
| ConsistencyReport 产出 | `[PLANNED]` | I5 改造 |
| L3-轮2 读 L4 对账 | `[PLANNED]` | I5 改造 |
| **PARSE/EXECUTE 修正** | | |
| PARSE 消费 ExplorationInstruction | `[PLANNED]` | parse/agent.py 待修正 |
| gis_agent 移除自取报告 | `[PLANNED]` | graph.py:94 待修正 |
| 消除双重 parse | `[PLANNED]` | graph.py:97 待移除 |
| PARSE state 空置字段填充 | `[PLANNED]` | parse/state.py code_mappings 等 |
