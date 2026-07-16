# Generation 层改造计划

> 版本: 3.0 | 日期: 2026-07-16 | 对齐: OUTPUT_ARCHITECTURE.md v3.0 + DictionaryCenter YAML + 统一操作序列

## 1. 问题诊断

### 1.1 核心问题：gen/plan 双路径产出完全一致

**现象**：gen（人工规划文本→LLM）和 plan（L3报告→LLM）的 intent 不同（面积比例、DLBM编码、facilities/axes/constraints 都不同），但最终生成的 planning_zone GeoJSON 哈希完全相同。

**根因链**：

```
LLM intent 输出功能分区名（"农业用地"）
    ↓
MIP allocator.solve(targets={"农业用地": 1936ha, ...})
    ↓
planning_zones = list(targets.keys()) = ["农业用地", "生态绿地", ...]
    ↓
_get_preference_cost(dlbm, "农业用地")
    → native_zone = DLBM_TO_PLANNING_ZONE[dlbm] = "农田保护区"
    → "农田保护区" == "农业用地"? NO → 返回 DEFAULT_PREFERENCE_COST
    ↓
所有 preference cost = 相同默认值 → 不同 targets 只影响面积偏差项
    ↓
change_penalty 锁定大部分地块 → 结果趋同
```

**零重叠统计**：
- 功能分区 keys: {农业用地, 生态绿地, 居住用地, 水域, 产业用地, 公共服务用地, 交通用地}
- 规划分区 keys: {农田保护区, 一般农业区, 生态保护区, 生态控制区, 村庄建设区, 林业发展区}
- **重叠: 0 个**

### 1.2 结构问题：5 层 vs 6 层，planning_zone 多余

OUTPUT_ARCHITECTURE.md v3.0 定义 5+1 个内部生成层，当前实现了 6 层：

| 架构层 | 当前层 | 差异 |
|--------|--------|------|
| ① ParcelReclass (20字段) | function_zone (仅 zone_type/color) | **缺 QMDLBM/GHFLBM/GHYTBM/GHYTMC** |
| ② SpaceControl | space_control_zone | ✅ |
| ③ UseZone (V/N/E) | land_use_zone | ✅ |
| ④ FacilityPlan | facility_point | ✅ |
| — | **planning_zone (6类)** | **❌ 架构未定义，应删除** |
| ⑤ RoadPlan | ❌ 缺失 | 待实现 |
| ⑥ OperationEngine | ❌ 缺失 | 待实现（统一操作执行引擎） |
| — | infrastructure (AxisBuilder) | 可视化叠加，不独立成层 |

### 1.3 数据流断裂

**架构要求数据流（统一操作序列）**：
```
规划文本 → PARSE → OperationSequence + ConstraintSet
    ↓
┌─ ConstraintSet → KG（约束三元组）→ 合规检查规则 ─┐
│                                                   │
└─ OperationSequence → EXECUTE_OPERATIONS（逐条执行）│
     ├── 空间定位 → 候选图斑                       │
     ├── 用途查表 → QMDLBM/GHYTBM                  │
     ├── 合规预检 → KG约束 + 冲突检测              │
     ├── 人工确认 → 确认卡片 / 批量确认            │
     └── 执行 + 变更日志                           │
           ├──→ 06_planned_landuse (20字段)
           ├──→ 10_space_control_zone
           ├──→ 11_land_use_zone
           ├──→ 13_planned_road
           └──→ changelog.jsonl
```

**当前数据流**：
```
current/landuse (DLBM) → ZoneGenerator → function_zone (zone_type/color)
                                              ↓ (不传入下游)
current/landuse (DLBM) → MIP allocator → allocated_geojson (assigned_zone)
                                              ↓ (下游不用 20 字段)
allocated_geojson → _make_planning_zone_layer → planning_zone (6类)
allocated_geojson → LandUseZoneGenerator → land_use_zone (V/N/E)
allocated_geojson → SpaceControlZoneGenerator → space_control_zone
intent → FacilityPlacer → facility_point
intent → AxisBuilder → infrastructure
```

**断裂点**：
1. 当前无 OperationSequence 解析，规划文本直接走 MIP → Generate，跳过了统一操作序列
2. ParcelReclass 的 20 字段输出缺失，下游层无法获得 QMDLBM/GHYTBM
3. planning_zone 独立生成，不在操作序列中
4. MIP allocator 作为独立管道步骤，而非按需调用的辅助工具

---

## 2. 改造目标

**一句话**：所有规划文本统一解析为 OperationSequence + ConstraintSet，通过 EXECUTE_OPERATIONS 逐条执行，MIP 降级为辅助 tool，对齐 OUTPUT_ARCHITECTURE.md v3.0 的统一路径。

