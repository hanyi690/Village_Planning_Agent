# PARSE 与 GIS 空间理解结合度分析

> 版本: 1.0 | 日期: 2026-07-16 | 状态: 设计讨论
> 触发问题: "parse设计的与gis结合度不足，真的能辅助gis agent做到空间理解吗"

## 0. 前提澄清

**DESIGN_GOALS.md v5.0 是权威设计文档**，parse_state.py 是部分实现。本分析基于设计文档，不将实现当设计。

DESIGN_GOALS.md §6 技术决策明确写道：

> **GIS 数据注入**: PARSE 阶段注入 GIS 现状摘要（统计信息，不含几何）
> **不选**: 不注入
> **理由**: LLM 需参照现状提取——自然村名/地类面积锚定防止幻觉

**"统计信息，不含几何"是显式设计决策**，不是实现遗漏。本分析的核心问题是：**这个设计决策是否充分？**

---

## 1. 当前设计回顾

### 1.1 PARSE 的设计定位

从 DESIGN_GOALS §3.2-3.3，PARSE Agent 是：

- **输入**: 规划文本 + GIS 现状摘要（统计信息，不含几何）
- **工具**: 3 个（parse_planning_text, extract_structured_text, lookup_land_use_code）
- **流程**: classify → route → extract → validate
- **输出**: OperationSequence + ConstraintSet + IntentJSON
- **架构**: 半结构化 ReAct（确定性骨架 + LLM 节点）

### 1.2 PARSE → LAYOUT 的交接面

```
PARSE 输出:
  OperationSequence: List[OperationItem]  # 5 种原子操作
  ConstraintSet: List[ConstraintItem]      # 约束规则
  IntentJSON: Dict                         # 规划意图

LAYOUT 消费:
  OperationSequence → EXECUTE_OPERATIONS（空间定位 → 合规预检 → 执行）
  ConstraintSet → KG（约束三元组 + 合规规则）
  IntentJSON → MIP 分配目标
```

### 1.3 空间定位的设计归属

DESIGN_GOALS §3.4 五步闭环流程明确将**空间定位**放在 LAYOUT 的 EXECUTE_OPERATIONS 阶段：

```
② 空间定位 → 候选图斑
   ① 地名解析 → 找到"刘村小组"点位 → 向东偏移
   ② 在搜索区寻找"晒谷场"图斑 → 分析其北侧相邻地块
   ③ 找到空闲地图斑 XG-005（面积≥400㎡）→ 作为操作对象
   ④ 若多个候选 → 生成列表要求规划师点击确认
```

**设计意图**: PARSE 负责"提取文本说了什么"，LAYOUT 负责"在空间上落地"。

---

## 2. 差距诊断：5 个具体问题

### 问题 1: GISSummary 只有统计，LLM 无法建立空间心智模型

**当前设计**:

```python
GISSummary:
  parcel_count, current_landuse_stats, natural_villages,
  planning_zone_stats, total_area_ha, construction_boundary_ha
```

**具体场景**: PARSE 提取到 `OperationItem(action="create", location_desc="刘村小组东侧")` 时：

- LLM 知道 natural_villages 包含 "刘村小组" ✓
- LLM 不知道 "刘村小组" 在村庄的哪个方位 ✗
- LLM 不知道 "东侧" 有什么地类分布 ✗
- LLM 无法判断 "东侧" 是否有足够空间容纳 400㎡ 新建用地 ✗

**影响**: PARSE 的 `location_desc` 是"盲写"——LLM 写下空间描述但无法验证其合理性。

### 问题 2: OperationItem 的 location_desc 是自由文本，无空间锚点

**当前设计**: `location_desc: Optional[str]` 纯文本

**具体场景**: `"刘村小组东侧、晒谷场北边空地"`

- LAYOUT 的 `resolve_place_name` 需要独立解析这段文本
- 但 PARSE 已经"看过"GIS 数据，本可以预判候选图斑
- 信息在 PARSE → LAYOUT 传递中丢失

**对比参考项目 Spatial-Agent (arXiv:2601.16965)**:

