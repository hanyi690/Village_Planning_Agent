# PARSE + KG：专业规划范式对齐差距分析

> **Status: [DIAGNOSTIC]** | **Type: Gap Analysis** | **Version: v1** | **Updated: 2026-07-22**
> **Scope**: PARSE Agent Schema + KG Builder — 对照专业教材/规范发现的系统性差距
> **References**: BIBLIOGRAPHY.md §A2-3, §A5, §B5-7, §B10
> **Source Documents**:
> - 《村庄规划用地分类指南》(住建部, 2014) — 3大类10中类15小类 V/N/E 分类体系
> - 《广东省村庄规划编制基本技术指南（试行）》(广东省自然资源厅, 2019) — 附表1/2/附录3/附录5
> - 《实用性村庄规划编制手册》——李巍等 (369页) — §2.6 GIS实验操作, §3-4 规划定位与空间布局
> - 《乡村规划原理》——李京生 — 空间结构理论, 规划体系演进

---

## 总览

| 差距编号 | 类别 | 严重度 | 简述 |
|----------|------|--------|------|
| G1 | PARSE | **Critical** | 用地分类体系缺失 — 无 V/N/E 3大类10中类15小类层级 |
| G2 | PARSE | **Critical** | "一图一表一规则"输出结构缺失 |
| G3 | PARSE | **High** | 规划目标表(附表1)未建模 — 7指标×3列结构缺失 |
| G4 | PARSE | **High** | 土地利用结构调整表(附表2)未建模 — 19子类×4列结构缺失 |
| G5 | PARSE | **Critical** | 管制规则(附录3)未建模 — 当前仅5个通用约束类型 |
| G6 | PARSE | **High** | 三区三线空间结构缺失 |
| G7 | PARSE | **Medium** | Section 分类不匹配 — 缺5种专业section类型 |
| G8 | PARSE | **Medium** | 双评价(GIS分析基础)缺失 |
| K1 | KG | **Critical** | V/N/E 精细分类三元组缺失 — 仅硬编码4个粗分区 |
| K2 | KG | **Critical** | 管制规则 RDF 实体缺失 — 仅3条规则 |
| K3 | KG | **High** | 规划指标表三元组缺失 — 指标无基期/目标/变化量结构 |
| K4 | KG | **High** | Ontology 缺失核心概念 — 缺6实体+4关系 |
| K5 | KG | **Medium** | `build_from_intent` 仍用 Dict 路径 |
| K6 | KG | **Medium** | 硬编码模式未替换为 YAML 规则 |

---

## PARSE Agent 差距详情

### G1. 用地分类体系缺失 (Critical)

**对照规范**：《村庄规划用地分类指南》表2.2.2

标准定义 3大类(V/N/E)、10中类、15小类的完整层级：

```
V 村庄建设用地
  V1 村民住宅用地
    V11 住宅用地
    V12 混合式住宅用地
  V2 村庄公共服务用地
    V21 村庄公共服务设施用地
    V22 村庄公共场地
  V3 村庄产业用地
    V31 村庄商业服务业设施用地
    V32 村庄生产仓储用地
  V4 村庄基础设施用地
    V41 村庄道路用地
    V42 村庄交通设施用地
    V43 村庄公用设施用地
  V9 村庄其他建设用地
N 非村庄建设用地
  N1 对外交通设施用地
  N2 国有建设用地
E 非建设用地
  E1 水域
    E11 自然水域
    E12 水库
    E13 坑塘沟渠
  E2 农林用地
    E21 设施农用地
    E22 农用道路
    E23 其他农林用地
  E9 其他非建设用地
```

**当前实现**：`parse/state.py` `ZoneTarget`

```python
class ZoneTarget(BaseModel):
    land_use: str = ""          # 自由字符串, 无枚举约束
    area_ratio: float = 0.0
    dlbm: Optional[str] = None  # 仅有附录5编码引用
    density: Literal["high", "medium", "low"] = "medium"
```

**差距**：
- 无 V/N/E 大类概念
- 无 10 中类 / 15 小类层级
- `land_use` 是自由字符串 — 可以是任意值，无法保证与标准对齐
- 缺少 `parent_category`、`vne_code`、`sub_class` 等层级字段

