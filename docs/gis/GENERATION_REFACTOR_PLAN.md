# Generation 层改造计划

> 版本: 1.0 | 日期: 2026-07-15 | 对齐: OUTPUT_ARCHITECTURE.md + DESIGN_GOALS.md

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

OUTPUT_ARCHITECTURE.md 定义 5 个内部生成层，当前实现了 6 层：

| 架构层 | 当前层 | 差异 |
|--------|--------|------|
| ① ParcelReclass (16字段) | function_zone (仅 zone_type/color) | **缺 QMDLBM/GHFLBM/GHYTBM/GHYTMC** |
| ② SpaceControl | space_control_zone | ✅ |
| ③ UseZone (V/N/E) | land_use_zone | ✅ |
| ④ FacilityPlan | facility_point | ✅ |
| — | **planning_zone (6类)** | **❌ 架构未定义，应删除** |
| ⑤ RoadPlan | ❌ 缺失 | 待实现 |
| — | infrastructure (AxisBuilder) | 可视化叠加，不独立成层 |

### 1.3 数据流断裂

**架构要求数据流**：
```
current/landuse (DLBM) + intent → ① ParcelReclass (16字段)
    ├──→ 06_planned_landuse
    ├──→ ② SpaceControl → 10_space_control_zone
    ├──→ ③ UseZone → 11_land_use_zone
    ├──→ ④ FacilityPlan → 14_planned_annotation
    └──→ ⑤ RoadPlan → 13_planned_road
```

**当前数据流**：
```
current/landuse (DLBM) → ZoneGenerator → function_zone (zone_type/color)
                                              ↓ (不传入下游)
current/landuse (DLBM) → MIP allocator → allocated_geojson (assigned_zone)
                                              ↓ (下游不用 16 字段)
allocated_geojson → _make_planning_zone_layer → planning_zone (6类)
allocated_geojson → LandUseZoneGenerator → land_use_zone (V/N/E)
allocated_geojson → SpaceControlZoneGenerator → space_control_zone
intent → FacilityPlacer → facility_point
intent → AxisBuilder → infrastructure
```

**断裂点**：
1. ZoneGenerator 和 MIP allocator 独立运行，不串联
2. ParcelReclass 的 16 字段输出缺失，下游层无法获得 QMDLBM/GHYTBM
3. planning_zone 独立生成，不用 MIP 结果
4. UseZone 直接从 allocated 读 DLBM，不经过 ParcelReclass

---

## 2. 改造目标

**一句话**：让 LLM 的 intent 差异真正传递到最终输出，对齐 OUTPUT_ARCHITECTURE.md 的 5 层架构。

**量化目标**：
- gen 和 plan 的 06_planned_landuse 输出不同（feature 级别差异 > 5%）
- 06_planned_landuse 包含完整 16 字段（QMDLBM/GHFLBM/GHYTBM/GHYTMC）
- 删除 planning_zone 独立层，6 类分区信息保留在 ParcelReclass 的 assigned_zone 字段
- 5 层按架构定义的输入输出契约串联

---

## 3. 改造方案

### 3.1 新增：DLBM → QMDLBM/GHFLBM/GHYTBM 映射表

**文件**: `backend/app/services/modules/gis/zone_schema/code_sets.py`

从 planned/landuse.geojson 实测数据反推 + 国标规范补充：

```python
# DLBM → (QMDLBM, GHFLBM, GHYTBM, GHYTMC)
# 规则：现状地类不变 → QMDLBM = DLBM；地类变更 → QMDLBM = 新编码
DLBM_TO_PLANNED_CODES: Dict[str, Dict[str, str]] = {
    "0100": {"QMDLBM": "0100", "GHFLBM": "011", "GHYTBM": "011A", "GHYTMC": "耕地"},
    "0300": {"QMDLBM": "0300", "GHFLBM": "031", "GHYTBM": "031A", "GHYTMC": "林地"},
    "1101": {"QMDLBM": "1101", "GHFLBM": "111", "GHYTBM": "111A", "GHYTMC": "坑塘水面"},
    "2121": {"QMDLBM": "0702", "GHFLBM": "071", "GHYTBM": "0712", "GHYTMC": "农村宅基地"},
    "1340": {"QMDLBM": "0201", "GHFLBM": "021", "GHYTBM": "021A", "GHYTMC": "商品林"},
    "1350": {"QMDLBM": "0301", "GHFLBM": "032", "GHYTBM": "032A", "GHYTMC": "生态林"},
    # ... 从 planned/landuse 实测数据补全全部 48 类
}
```

**数据来源**：`data/gis/jintian/planned/landuse.geojson` 中 582 features 的 GHYTBM/GHYTMC 字段。

