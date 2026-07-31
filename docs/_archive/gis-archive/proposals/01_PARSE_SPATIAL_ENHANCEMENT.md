# PARSE Agent 空间理解增强方案（可执行版）

> **Status: [PROPOSAL]** | **Type: Executable Enhancement Plan** | **Version: 2.1** | **Updated: 2026-07-24**
> **⚠️ 本方案基于 v11 实测数据（金田村 2026-07-22）+ v12 管线测试数据（2026-07-24），从理论批判转为可执行路径。**
> **Relationship to DESIGN_GOALS**: 本方案不再争论 "statistics only vs statistics+spatial"，而是解决实际瓶颈：
> 编码无效、锚定断裂、约束缺失、area_ratio 不完整、渲染映射断裂——这些问题在现有设计框架内即可修复。
> **References**: BIBLIOGRAPHY.md §A3-4, §F1-7
> **Related**: 01_DESIGN_GOALS.md §6, diagnostics/01_PARSE_AGENT_STATUS.md, diagnostics/02_RELIABILITY_ASSESSMENT.md

---

## 0. 前提：v11 突破与 v12 管线测试发现

### 0.1 v11 取得的突破

v11 通过恢复单批次处理 + Think-Then-Format 分离，实现了核心瓶颈的突破：

| 指标                       | v10       | v11        | 变化              |
| -------------------------- | --------- | ---------- | ----------------- |
| explore_projects draft     | 138 chars | 2185 chars | **+16x** 🎉 |
| explore_targets draft      | 109 chars | 2605 chars | **+24x** 🎉 |
| format_projects operations | 2         | 30         | **15x** 🎉  |
| "length limit" 错误        | 0         | 0          | ✅ 稳定           |

### 0.2 v12 管线测试新发现（2026-07-24）

运行 `run_parse_pipeline.py --source mineru` + `run_layout_pipeline.py --source mineru` 后发现：

| 问题                                            | 严重度 | 影响范围          | 根因                                                                                                                                                 |
| ----------------------------------------------- | ------ | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **area_ratio 之和 83.6%**                 | 🔴 P0  | zone_targets 全部 | LLM 从文本提取 8 个 zone_targets，遗漏水域/未利用地等；无工具查询现状地类分布作为参考                                                                |
| **query_village_kg 工具空壳**             | 🔴 P0  | explore 阶段      | 工具返回 "Tool called — execution handled by agent loop."，无实际 SPARQL 查询                                                                       |
| **constraint_summary 只在 fallback 使用** | 🔴 P0  | 正常路径约束缺失  | validate_and_merge 只在 LLM 提取失败时从 constraint_summary 生成约束；正常路径未合并                                                                 |
| **渲染空白（zone_type 不匹配）**          | 🔴 P0  | planning_zone.png | MIP allocator 输出`assigned_zone` = GHYTMC 中文名（如 "商品林"），但 PLANNING_ZONE_COLORS key 是 6 个大区名（如 "林业发展区"），无映射导致全部灰色 |
| **Direction 枚举值缺失**                  | 🟡 P1  | generate 阶段     | LLM 输出 "expand" / "村庄建设发展轴" 等不在 Direction Enum 中的值，导致 ValueError                                                                   |
| **schema.intent 模块不存在**              | 🟡 P1  | generate + render | `generate.py` 和 `render_planning_layout.py` 引用 `app.modules.gis.schema.intent`，实际类型在 `schema.contracts`                             |
| **hasattr 返回 bool 不可下标**            | 🟡 P1  | allocate 阶段     | `hasattr(intent, 'zone_targets')[0:]` 中 `hasattr` 返回 bool，不能切片                                                                           |
| **村名映射断裂**                          | 🟡 P1  | cache 查找        | PARSE 缓存用 "金田村"，LAYOUT 默认查找 "jintian"，找不到缓存                                                                                         |
| **kg.serialize 签名不匹配**               | 🟡 P1  | layout 阶段       | `kg.serialize(format="turtle")` 需要 `filepath` 参数，应使用 `kg.to_turtle()`                                                                  |
| **DB 来源 LLM 超时**                      | 🟡 P1  | PARSE 阶段        | DB 12 维度合并后 17688 chars，截断到 12000；validate_and_merge 处理大量结构化输出导致 LLM 响应超时（489s）                                           |

### 0.3 已修复（v12 热修复）