**已有可用数据**：
- `dicts/encodings/vne.yaml` — VNE 编码字典
- `dicts/rules/land_use_structure.yaml` — 附表2 的 19 个用地分类 (含 code/name/parent/ghytbm)
- `spatial_types.py` `LandUseZone` — 土地用途分区 dataclass (含 tdyfqdm 编码)

---

### G2. "一图一表一规则"输出结构缺失 (Critical)

**对照规范**：《广东省技术指南》第四章"规划成果"

> 村庄规划基本成果应包括"一图一表一规则"，分别为村庄规划总图、近期建设项目表和村庄规划管制规则。

要求：
- 村庄规划总图：5条控制线 + 用地布局 + 附表1 + 附表2
- 近期建设项目表(附录2)：11列 (项目类型/名称/空间位置/用地面积/建筑面积/资金规模/筹措方式/责任主体/协作部门/建设方式/备注)
- 村庄规划管制规则(附录3)：6大类

**当前实现**：`SpatialPlanningIntent` 仅输出

```python
class SpatialPlanningIntent(BaseModel):
    village_name: str = ""
    planning_period: str = ""
    zone_targets: List[ZoneTarget]       # → 对应"图"的部分内容
    facilities: List[FacilityTarget]     # → 对应"近期项目"的一部分
    development_axes: List[AxisTarget]   # → 自定义概念, 不在标准中
    total_area_ha: Optional[float]
    construction_area_ha: Optional[float]
    farmland_area_ha: Optional[float]
    ecological_area_ha: Optional[float]
    population: Optional[int]
```

**差距**：
- 缺少 `PlanningMap` (规划总图) 结构化输出
- 缺少 `RecentProjectTable` (近期建设项目表) — 11 列结构
- 缺少 `ControlRuleSet` (管制规则) — 6 大类
- `AxisTarget` 是自定义概念，标准中用 "村庄建设边界"+"产业空间布局" 替代

---

### G3. 规划目标表(附表1)未建模 (High)

**对照规范**：《广东省技术指南》附表1

7 个指标 × 3 列时间维度：

| 指标 | 属性 | 
|------|------|
| 耕地保有量 | 约束性 |
| 基本农田保护面积 | 约束性 |
| 村庄建设用地规模 | 约束性 |
| 公共服务设施用地规模 | 预期性 |
| 基础设施用地规模 | 预期性 |
| 户均宅基地 | 预期性 |
| 人均村庄建设用地 | 预期性 |

每项有：基期年值 / 目标年值 / 变化量

**当前实现**：散落在 `SpatialPlanningIntent` 的裸字段

```python
construction_area_ha: Optional[float]  # 仅一个时间点
farmland_area_ha: Optional[float]      # 仅有现状值
ecological_area_ha: Optional[float]    # 无指标属性标记
population: Optional[int]              # 无户均/人均计算
```

**差距**：
- 未区分"约束性"vs"预期性"
- 缺少基期年/目标年/变化量的时间维度
- 缺 4 个指标：公共服务设施/基础设施/户均宅基地/人均村庄建设用地
- 指标数据无结构化来源标记 (上位传导 vs 本级规划)

**已有可用数据**：`dicts/rules/planning_targets.yaml` 已完整定义 7 个指标(code/name/unit/attribute/field)

---

### G4. 土地利用结构调整表(附表2)未建模 (High)

**对照规范**：《广东省技术指南》附表2

19 个子类别，每类有：基期年面积/比重 + 目标年面积/比重 + 规划期内增减

三大类结构：农业用地(6) + 建设用地(12) + 生态用地(3)

**当前实现**：无。`SpatialPlanningIntent` 仅有 3 个总面积字段

**差距**：
- 完全缺失 19 子类 × 4 列(面积/比重 × 现状/规划) 的结构
- 无法生成土地平衡表
- 无法追踪各地类的增减变化

**已有可用数据**：`dicts/rules/land_use_structure.yaml` 已完整定义 19 个分类(code/name/parent/ghytbm)

---

### G5. 管制规则(附录3)未建模 (Critical)

**对照规范**：《广东省技术指南》附录3