**量化目标**：
- 统一生产路径：PARSE → {OperationSequence + ConstraintSet} → KG → CONFLICT → EXECUTE_OPERATIONS → VALIDATE → EXPORT → RENDER
- 5 种原子操作（create/split/merge/modify/reclassify）作为统一指令集，"整村生成"= 批量 reclassify，"增量编辑"= 逐条操作
- 06_planned_landuse 包含完整 20 必选字段（QMDLBM/GHFLBM/GHYTBM/GHYTMC）
- MIP allocator 降级为辅助 tool `optimize_allocation`，由执行引擎按需调用，非独立管道步骤
- 删除 planning_zone 独立层，6 类分区信息保留在 ParcelReclass 的 assigned_zone 字段

---

## 3. Phase 2：架构对齐

### 3.1 映射修复 ✅ 已完成

- `map_zone_type_to_planning_zone`：✅ `planning_zone_mapper.py` 已实现
- `remap_assigned_zones`：✅ 已实现（7类zone_type → 6类规划分区）
- MIP solve() 集成：⚠️ 映射函数存在但未在 solve() 开头调用，pipeline.py 中 targets 未映射

### 3.2 ParcelReclass 升级 ❌ 未开始

**新文件**: `backend/app/modules/gis/generation/parcel_reclass_generator.py`

**核心变更**：ParcelReclass 本质是**批量 reclassify 操作**的执行器——整村 660 地块重分类 = 660 个 reclassify 操作的批量执行，每地块输出 20 必选字段（对齐 QMDLTB 规范表4）。

```python
class ParcelReclassGenerator:
    """① ParcelReclass — 地块重分类（OUTPUT_ARCHITECTURE.md v3.0 Layer ①）

    本质: 批量 reclassify 操作的执行器
    - 整村生成 = 660 个 reclassify 操作批量执行
    - 单项目落地 = 1-5 个 reclassify 操作逐条执行
    两者共享同一套编码映射和合规检查逻辑。

    输入: current/landuse (660 features) + OperationSequence + ConstraintSet
    辅助: optimize_allocation (MIP) — 批量场景按需调用
    输出: 每地块含 20 必选字段的重分类结果

    编码映射: DictionaryCenter.dlbm.lookup() + ghytbm.yaml + ghflbm.yaml
    """
    def generate(self, landuse_geojson, operation_sequence, constraint_set, gis_data) -> Dict:
        """输出 GeoJSON FeatureCollection，每 feature 含 20 必选字段

        批量场景: 检测到 660 地块 reclassify → 调用 optimize_allocation 辅助工具
        逐条场景: 直接执行单个 reclassify 操作
        """
```

**输出 feature 示例**：
```json
{
    "type": "Feature",
    "geometry": {...},
    "properties": {
        "BSM": "001",
        "YSDM": "2003070100",
        "TBH": "00000001",
        "XZQHDM": "441426108004",
        "XZQHMC": "金田村委会",
        "DLBM": "2121",
        "DLMJ": 1234.5,
        "QMDLBM": "0702",
        "GHFLBM": "071",
        "QMGHFLBM": "071",
        "GHYTBM": "0712",
        "GHYTMC": "农村宅基地",
        "assigned_zone": "村庄建设区",
        "zone_type": "居住用地",
        "color": "#FF6347",
        "changed": true,
        "area_ha": 0.12
    }
}
```

### 3.3 删除 planning_zone 独立层 ❌ 未开始

**文件**: `backend/app/tools/gis/generate.py`

- 删除 `_make_planning_zone_layer()` 函数（当前在 generate.py:206）
- 更新 `pipeline.py:128` 调用处
- 前端如需 6 类分区显示，从 ParcelReclass 的 `assigned_zone` 字段提取并 dissolve

### 3.4 RoadPlan 实现 ❌ 未开始

**新文件**: `backend/app/modules/gis/generation/road_plan_generator.py`

```python
class RoadPlanGenerator:
    """⑤ RoadPlan — 道路规划（OUTPUT_ARCHITECTURE.md v3.0 Layer ⑤）

    输入: current/road + ① ParcelReclass 输出（新增建设用地连通需求）
    输出: 规划道路网络 MultiLineString

    策略:
      1. 保留现有道路（直接继承 current/road）
      2. 识别新增建设用地区域（① 输出中 changed=True 且 assigned_zone=村庄建设区）
      3. 连接孤立建设地块到最近道路
      4. 输出合并后的规划道路网络
    """
```

---

## 4. 统一操作执行引擎

