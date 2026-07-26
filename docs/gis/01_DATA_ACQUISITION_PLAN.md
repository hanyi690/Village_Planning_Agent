# 数据集获取计划：Schema 空间要素全覆盖

> **Status: [CURRENT]** | **Type: Data Acquisition Plan** | **Updated: 2026-07-24**
> **Scope**: 全国平台 + 广东省平台 -> Schema 空间要素类型全覆盖
> **References**: 03_DATA_SOURCE.md, schema对接kg，parse.md, diagnostics/03_DATA_GAP_ANALYSIS.md
> **Related**: BIBLIOGRAPHY.md §A3, §B9-11
> **Data module**: P0 获取清单、重复数据集去重原则、DEM 选型已迁入 `backend/app/modules/data/README.md` 附录A，作为 sources.yaml 配置依据；本文档聚焦 Schema 映射与扩展需求

---

## 一、Schema 空间要素完整清单

| # | Schema 类型 | 组 | 几何 | 数据状态 | KG入库 |
|---|-----------|----|------|---------|--------|
| 1 | `AdminArea` | A 行政区划 | 面 | ✅ | ❌ |
| 2 | `AdminBoundaryLine` | A | 线 | ✅ | ❌ |
| 3 | `CurrentLandUseParcel` | B 地类图斑 | 面 | ✅ 660 | ✅ |
| 4 | `PlannedLandUseParcel` | B | 面 | ✅ 582 | ❌ |
| 5 | `CurrentBuilding` | C 现状要素 | 面 | ❌ | ❌ |
| 6 | `CurrentRoad` | C | 线 | ✅ 131 | ✅ |
| 7 | `CurrentFacility` | C | 点 | ✅ 34 | ✅ |
| 8 | `CurrentAnnotation` | C | 点 | ✅ 34 | ✅ |
| 9 | `FarmlandProtection` | D 规划要素 | 面 | ✅ 88 | ❌ |
| 10 | `EcologicalRedline` | D | 面 | ✅ 5 | ❌ |
| 11 | `CultivatedLandTarget` | D | 面 | ❌ | ❌ |
| 12 | `UrbanDevBoundary` | D | 面 | ❌ | ❌ |
| 13 | `VillageDevBoundary` | D | 面 | ❌ | ❌ |
| 14 | `HazardControlLine` | D | 面 | ❌ | ❌ |
| 15 | `FloodControlLine` | D | 面 | ❌ | ❌ |
| 16 | `GeologicalHazardPoint` | D | 点 | ✅ 40 | ❌ |
| 17 | `HistoricalProtection` | D | 面 | ✅ 3 | ❌ |
| 18 | `LandUseZone` | D | 面 | ❌ | ❌ |
| 19 | `ConstructionCtrlZone` | D | 面 | ❌ | ❌ |
| 20 | `ConditionalConstructionZone` | D | 面 | ✅ 139 | ❌ |
| 21 | `PlanningScope` | D | 面 | ✅ 1 | ❌ |
| 22 | `PlannedRoad` | D | 线 | ✅ 170 | ❌ |
| 23 | `PlannedAnnotation` | D | 点 | ✅ 71 | ❌ |
| 24 | `ContourLine` | E 基础地理 | 线 | ❌ | ❌ |
| 25 | `ElevationPoint` | E | 点 | ❌ | ❌ |
| 26 | `WaterFeature` | E | 线/面 | ⚠️ 部分 | ❌ |
| 27 | `DEMInput` | 栅格 | GeoTIFF | ❌ | ❌ |
| 28 | `DOMInput` | 栅格 | GeoTIFF | ❌ | ❌ |
| 29 | `ThreeZone` | KG独有 | - | ❌ | ❌ |
| 30 | `ThreeLine` | KG独有 | - | ❌ | ❌ |
| 31 | `ControlRule` | KG独有 | - | ⚠️ 文本 | ❌ |

> **当前**: 11/29 有数据（38%），KG入库 4/29（14%）
>
> Group A: 行政区划 / B: 地类图斑 / C: 现状要素 / D: 规划要素 / E: 基础地理 / 栅格 / KG独有

---

## 二、全国平台数据集 -> Schema 映射