| 修复                                 | 文件                                           | 说明                                                                                |
| ------------------------------------ | ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| ✅ GHYTMC → PlanningZone 映射       | `code_sets.py`                               | 新增`GHYTMC_TO_PLANNING_ZONE` 字典，21 个中文用地名映射到 6 个大区                |
| ✅`_make_planning_zone_layer` 映射 | `generate.py`                                | 当`assigned_zone` 不在 PLANNING_ZONE_COLORS 时，通过 GHYTMC_TO_PLANNING_ZONE 反查 |
| ✅ Direction 枚举容错                | `generate.py`                                | `try/except ValueError` fallback 到 `Direction.CENTER`，保留原始 label          |
| ✅ schema.intent → schema.contracts | `generate.py`, `render_planning_layout.py` | 修正 import 路径                                                                    |
| ✅ hasattr bool 切片                 | `allocate.py`                                | `hasattr(intent, 'zone_targets')[0:]` → `intent.zone_targets`                  |
| ✅ 村名别名映射                      | `run_layout_pipeline.py`                     | 新增`VILLAGE_NAME_ALIASES` + `_resolve_village_names()`                         |
| ✅ kg.serialize → kg.to_turtle      | `run_layout_pipeline.py`                     | 修正方法调用                                                                        |
| ✅ gpd.GeoDataFrame 类型提示         | `geojson_utils.py`                           | 改为字符串注解，避免 geopandas 未安装时 NameError                                   |
| ✅ requirements.txt 补全             | `requirements.txt`                           | 新增 requests/sqlalchemy/matplotlib/rdflib/pulp/instructor/httpx/pandas/pyyaml      |

---

## 1. 优化路径总览

```
Path 1: 编码硬校验 ──→ Path 2: 锚定自动填充 ──→ Path 3: 约束提取增强
  (P0, 0.5天)           (P0, 1天)               (P0, 1天)
                              ↓
        第一批交付: 可用解析结果 → GIS Agent → 规划分区图+设施图
                              ↓
Path 4: 忠实度评估 ←──→ Path 5: 并行度提升
  (P1, 1.5天)              (P1, 1天)
                              ↓
Path 6: 注记+空间关系+KG 注入 ←──→ Path 7: DEM数据准备
  (P2, 2天)                        (P2, 0.5天)
                              ↓
Path 8: query_village_kg 实际执行 ←──→ Path 9: DB 12 维度并行化
  (P0, 1天)                          (P1, 1天)
```

**新增 Path 8-9** 来自 v12 管线测试发现。

---

## 1. 优化路径总览

```
Path 1: 编码硬校验 ──→ Path 2: 锚定自动填充 ──→ Path 3: 约束提取增强
  (P0, 0.5天)           (P0, 1天)               (P0, 1天)
                              ↓
        第一批交付: 可用解析结果 → GIS Agent → 规划分区图+设施图
                              ↓
Path 4: 忠实度评估 ←──→ Path 5: 并行度提升
  (P1, 1.5天)              (P1, 1天)
                              ↓
Path 6: 注记+空间关系+KG 注入 ←──→ Path 7: DEM数据准备
  (P2, 2天)                        (P2, 0.5天)
```

---

## 2. Path 1: 编码硬校验（P0，0.5天）

### 问题

format 阶段 LLM 直接输出 `GHYTBM=2121`，而非从 explore 阶段的 `code_mappings` 中取正确编码。

### 根因

code_table 已注入 prompt 但 LLM 忽略。需要 Python 层硬校验兜底。

### 修改点

**A. format_projects_node 赛后自动修正** (`parse/agent.py` L719-761):

```python
async def format_projects_node(state: ParseAgentState) -> dict:
    # ... 现有 format 逻辑 ...
    result = await _format_structured(format_llm, ProjectExtractionResult, messages)

    if result is not None:
        ops = [o.model_dump() for o in result.operations]

        # === NEW: Python 硬校验 + 自动修正 ===
        from app.modules.gis.schema import GHYTBM_TO_GHYTMC
        for i, op in enumerate(ops):
            code = op.get("land_use_code", "")
            if code and code not in GHYTBM_TO_GHYTMC:
                # 从 code_mappings 中找最近似匹配
                corrected = _auto_correct_code(op, state.code_mappings_projects)
                ops[i]["land_use_code"] = corrected
                ops[i]["_code_auto_corrected"] = True

        return {"raw_operations": ops}
```

**B. 新增 `_auto_correct_code` 辅助函数**:

```python
def _auto_correct_code(op: dict, code_mappings: dict) -> str:
    """从 code_mappings 中查找最匹配的编码"""
    land_use_name = op.get("land_use_name", "")
    # 精确匹配
    if land_use_name in code_mappings:
        return code_mappings[land_use_name]
    # 子串匹配
    for name, code in code_mappings.items():
        if land_use_name in name or name in land_use_name:
            return code
    # 从 DictionaryCenter 直接查询
    from app.tools.gis.parse_tools import lookup_land_use_code
    result = lookup_land_use_code.invoke({"land_use_name": land_use_name})
    if result and "ghytbm" in result:
        return result["ghytbm"]
    return op.get("land_use_code", "")
```

**文件**: `backend/app/agent/gis/parse/agent.py`

---

## 3. Path 2: 空间锚定自动填充（P0，1天）

### 问题

`resolve_place` 返回 `{village_name, parcel_ids, confidence}`，但这些信息未自动写入 `SpatialAnchor`。

### 根因

format 阶段依赖 LLM 填写 SpatialAnchor 字段，LLM 不擅长这种结构化数据搬运任务。

### 修改点

**A. format_projects_node 自动推导 SpatialAnchor** (`parse/agent.py` L719-761):