> "formalizes geo-analytical QA as a concept transformation problem"
> 自然语言 → 空间概念节点 + 变换边 → 可执行工作流

Spatial-Agent 的关键洞察：**解析阶段就应将语言映射为具有几何含义的计算表示**，而非延迟到执行阶段。

### 问题 3: ConstraintItem 的 spatial_constraint 无法直接映射为空间运算

**当前设计**: `spatial_constraint` 只有 `zone_type` + `rule`（自由文本）

**具体场景**: `"允许建设区内不得安排基本农田"`

- PARSE 提取为 `ConstraintItem(type="spatial_constraint", zone_type="允许建设区", rule="不得安排基本农田")`
- LAYOUT 的 KG 需要重新将这条规则编码为 RDF 三元组
- 但这条规则可以直接表示为空间运算：`intersection(建设区, 基本农田) == empty`

**对比参考项目 GeoAgents**:

> `spatial.intersects` 和 `spatial.nearby` 是一等公民工具
> 约束 = 确定性空间操作 + 参数

### 问题 4: PlanningIntent 缺乏空间排列信息

**当前设计**: `zone_targets: Dict[str, float]` 只有面积比例

**具体场景**: 规划报告写 "居住用地集中在村庄中心，产业用地布局在村庄外围"

- PARSE 提取为 `zone_targets = {"居住用地": 0.35, "产业用地": 0.15}`
- 面积比例正确，但"中心"vs"外围"的空间偏好丢失
- MIP 分配器只能优化面积偏差 + 邻接紧凑度，无法利用空间偏好

**注意**: prompts.py 的 SPATIAL_LAYOUT_PARSE_PROMPT 已定义 `location_bias.direction` 和 `adjacency` 字段，但 PlanningIntent 的 zone_targets 是简单 Dict，**设计上没有携带这些信息**。

### 问题 5: PARSE → LAYOUT 单向无反馈

**当前设计**: state injection 是单向的

**具体场景**: PARSE 提取 `location_desc="晒谷场北侧"` 但 GIS 数据中不存在"晒谷场"

- LAYOUT 的 resolve_place_name 解析失败
- 无法回退到 PARSE 要求补充描述
- 操作只能标记为 `resolution_status="unresolved"` 等待人工干预

**对比参考项目 GeoPlanAgent**:

> "document-grounded, geospatial-tool-in-the-loop"
> 解析和空间推理交替进行：解析 → 定位 → 失败 → 补充解析 → 重试

---

## 3. 根因分析

### 3.1 设计决策的原始理由

DESIGN_GOALS §6 记录的技术决策：

| 决策         | 选择                                              | 不选   | 理由                                                |
| ------------ | ------------------------------------------------- | ------ | --------------------------------------------------- |
| GIS 数据注入 | PARSE 阶段注入 GIS 现状摘要（统计信息，不含几何） | 不注入 | LLM 需参照现状提取——自然村名/地类面积锚定防止幻觉 |

**原始理由只考虑了"不注入"的对比**，没有考虑"注入更多空间信息"的选项。

### 3.2 可能的隐性考量

1. **上下文窗口限制**: 660 个地块的 GeoJSON ≈ 5MB，注入 LLM 不经济
2. **单一职责**: PARSE 负责文本，LAYOUT 负责空间
3. **确定性保证**: PARSE 不做空间决策（避免 LLM 选错图斑）

### 3.3 这些考量是否仍然成立？

1. **上下文窗口**: ✗ 不需要注入原始几何——只需要空间关系摘要（~2KB），参考 Spatial-Agent 的 "spatial grounding" 概念
2. **单一职责**: ✗ 不冲突——PARSE 仍负责文本提取，但输出应携带空间语义（不是做空间计算）
3. **确定性保证**: ✓ 仍然成立——PARSE 不应执行空间操作，但应提供空间锚定信息供 LAYOUT 验证

---

## 4. 参考项目关键启示

### 4.1 Spatial-Agent (arXiv:2601.16965) — 最相关

**核心概念**: GeoFlow Graph

