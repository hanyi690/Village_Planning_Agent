# EXPLORE 桥接层设计

> **EXPLORE 是文本主线与空间主线的唯一桥接节点，提升为主图顶层节点。**
> 对应 `00_SYSTEM_DESIGN` 第四部分展开。

---

## 1. 设计目标：EXPLORE -> PARSE -> EXECUTE 三段式

```
规划文本(L1+L2+L3报告)
  │
  ▼
EXPLORE Agent (主图顶层节点)
  │ 按需读取 L1/L2/L3 报告
  │ KG 交互查候选实体
  │ 产出: ExplorationInstructionCollection + ReportSummaryIndex
  │
  ▼
PARSE Agent (gis_agent 内)
  │ 消费 ExplorationInstruction + 概要索引
  │ 按维度取 L3 报告原文 (通过 ReportSummaryIndex 导航)
  │ 产出: ZoneTarget / FacilityTarget / AxisTarget / RoadTarget
  │
  ▼
EXECUTE Agent (gis_agent 内)
  │ 消费意图 + KG + 空间操作
  │ 产出: 布局成果 + L4 回写
  │
  ▼
布局成果 + GDB 汇交
```

---

## 2. 为什么 EXPLORE 要提升出 gis_agent

### 2.1 文本生成的全部产物都在 EXPLORE 的视野内

当前 `gis_agent` 只取 L3 报告（`graph.py:207` `get_layer_summaries(session_id, layer=3)`），L1/L2 的空间线索丢失：
- L1 `land_use` 维度的现状用地分布 -- 空间布局的基础事实
- L1 `natural_environment` 的三区三线覆盖 -- 约束条件
- L2 `planning_positioning` 的村庄分类 -- 决定分区方向
- L2 `development_goals` 的发展方向 -- 决定产业用地

EXPLORE 提升为主图顶层节点后，**按需读取 L1+L2+L3 全部报告**，不遗漏任何空间线索。

### 2.2 EXPLORE 是文本主线与空间主线的唯一桥接点

不应埋在 gis_agent 内部（只能看到 L3），应在主图层直面全部文本产物。这样：
- 文本主线（L1/L2/L3）的产出有明确的消费者
- 空间主线（PARSE/EXECUTE）的输入有明确的来源
- KG 交互集中在 EXPLORE，PARSE 不直接查 KG，职责清晰

### 2.3 KG 交互前置

EXPLORE 查 KG 候选（BSM/几何/规划分区/建设许可），PARSE 消费候选不直接查。避免 PARSE 的 `ParseAgentState` 中 `code_mappings`/`place_mappings`/`context_blocks` 字段空置问题。

### 2.4 产出概要索引

参考 Claude Code 的代码库探索模式：EXPLORE 读 L1/L2/L3 后不只产出 ExplorationInstruction 列表，还产出**结构化概要索引**（ReportSummaryIndex），供 GIS agent 按维度导航访问对应 L3 报告原文。

---

## 3. EXPLORE Agent 详细设计

### 3.1 触发方式

| 触发 | 条件 | 实现 |
|------|------|------|
| 自动触发 | L3 完成 + 非 step_mode | `[PLANNED]` routing.py `after_analysis` 增加 `explore` 分支 |
| 手动触发 | 用户显式请求空间探索 | `[PLANNED]` 新增 `explore_analysis` tool_call，类似 `gis_analysis` |

### 3.2 输入：按需读取 L1+L2+L3

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

### 3.3 KG 交互

```python
from app.modules.kg import require_session_kg, query_session_template

kg = require_session_kg(session_id)

# 查候选实体
candidates = query_session_template(session_id, "entity_candidates", domain="landuse")
# 查规划分区
zones = query_session_template(session_id, "planning_zone")
# 查建设许可
perms = query_session_template(session_id, "construction_permission")
```

### 3.4 产出

#### 3.4.1 ExplorationInstructionCollection

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