```python
async def format_projects_node(state: ParseAgentState) -> dict:
    # ... 现有 format 逻辑 + 编码修正 ...

    for i, op in enumerate(ops):
        # === NEW: 自动填充 SpatialAnchor（不依赖LLM） ===
        location = op.get("location_desc", "")
        anchor = _auto_fill_spatial_anchor(
            location,
            state.place_mappings_projects,
            state.spatial_context
        )
        if anchor:
            ops[i]["spatial_anchor"] = anchor
```

**B. 新增 `_auto_fill_spatial_anchor` 辅助函数**:

```python
def _auto_fill_spatial_anchor(
    location_desc: str,
    place_mappings: dict,
    spatial_context
) -> dict | None:
    """从 place_mappings 自动推导 SpatialAnchor。

    策略:
    1. 精确匹配 place_mappings 中的已解析地名
    2. 模糊匹配 natural_villages 中的村组名
    3. 从 location_desc 中提取方向词（东/南/西/北/中/侧/边）
    """
    if not location_desc:
        return None

    # Step 1: 精确匹配 place_mappings
    for place_name, info in place_mappings.items():
        if place_name in location_desc:
            confidence = info.get("confidence", 0.5)
            return {
                "reference": place_name,
                "candidate_parcels": info.get("parcel_ids", []),
                "confidence": confidence,
                "resolution_status": "RESOLVED" if confidence > 0.5 else "NEEDS_CONFIRMATION",
            }

    # Step 2: 模糊匹配 natural_villages
    for nv in (spatial_context.natural_villages or []):
        if nv.name in location_desc:
            return {
                "reference": nv.name,
                "candidate_parcels": nv.parcel_ids[:10] if hasattr(nv, 'parcel_ids') else [],
                "confidence": 0.5,
                "resolution_status": "NEEDS_CONFIRMATION",
            }

    # Step 3: 方向词提取（保留给后续 KG 查询）
    directions = ["东", "南", "西", "北", "中", "侧", "边", "沿", "周边"]
    for d in directions:
        if d in location_desc:
            # 提取方向词前的参照物名称
            idx = location_desc.index(d)
            ref_candidate = location_desc[:idx].strip()
            if ref_candidate:
                return {
                    "reference": ref_candidate,
                    "offset": d,
                    "candidate_parcels": [],
                    "confidence": 0.2,
                    "resolution_status": "UNRESOLVED",
                }

    return None
```

**文件**: `backend/app/agent/gis/parse/agent.py`

---

## 4. Path 3: 约束提取增强（P0，1天）

### 问题

`extract_regulations_node` 零产出。当前只用 regex 提取，模式覆盖不全。

### 修改点

**A. 扩展 regex 模式库** (`extract_regulations_node` L503):

```python
# 现有模式（太窄）
REGULATION_PATTERNS = [
    # === NEW: 面积约束 ===
    (r"(建设用地|耕地|生态)[面积用].{0,10}(不[超少低][于過]|≤|≥)\s*(\d+\.?\d*)\s*(ha|公顷|亩)", "area"),
    # === NEW: 距离约束 ===
    (r"(距|距离|退).{0,8}(河道|道路|公路|设施|红线|边界).{0,8}(不[小少][于於]|≥)\s*(\d+)\s*(米|m)", "spatial"),
    # === NEW: 建筑物约束 ===
    (r"(建筑|房屋).{0,5}(高度|层数|面积).{0,8}(不[超多][过過]|≤)\s*(\d+)\s*(米|m|层)", "building"),
    # === NEW: 保护约束 ===
    (r"(禁止|不得|严禁|不得).{0,10}(占用|侵占|破坏|开发).{0,10}(基本农田|生态林|水源|保护区|红线)", "protection"),
    # === NEW: 指标约束 ===
    (r"(人均|户均).{0,8}(不[低少][于於]|≥)\s*(\d+\.?\d*)\s*(m²|平方米|㎡)", "indicator"),
]
```

**B. 注入预填充结果到 prompt**:

```python
# extract_regulations_node 流程:
# Step 1: regex 预提取 → 预填充列表
# Step 2: 将预填充列表注入 LLM prompt
# Step 3: LLM 补充遗漏的约束（thinking 模式）
# Step 4: 合并 regex + LLM 结果

prefilled = _regex_extract_regulations(sections_text)
prefill_block = "\n".join(
    f"- [{c['type']}] {c['text']} → {c.get('value', '')}"
    for c in prefilled
)

messages = [
    SystemMessage(content=(
        "You are extracting planning constraints from village planning text.\n"
        f"The following constraints were pre-extracted by regex:\n{prefill_block}\n\n"
        "Your task: verify each pre-extracted constraint, correct errors,\n"
        "and add any missing constraints. Return all as ConstraintItem list."
    )),
    ...
]
```

**C. 新增 llm 验证阶段**（类同 projects/targets 的 Phase A/B 分拆）:

```
extract_regulations:
  Phase A (regex prefill): deterministic regex scan → List[dict]
  Phase B (llm complete): thinking=ON, tools=OFF → verify + add missing
```

**文件**: `backend/app/agent/gis/parse/agent.py` — `extract_regulations_node`

---

## 5. Path 4: 忠实度评估器（P1，1.5天）