- 自然语言 → 空间概念节点（Object/Field/Event/Network）+ 变换边
- 每个节点有明确的几何含义
- 模板库加速常见空间模式的生成

**对本项目的启示**:

> PARSE 应输出"空间概念 + 变换关系"的抽象表示，而非自由文本。
> 例如 "刘村小组东侧" → SpatialAnchor(reference="刘村小组", offset="east")
> 而非 location_desc="刘村小组东侧"

### 4.2

 GeoPlanAgent (degenfabian/GeoPlanAgent)

**核心概念**: document-grounded, geospatial-tool-in-the-loop

- 解析与空间推理交替进行
- 工具在解析过程中被调用

**对本项目的启示**:

> 太激进——本项目坚持"人工确认"原则，PARSE 阶段不应执行空间操作。
> 但启示是：PARSE 阶段应能**查询**空间信息来验证提取结果。

### 4.3 GeoAgents (juaquicar/GeoAgents)

**核心概念**: spatial 工具一等公民

- `spatial.context_pack`: 为位置生成空间上下文
- `spatial.intersects`, `spatial.nearby`: 空间关系查询

**对本项目的启示**:

> ConstraintItem 应能直接映射为空间操作（no_overlap, buffer_exclusion, contained_by）。
> 当前 rule 自由文本是信息浪费。

### 4.4 GeoWorkbench (chrislyonsKY/GeoWorkbench)

**核心概念**: 空间语义是显式管线阶段

- Intent Interpretation → Dataset Discovery → **Spatial Semantics** → Workflow Planner

**对本项目的启示**:

> `compute_spatial_context()` 应是 PARSE 之前的独立阶段，
> 将 GISDataBundle 转为紧凑的 SpatialContext 注入 PARSE。

### 4.5 GISDataAgent (zhouning/gisdataagent)

**核心概念**: 地理知识图谱

- networkx 实体关系建模，空间邻接/包含关系检测，N跳邻居查询

**对本项目的启示**:

> SpatialContext 应包含从 GIS 数据计算的空间关系图（邻接、包含、方向），
> 而非只有统计数字。

---

## 5. 设计方案建议

### 5.1 核心原则

**不改变"PARSE 不做空间计算"原则**，但让 PARSE 输出具有空间语义的中间表示。

类比：PARSE 是"读懂图纸的助理"——助理不需要画图，但需要理解"东侧"意味着什么。

### 5.2 升级 GISSummary → SpatialContext

**设计变更**: 在 PARSE 之前增加 `compute_spatial_context()` 阶段

```
Before:
  GISDataBundle → GISSummary(统计) → PARSE

After:
  GISDataBundle → compute_spatial_context() → SpatialContext(统计+空间关系) → PARSE
```

**SpatialContext 新增内容**（~2KB，不注入原始几何）:

| 新增字段                | 类型                 | 来源                          | 用途               |
| ----------------------- | -------------------- | ----------------------------- | ------------------ |
| village_center          | (lon, lat)           | boundary 质心                 | LLM 空间参照原点   |
| natural_village_anchors | List[Anchor]         | 图斑聚类 + DLMC 字段 + POI 搜索 | 解析 location_desc |
| spatial_relations       | List[Relation]       | 图斑邻接计算                  | LLM 理解空间关系   |
| constraint_summary      | List[Constraint]     | 保护图层概要                  | 结构化约束提取     |
| zone_adjacency          | Dict[str, List[str]] | 分区邻接矩阵摘要              | MIP 邻接偏好       |

**NaturalVillageAnchor**:

```python
class NaturalVillageAnchor(BaseModel):
    name: str                    # "刘村小组"
    center: Tuple[float, float]  # (116.xx, 23.xx)
    parcel_ids: List[str]        # ["XG-001", "XG-002"]
    dominant_landuse: str        # "宅基地"
    adjacent_to: List[str]       # ["晒谷场", "主干道"]
```

**SpatialRelation**:

```python
class SpatialRelation(BaseModel):
    subject: str        # "刘村小组"
    relation: str       # "east_of" / "adjacent_to" / "contains" / ...
    object: str         # "晒谷场"
    confidence: float   # 1.0 (几何计算) / 0.7 (别名查找)
```