#### 3.4.2 ReportSummaryIndex（新设计，参考 Claude Code）

EXPLORE 产出的**概要索引**，供 GIS agent 按维度导航访问 L3 报告原文：

```python
class DimensionSummaryEntry(BaseModel):
    """单个维度的概要索引条目"""
    dimension_key: str                     # "land_use_planning"
    layer: int                             # 1/2/3
    dimension_name: str                    # "土地利用规划"
    spatial_relevance: Literal["high", "medium", "low", "none"]  # 空间相关度
    key_spatial_findings: List[str]        # 关键空间发现摘要
    # 如: ["耕地127.18公顷", "建设用地占比12%"]
    mentioned_entities: List[str]          # 提及的空间实体
    # 如: ["金田村", "杉木家具产业园", "G235国道"]
    mentioned_bsms: List[str]             # 提及的BSM标识码
    spatial_hints: List[str]              # 空间提示
    # 如: ["沿河布置", "集中建设区北侧"]
    report_available: bool                 # 报告原文是否可获取
    # 若 True, GIS可通过 ReportStore.get_latest_report(session_id, dim_key) 获取原文

class ReportSummaryIndex(BaseModel):
    """EXPLORE产出的概要索引，供GIS按维度导航"""
    session_id: str
    village_name: str
    total_dimensions: int
    spatial_relevant_count: int            # 空间相关维度数
    entries: Dict[str, DimensionSummaryEntry]  # dim_key -> entry
    cross_dimension_findings: List[str]    # 跨维度发现
    # 如: ["L2定位为集聚提升类，L3产业用地需配套基础设施"]
```

**GIS agent 使用概要索引的方式**：

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

### 3.5 独立 Flash LLM 配置

EXPLORE 使用独立配置的 Flash 模型（快速、低成本），与 PARSE formatter LLM 独立：

```env
GIS_EXPLORE_LLM_ENABLED=true           # opt-in, 确定性基线优先
GIS_EXPLORE_MODEL=qwen-flash           # Flash 模型
GIS_EXPLORE_TEMPERATURE=0.3            # 低温度，偏确定性
GIS_EXPLORE_MAX_TOKENS=4096
```

### 3.6 ExploreFlashAgent 实现来源

`ExploreFlashAgent` 源码在 `25e24847` 分支（`backend/app/agent/gis/explore/agent.py`），核心逻辑：

1. **文本分块**：按章节/页码分块（`\f` 分页符 + `^#{1,6}\s+` 标题）
2. **域分类**：6域关键词评分（road/facility/landuse/zone/regulation/axis）
3. **实体识别**：引号短语 + 中文地名模式 + BSM 正则
4. **KG 查询**：`SessionKGQuery` -> `require_session_kg` + `query_session_template`
5. **产出**：`ExplorationInstructionCollection`

**待合入部分**：
- `ExploreFlashAgent` 主体（explore/agent.py）
- `ExplorationInstruction` 契约（explore/contracts.py）
- Flash LLM 配置（settings.py）

**已合入部分**：
- `SessionKGQuery` -> `require_session_kg` / `query_session_template`（087cfc6e）

---

## 4. EXPLORE 与 PARSE 的边界

| | EXPLORE | PARSE | EXECUTE |
|---|---|---|---|
| **产** | 证据 + 候选BSM + 域分类 + 约束 + 概要索引（非几何） | 类型化 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget（结构化） | 几何布局成果 + L4 回写 |
| **KG** | 查候选 | 不直接查（消费 EXPLORE 结果） | 查 + 写 L4 |
| **位置** | 主图顶层节点 | gis_agent 内 | gis_agent 内 |
| **输入** | L1+L2+L3 报告（按需） + KG | ExplorationInstruction + ReportSummaryIndex | SpatialPlanningIntent + KG + VillageBundle |

---

## 5. PARSE Agent 修正方向

### 5.1 当前：纯正则，不查 KG