| 类别 | 数据集 | Schema | 优先级 |
|------|--------|--------|--------|
| 行政区划 | 2024行政村边界 / 区县 / 乡镇 / 地市 / 省级 | `AdminArea` 🔧(扩展admin_level) | P0/P0/P0/P1/P1 |
| 地形地貌 | ALOS 12.5m DEM / 坡度 / 坡向 / 起伏度 | `DEMInput` / `TerrainAnalysisResult` | P0/P0/P0/P1 |
| 遥感影像 | 哨兵10m / 高分真彩色 / Landsat时序 / GF-1/GF-2 | `DOMInput` | P0/P0/P1/P1 |
| 土地利用 | 2025土地利用现状 / 多时期土地利用 | `CurrentLandUseParcel` / 变化检测 | P1 |
| 土壤 🆕 | 土壤类型 / 质地 / 侵蚀 / 水蚀风蚀模数 | `SoilType` / `SoilErosion` | P1 |
| 水系流域 🆕 | 河流水系 / 三级流域 / DEM提取流域 | `WaterFeature` / `Watershed` | P0/P1 |
| 地理分区 🆕 | 农业区划 / 熟制 / 气候 / 植被 | `AgriculturalZone` / `CroppingSystemZone` 等 | P1/P2 |
| 社会经济 🆕 | 人口网格 / GDP网格 | `PopulationGrid` / `GDPGrid` | P2/P2 |
| 生态/环境 🆕 | 自然保护区 / 生态系统类型 | `NatureReserve` / `EcologicalRedline` | P1 |
| 农业专项 🆕 | 农田生产潜力 / 农田熟制 | `FarmlandProductivity` / `CroppingSystemZone` | P1 |
| 灾害/地质 | 地震地质 / 台风路径 | `GeologicalHazardPoint` / 通用Feature | P2 |
| 基础设施 | POI / 建筑轮廓 / 道路 | `CurrentFacility` / `CurrentBuilding` / `CurrentRoad` | P1 |

> 不需要的全国数据集（16项）：西南石漠化/黄土高原/三峡库区（与广东无关）、区域不匹配影像、全球国家边界、CMIP6未来气候、100万比例尺数据等。
>
> **村庄尺度适配（2026-07-26 审查修正）**：
> - 人口/GDP 公里网格在村域仅覆盖数格，村级人口以村委台账/户籍/规划文本为准，网格数据只作区域背景参考，降级 P2。
> - ALOS 12.5m DEM 满足坡度/坡向分析，但对 1:2000 工作底图与宅基地选址精度不足；涉及精细地形时需另行获取大比例尺地形图/DLG。

---

## 三、广东省平台数据集 -> Schema 映射

| 类别 | 数据集 | Schema | 优先级 |
|------|--------|--------|--------|
| 核心控制线 | 三区三线 / 永久基本农田 / 生态红线 / 城镇开发边界 | `ThreeZone`+`ThreeLine`+`FarmlandProtection`+`EcologicalRedline`+`UrbanDevBoundary` | **P0** |
| 国土变更调查 | 2023耕地/园地/水域/林地/草地 | `CurrentLandUseParcel` / `WaterFeature` | P1 |
| 灾害/地质 | 地质灾害隐患点 / 易发分区 / 水文地质图 | `GeologicalHazardPoint` / `HazardControlLine` / `HydrogeologyZone` 🆕 | P0/P1/P1 |
| 影像 | 2023影像 / 90-2023多时相 | `DOMInput` | P0/P1 |
| 设施/POI | 公厕 | `CurrentFacility` | P1 |

> 不需要的广东数据集（6项）：地质旅游点/红色革命（走文本parse）、古驿道（村域价值有限）、GDCORS/测绘资质（无关）、广州90年代影像（空间不匹配）。
>
> 去重原则（墨卡托/非墨卡托取非墨卡托、DEM取ALOS、影像取2023+多时相）见 `backend/app/modules/data/README.md` 附录A.3。

---

## 四、Schema 扩展需求

> **优先级前提（2026-07-26 审查修正）**：DLBM->GHYTBM 正向映射表（基数转换，GAP-D）
> 优先于一切新增 Schema 类型——基数转换未落地前，新增自然资源类型不产生规划价值
> （见 `05_MODULE_BOUNDARY_AUDIT.md` §四 GAP-D）。

### 4.1 需新建空间类型（7 个）

| # | 新类型 | 几何 | 组 | 驱动数据集 | 优先级 |
|---|--------|------|-----|-----------|--------|
| 1 | `SoilType` | 面 | Group F (自然资源) | 土壤类型/质地/土系志 | P1 |
| 2 | `SoilErosion` | 面 | Group F | 土壤侵蚀/水蚀风蚀 | P1 |
| 3 | `Watershed` | 面 | 扩展 Group E | 三级流域/九大流域片 | P1 |
| 4 | `NatureReserve` | 面 | 扩展 Group D | 自然保护区边界 | P1 |
| 5 | `HydrogeologyZone` | 面 | Group F | 广东省50万水文地质图 | P1 |
| 6 | `PopulationGrid` | 栅格 | 栅格 | 人口空间分布公里网格 | P2 |
| 7 | `GDPGrid` | 栅格 | 栅格 | GDP空间分布公里网格 | P2 |