### 5.3 升级 OperationItem → 添加 SpatialAnchor

**设计变更**: `location_desc` 自由文本 → `SpatialAnchor` 结构化空间锚定

```python
class SpatialAnchor(BaseModel):
    reference: str = ""              # 主参照: "刘村小组"
    offset: Optional[str] = None     # 方向偏移: "east"
    secondary_ref: Optional[str] = None   # 次参照: "晒谷场"
    secondary_offset: Optional[str] = None
    candidate_parcels: List[str] = []     # 预判候选图斑
    confidence: float = 0.0
    resolution_status: str = "unresolved"
    # "anchored" = 已锚定, "partial" = 锚定到区域, "unresolved" = 需 LAYOUT 解析
```

**OperationItem 变更**:

```python
class OperationItem(BaseModel):
    # ... 保留所有现有字段 ...
    location_desc: Optional[str] = None  # 保留作为 fallback
    spatial_anchor: Optional[SpatialAnchor] = None  # 新增
```

**关键**: PARSE 不执行空间操作，但利用 SpatialContext 中的 natural_village_anchors 预判候选图斑。如果预判成功，`resolution_status="anchored"`；否则 `"unresolved"` 交给 LAYOUT。

### 5.4 升级 ConstraintItem → 添加 SpatialRule

**设计变更**: `rule` 自由文本 → `SpatialRule` 可计算空间规则

```python
class SpatialRule(BaseModel):
    operation: str   # "no_overlap" / "buffer_exclusion" / "contained_by" / ...
    subject: str     # "建设区"
    object: str      # "基本农田"
    distance_m: Optional[float] = None  # buffer_exclusion 时必填
```

**ConstraintItem 变更**:

```python
class ConstraintItem(BaseModel):
    # ... 保留所有现有字段 ...
    rule: Optional[str] = None  # 保留自由文本作为 fallback
    spatial_rule: Optional[SpatialRule] = None  # 新增
```

**映射关系**:

| 规划文本                       | SpatialRule                       | Shapely 等价            |
| ------------------------------ | --------------------------------- | ----------------------- |
| "允许建设区内不得安排基本农田" | no_overlap(建设区, 基本农田)      | intersection() == empty |
| "产业用地距居住区≥200m"       | buffer_exclusion(产业, 居住, 200) | distance() > 200        |
| "宅基地必须在建设边界内"       | contained_by(宅基地, 建设边界)    | within()                |

### 5.5 升级 PlanningIntent → 添加空间偏好

**设计变更**: `zone_targets: Dict[str, float]` → `List[ZoneTarget]` 携带空间偏好

```python
class ZoneTarget(BaseModel):
    land_use: str
    area_ratio: float
    dlbm: Optional[str] = None
    spatial_preference: Optional[SpatialPreference] = None  # 新增
    adjacency_rules: Optional[AdjacencyRules] = None  # 新增

class SpatialPreference(BaseModel):
    direction: Optional[str] = None   # "center" / "north" / ...
    reference: Optional[str] = None   # "靠近村委会"

class AdjacencyRules(BaseModel):
    prefer: List[str] = []   # 希望邻接
    avoid: List[str] = []    # 避免邻接
```

**注意**: prompts.py 的 SPATIAL_LAYOUT_PARSE_PROMPT 已定义 `location_bias.direction` 和 `adjacency` 字段——这些信息在 LLM 生成时已经存在，只是 PlanningIntent 没有携带。现在激活这些已有定义。

---

## 6. 原创性分析：我们与参考项目的本质区别

### 6.1 参考项目解决什么问题？我们解决什么问题？