### 设计

在 `validate_and_merge` 之后新增 `evaluate_fidelity` 节点，对解析结果进行五维评估。

### 新建文件: `backend/app/agent/gis/evaluate_fidelity.py`

```python
"""Parse结果忠实度评估器。

对 PARSE Agent 输出进行五维评估:
1. 编码有效性: 所有 land_use_code ∈ DictionaryCenter
2. 面积一致性: 解析面积 vs 原文数值
3. 地名召回率: 原文地名 ∩ SpatialAnchor
4. 操作覆盖率: 解析操作是否覆盖原文建设项目
5. 约束覆盖率: 解析约束是否覆盖原文限制条件
"""

class FidelityReport(BaseModel):
    """忠实度评估报告"""
    code_validity: CodeValidity
    area_consistency: AreaConsistency
    place_recall: PlaceRecall
    operation_coverage: float  # 0.0-1.0
    constraint_coverage: float  # 0.0-1.0
    overall_score: float  # 0.0-1.0
    warnings: List[str]
    details: dict

class CodeValidity(BaseModel):
    valid_count: int
    total_count: int
    auto_corrected: int
    pass_rate: float

class AreaConsistency(BaseModel):
    matched_count: int
    deviations: List[dict]  # [{parsed: X, original: Y, deviation_pct: Z}]

class PlaceRecall(BaseModel):
    recalled_count: int
    total_in_text: int
    recall_rate: float

def evaluate_fidelity(
    original_text: str,
    operations: List[dict],
    constraints: List[dict],
    code_mappings: dict,
    spatial_context,
    llm  # 轻量 LLM
) -> FidelityReport:
    """执行忠实度评估"""
    # 1. 编码有效性（纯 Python）
    code_valid = _check_code_validity(operations)

    # 2. 面积一致性（regex 提取原文面积 + 比对）
    area_consistency = _check_area_consistency(original_text, operations)

    # 3. 地名召回（regex 提取原地名 + 比对 SpatialAnchor）
    place_recall = _check_place_recall(original_text, operations)

    # 4-5. 操作/约束覆盖率（LLM 轻量评判）
    op_cov, con_cov = _llm_coverage_check(original_text, operations, constraints, llm)

    overall = (
        code_valid.pass_rate * 0.4
        + area_consistency.score * 0.2
        + place_recall.recall_rate * 0.2
        + op_cov * 0.1
        + con_cov * 0.1
    )

    return FidelityReport(
        code_validity=code_valid,
        area_consistency=area_consistency,
        place_recall=place_recall,
        operation_coverage=op_cov,
        constraint_coverage=con_cov,
        overall_score=overall,
        ...
    )
```

**文件**: 新建 `backend/app/agent/gis/evaluate_fidelity.py`
**文件**: 修改 `backend/app/agent/gis/parse/agent.py` — 添加 `evaluate_fidelity` 节点到 graph

### 评估阈值

| 维度       | 方法                                  | 通过阈值                 |
| ---------- | ------------------------------------- | ------------------------ |
| 编码有效性 | Python 查表`GHYTBM_TO_GHYTMC`       | **100%**（硬要求） |
| 面积一致性 | 正则提取原文面积 + 对比               | **偏差 <20%**      |
| 地名召回   | 正则提取原文地名 + SpatialAnchor 对比 | **召回率 >70%**    |
| 操作覆盖率 | 轻量 LLM 评判                         | **覆盖率 >60%**    |
| 约束覆盖率 | 轻量 LLM 评判                         | **覆盖率 >50%**    |

---

## 6. Path 5: 并行度提升（P1，1天）

### 当前瓶颈

15 个节点全串行，总耗时 ~300s。format 和 explore 节点之间有独立数据依赖，可安全并行。

### 并行化点

| 并行组 | 节点                                                      | 安全性                                              | 预期加速 |
| ------ | --------------------------------------------------------- | --------------------------------------------------- | -------- |
| 组1    | format_projects ‖ format_targets                         | ✅ 安全：各自独立 draft + 独立 state key            | ~1.5x    |
| 组2    | extract_regulations ‖ extract_tables ‖ explore_projects | ✅ 安全：各自读取不同 section text                  | ~1.3x    |
| 组3    | 两轮 ReAct 优化                                           | ✅ 如果第一轮 tool_calls 已覆盖所有实体，跳过第二轮 | ~1.2x    |

### 实现

```python
# 使用 LangGraph Send API 实现并行 fan-out
from langgraph.types import Send

def route_parallel(state: ParseAgentState):
    """并行路由：根据 section_map 同时发起所有独立节点"""
    sends = []

    # 组2: explore 节点可以并行
    if state.section_map.get("projects"):
        sends.append(Send("explore_projects", {"sections": state.projects_sections}))
    if state.section_map.get("regulations"):
        sends.append(Send("extract_regulations", {"sections": state.regulation_sections}))

    return sends

# graph builder 中:
graph.add_conditional_edges("route_by_section", route_parallel, [
    "explore_projects", "extract_regulations", "extract_tables"
])

# 组1: format 节点也并行
graph.add_conditional_edges("after_explore", route_format_parallel, [
    "format_projects", "format_targets"
])
```