<details>
<summary>新类型字段定义（点击展开）</summary>

```python
@dataclass
class SoilType(SpatialFeature):
    soil_code: str = ""        # GB/T 17296
    soil_name: str = ""
    soil_group: str = ""       # 土类
    soil_subgroup: str = ""    # 亚类
    texture: str = ""          # 砂土/壤土/黏土
    area_ha: float = 0.0

@dataclass
class SoilErosion(SpatialFeature):
    erosion_type: str = ""       # 水蚀/风蚀/冻融
    erosion_intensity: str = ""  # 微度/轻度/中度/强烈/极强烈/剧烈
    erosion_modulus: float = 0.0 # t/km²·a
    area_ha: float = 0.0

@dataclass
class Watershed(SpatialFeature):
    watershed_code: str = ""
    watershed_name: str = ""
    watershed_level: int = 0    # 1/2/3
    area_ha: float = 0.0
    water_yield_modulus: float = 0.0  # 万m³/km²

@dataclass
class NatureReserve(SpatialFeature):
    reserve_name: str = ""
    reserve_type: str = ""      # 自然保护区/风景名胜区/森林公园/地质公园/水源保护区
    protection_level: str = ""  # 国家级/省级/市县级
    area_ha: float = 0.0
    established_year: int = 0

@dataclass
class HydrogeologyZone(SpatialFeature):
    zone_type: str = ""
    aquifer_type: str = ""      # 孔隙水/裂隙水/岩溶水
    water_richness: str = ""    # 丰富/中等/贫乏
    groundwater_depth: float = 0.0
```

</details>

### 4.2 需扩展现有类型

| 类型 | 扩展 | 驱动数据集 |
|------|------|-----------|
| `AdminArea` | + `admin_level` (village/town/county/city/province) + `parent_code` | 行政区划5级边界 |

### 4.3 可选新建类型（6 个，参考数据可不入 KG）

`AgriculturalZone` / `CroppingSystemZone` / `ClimateZone` / `VegetationZone` / `FarmlandProductivity` / `ContourLine`(已存在)

> 决策条件：若参与 KG 推理则必建，纯参考可不建。

---

## 五、获取优先级总清单

> P0 清单（12项）及 driver/layer_type 映射见 `backend/app/modules/data/README.md` 附录A.2。

### P1（20 项，摘要）

坡度/坡向/起伏度分布、土壤类型/质地/侵蚀、三级流域、农业区划/熟制、自然保护区、农田生产潜力、2025土地利用、2023国土变更(耕地/水域/林地)、地质灾害易发分区、水文地质图、公厕。

### P2（10 项，摘要）

植被/气候区划、人口网格、GDP网格、地震地质、台风路径、POI、建筑轮廓、历史道路、土系志、多时相影像。

---

## 六、Schema 实施顺序

```
Phase 1 - P0 到位（Schema 核心入库）:
  ├── AdminArea 扩展 admin_level + parent_code
  ├── FarmlandProtection / EcologicalRedline / UrbanDevBoundary -> KG add_protection_zones()
  ├── ThreeZone / ThreeLine -> KG 实体创建
  ├── DEMInput -> TerrainAnalyzer (slope/aspect/suitability)
  ├── DOMInput -> 现状判读 + 建筑轮廓
  ├── WaterFeature -> 独立图层
  └── GeologicalHazardPoint -> KG add_natural_features()

Phase 2 - P1 到位（新建类型 + KG 入库）:
  ├── 新建 SoilType/SoilErosion/Watershed/NatureReserve/HydrogeologyZone
  ├── 新建 PopulationGrid/GDPGrid 栅格类型
  ├── HazardControlLine -> KG add_control_lines()
  ├── CurrentBuilding -> DOM 提取或数据导入
  └── CurrentFacility -> POI + 公厕补充

Phase 3 - P2 到位（参考数据 + 全链路贯通）:
  ├── 可选 ClimateZone/VegetationZone/FarmlandProductivity
  ├── TerrainProfile -> SpatialContext 全链路
  └── 长时序变化检测 -> 规划逻辑验证
```

---

## 七、参考标准

| 标准 | 用途 |
|------|------|
| GB/T 2260 | 行政区划代码 (12位) |
| GB/T 21010-2017 | 土地利用现状分类 |
| GB/T 17296 | 中国土壤分类与代码 |
| GB/T 13923-2022 | 基础地理信息要素分类与代码 |
| 自然资发〔2023〕234号 | 用地用海分类 (YDYHFLDM) |
| 广东省村庄规划编制基本技术指南(试行)(2019) | 数据库技术规范 |