| 项目 | 领域 | 核心问题 | 输入 | 输出 |
|------|------|---------|------|------|
| Spatial-Agent | 通用地理空间 QA | "哪个地铁站 1km 内犯罪率最高？" | 自然语言问题 | 数值答案 |
| GeoPlanAgent | 英国规划文档 → 边界 | 从 PDF 重建 GeoJSON 边界 | 规划 PDF + 地图图片 | GeoJSON 边界 |
| GeoAgents | 通用 GIS 分析 | "这个区域有哪些学校？" | 空间查询 | 分析报告 |
| OpenEarthAgent | 遥感影像分析 | "这片区域 NDVI 变化如何？" | 卫星影像 + 查询 | 指数图 + 统计 |
| GeoFaham | 自然语言 → GIS 工作流 | "分析佛罗伦萨的城市热岛" | 自然语言 | 代码 + 地图 |
| **本项目** | **中国村庄规划编制** | **规划文本 → 14 层标准 GIS 成果** | **规划报告 + GIS 现状** | **GDB 14 层 + 平衡表** |

**本质区别**：参考项目都是"问答型"或"分析型"——输入一个问题，输出一个答案。
本项目是**"编制型"**——输入规划文本，输出一整套合规的 GIS 成果包。这要求：

1. **编码合规**：每个图斑的 20 个字段必须符合 GB/T 21010 + DB22/T 3407
2. **面积守恒**：660 地块面积总和不可变，split/merge 操作必须守恒
3. **三线约束**：生态红线/基本农田/建设边界是不可违反的法律红线
4. **人工确认**：所有空间操作必须经规划师确认，Agent 不做规划决策
5. **变更留痕**：每步操作的来源文本、前后快照、确认人必须可审计

**没有参考项目同时处理这 5 个约束**。

### 6.2 逐项对比：借鉴 vs 原创

| 设计元素 | 参考项目做法 | 我们的做法 | 原创性 |
|---------|------------|-----------|--------|
| **SpatialContext** | Spatial-Agent: "spatial grounding" 概念 | 我们：从 GISDataBundle 计算 GB/T 21010 编码感知的空间摘要 | **半原创**——概念借鉴，但编码体系（DLBM→GHYTBM→VNE 三级映射）是我们独有的 |
| **SpatialAnchor** | GeoPlanAgent: "localisation" 步骤 | 我们：PARSE 输出预判锚定 + LAYOUT 验证修正的双阶段模式 | **原创**——GeoPlanAgent 是单阶段（定位即执行），我们是双阶段（预判→确认），因为我们必须人工确认 |
| **SpatialRule** | GeoAgents: spatial.intersects/nearby 工具 | 我们：ConstraintItem → SpatialRule → KG 三元组 → Shapely 操作的四层映射 | **原创**——GeoAgents 直接调工具，我们走"规则→知识图谱→合规预检→空间运算"链路，因为管制规则要先注入 KG |
| **ZoneTarget** | 通用概念（面积+偏好） | 我们：ZoneTarget 携带 DLBM 编码 + 广东省 6 类规划分区映射 + 三线约束 | **原创**——没有任何参考项目处理中国村庄规划的三区三线约束体系 |
| **5 种原子操作** | 无参考（独特设计） | create/split/merge/modify/reclassify + 面积守恒 + 变更日志 | **完全原创** |
| **DictionaryCenter** | 无参考（独特设计） | 12 个 YAML 字典 + CandidateEngine + 三置信度 | **完全原创** |
| **MIP + KG + Conflict 三合一** | 无参考（独特设计） | MILP 分配 + RDF 约束 + 冲突检测器联合 | **完全原创** |

### 6.3 原创性的核心：不是概念创新，是"约束感知"的组合创新

我们的原创性不在于发明了"SpatialAnchor"这个概念（这确实是借鉴 Spatial-Agent），而在于：

1. **编码感知的空间锚定**：SpatialAnchor 不只是"刘村小组东侧"，还携带了 DLBM→GHYTBM→VNE 的三级编码映射。当 PARSE 提取"经营性建设用地"时，SpatialAnchor 同时关联了 `land_use_code="2124"` + `vne_code="V31"` + `ghflbm="2120"`。**这来自 DictionaryCenter 的独特设计，任何参考项目都没有。**

