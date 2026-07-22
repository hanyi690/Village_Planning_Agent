# GIS Agent 可靠性评估：从"意图"到"GIS图"的鸿沟分析

> **Status: [DIAGNOSTIC]** | **Type: Reliability Assessment** | **Updated: 2026-07-21**
> **Scope**: 3个核心鸿沟(空间锚定/操作粒度/GIS分析) + KG利用不足
> **References**: BIBLIOGRAPHY.md §A3-4, §F1-11, §G1-5
> **Related**: 01_DESIGN_GOALS.md §6, diagnostics/03_DATA_GAP_ANALYSIS.md, proposals/01_PARSE_SPATIAL_ENHANCEMENT.md
>
> 分析范围: parse_results → GIS layout pipeline → 实际GIS图输出
> 数据源: 金田村 parse 报告 + Exa 搜索人工规划流程 + 代码逐行审查

---

## 一、核心结论

**GIS Agent 当前能产出"框架级"规划图，不能产出"项目级"规划图。**

| 层级 | 可靠性 | 说明 |
|------|--------|------|
| 框架级（4区分区/空间管制/VNE分类） | 🟢 可以 | MIP+DLBM映射逻辑正确，660真实地块重分类 |
| 自然村级（项目锚定到VillageGroup） | 🟡 可行 | 需先解决空间锚定断裂 |
| 地块级（项目精确落位到具体地块） | 🔴 中期可行 | 需空间约束MIP+操作执行器 |
| 合规入库级（满足"一张图"标准） | 🔴 长期目标 | 需完整分析+拓扑+GDB输出 |

---

## 二、系统当前能力确认

**系统不是"意图模拟器"，是真实的 GIS 操作引擎：**

- ✅ 660 真实地块 + 2,150K 坐标点（EPSG:4326 → CGCS2000 精密投影）
- ✅ 7 套 DLBM 编码体系映射到规划分区
- ✅ PuLP MIP 求解器：660地块×7分区，44K 二值变量
- ✅ Shapely 几何操作：union/difference/intersection/buffer
- ✅ 面积约束强制执行：建设用地≤30.5ha、基本农田≥78.83ha、生态红线≥362.02ha
- ✅ 6 层空间图层生成：function_zone、planning_zone、facility_point、infrastructure、space_control_zone、land_use_zone

**但存在 3 个致命鸿沟 + 1 个 KG 利用不足问题。**

---

## 三、鸿沟1：空间锚定断裂（最严重）

### 现象

parse 报告中的操作引用的是**自然语言地名**（园寨、社前、田坑、长塘），但 GIS 数据中只有 `VillageGroup_1` ~ `VillageGroup_15` 的聚类锚点。

```
来源文本: "林下林芝扩种项目：位于园寨、社前林地"
  ↓ parse
参照: 园寨 None, 社前 None  ← 锚定置信度 0.4
  ↓ pipeline
allocate_zones: 不知道"园寨"在哪，只能按DLBM全局分配
```

### 数据证据（金田村 parse 报告）

| 操作 | 空间锚定 | 置信度 | 参照匹配 |
|------|---------|--------|---------|
| CREATE 林地 20000㎡ | 🟡 partial | 0.4 | 园寨=None, 社前=None |
| MODIFY 耕地 40000㎡ | 🟡 partial | 0.4 | 田坑=None, 长塘=None |
| CREATE 水田 133333㎡ | 🟡 partial | 0.4 | 塘笃=None, 炉池=None |
| CREATE 林地 10000㎡ | 🟡 partial | 0.4 | 分水=None, 清明=None |
| CREATE 绿地 500㎡ | 🟡 partial | 0.5 | 社前=None |

**5/5 操作的空间参照全部为 None。**

### 人工规划怎么做

规划师驻村调研，在 ArcGIS 中直接标注"园寨"对应的具体地块，**手工绘制规划地块**。

### 解决方案探索

#### 方案A：地名词典(Gazetteer)匹配