`parse/agent.py`（214行）是纯规则解析器：
- 4 个正则模式提取 zone/facility/axis/road
- 不接收 `session_id`，不查询 KG
- `ParseAgentState` 的 `context_blocks`/`code_mappings_*`/`place_mappings_*` 字段全部空置

### 5.2 目标：消费 ExplorationInstruction + 概要索引

```
PARSE 修正后:
  1. 从 state 读取 ExplorationInstructionCollection + ReportSummaryIndex
  2. 扫描概要索引，识别空间相关维度
  3. 按需获取该维度完整 L3 报告原文 (ReportStore.get_latest_report)
  4. 结合 ExplorationInstruction 的候选BSM + 域分类 + 约束
  5. 产出类型化 ZoneTarget/FacilityTarget/AxisTarget/RoadTarget
  6. 填充 ParseAgentState 的空置字段 (code_mappings/place_mappings/context_blocks)
```

### 5.3 消除双重 parse

当前双重 parse：
1. `graph.py:97` `gis_agent_node` 独立调 `create_parse_agent_graph()`
2. `layout_pipeline.py:123` `_parse_intent_node` 再调 `parse_async()`

EXPLORE 提升后：
- `gis_agent_node` 移除独立 parse 调用
- `layout_pipeline.py` 的 `_parse_intent_node` 统一消费 EXPLORE 产出
- 消除 `graph.py:97` 的 `create_parse_agent_graph`

---

## 6. gis_agent 简化

### 6.1 当前（DEGRADED）

```python
# graph.py:52 gis_agent_node 当前:
reports, summaries = await _get_reports_and_summaries(state)  # 只取L3
parse_graph = create_parse_agent_graph()                        # 双重parse
parse_result = await parse_graph.ainvoke({...})                 # 独立parse
pipeline = build_layout_pipeline()
layout_result = await pipeline.ainvoke({...})
```

### 6.2 目标（简化后）

```python
# graph.py:52 gis_agent_node 目标:
# 从 state 读取 EXPLORE 产出
explore_instructions = state.get("explore_instructions", {})
report_summary_index = state.get("report_summary_index", {})

# 直接调 layout_pipeline (不再独立 parse)
pipeline = build_layout_pipeline()
layout_result = await pipeline.ainvoke({
    ...,
    "explore_instructions": explore_instructions,
    "report_summary_index": report_summary_index,
    ...
})
```

移除：
- `_get_reports_and_summaries()`（改为 EXPLORE 按需读取 L1+L2+L3）
- `create_parse_agent_graph()` 独立调用（消除双重 parse）
- 只传 L3 报告的缺陷（改为传概要索引，PAR
PARSE 按需取原文）

---

## 7. 实现状态总览

| 组件 | 状态 | 证据 |
|------|------|------|
| ExploreFlashAgent | `[PLANNED]` | 25e24847 分支待合入 |
| ExplorationInstruction 契约 | `[PLANNED]` | 25e24847 explore/contracts.py |
| SessionKGQuery | `[IMPLEMENTED]` | 087cfc6e 合入为 require_session_kg |
| ReportSummaryIndex | `[PLANNED]` | 新设计 |
| Flash LLM 配置 | `[PLANNED]` | GIS_EXPLORE_LLM_ENABLED 等 |
| after_analysis L3->explore 自动路由 | `[PLANNED]` | I6 改造 |
| explore_analysis 手动触发 | `[PLANNED]` | 新增 tool_call |
| explore -> gis_agent 边 | `[PLANNED]` | 新增边 |
| PARSE 消费 ExplorationInstruction | `[PLANNED]` | parse/agent.py 待修正 |
| gis_agent 移除自取报告 | `[PLANNED]` | graph.py:94 待修正 |
| 消除双重 parse | `[PLANNED]` | graph.py:97 待移除 |
| PARSE state 空置字段填充 | `[PLANNED]` | parse/state.py code_mappings 等 |