2. **合规前置的空间规则**：SpatialRule 不只是 `no_overlap(建设区, 基本农田)`，还必须经过 KG 合规预检——规则先注入知识图谱，再由 EXECUTE_OPERATIONS 的 ReAct 子图查询 KG 判断操作是否违规。**这条"规则→KG→合规预检→空间运算"链路是我们的独创。**

3. **双阶段空间定位**：PARSE 预判候选图斑（SpatialAnchor.candidate_parcels + resolution_status），LAYOUT 的 resolve_place_name 验证修正。**这来自"Agent 是绘图员不是规划师"原则——GeoPlanAgent 的单阶段定位不适合需要人工确认的场景。**

4. **面积守恒的操作引擎**：split/merge 操作必须保证 660 地块总面积不变，变更日志记录 before/after 快照。**这是中国村庄规划的法规要求，任何参考项目都没有处理。**

### 6.4 结论：原创性矩阵

| 维度 | 原创程度 | 说明 |
|------|---------|------|
| 问题定义 | ★★★★★ | 中国村庄规划 Text→GIS 编制，全球无同类系统 |
| 编码体系 | ★★★★★ | DLBM/GHYTBM/VNE 三级正交 + DictionaryCenter，完全原创 |
| 操作引擎 | ★★★★★ | 5 原子操作 + 面积守恒 + 变更日志 + 人工确认，完全原创 |
| 空间约束 | ★★★★☆ | SpatialRule 概念借鉴 GeoAgents，但 KG 合规预检链路原创 |
| 空间锚定 | ★★★☆☆ | SpatialAnchor 概念借鉴 Spatial-Agent，但双阶段模式原创 |
| 空间上下文 | ★★★☆☆ | SpatialContext 概念借鉴 GeoWorkbench，但编码感知摘要原创 |
| MIP+KG+Conflict | ★★★★★ | 三合一组合，完全原创 |

**总体**：我们的原创性在于**"中国村庄规划编制"这个独特问题域**以及**"编码感知 + 合规前置 + 人工确认"**的独特约束组合。概念层借鉴是正常的——Spatial-Agent 也借鉴了 GIScience 的 core concepts 理论，GeoAgents 也借鉴了 GeoFaham 的多 Agent 架构。关键是我们如何将这些概念适配到**没有人处理过的约束空间**中。

### 决策：不采用交错解析，采用"丰富中间表示"

| 方案                                                              | 优点                     | 缺点                                       | 判定    |
| ----------------------------------------------------------------- | ------------------------ | ------------------------------------------ | ------- |
| **A: 交错解析**（PARSE 调用 resolve_place_name）            | 空间定位在提取时完成     | 违反"Agent 是绘图员"原则；PARSE 做空间决策 | ✗ 不选 |
| **B: 丰富中间表示**（PARSE 输出 SpatialAnchor/SpatialRule） | 保持职责分离；信息不丢失 | LAYOUT 仍需验证锚定                        | ✓ 选   |
| **C: 维持现状**（只输出自由文本）                           | 最简单                   | 已证明空间信息不足                         | ✗ 不选 |

**方案 B 的管线变化**:

```
Before:
  规划文本 + GISSummary(统计) → PARSE → OperationSequence(自由文本) → LAYOUT

After:
  规划文本 + SpatialContext(统计+空间关系) → PARSE →
    SpatialOperation(空间锚定) + SpatialConstraint(可计算规则) + SpatialPlanningIntent(空间偏好)
  → LAYOUT (验证锚定 → 执行操作)
```

**关键新增环节**:

```
GISDataBundle → compute_spatial_context() → SpatialContext → 注入 PARSE
```

这对应 GeoWorkbench 的 "Spatial Semantics" 显式阶段。

---

## 7. 与 DESIGN_GOALS 的对齐

### 7.1 不冲突的设计原则

| 原则                       | 当前设计 | 本方案                           | 是否冲突 |
| -------------------------- | -------- | -------------------------------- | -------- |
| Agent 是绘图员不是规划师   | ✓       | PARSE 不做空间决策，只提供锚定   | 否       |
| 不确定性必须由人消除       | ✓       | 候选图斑仍需人工确认             | 否       |
| 编码映射不做自动转换       | ✓       | SpatialAnchor 不做自动选择       | 否       |
| 合规检查是前置条件         | ✓       | SpatialRule 可直接映射为合规检查 | 否       |
| PARSE 架构: 半结构化 ReAct | ✓       | 不变                             | 否       |