**数据源**：
1. **天地图地理编码API** — 支持村庄级地名查询
2. **villages-ML 项目**（GitHub: jengzang/villages-ML）— **285,000+ 广东省自然村**坐标+语义标注，与金田村（广东梅州）高度匹配
3. **OSM Nominatim** — 开源地理编码

**实现路径**：
```
parse 提取地名 → 天地图地理编码 → 获取坐标
→ 匹配最近的 VillageGroup 锚点 → 空间锚定置信度提升
```

**可行性**：✅ 技术成熟，1-2周可实现

#### 方案B：NLP地名识别+LLM地理推理

**技术参考**：
- RB-TRNet：规律引导+边界感知的中文地名识别
- GTBERT-Pointer：地名词典增强的 BERT 地址解析
- villages-ML 的语义标注体系（9类：山地/水系/聚落/方位/姓氏/象征/农业/植被/基建）

**推荐**：**方案A为主，方案B为辅**。先用天地图API+VillageGroup匹配解决80%的地名锚定问题。

---

## 四、鸿沟2：操作粒度不匹配

### 现象

parse 输出的5条操作是**项目级**（"创建林地20000㎡"），但 GIS 生成器需要**地块级**操作（"将parcel_123从耕地改为林地"）。当前 ZoneGenerator 按 DLBM 全局重分类，**完全忽略操作序列中的空间锚定信息**。

```
parse输出: [CREATE] 林地 20000㎡ @ 园寨
  ↓ 实际执行
ZoneGenerator: 找所有DLBM=0301(林地)的地块 → 合并 → 按area_ratio=81%保留
  → 完全没有"在园寨创建"这个空间约束
```

### 解决方案探索

#### 方案A：空间约束MIP

在 MIPZoneAllocator 中增加空间约束变量：

```python
# 当前模型
min Σ_z (面积偏差) + Σ_i Σ_z x[i][z] * 偏好成本
s.t. Σ_z x[i][z] = 1, 面积约束, DLBM约束

# 扩展后
新增: Σ_{i∈园寨VillageGroup} area[i] * x[i][林地] >= 20000
新增: Σ_{i∈园寨VillageGroup} area[i] * x[i][林地] <= 25000
```

**参考**：GenPlanner (PyPI: genplanner v1.0.2) — 领土地域分区引擎，支持 ratio-based zoning + adjacency constraints + spatial anchor points + MILP allocation

**可行性**：✅ PuLP 原生支持，660地块增加5-10条约束不影响求解

#### 方案B：操作序列执行器

在 generate_layout 之后增加 operation_executor 模块：

```python
for op in operation_sequence:
    if op.action == "CREATE":
        target_parcels = select_parcels_in_area(
            village_group=op.anchor_village_group,
            target_area=op.area,
            preferred_dlbm=op.land_use_code,
        )
        for parcel in target_parcels:
            parcel.properties["DLBM"] = op.land_use_code
```

**推荐**：**方案A为主，方案B为辅**。先用空间约束MIP解决宏观分配，再用操作执行器处理细粒度操作。

---

## 五、鸿沟3：缺少关键GIS分析能力

| 人工规划必需操作 | 系统当前状态 | 改进难度 |
|------------------|-------------|---------|
| 坡度/坡向分析 | ❌ 无 | 1-2周（rasterio+numpy） |
| 服务半径/等时圈分析 | ⚠️ accessibility.py 未集成 | 1周（简化版）/ 3-4周（路网版） |
| 道路网络分析 | ❌ 无 | 3-4周（需OSM路网数据） |
| 拓扑检查 | ⚠️ merge_parcels 非严格拓扑 | 1-2天（geopandas） |
| 地类编码校验 | ⚠️ 4/5 操作编码无效 | 1周（修复code_sets映射） |
| 建设边界精确划定 | ⚠️ 依赖输入数据 | 已有SpaceControlZoneGenerator |

**设施选址学术参考**：
- 反向最大覆盖模型：以村庄为服务提供方、设施为需求方
- 双目标位置分配：最大化覆盖人口 + 最小化总出行成本

### 5.1 缺漏根因分析：为什么技术指南没有提及DEM等专业数据

**核心结论：不是"没有提及"，而是"提及方式不同"。**