6 大类管制规则，每类含具体约束条款模板：

1. **生态保护**：保护红线范围+禁止建设活动+保护生态用地名录
2. **耕地和永久基本农田保护**：基本农田面积+集中分布区+占用审批程序+设施农用地管理规定
3. **历史文化传承与保护**：文物保护单位名录+历史文化保护线范围+修缮审批要求
4. **建设空间管制**：
   - 产业发展空间：经营性建设用地密度/高度/容积率/绿地率
   - 农村住房：宅基地面积上限/建筑层数/高度/风貌要求
   - 基础设施和公共服务设施：退线距离/设施用地保护
5. **村庄安全和防灾减灾**：避开自然灾害区/消防通道要求/应急庇护场所
6. **其他管制规则**：各村实际情况制定

**当前实现**：`SpatialConstraint`

```python
class SpatialConstraint(BaseModel):
    type: Literal[
        "area_constraint",
        "spatial_constraint",
        "building_constraint",
        "use_constraint",
        "boundary_constraint",
    ] = "spatial_constraint"
```

**差距**：
- 5 个通用类型 (area/spatial/building/use/boundary) 不匹配 6 大管制类别
- 缺少管管制规则的标准模板结构 (分类→条款列表→空间关联→量化限值)
- `building_constraint` 仅含 max_area_sqm/max_height_m/max_floors/setback_m，缺少容积率/绿地率/建筑密度/风貌要求

---

### G6. 三区三线空间结构缺失 (High)

**对照规范**：《中共中央 国务院关于建立国土空间规划体系并监督实施的若干意见》

> "三区"：生态空间、农业空间、城镇空间
> "三线"：生态保护红线、永久基本农田、城镇开发边界

**当前实现**：无。`SpatialPlanningIntent` 无三区三线概念

**差距**：
- 缺 `ThreeZones` (生态/农业/建设空间面积)
- 缺 `ThreeLines` (三条控制线面积+空间范围)
- 现有 `SpatialContext` 的 `zone_adjacency` 仅有 7 个自定义 zone，无三区映射

**已有可用数据**：
- `dicts/rules/three_line_types.yaml` — 三线图层定义 (含颜色/线型/GDB key)
- `dicts/rules/planning_zone_rules.yaml` — 规划分区到三区的映射 (`planning_zone_to_primary_zone`)

---

### G7. Section 分类不匹配 (Medium)

**对照规范**：《广东省技术指南》第三章"规划内容" — 7大规划内容：

1. 村庄发展目标
2. 生态保护修复
3. 耕地和永久基本农田保护
4. 历史文化传承与保护
5. 产业和建设空间安排
6. 村庄安全和防灾减灾
7. 近期建设行动

**当前实现**：`SectionInfo.section_type` 13 种

```python
Literal["preamble", "target", "regulation", "project_table",
        "land_use_table", "indicator_table", "heritage_table",
        "facility_table", "ecological_table", "spatial_layout",
        "protection", "infrastructure", "governance"]
```

**差距**：
- 缺少 `ecological_restoration` (生态保护修复)
- 缺少 `farmland_protection` (耕地和永久基本农田保护)
- 缺少 `disaster_prevention` (村庄安全和防灾减灾)
- 缺少 `recent_projects` (近期建设行动)
- 缺少 `development_targets` (村庄发展目标 — 与 `target` 区分，含指标体系)
- `ecological_table` 存在但不精确 → 应为 `ecological_restoration`

---

### G8. 双评价(GIS分析基础)缺失 (Medium)

**对照规范**：《实用性村庄规划编制手册》§2.5 调查内容分析, §4.8 GIS实验操作

"双评价"是划定三区三线的科学基础：
- **生态保护重要性评价**：生态系统服务功能重要性 + 生态敏感性
- **农业生产适宜性评价**：土地资源 + 水资源 + 气候 + 环境 + 灾害
- **城镇建设适宜性评价**：高程 + 坡度 + 坡向 + 地质灾害 + 交通可达性 + 基本农田

手册 §2.6 详细描述了 GIS 实验操作流程：
- 实验一：数据库建立与出图设置
- 实验三：地形分析 (高程分析/坡度分析/坡向分析/起伏度分析)
- §4.8：双评价成果空间落位 → 三区三线衔接