### 3.2 升级 ZoneGenerator → ParcelReclassGenerator

**新文件**: `backend/app/services/modules/gis/generation/parcel_reclass_generator.py`

**核心变更**：每个地块输出 16 字段，而非合并后区域。

```python
class ParcelReclassGenerator:
    """① ParcelReclass — 地块重分类（OUTPUT_ARCHITECTURE.md Layer ①）
    
    输入: current/landuse (660 features) + intent (zones: area_ratio, land_use) + MIP allocation result
    输出: 每地块含 16 字段的重分类结果
    
    处理:
      1. 继承 MIP allocation 的 assigned_zone（规划分区）
      2. 保护地块锁定（基本农田/生态红线 → QMDLBM = DLBM，不变）
      3. 非保护地块：assigned_zone → 查表获取 QMDLBM/GHFLBM/GHYTBM/GHYTMC
      4. 计算几何属性（Shape_Length/Shape_Area）
    """
    
    def generate(
        self,
        landuse_geojson: Dict,           # current/landuse (660 features)
        allocated_geojson: Dict,          # MIP allocation result (每地块 assigned_zone)
        intent: Dict,                     # UnifiedSpatialIntent
        gis_data: Dict,                   # 保护红线等
    ) -> Dict:
        """输出 GeoJSON FeatureCollection，每 feature 含 16 字段"""
```

**输出 feature 示例**：
```json
{
    "type": "Feature",
    "geometry": {...},
    "properties": {
        "BSM": "001",
        "YSDM": "2003070100",
        "DLBM": "2121",
        "DLMJ": 1234.5,
        "QMDLBM": "0702",
        "GHFLBM": "071",
        "GHYTBM": "0712",
        "GHYTMC": "农村宅基地",
        "Shape_Length": 5678.9,
        "Shape_Area": 1234500.0,
        "assigned_zone": "村庄建设区",
        "zone_type": "居住用地",
        "color": "#FF6347",
        "changed": true,
        "area_ha": 0.12
    }
}
```

### 3.3 修复 MIP Allocator — targets 映射

**文件**: `backend/app/services/modules/gis/generation/optimizer/mip_allocator.py`

在 `solve()` 方法开头添加映射：

```python
def solve(self, landuse_geojson, targets, constraints=None, kg=None, ...):
    # ── 功能分区 targets → 规划分区 targets ──
    from .planning_zone_mapper import map_zone_type_to_planning_zone
    mapped_targets = {}
    for zone_name, area in targets.items():
        planning_zone = map_zone_type_to_planning_zone(zone_name)
        if planning_zone:
            mapped_targets[planning_zone] = mapped_targets.get(planning_zone, 0) + area
        else:
            # 未知分区名（可能是规划分区名），保留原样
            mapped_targets[zone_name] = area
    if mapped_targets:
        targets = mapped_targets
    
    planning_zones = list(targets.keys())
    # ... 后续逻辑不变，此时 _get_preference_cost 能正确匹配
```

### 3.4 删除 planning_zone 独立层

**文件**: `backend/app/tools/gis/generate.py`

- 删除 `_make_planning_zone_layer()` 函数
- 前端如需 6 类分区显示，从 ParcelReclass 的 `assigned_zone` 字段提取并 dissolve

### 3.5 串联 5 层数据流

**新的 generate.py 层结构**：

```python
# ── Step 1: ALLOCATE (MIP, 使用规划分区 targets) ──
mapped_targets = _map_zone_type_targets_to_planning_zone(intent_targets)
allocated_geojson, trace = MIPZoneAllocator().solve(landuse, mapped_targets, ...)

# ── Step 2: ① ParcelReclass (16字段, 依赖 allocated) ──
parcel_reclass = ParcelReclassGenerator().generate(landuse, allocated_geojson, intent, gis_data)
# → 输出 06_planned_landuse

# ── Step 3: ② SpaceControl (依赖 ①) ──
space_control = SpaceControlZoneGenerator().generate(boundary, ..., planned_landuse=parcel_reclass, ...)
# → 输出 10_space_control_zone

# ── Step 4: ③ UseZone (依赖 ①) ──
use_zone = LandUseZoneGenerator().generate(allocated_geojson=parcel_reclass, ...)
# → 输出 11_land_use_zone

# ── Step 5: ④ FacilityPlan (依赖 intent + ①) ──
facilities = FacilityPlacer().place(intent["facilities"], landuse_geojson=parcel_reclass, ...)
# → 输出 14_planned_annotation

# ── Step 6: ⑤ RoadPlan (依赖 current/road + ①) ──
road_plan = RoadPlanGenerator().generate(current_road, planned_landuse=parcel_reclass, ...)
# → 输出 13_planned_road
```

### 3.6 新增 RoadPlanGenerator