广东省技术指南 §工作流程确实提到了基础数据要求，但以**一句话**概括：

> "应采用第三次全国国土调查数据成果或最新土地变更调查数据成果、数字线划地图和
> 比例尺不低于1:2000的地形图或国土数字正射影像图作为工作底图，并用农村地籍
> 调查数据、地理国情普查及监测数据作补充"

| 指南原文                  | 隐含的数据                       | 系统现状  |
| ------------------------- | -------------------------------- | --------- |
| "三调数据成果"            | 地类图斑DLTB + 村级调查区CJDCQ  | ✅ 已有   |
| "数字线划地图(DLG)"       | 等高线/高程点/水系矢量           | ❌ 缺失   |
| "1:2000地形图"            | DEM/等高线                       | ❌ 缺失   |
| "国土数字正射影像图(DOM)" | 卫星/航拍影像                    | ❌ 缺失   |
| "农村地籍调查数据"        | 宅基地确权数据                   | ❌ 缺失   |
| "地理国情普查及监测数据"  | 地表覆盖/地理国情                | ❌ 缺失   |

**三层脱节**：

1. **指南提了但没展开**：广东省技术指南只用一句话列出数据清单，没有展开精度/格式/获取方式
2. **展开内容在测绘标准中**：DEM精度要求在CH/T 9008.2-2010，不在规划指南中
3. **展开内容在专业教材中**：DEM获取+分析在李巍手册第2章§2.1.3和§2.5，不在技术规范中

```
广东省技术指南: "1:2000地形图"  ← 一句话
    ↓ 展开
CH/T 9008.2-2010: 1:2000 DEM格网1m×1m, 高程中误差≤0.30m(山地)  ← 技术规格
    ↓ 操作
李巍手册第2章: GDEMV3 30M下载→ArcMap按掩膜提取→坡度/坡向分析  ← 实操步骤
```

**数据分类：空间数据 vs 文本数据**

只有**需要空间定位**的数据才需要严谨的后端数据模型。文本描述型数据通过规划文本路径
（parse → OperationSequence + ConstraintSet）进入系统，不需要建数据模型。

需要空间数据模型的数据（P0）：
- 🔴 DEM → 坡度/坡向/建设适宜性/洪涝风险
- 🔴 地名地址 → 空间锚定（解决鸿沟1的锚定断裂）
- 🔴 遥感影像(DOM) → 现状判读/房屋轮廓提取

只需文本记录的数据（已通过规划文本路径覆盖）：
- 社会经济概况（人口/产业/收入）→ parse
- 历史文化资源 → parse
- 居民点建设需求 → OperationSequence
- 公共服务设施需求 → OperationSequence
- 村庄安全防灾 → ConstraintSet

**如果最初参考的是专业教材（李巍手册第2章）而非仅技术规范，DEM等数据就不会被遗漏。**

---

## 六、KG 模块利用不足（关键发现）

### 6.1 operation_sequence 完全未进入 KG

```
parse_agent → operation_sequence: [CREATE林地@园寨, MODIFY耕地@田坑, ...]
  ↓ 存入 state.operation_sequence
  ↓
build_kg_node → 只读 state.intent（zone/facility/axis/constraint）
  → 完全忽略 state.operation_sequence
  ↓
allocate_and_generate → 也只读 state.intent + state.kg_constraints
  → operation_sequence 被彻底跳过
```

**影响**：
- KG 中没有 `Project→Parcel` 关联（无法查询"林芝种植基地对应哪些地块"）
- KG 中没有操作意图的三元组
- 下游 MIP allocator 无法利用操作序列的空间约束

### 6.2 KG 查询能力未被下游充分利用

KG 有 18 个 SPARQL 查询模板，**仅使用1个**：