**当前实现**：无。`SpatialContext` 无评价结果字段

**已有可用数据**：
- `spatial_types.py` `ContourLine`, `ElevationPoint` — 地形要素 dataclass (Group E, 标记为"🔴 未实现")
- `canonical.py` `GISDataBundle.dem: Optional[Any]` — DEM 字段已预留但未填充
- `analysis/terrain.py` — 不存在 (需新建)

---

## KG Builder 差距详情

### K1. V/N/E 精细分类三元组缺失 (Critical)

**当前实现**：`builder.py` `ZONE_TYPE_PATTERNS` 仅 4 个粗分区

```python
ZONE_TYPE_PATTERNS = {
    "农田保护区": {"color": "#FFE4B5", "restrictions": [...]},
    "村庄建设区": {"color": "#FF6347", "restrictions": [...]},
    "生态保护区": {"color": "#2E8B57", "restrictions": [...]},
    "一般农业区": {"color": "#98FB98", "restrictions": [...]},
}
```

**差距**：
- 4 个粗分区 vs 标准 15 小类
- 无 V/N/E 大类层级关系
- `restrictions` 是自由文本而非结构化管制规则
- 未使用 `land_use_structure.yaml` 中的 19 分类定义

**已有可用数据**：`dicts/rules/land_use_structure.yaml` — 19 子类(code/name/parent/ghytbm)

---

### K2. 管制规则 RDF 实体缺失 (Critical)

**当前实现**：`_add_regulations()` 仅创建 3 条规则

```python
REGULATION_TYPES = {
    "永久基本农田保护": {"protects": "农田保护区", "field": "farmland_area_ha"},
    "生态保护红线": {"protects": "生态保护区", "field": "ecological_redline_ha"},
    "村庄建设边界": {"protects": "村庄建设区", "field": "construction_area_ha"},
}
```

**差距**：
- 仅 3 条规则 vs 标准 6 大类管制规则 (缺：历史文化/建设空间管制/安全防灾/其他)
- 规则仅含 `protects` + `field`，缺少管制条款文本、量化限值、审批程序等
- 无 `controls_use` 关系连接管制规则→地块

---

### K3. 规划指标表三元组缺失 (High)

**当前实现**：`_add_indicators()` 直接 dump 所有 report metric key-values

```python
for key, val in metrics.items():
    if val is None: continue
    indicator = PLN[f"indicator_{dk}_{key}"]
    self.g.add((indicator, PLN.name, Literal(key)))
    self.g.add((indicator, PLN.value, Literal(float(val))))
```

**差距**：
- 无结构化字段 (code I01-I07, attribute 约束性/预期性, unit 公顷/平方米)
- 无时间维度 (基期年 vs 目标年 vs 变化量)
- 来源仅记录 dimension key 而非 "上位规划传导" vs "本级规划确定"

**已有可用数据**：`dicts/rules/planning_targets.yaml` — 7 指标完整定义

---

### K4. Ontology 缺失核心概念 (High)

**当前实现**：`ontology.py` 16 实体 + 11 关系

**缺失实体** (对照专业教材)：

| 缺失实体 | 来源 | 说明 |
|----------|------|------|
| `ControlRule` | 广东省技术指南 附录3 | 6 大类管制规则 |
| `LandUseCategory` | 村庄规划用地分类指南 表2.2.2 | V/N/E 15 小类 |
| `PlanningIndicator` | 广东省技术指南 附表1 | 7 指标×3 时间维度 |
| `ThreeZone` | 三区三线政策 | 生态/农业/建设空间 |
| `ThreeLine` | 三区三线政策 | 三条控制线 |
| `UpperPlan` | 广东省技术指南 三(一) | 上位规划传导 |

**缺失关系**：

| 缺失关系 | 说明 | 示例 |
|----------|------|------|
| `delineates` | 控制线划定 | `ThreeLine → delineates → Parcel` |
| `controls_use` | 用途管制 | `ControlRule → controls_use → LandUseCategory` |
| `conducted_from` | 上位传导 | `PlanningIndicator → conducted_from → UpperPlan` |
| `evaluated_as` | 双评价结果 | `Parcel → evaluated_as → SuitabilityClass` |