**核心洞察**：所有规划文本最终都被解析为 OperationSequence + ConstraintSet，不存在独立的"Text2GIS 层"或"增量编辑模式"。区别只在操作批量程度和确认粒度：

| 文本类型 | 解析输出 | 操作规模 | 确认方式 |
|----------|---------|---------|---------|
| 规划报告（"农田保护区≥98.54ha"） | OperationSequence（批量 reclassify） | 660 地块 | 批量确认+抽查 |
| 建设项目表（"新建400㎡展销中心"） | OperationSequence（create/split） | 1-5 地块 | 逐条确认卡片 |
| 管制规则（"允许建设区内不得安排基本农田"） | ConstraintSet（约束注入） | 规则级 | 自动生效（不修改图斑） |
| 村民决议（"同意搬迁学校"） | OperationSequence（modify+create） | 中等 | 逐条确认 |

### 4.1 操作执行引擎

**新文件**: `backend/app/modules/gis/generation/operation_engine.py`

```python
class OperationEngine:
    """统一操作执行引擎（OUTPUT_ARCHITECTURE.md v3.0 EXECUTE_OPERATIONS）

    5 种原子操作（统一指令集）:
      - create: 新增图斑（面积+用途+位置描述 → 新BSM）
      - split: 分割图斑（源BSM+面积比例 → 2+新BSM）
      - merge: 合并图斑（源BSM列表 → 1新BSM）
      - modify: 属性修改（源BSM+字段变更 → 属性更新）
      - reclassify: 地类重分类（源BSM+新QMDLBM → 编码+属性更新）

    批量 vs 逐条:
      - 批量（整村 660 reclassify）→ 按需调用 optimize_allocation 辅助工具
      - 逐条（1-5 操作）→ 直接执行，不调用 MIP

    合规检查: 复用 conflict/detector.py
    变更日志: 追加写入 changelog.jsonl
    """

    def execute(self, operation: Dict, current_layers: Dict, confirmed: bool = False) -> Dict:
        """执行操作，返回变更结果 + 合规报告 + 变更日志条目"""

    def execute_batch(self, operations: List[Dict], current_layers: Dict, confirmed: bool = False) -> List[Dict]:
        """批量执行操作序列，批量场景按需调用 optimize_allocation"""
```

### 4.2 辅助工具集

MIP allocator 从独立管道步骤降级为辅助工具，由执行引擎按需调用：

| 工具 | 功能 | 调用场景 |
|------|------|---------|
| `optimize_allocation` | MIP 分配 6 规划分区（原 ALLOCATE 步骤） | 批量 reclassify 时由执行引擎自动调用 |
| `resolve_place_name` | 空间地名解析：自然语言 → 候选图斑 | create/split 操作需要空间定位时 |
| `lookup_land_use_code` | 规划用途字典：名称 → 编码 | 任何需要 GHYTBM/QMDLBM 的操作 |
| `check_compliance` | 合规检查：拟操作图斑 → 实时检测 | 所有操作执行前的合规预检 |
| `extract_structured_text` | 表格文本 → 结构化 JSON | 建设项目表/用地指标表解析 |

**`optimize_allocation` 辅助工具**：

```python
# MIP allocator 不再是独立管道步骤，而是按需调用的辅助工具
async def optimize_allocation(
    landuse_geojson: Dict,
    targets: Dict[str, float],
    constraints: List[Dict] = None,
) -> Dict:
    """辅助工具: MIP 分配 6 规划分区。

    仅在批量操作场景下由 OperationEngine 调用：
    - 整村重分类（660 reclassify）→ 调用 MIP 优化分配
    - 单项目落地（1-5 操作）→ 不调用 MIP
    """
```

### 4.3 空间地名解析

**新文件**: `backend/app/tools/gis/place_resolver.py`

```python
async def resolve_place_name(
    location_desc: str,
    gis_data: Dict,
    village_name: str = "",
) -> Dict:
    """将自然语言空间描述解析为候选图斑列表。

    实现:
      1. 本地别名库查找 (dicts/place_aliases.yaml)
      2. Amap POI search_poi_text 模糊匹配
      3. 空间关系推理（"东侧"= X偏移, "沿河"= 河流缓冲区）
      4. 返回候选图斑列表 + 置信度
    """
```

**本地别名库**: `backend/app/modules/gis/schema/dicts/place_aliases.yaml`

```yaml
# 村域内重要地名与空间坐标/图斑关联
aliases:
  - name: "刘村小组"
    type: "natural_village"
    center: [116.xxx, 23.xxx]
    parcel_ids: ["XG-001", "XG-002"]
  - name: "晒谷场"
    type: "facility"
    dlbm: "1510"
    parcel_ids: ["XG-003"]
```