| 查询模板 | 被谁调用 | 应该被谁使用 |
|---------|---------|-------------|
| `get_constraints` | ✅ build_kg_node → kg_constraints | — |
| `get_adjacent_parcels` | ❌ 未调用 | FacilityPlacer（设施选址应考虑邻接） |
| `get_parcels_by_zone_type` | ❌ 未调用 | ZoneGenerator（应按分区查地块） |
| `get_zone_restrictions` | ❌ 未调用 | SpaceControlZoneGenerator |
| `get_facility_serve_areas` | ❌ 未调用 | 设施选址优化 |
| `get_road_network` | ❌ 未调用 | 道路连通性分析 |
| `get_designated_zones` | ❌ 未调用 | LayoutValidator |
| `check_protected_parcels` | ❌ 未调用 | 约束检测 |

**核心问题**：KG 被构建了，但只提取了 `constraints` 传给下游，**丰富的空间关系（邻接、分区、设施服务范围、路网）全部浪费了**。

### 6.3 改进方案：让 KG 成为 parse→layout 的桥梁

1. **新增 KG 实体**：`Operation`（操作意图）、`SpatialAnchor`（空间锚点）
   ```turtle
   pln:op_1 a pln:Operation ;
       pln:action "CREATE" ;
       pln:land_use "林地" ;
       pln:area_sqm 20000 ;
       pln:anchored_at pln:VillageGroup_1 ;
       pln:source_text "林下林芝扩种项目" .
   ```

2. **下游消费 KG 查询**：
   - `MIPZoneAllocator`：查询 `get_operations_by_zone` 获取空间约束
   - `FacilityPlacer`：查询 `get_adjacent_parcels` 获取邻接关系
   - `LayoutValidator`：查询 `check_protected_parcels` + `get_designated_zones`
   - `SpaceControlZoneGenerator`：查询 `get_zone_restrictions` 获取管制规则

3. **空间锚定通过 KG 解析**：
   - `resolve_place_name` 工具查询 KG 获取候选地块
   - 将 "园寨" 映射到 KG 中 `pln:VillageGroup_1` 的坐标和范围

---

## 七、与人工规划的本质差异

**人工规划核心循环**：手工绘制 → 自动校验 → 手工调整

**当前系统循环**：LLM解析 → MIP分配 → 自动生成

两者在**分区层面等价**，但在项目级精确落位层面，系统缺少"手工绘制"这个关键环节。

**可行替代方案**：用**空间约束MIP**替代"手工绘制"——不是让规划师画线，而是让 LLM 解析的意图转化为 MIP 约束，由求解器自动找到最优地块组合。**数学上等价，但前提是空间锚定必须先解决。**

---

## 八、可行性与优先级矩阵

| 鸿沟 | 解决方案 | 技术成熟度 | 实现周期 | 依赖 |
|------|----------|-----------|---------|------|
| 空间锚定 | 天地图地理编码 + VillageGroup匹配 | ✅ 成熟 | 1-2周 | 天地图API key |
| KG桥梁 | operation_sequence注入KG + 下游查询 | ✅ 成熟 | 1-2周 | 无 |
| 操作粒度 | 空间约束MIP + 操作执行器 | ✅ 成熟 | 2-3周 | 依赖空间锚定 |
| GIS分析 | DEM坡度/设施选址/拓扑检查 | ✅ 成熟 | 3-4周 | DEM数据源 |

---

## 九、关键参考资源

### 学术/技术
- **GenPlanner** (PyPI genplanner v1.0.2) — MILP+spatial anchor 领土分区引擎
- **villages-ML** (GitHub jengzang/villages-ML) — 广东285K自然村坐标+语义标注
- **RB-TRNet** — 规律引导+边界感知中文地名识别
- **GTBERT-Pointer** — 地名词典增强BERT地址解析

### 人工规划工具
- **bxgis** (GitHub vanadis91/bxgis) — 基于ArcPy的详规入库数据库构建
- **ArcGIS村庄规划辅助工具V1.0** — 半自动化流程（导入三调→字段处理→**手工做规划地块**→自动出图）

### 省级规程
- 湖北省村庄规划编制技术规程（1:2000地形图、CGCS2000坐标系、1+1+1成果体系）
- 贵州省村庄规划编制技术指南（基础内容+细化增补内容分步编制）
- DB35/T 2061-2022 福建省村庄规划编制规程