---

### K5. `build_from_intent` 仍用 Dict 路径 (Medium)

**当前实现**：`build_from_intent(intent: Dict[str, Any], ...)`

```python
def build_from_intent(self, intent: Dict[str, Any], ...):
    zones = intent.get("zones", [])
    for z in zones:
        zone_id = z.get("zone_id", z.get("land_use", "unknown"))
```

**差距**：typed `SpatialPlanningIntent` 已在 `parse/state.py` 中定义，但 `build_from_intent` 仍接收 `Dict[str, Any]` 并用 `.get()` 访问

---

### K6. 硬编码模式未替换为 YAML 规则 (Medium)

**当前**：`CONSTRAINT_PATTERNS` (7 条) + `ZONE_TYPE_PATTERNS` (4 条) + `SEMANTIC_CONSTRAINT_MAP` (5 条) 全部硬编码

**已有 YAML**：
- `planning_targets.yaml` — 7 指标
- `planning_zone_rules.yaml` — 16 决策规则 + planning_zone_to_primary_zone 映射
- `land_use_structure.yaml` — 19 用地分类
- `three_line_types.yaml` — 三线定义

**差距**：从未从 YAML 加载，更新规则需改代码

---

## 修复优先级建议

### Phase A: 数据结构对齐 (先修 Schema，不改流程)

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P0 | G1 VNE分类 | `parse/state.py` | 新增 VNE 枚举 + ZoneTarget 增强 |
| P0 | G5 管制规则 | `parse/state.py` | 新增 ControlRule 模型 |
| P0 | G3 规划指标表 | `parse/state.py` | 引用 planning_targets.yaml |
| P1 | G4 用地结构表 | `parse/state.py` | 引用 land_use_structure.yaml |
| P1 | G6 三区三线 | `parse/state.py` | 新增 ThreeZonesThreeLines |
| P1 | G7 Section分类 | `parse/state.py` | 扩展 Literal 类型 |
| P2 | G2 输出结构 | `parse/state.py` | 新增 PlanningOutput 包装 |
| P2 | G8 双评价 | `contracts.py` | 新增 DualEvaluation 可选字段 |

### Phase B: KG 对齐

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P0 | K1 VNE分类三元组 | `kg/builder.py` | YAML加载替换 ZONE_TYPE_PATTERNS |
| P0 | K4 Ontology扩展 | `kg/ontology.py` | 新增 6 实体 + 4 关系 |
| P1 | K2 管制规则实体 | `kg/builder.py` | _add_regulations → 6类 |
| P1 | K3 指标实体 | `kg/builder.py` | _add_indicators 结构化 |
| P2 | K5 typed输入 | `kg/builder.py` | build_from_intent Dict→Typed |
| P2 | K6 YAML加载 | `kg/builder.py` | 替换所有硬编码模式 |

### Phase C: 下游对齐

| 优先级 | 差距 | 文件 | 工作量 |
|--------|------|------|--------|
| P1 | Dict桥接清除 | `generate.py`, `allocate.py` | 删除 isinstance(dict) 分支 |
| P1 | 管线对齐 | `layout_pipeline.py` | 删除 intent_json |
| P2 | Reporter对齐 | `parse_reporter.py` | hasattr → typed |

---

## 参考来源

- 《村庄规划用地分类指南》(住建部, 2014) — `data/RAG_doc/_doc_md/04_技术规范/01_国家层面/01 《村庄规划用地分类指南》_minerU_parsed.md`
- 《广东省村庄规划编制基本技术指南（试行）》(2019) — `data/RAG_doc/_doc_md/04_技术规范/02_地方层面/01_广东省/01 《广东省村庄规划编制基本技术指南（试行）》_minerU_parsed.md`
- 《实用性村庄规划编制手册》李巍等 — `data/RAG_doc/_doc_md/01_专业教材/05 《实用性村庄规划编制手册》——李巍等_minerU_parsed.md`
- 《乡村规划原理》李京生 — `data/RAG_doc/_doc_md/01_专业教材/02 《乡村规划原理 》——李京生_minerU_parsed.md`