**新文件**: `backend/app/services/modules/gis/generation/road_plan_generator.py`

```python
class RoadPlanGenerator:
    """⑤ RoadPlan — 道路规划（OUTPUT_ARCHITECTURE.md Layer ⑤）
    
    输入: current/road + ① ParcelReclass 输出（新增建设用地连通需求）
    输出: 规划道路网络 MultiLineString
    
    策略:
      1. 保留现有道路（直接继承 current/road）
      2. 识别新增建设用地区域（① 输出中 changed=True 且 assigned_zone=村庄建设区）
      3. 连接孤立建设地块到最近道路（A* 最短路径 or 直线连接）
      4. 输出合并后的规划道路网络
    """
```

---

## 4. 文件变更清单

### 新增文件

| # | 文件路径 | 说明 |
|---|---------|------|
| 1 | `generation/parcel_reclass_generator.py` | ① ParcelReclass（16字段重分类） |
| 2 | `generation/road_plan_generator.py` | ⑤ RoadPlan（道路规划） |

### 修改文件

| # | 文件路径 | 改动 | 说明 |
|---|---------|------|------|
| 1 | `generation/optimizer/mip_allocator.py` | solve() 开头 | 功能分区→规划分区 targets 映射 |
| 2 | `generation/optimizer/planning_zone_mapper.py` | 新增反向映射 | map_zone_type_targets_to_planning_zone(dict) → dict |
| 3 | `zone_schema/code_sets.py` | 新增映射表 | DLBM_TO_PLANNED_CODES (QMDLBM/GHFLBM/GHYTBM) |
| 4 | `tools/gis/generate.py` | 重构 | 删除 _make_planning_zone_layer，新增 ParcelReclass 串联 |
| 5 | `tools/gis/allocate.py` | 修改 | targets 映射逻辑 |
| 6 | `api/gis_test_routes.py` | 修改 | 管线使用新层结构 + targets 映射 |
| 7 | `scripts/render_comparison.py` | 修改 | 加入 MIP 分配 + 使用新层结构 |

### 删除文件/函数

| # | 目标 | 说明 |
|---|------|------|
| 1 | `tools/gis/generate.py::_make_planning_zone_layer()` | planning_zone 层被 UseZone 替代 |

---

## 5. 验证计划

### 5.1 功能验证

```bash
# 1. MIP targets 映射正确
python -c "
from app.services.modules.gis.generation.optimizer.planning_zone_mapper import map_zone_type_to_planning_zone
assert map_zone_type_to_planning_zone('农业用地') == '农田保护区'  # 或一般农业区
assert map_zone_type_to_planning_zone('居住用地') == '村庄建设区'
"

# 2. gen/plan 分配结果不同
python -c "
from app.services.modules.gis.layout.data_loader import load_all
from app.services.modules.gis.layout.intent_cache import resolve_gen_intent_cached, resolve_plan_intent_cached
# ... 运行 MIP 并比较 allocated_geojson
# 预期: gen_allocated != plan_allocated (feature-level diff > 5%)
"

# 3. ParcelReclass 16 字段完整
python -c "
# 运行管线，检查 06_planned_landuse 输出
required_fields = ['BSM','YSDM','DLBM','DLMJ','QMDLBM','GHFLBM','GHYTBM','GHYTMC','Shape_Length','Shape_Area']
# 每个 feature 的 properties 必须包含以上字段
"
```

### 5.2 测试验证

```bash
pytest tests/unit/test_gis_unit.py -v          # 32/32 通过
pytest tests/e2e/test_gis_e2e.py -v            # 含新增差异性验证
```

### 5.3 渲染验证

```bash
python scripts/render_comparison.py
# 预期: gen 和 plan 面板渲染不同
```

---

## 6. 实施顺序

```
Phase A: 映射修复（最小改动，解决 gen/plan 一致问题）
  ├── A1. code_sets.py 新增 DLBM_TO_PLANNED_CODES
  ├── A2. planning_zone_mapper.py 新增 map_zone_type_targets_to_planning_zone
  ├── A3. mip_allocator.py solve() 添加 targets 映射
  ├── A4. gis_test_routes.py 管线 targets 映射
  └── A5. 验证 gen/plan 分配结果不同

Phase B: ParcelReclass 升级（对齐 16 字段）
  ├── B1. 新建 parcel_reclass_generator.py
  ├── B2. generate.py 串联 ParcelReclass → 下游层
  ├── B3. 删除 _make_planning_zone_layer
  └── B4. 验证 06_planned_landuse 16 字段完整

Phase C: RoadPlan 实现
  ├── C1. 新建 road_plan_generator.py
  ├── C2. generate.py 集成
  └── C3. 验证 13_planned_road 输出
```