### 7.2 需要修订的设计决策

| 决策         | 当前                        | 建议                                          | 修订理由                                           |
| ------------ | --------------------------- | --------------------------------------------- | -------------------------------------------------- |
| GIS 数据注入 | 统计信息，不含几何          | 统计信息 + 空间关系摘要（~2KB，不含原始几何） | 空间关系≠几何数据；2KB 可承受；参考 Spatial-Agent |
| PARSE 输出   | OperationSequence(自由文本) | OperationSequence(空间锚定)                   | SpatialAnchor 是"语义"不是"计算"；不违反单一职责   |

### 7.3 不需要修改的部分

- DictionaryCenter / YAML 字典：无需改动
- MIP allocator：只需读取 ZoneTarget.adjacency_rules 作为额外约束
- conflict/detector.py：SpatialRule 可直接映射为检测逻辑
- kg/builder.py：SpatialConstraint 可直接转化为 RDF 三元组
- 5 种原子操作定义：不变
- 人工确认流程：不变

---

## 8. 修改文件清单

| 文件                                        | 修改类型 | 说明                                                                                                                   |
| ------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| `docs/gis/DESIGN_GOALS.md`                | 修订     | §6 技术决策：GIS 注入从"统计"改为"统计+空间关系"                                                                      |
| `docs/gis/SCHEMA_REFERENCE.md`            | 新增     | SpatialContext, SpatialAnchor, SpatialRule 模型文档                                                                    |
| `parse_state.py`                          | 重写     | GISSummary → SpatialContext, OperationItem + SpatialAnchor, ConstraintItem + SpatialRule, PlanningIntent + ZoneTarget |
| **新增** `spatial_context.py`       | 新建     | compute_spatial_context() 从 GISDataBundle 计算紧凑空间上下文                                                          |
| **新增** `dicts/place_aliases.yaml` | 新建     | 地名词典（动态推断辅助，DLMC+POI+用户修正，非静态别名库）                                                                  |
| `parse_prompts.py`                        | 更新     | 注入 SpatialContext 替代 GISSummary                                                                                    |
| `layout_pipeline.py`                      | 更新     | _parse_intent_node 接收 SpatialOperation/SpatialConstraint                                                             |

---

## 9. 验证方案

1. **SpatialContext 大小测试**: compute_spatial_context() 对金田村 660 地块，验证输出 < 3KB
2. **空间锚定测试**: 给定 "刘村小组东侧、晒谷场北边"，验证 SpatialAnchor.candidate_parcels 非空
3. **SpatialRule 映射测试**: 验证每条 SpatialRule 可直接映射为 Shapely 操作
4. **E2E 测试**: 从规划文本到 14 层输出，验证 PARSE 输出的 SpatialConstraint 可被 KG 直接消费

---

## 10. 参考项目映射

| 本项目设计元素             | 参考项目                                 | 核心借鉴                             |
| -------------------------- | ---------------------------------------- | ------------------------------------ |
| SpatialContext             | Spatial-Agent 的 "spatial grounding"     | 语义描述 → 计算表示（不含原始几何） |
| SpatialAnchor              | GeoPlanAgent 的 "localisation"           | 文本定位 → 候选图斑（预判，不执行） |
| SpatialRule                | GeoAgents 的 spatial 工具集              | 约束 = 确定性空间操作 + 参数         |
| ZoneTarget.adjacency_rules | prompts.py 已有 adjacency 字段           | 激活已有但未携带的信息               |
| compute_spatial_context()  | GeoWorkbench 的 "Spatial Semantics" 阶段 | 显式空间语义计算                     |
| place_aliases.yaml         | GeoFaham 的 Maps Agent 地名库            | 地名词典（动态推断辅助，非静态别名映射）                 |