**预期效果**: 总耗时 300s → 150-180s（~1.7-2x 加速）

**文件**: `backend/app/agent/gis/parse/agent.py` — `route_by_section`, `build_parse_agent_graph`

---

## 7. Path 6: 注记+空间关系+KG 注入（P2，2天）

### 问题

LLM 只知道统计数字（660地块、2396ha），无法建立空间心智模型。而且KG对于schema利用不够，自定义了很多关系之类的，没有考虑后续增加栅格数据，增加分析工具的提升。

### 可利用的已有数据

| 数据              | 位置                                       | 当前状态                              |
| ----------------- | ------------------------------------------ | ------------------------------------- |
| 34 个设施注记点   | `current/annotation.geojson`, KG triples | ✅ 已入KG，**未注入LLM prompt** |
| 225 条空间关系    | `spatial_context.spatial_relations`      | ✅ 已计算，**未注入LLM prompt** |
| 18 个 SPARQL 模板 | `builder.py`                             | ⚠️ 只用1个（get_constraints）       |
| 15 个自然村锚点   | `spatial_context.natural_villages`       | ✅ 已注入但LLM未充分使用              |

### 修改点

**A. 注入设施分布摘要** (`spatial_context.py` — `format_spatial_context_for_prompt`):

```python
## 现状设施分布（来自GIS注记层，34个设施点）
| 设施类型 | 计数 | 主要分布 |
|----------|------|----------|
| 篮球场(篮) | 3 | VillageGroup_3, VillageGroup_7, VillageGroup_12 |
| 卫生站(卫/健) | 3 | VillageGroup_1, VillageGroup_5, VillageGroup_9 |
| 变电站(电) | 2 | VillageGroup_2, VillageGroup_8 |
| 污水处理(污) | 1 | VillageGroup_4 |
| 祠堂(祠) | 2 | VillageGroup_1, VillageGroup_6 |
| ... | ... | ... |
```

**B. 注入空间关系摘要**:

```
## 自然村空间关系（225条，方向+邻接）
- VillageGroup_1 (园寨): 位于VillageGroup_2西侧，相邻；含66块地类图斑，以宅基地(2121)为主
- VillageGroup_2 (社前): 位于VillageGroup_1东侧；含78块地类图斑，沿金田河分布
- VillageGroup_3 (田坑): 位于村庄北部；含45块地类图斑，以耕地(1100)为主
...
```

**C. 新增 `query_facilities` KG 工具** (`parse/agent.py` L197):

```python
@_langchain_tool
def query_facilities(anchor_name: str = "", facility_type: str = "") -> str:
    """Query facilities near a village anchor or by type.
  
    Examples:
      query_facilities(anchor_name="园寨") → nearby facilities within 500m
      query_facilities(facility_type="卫生") → all health-related facilities
    """
    kg = _kg_instance
    if kg is None:
        return json.dumps({"error": "KG not initialized"})
    return kg.query_facilities(anchor_name=anchor_name, facility_type=facility_type)
```

**文件**:

- `backend/app/modules/gis/spatial_context.py` — `format_spatial_context_for_prompt`
- `backend/app/agent/gis/parse/agent.py` — 新增 `query_facilities` 工具
- `backend/app/modules/gis/kg/builder.py` — 新增 `query_facilities` SPARQL 方法

---

## 8. Path 7: DEM 数据准备（P2，0.5天）

### 问题

`raster_types.py` + `dem_provider.py` 已有完整分析基础设施，但数据文件缺失。

### 操作

1. 从地理空间数据云 (gscloud.cn) 下载 GDEMV3 30m，覆盖金田村（116.03-116.06°E, 24.81-24.83°N）
2. 放置到 `data/gis/jintian/terrain/dem.tif`
3. 运行 `TerrainAnalyzer` 计算坡度/坡向/建设适宜性
4. 注入 SpatialContext: `terrain_profile = {slope_violations_gt25: N, flat_areas_lt6: M, ...}`

**文件**:

- `data/gis/jintian/terrain/dem.tif` (新下载)
- `backend/app/modules/gis/spatial_context.py` — 新增 terrain 注入

---

## 9. Path 8: query_village_kg 工具实际执行（P0，1天）

### 问题

`query_village_kg` 工具当前是空壳：

```python
@_langchain_tool
def query_village_kg(template_name: str, **params) -> str:
    return "Tool called — execution handled by agent loop."  # 没有实际执行！
```

LLM 调用 `query_village_kg('count_by_zone_type')` 等工具时，得到的是占位符字符串，不是真实 KG 查询结果。这导致：

- PARSE 无法获取现状地类分布作为 `area_ratio` 参考
- PARSE 无法获取真实保护区域边界作为约束
- explore 阶段的 tool_calls 全部无效

### 根因

工具定义在 `agent.py` 中，但执行逻辑未实现。需要：

1. 实现 SPARQL 模板查询（`count_by_zone_type`, `get_designated_zones`, `get_constraints` 等）
2. 将 KG 实例绑定到工具函数
3. 返回结构化 JSON 而非占位符字符串