### 4.4 人工确认机制

**API 端点**:

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/gis/operations/confirm` | POST | 提交确认/拒绝/修改 |
| `/api/gis/operations/preview` | POST | 获取操作预览 GeoJSON |
| `/api/gis/operations/changelog` | GET | 查询变更日志 |

**确认卡片生成**: OperationEngine 生成确认卡片 JSON，前端渲染为确认对话框 + 地图预览。

---

## 5. 文件变更清单

### 新增文件

| # | 文件路径 | 说明 |
|---|---------|------|
| 1 | `generation/parcel_reclass_generator.py` | ① ParcelReclass（20字段重分类） |
| 2 | `generation/road_plan_generator.py` | ⑤ RoadPlan（道路规划） |
| 3 | `generation/operation_engine.py` | 统一操作执行引擎（5种原子操作+变更日志+MIP辅助工具） |
| 4 | `tools/gis/place_resolver.py` | 空间地名解析工具 |
| 5 | `schema/dicts/place_aliases.yaml` | 本地地名别名库 |

### 修改文件

| # | 文件路径 | 改动 | 说明 |
|---|---------|------|------|
| 1 | `generation/pipeline.py` | 删除 _make_planning_zone_layer 调用 | 管线使用新层结构 |
| 2 | `tools/gis/generate.py` | 删除 _make_planning_zone_layer | planning_zone 层被 UseZone 替代 |
| 3 | `generation/optimizer/mip_allocator.py` | solve() 添加 targets 映射 | 功能分区→规划分区 |
| 4 | `api/gis_test_routes.py` | 新增 operations 端点 | 确认/预览/变更日志 |

### 删除

| # | 目标 | 说明 |
|---|------|------|
| 1 | `tools/gis/generate.py::_make_planning_zone_layer()` | planning_zone 层被 UseZone 替代 |

---

## 6. 验证计划

### 6.1 功能验证

```bash
# 1. MIP targets 映射正确
python -c "
from app.modules.gis.generation.optimizer.planning_zone_mapper import map_zone_type_to_planning_zone
assert map_zone_type_to_planning_zone('农业用地') in ('农田保护区', '一般农业区')
assert map_zone_type_to_planning_zone('居住用地') == '村庄建设区'
"

# 2. gen/plan 分配结果不同
# 运行 MIP 并比较 allocated_geojson
# 预期: gen_allocated != plan_allocated (feature-level diff > 5%)

# 3. ParcelReclass 20 字段完整
# 运行管线，检查 06_planned_landuse 输出
# 每个 feature 的 properties 必须包含 QMDLTB 20 必选字段

# 4. 统一操作引擎
# create: 新增图斑 → BSM 生成 + 属性赋值
# split: 分割图斑 → 2 新 BSM + 面积守恒
# reclassify: 重分类 → QMDLBM/GHYTBM 更新
# 批量场景: 660 reclassify → 自动调用 optimize_allocation
# 逐条场景: 1-5 操作 → 直接执行，不调用 MIP
```

### 6.2 测试验证

```bash
pytest tests/unit/test_gis_unit.py -v
pytest tests/e2e/test_gis_e2e.py -v
```

### 6.3 渲染验证

```bash
python scripts/render_comparison.py
# 预期: gen 和 plan 面板渲染不同
```

---

## 7. 实施顺序

```
Phase 2: 架构对齐
  ├── 2.1 映射修复 ✅（已完成）
  ├── 2.2 ParcelReclass 升级 ❌
  │     ├── 新建 parcel_reclass_generator.py
  │     ├── 编码映射: DictionaryCenter 驱动
  │     └── generate.py 串联 ParcelReclass → 下游层
  ├── 2.3 删除 planning_zone 独立层 ❌
  │     ├── 删除 _make_planning_zone_layer
  │     └── 更新 pipeline.py 调用
  └── 2.4 RoadPlan 实现 ❌
        ├── 新建 road_plan_generator.py
        └── generate.py 集成

Phase 2.5: 统一操作执行引擎
  ├── 2.5.1 OperationEngine（5 种原子操作 + 变更日志 + 批量/逐条执行）
  ├── 2.5.2 MIP 降级为 optimize_allocation 辅助工具
  ├── 2.5.3 空间地名解析（Amap POI + 本地别名库）
  ├── 2.5.4 合规预检集成（复用 conflict/detector）
  ├── 2.5.5 人工确认卡片 API（/api/gis/operations/confirm + /preview + /changelog）
  └── 2.5.6 前端确认界面
```