### 修改点

**A. 实现 `query_village_kg` 实际执行** (`parse/agent.py` L229):

```python
@_langchain_tool
def query_village_kg(template_name: str, **params) -> str:
    """Query village planning knowledge graph for spatial information.
  
    Available templates:
      - count_by_zone_type: 返回现状地类分布 {zone_type: {count, total_area_ha}}
      - get_designated_zones: 返回规划分区 {zone_type: {area_ha, parcels}}
      - get_constraints: 返回约束列表 [{type, zone_type, rule, area_ha}]
      - get_adjacent_parcels: 返回邻接地块 {parcel_id: [adjacent_ids]}
      - check_protected_parcels: 返回保护地块列表 [parcel_ids]
      - get_road_network: 返回道路网络 [{road_id, length_m, connects}]
      - get_water_bodies: 返回水域 [{water_id, area_ha, type}]
    """
    import json as _json
  
    # Get KG instance from manager
    from app.modules.kg.manager import get_kg_manager
    manager = get_kg_manager()
    kg = manager.get_kg("parse_pipeline")  # or current session
  
    if kg is None:
        return _json.dumps({"error": "KG not initialized"}, ensure_ascii=False)
  
    # Execute SPARQL template
    try:
        if template_name == "count_by_zone_type":
            result = kg.query_count_by_zone_type()
        elif template_name == "get_designated_zones":
            result = kg.query_designated_zones(**params)
        elif template_name == "get_constraints":
            result = kg.query_constraints(**params)
        elif template_name == "get_adjacent_parcels":
            result = kg.query_adjacent_parcels(**params)
        elif template_name == "check_protected_parcels":
            result = kg.query_protected_parcels(**params)
        else:
            return _json.dumps({"error": f"Unknown template: {template_name}"}, ensure_ascii=False)
      
        return _json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return _json.dumps({"error": str(e), "template": template_name}, ensure_ascii=False)
```

**B. 在 `PlanningKG` 中实现查询方法** (`modules/kg/builder.py`):

```python
def query_count_by_zone_type(self) -> Dict[str, Dict[str, Any]]:
    """Return current landuse distribution by zone_type."""
    sparql = """
    SELECT ?zone_type (COUNT(?parcel) as ?count) (SUM(?area) as ?total_area)
    WHERE {
        ?parcel a :Parcel ;
                :hasZoneType ?zone_type ;
                :hasArea ?area .
    }
    GROUP BY ?zone_type
    """
    results = self.g.query(sparql)
    return {
        str(row.zone_type): {
            "count": int(row.count),
            "total_area_ha": float(row.total_area) / 10000.0,
        }
        for row in results
    }
```

**文件**:

- `backend/app/agent/gis/parse/agent.py` — 实现 `query_village_kg` 实际执行
- `backend/app/modules/kg/builder.py` — 新增 SPARQL 查询方法

---

## 10. Path 9: DB 12 维度并行化（P1，1天）

### 问题

DB 来源运行时：

- 12 个维度合并后 17688 chars，截断到 12000 chars，丢失信息
- validate_and_merge 处理大量结构化输出，LLM 响应超时（489s，8 分钟）
- 最终 operations=0（LLM 连接问题）

### 根因

当前实现是串行处理：

1. `load_l3_from_db()` 合并 12 个维度为单一文本
2. PARSE Agent 一次性处理全部文本
3. 文本过长导致截断 + LLM 处理超时

### 修改点

**A. 维度级并行处理架构**:

```
DB 12 维度
  ├─ dimension 1 (industry) → PARSE Agent (轻量) → partial_ops_1
  ├─ dimension 2 (spatial_structure) → PARSE Agent → partial_ops_2
  ...
  └─ dimension 12 (project_bank) → PARSE Agent → partial_ops_12
       ↓
  Merge Node: 合并 12 个 partial results
       ↓
  Validate & Deduplicate
       ↓
  Final Output
```

**B. 每个维度独立调用 PARSE Agent**:

```python
async def parse_dimension(dimension_key: str, content: str, spatial_context: SpatialContext) -> Dict:
    """Parse a single dimension independently."""
    # 使用轻量 prompt（只提取该维度的操作/约束/目标）
    prompt = DIMENSION_PARSE_PROMPT.format(
        dimension_key=dimension_key,
        content=content[:2000],  # 单个维度通常 < 2000 chars
        spatial_context=format_spatial_context_for_prompt(spatial_context, "minimal"),
    )
  
    # 轻量 LLM 调用（thinking_budget=500, max_tokens=4096）
    llm = _get_llm(enable_thinking=True, thinking_budget=500)
    result = await _format_structured(llm, DimensionParseResult, [SystemMessage(...), HumanMessage(content=prompt)])
  
    return {
        "operations": result.operations if result else [],
        "constraints": result.constraints if result else [],
        "zone_targets": result.zone_targets if result else [],
    }
```

**C. 合并节点去重 + 校验**:

```python
async def merge_dimension_results(results: List[Dict]) -> Dict:
    """Merge 12 dimension parse results."""
    all_ops = []
    all_constraints = []
    all_targets = []
  
    for r in results:
        all_ops.extend(r.get("operations", []))
        all_constraints.extend(r.get("constraints", []))
        all_targets.extend(r.get("zone_targets", []))
  
    # Deduplicate by source_text
    seen_sources = set()
    unique_ops = []
    for op in all_ops:
        src = op.get("source_text", "")
        if src not in seen_sources:
            seen_sources.add(src)
            unique_ops.append(op)
  
    # Validate area_ratio sum
    total_ratio = sum(t.get("area_ratio", 0) for t in all_targets)
    if abs(total_ratio - 1.0) > 0.05:
        logger.warning(f"[DB Merge] area_ratio sum = {total_ratio:.1%}, needs adjustment")
  
    return {
        "operation_sequence": unique_ops,
        "constraint_set": all_constraints,
        "planning_intent": SpatialPlanningIntent(zone_targets=all_targets),
    }
```

**文件**:

- `backend/scripts/run_parse_pipeline.py` — 新增 `parse_dimension()` + `merge_dimension_results()`
- `backend/app/modules/prompts/parse_prompts.py` — 新增 `DIMENSION_PARSE_PROMPT`

**预期效果**:

| 指标              | 当前（串行）                | 并行化后                      |
| ----------------- | --------------------------- | ----------------------------- |
| 文本截断          | 17688 → 12000 (32% 丢失)   | 每个维度 < 2000 chars，无截断 |
| LLM 超时          | 489s (format_projects 超时) | 每维度 ~30s，12 维度并行 ~60s |
| 操作产出          | 0 (超时失败)                | 预计 20-30 ops                |
| area_ratio 完整性 | 83.6% (遗漏水域等)          | 各维度独立提取，合并后补全    |

---

## 11. 执行路线图

### 第一批：P0 — 让 30 个操作可用（3天）

```
Path 1 (0.5天) → Path 2 (1天) → Path 3 (1天) → Path 8 (1天) → 联调 (0.5天)
```

**里程碑**: 金田村解析 → ≥20/30 编码正确 + ≥15/30 锚定已解析 + ≥5 条约束 + query_village_kg 工具实际执行 →
**可交付 GIS Agent 生成第一版规划分区图 + 规划设施图**

### 第二批：P1 — 质量与效率（2.5天）

```
Path 4 (1.5天) → Path 5 (1天) → Path 9 (1天)
```

**里程碑**: 忠实度各维度 >60% + 总耗时 <180s + DB 来源可正常运行

### 第三批：P2 — 深度空间理解（2.5天）

```
Path 6 (2天) → Path 7 (0.5天)
```

**里程碑**: 锚定置信度 >0.5 的 ops >70% + 地形约束可解析

---

## 12. 修改文件清单

| 优先级           | 文件                                             | 改动类型       | 改动内容                                                                                              |
| ---------------- | ------------------------------------------------ | -------------- | ----------------------------------------------------------------------------------------------------- |
| **P0**     | `backend/app/agent/gis/parse/agent.py`         | 修改           | 编码硬校验`_auto_correct_code` + 锚定自动填充 `_auto_fill_spatial_anchor` + 约束 regex 扩展       |
| **P0**     | `backend/app/agent/gis/parse/agent.py`         | 修改           | `extract_regulations_node` 分拆 Phase A(regex) + Phase B(LLM)                                       |
| **P0**     | `backend/app/agent/gis/parse/agent.py`         | 修改           | `query_village_kg` 工具实际执行 SPARQL 查询                                                         |
| **P0**     | `backend/app/modules/kg/builder.py`            | 修改           | 新增 SPARQL 查询方法：`query_count_by_zone_type`, `query_designated_zones`, `query_constraints` |
| **P1**     | `backend/app/agent/gis/evaluate_fidelity.py`   | **新建** | 忠实度评估器：五维评估 + FidelityReport                                                               |
| **P1**     | `backend/app/agent/gis/parse/agent.py`         | 修改           | graph 添加`evaluate_fidelity` 节点 + LangGraph Send 并行                                            |
| **P1**     | `backend/scripts/run_parse_pipeline.py`        | 修改           | DB 12 维度并行化：`parse_dimension()` + `merge_dimension_results()`                               |
| **P1**     | `backend/app/modules/prompts/parse_prompts.py` | 修改           | 新增`DIMENSION_PARSE_PROMPT`                                                                        |
| **P2**     | `backend/app/modules/gis/spatial_context.py`   | 修改           | `format_spatial_context_for_prompt` 注入注记摘要+空间关系                                           |
| **P2**     | `backend/app/agent/gis/parse/agent.py`         | 修改           | 新增`query_facilities` KG 工具                                                                      |
| **P2**     | `backend/app/modules/gis/kg/builder.py`        | 修改           | 新增`query_facilities` SPARQL 方法                                                                  |
| **P2**     | `data/gis/jintian/terrain/dem.tif`             | 新数据         | GDEMV3 30m DEM 下载                                                                                   |
| **已修复** | `backend/app/modules/gis/schema/code_sets.py`  | 修改           | 新增`GHYTMC_TO_PLANNING_ZONE` 映射                                                                  |
| **已修复** | `backend/app/tools/gis/generate.py`            | 修改           | `_make_planning_zone_layer` 使用 GHYTMC_TO_PLANNING_ZONE 映射                                       |
| **已修复** | `backend/app/tools/gis/generate.py`            | 修改           | Direction 枚举容错 + AxisIntent label 保留                                                            |
| **已修复** | `backend/scripts/run_layout_pipeline.py`       | 修改           | 村名别名映射 +`kg.to_turtle()` 修复                                                                 |
| **已修复** | `backend/app/tools/gis/allocate.py`            | 修改           | `hasattr` bool 切片修复                                                                             |
| **已修复** | `backend/app/utils/geojson_utils.py`           | 修改           | `gpd.GeoDataFrame` 字符串注解                                                                       |
| **已修复** | `requirements.txt`                             | 修改           | 新增 9 个缺失依赖包                                                                                   |

---

## 13. 验证方案

### 端到端测试

```bash
cd backend
# Test MinerU source
python -m scripts.run_parse_pipeline --source mineru
python -m scripts.run_layout_pipeline --source mineru

# Test DB source (after Path 9)
python -m scripts.run_parse_pipeline --source db
python -m scripts.run_layout_pipeline --source db

# Test compare mode
python -m scripts.run_layout_pipeline --compare
```

检查 `output/parse_results/金田村_YYYY-MM-DD.md`:

| 检查项                  | 目标值                 |
| ----------------------- | ---------------------- |
| 编码正确的操作数        | ≥ 25/30               |
| 锚定已解析的操作数      | ≥ 15/30               |
| 约束数量                | ≥ 5                   |
| 规划意图 (zone_targets) | ≥ 5 分区 + ≥ 10 设施 |
| area_ratio 之和         | 95%-105%               |
| 校验通过率              | > 70%                  |
| 忠实度 overall_score    | > 0.6                  |
| 总耗时                  | < 180s                 |

### LAYOUT Pipeline 验证

检查 `output/layout_results/jintian_YYYY-MM-DD/`:

| 检查项                       | 目标值                |
| ---------------------------- | --------------------- |
| planning_zone.png 非空白     | ✅ 4 区颜色正确       |
| comparison.png 左右对比      | ✅ 现状 vs 规划       |
| mip_result.json zone_targets | 8 个 zone，偏差 < 10% |
| validation_detail.json       | 3 轮验证记录          |
| trace 文件完整性             | 4 个 JSON 文件        |

---

## 14. 与原始 v1.1 提案的关系

| v1.1 主张                             | v2.1 调整                                                                                                  |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 升级 SpatialContext 为"统计+空间关系" | **不再争论设计**。现有 statistics-only 框架足以支撑 Path 1-3 的修复。空间关系增强移至 P2 的 Path 6   |
| 重写 parse/state.py 全部 Schema       | **不重写**。现有 Schema 定义正确，问题是 LLM→Python 数据传递链断裂 + 工具空壳，通过 Path 1+2+8 修复 |
| 新建 spatial_context.py               | **已实现**。当前 spatial_context.py 工作正常，Path 6 仅增强其 prompt 输出                            |
| 修订 DESIGN_GOALS §6                 | **暂缓**。先验证 Path 1-3+8 能否在现有框架内解决问题                                                 |
| DB 12 维度串行处理                    | **Path 9 并行化**。当前串行处理导致文本截断 + LLM 超时，需拆分为维度级并行                           |

---

## 附录 A: v11 实测数据速查

来自 `output/parse_results/金田村_2026-07-22.md`：

- **30 个操作**: 全部 CREATE 类型，28个宅基地(2121无效) + 1个耕地 + 1个危房改造
- **面积范围**: 120-9300 m²
- **空间参照**: 候车亭、村级公共服务中心、文化室、综合服务中心、卫生站、养老中心、文化广场、篮球场、公共厕所、给水管道、排水管道、污水池... 全部 confidence=0
- **校验**: 46 错误 = 23 编码无效 + 23 锚定置信度低
- **约束**: 0 条
- **规划意图**: 仅有 4 个面积指标，无 zone_targets/facilities/axes

## 附录 B: v12 管线测试数据速查

来自 `output/parse_results/金田村_2026-07-23.md`（MinerU 来源）+ `output/layout_results/jintian_2026-07-23/`：

- **PARSE**: ops=4, constraints=2, zone_targets=8, valid=False (area_ratio=83.6%)
- **LAYOUT**: KG=9395 triples, MIP=Optimal/5280 vars/8 zones, Generate=6 layers, Validate=5/8 checks
- **渲染**: planning_zone.png 非空白（4 区颜色正确），comparison.png 现状 vs 规划对比清晰
- **Trace 文件**: kg_output.json (577 KB), allocation_result.json (6.3 MB), validation_detail.json (4.7 KB), pipeline_run.json, mip_result.json (3.3 KB)
- **总耗时**: PARSE 377s + LAYOUT 63s = 440s
- **已修复 Bug**: 9 个（见 §0.3 已修复表格）
