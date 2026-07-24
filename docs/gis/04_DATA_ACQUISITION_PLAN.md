# 数据集获取计划：Schema 空间要素全覆盖

> **Status: [CURRENT]** | **Type: Data Acquisition Plan** | **Updated: 2026-07-24**
> **Scope**: 全国平台 + 广东省平台 → Schema 空间要素类型全覆盖
> **References**: 03_DATA_SOURCE.md, schema对接kg，parse.md, diagnostics/03_DATA_GAP_ANALYSIS.md
> **Related**: BIBLIOGRAPHY.md §A3, §B9-11
>
> 本文档对两个数据平台（全国资源环境科学数据中心 + 广东省地理信息公共服务平台）的
> 数据集进行系统性分析，逐项映射到项目 Schema 空间要素类型，明确获取优先级和
> Schema 扩展需求。

---

## 一、Schema 空间要素完整清单（29 类型 + 2 栅格 + KG 独有）

| # | Schema 类型 | 组 | 几何 | 当前数据状态 | 当前KG入库 |
|---|-----------|----|------|------------|-----------|
| 1 | `AdminArea` | A 行政区划 | 面 | ✅ GDB: JT_行政区划 | ❌ |
| 2 | `AdminBoundaryLine` | A 行政区划 | 线 | ✅ GDB: PY_行政区划界线 | ❌ |
| 3 | `CurrentLandUseParcel` | B 地类图斑 | 面 | ✅ 660地块 | ✅ |
| 4 | `PlannedLandUseParcel` | B 地类图斑 | 面 | ✅ 582地块 | ❌ |
| 5 | `CurrentBuilding` | C 现状要素 | 面 | ❌ 无数据 | ❌ |
| 6 | `CurrentRoad` | C 现状要素 | 线 | ✅ 131条 | ✅ |
| 7 | `CurrentFacility` | C 现状要素 | 点 | ✅ 34设施注记 | ✅ |
| 8 | `CurrentAnnotation` | C 现状要素 | 点 | ✅ 34注记点 | ✅ |
| 9 | `FarmlandProtection` | D 规划要素 | 面 | ✅ GDB 88图斑 | ❌ |
| 10 | `EcologicalRedline` | D 规划要素 | 面 | ✅ GDB 5图斑 | ❌ |
| 11 | `CultivatedLandTarget` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 12 | `UrbanDevBoundary` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 13 | `VillageDevBoundary` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 14 | `HazardControlLine` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 15 | `FloodControlLine` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 16 | `GeologicalHazardPoint` | D 规划要素 | 点 | ✅ GDB 40个点 | ❌ |
| 17 | `HistoricalProtection` | D 规划要素 | 面 | ✅ GDB 3图斑 | ❌ |
| 18 | `LandUseZone` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 19 | `ConstructionCtrlZone` | D 规划要素 | 面 | ❌ 无数据 | ❌ |
| 20 | `ConditionalConstructionZone` | D 规划要素 | 面 | ✅ GDB 139图斑 | ❌ |
| 21 | `PlanningScope` | D 规划要素 | 面 | ✅ GDB 1图斑 | ❌ |
| 22 | `PlannedRoad` | D 规划要素 | 线 | ✅ GDB 170条 | ❌ |
| 23 | `PlannedAnnotation` | D 规划要素 | 点 | ✅ GDB 71注记 | ❌ |
| 24 | `ContourLine` | E 基础地理(DLG) | 线 | ❌ 无数据 | ❌ |
| 25 | `ElevationPoint` | E 基础地理(DLG) | 点 | ❌ 无数据 | ❌ |
| 26 | `WaterFeature` | E 基础地理(DLG) | 线/面 | ⚠️ 部分(DLBM推断) | ❌ |
| 27 | `DEMInput` | 栅格 | GeoTIFF | ❌ 无数据 | ❌ |
| 28 | `DOMInput` | 栅格 | GeoTIFF | ❌ 无数据 | ❌ |
| 29 | `ThreeZone` | KG独有 | — | ❌ | ❌ |
| 30 | `ThreeLine` | KG独有 | — | ❌ | ❌ |
| 31 | `ControlRule` | KG独有 | — | ⚠️ 文本parse | ❌ |

> **当前状态**: 11/29 有数据（38%），KG 入库率 4/29（14%）
>
> **数据分组说明**:
> - Group A: 行政区划 (AdminBoundary)
> - Group B: 地类图斑 (LandUse — 基期年现状 + 目标年规划用地分类)
> - Group C: 基期年现状要素 (CurrentFeatures)
> - Group D: 目标年规划要素 (Planned)
> - Group E: 基础地理信息要素 (DLG)
> - 栅格: DEM/DOM 输入
> - KG独有: 仅存在于知识图谱中的实体类型

---

## 二、全国平台数据集 → Schema 映射

### 2.1 行政区划（5 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 | 备注 |
|--------|-----------|------|--------|------|
| **全国2024年行政村边界数据** | `AdminArea` | 已有类型，需外部数据 | **P0** | Schema 的 `djzqdm`(12位) 依赖此数据 |
| **中国多年度区县行政区划边界** | `AdminArea` 🔧 | **需扩展** | **P0** | 当前 `AdminArea` 仅有村级别 |
| **多时期乡镇行政区划边界** | `AdminArea` 🔧 | **需扩展** | **P0** | 上位规划 `conducted_from` 关系到镇级 |
| **中国多年度地市行政区划边界** | `AdminArea` 🔧 | **需扩展** | **P1** | `EcologicalRedline.city` 字段校验 |
| **中国多年度省级行政区划边界** | `AdminArea` 🔧 | **需扩展** | **P1** | 省级上位规划上下文 |

> 🔧 **Schema 扩展**: `AdminArea` 增加 `admin_level: str` (village/town/county/city/province) + `parent_code: str`
>
> ⚠️ 5个数据集是同一行政体系的5个层级。如果"全国2024年行政村边界数据"带有完整 `XZQHDM` 编码字段，
> 可通过编码前缀推导上级行政区，不一定需要独立购买全部5个。建议优先获取行政村+区县两级。

### 2.2 地形地貌（6 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **全国分省12.5m DEM（ALOS）** | `DEMInput` | 已有类型，无数据 | **P0** |
| 分省DEM 30m（SRTM） | `DEMInput` | 备选（ALOS不可用时的降级方案） | P1 |
| **中国坡度空间分布数据** | `TerrainAnalysisResult` | 预计算产品，可跳过 `compute_slope()` | **P0** |
| **中国地形坡向空间分布数据** | `TerrainAnalysisResult` | 同上 | **P0** |
| **中国地形起伏度空间分布数据** | `TerrainAnalysisResult` | 建设适宜性评价输入 | P1 |
| 基于GF7卫星影像的DSM | `DEMInput` | 备选DEM | P1 |

> ⚠️ **重复**: DEM 类数据出现 5 次（ALOS 12.5m / SRTM 30m / SRTM 90m / 全国海拔高度DEM / DEM数字高程数据）。
> **推荐 ALOS 12.5m** 优先，SRTM 30m 作为备选。其余不需要重复获取。

### 2.3 遥感影像（6 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **哨兵10米分辨率多光谱遥感影像** | `DOMInput` | 已有类型，无数据 | **P0** |
| **不同年度高分辨率卫星遥感真彩色合成影像** | `DOMInput` | 建筑轮廓提取 | **P0** |
| **Landsat卫星长时间序列遥感影像** | `DOMInput` | 多时相变化检测 | P1 |
| 高分1号16m遥感影像 | `DOMInput` | 国产替代 | P1 |
| 高分1、2号原始遥感影像 | `DOMInput` | GF-2 0.8m全色 | P1 |
| SPOT系列卫星遥感影像 | `DOMInput` | 备选 | P2 |

> ⚠️ **重复**: "其他"列表中 Landsat 系列（8-9 OLI、4-5 MSS/TM、7 ETM、1-3 MSS）与
> "Landsat卫星长时间序列遥感影像"高度重叠。`Landsat 8 OLI_TIRS` 和 `Landsat 8-9 OLI/TIRS C2 L2`
> 是同一产品的不同处理级别（C2 L2 = Collection 2 Level-2 地表反射率），选其一即可。

### 2.4 土地利用（3 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国2025年土地利用现状遥感监测数据** | `CurrentLandUseParcel` | 外部验证，与GDB 660地块交叉校验 | P1 |
| **中国多时期土地利用遥感监测数据集** | 变化检测 | 多时期对比验证规划逻辑 | P1 |
| 中国1980年代100万土地利用数据 | — | ❌ 比例尺太粗(1:100万)，村域仅1-2像素 | — |

### 2.5 土壤（6 个数据集）🆕 需新建 Schema 类型

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国土壤类型空间分布数据** | `SoilType` 🆕 | **需新建类型** | **P1** |
| **中国土壤质地空间分布数据** | `SoilType` 🆕 | **需新建类型** | **P1** |
| **中国土壤侵蚀类型和程度空间分布数据** | `SoilErosion` 🆕 | **需新建类型** | **P1** |
| **中国土壤水蚀和风蚀模数数据** | `SoilErosion` 🆕 | 同上类型，补充模数字段 | P1 |
| 中国土系志土壤属性数据(2010) | `SoilType` 🆕 | 详细土系属性 | P2 |
| 中国土种志1-6卷土壤属性数据 | `SoilType` 🆕 | 历史土种调查 | P2 |

> 🆕 **需新建 Schema 类型 `SoilType`**:
> ```python
> @dataclass
> class SoilType(SpatialFeature):
>     soil_code: str = ""        # 土壤分类代码 (GB/T 17296)
>     soil_name: str = ""        # 土壤名称
>     soil_group: str = ""       # 土类
>     soil_subgroup: str = ""    # 亚类
>     parent_material: str = ""  # 成土母质
>     texture: str = ""          # 质地 (砂土/壤土/黏土)
>     area_ha: float = 0.0
> ```
>
> 🆕 **需新建 Schema 类型 `SoilErosion`**:
> ```python
> @dataclass
> class SoilErosion(SpatialFeature):
>     erosion_type: str = ""       # 侵蚀类型 (水蚀/风蚀/冻融)
>     erosion_intensity: str = ""  # 侵蚀强度 (微度/轻度/中度/强烈/极强烈/剧烈)
>     erosion_modulus: float = 0.0 # 侵蚀模数 (t/km²·a)
>     area_ha: float = 0.0
> ```

### 2.6 水系流域（5 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国河流水系空间分布数据** | `WaterFeature` | 已有类型，无外部数据 | **P0** |
| **中国三级流域空间分布** | `Watershed` 🆕 | **需新建类型** | **P1** |
| **基于DEM提取的中国流域、河网数据** | `WaterFeature` + `Watershed` 🆕 | DEM派生验证 | P1 |
| 中国一级河流空间分布数据集 | `WaterFeature` | 区域性骨架水系 | P1 |
| 中国三级流域产水模数 | `Watershed` 🆕 | 水资源评估辅助 | P2 |

> 🆕 **需新建 Schema 类型 `Watershed`**:
> ```python
> @dataclass
> class Watershed(SpatialFeature):
>     watershed_code: str = ""    # 流域编码
>     watershed_name: str = ""    # 流域名称
>     watershed_level: int = 0    # 流域级别 (1/2/3)
>     area_ha: float = 0.0
>     water_yield_modulus: float = 0.0  # 产水模数 (万m³/km²)
> ```

### 2.7 地理分区（6 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国九大农业区划** | `AgriculturalZone` 🆕 | 可选新建，或作参考数据 | P1 |
| **中国农业熟制区划** | `CroppingSystemZone` 🆕 | 耕地保护等级评定的空间约束 | P1 |
| **中国农业自然区划** | `AgriculturalZone` 🆕 | 农业适宜性背景 | P1 |
| 中国九大流域片 | `Watershed` 🆕 | 与三级流域互补 | P2 |
| 中国气候区划 | `ClimateZone` 🆕 | 气候背景参考 | P2 |
| 中国植被区划 | `VegetationZone` 🆕 | 生态修复参考 | P2 |

> 这6个区划数据集是否需要独立的 Schema 空间类型，取决于是否参与 KG 推理。
> 农业区划类建议建类型（影响耕地保护决策），其余可作参考数据层。

### 2.8 社会经济（3 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国人口空间分布公里网格数据集** | `PopulationGrid` 🆕 | 栅格类型，设施服务半径分析 | **P0** |
| **中国GDP空间分布公里网格数据集** | `GDPGrid` 🆕 | 产业规划经济可行性评估 | P1 |
| 2015-2017年各省市统计年鉴 | — | 文本路径（parse 覆盖），不建空间类型 | P2 |

> 🆕 人口/GDP 网格定义为栅格类型（类似 `DEMInput`/`DOMInput`），通过 `RasterInput` 基类统一处理。

### 2.9 生态/环境（4 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **自然保护区边界数据** | `NatureReserve` 🆕 | **需新建类型** | P1 |
| **中国多时期生态系统类型空间分布数据** | `EcologicalRedline` | 生态空间划定验证 | P1 |
| 中国植被指数遥感反演数据集(NDVI) | — | 栅格参考，不建独立类型 | P2 |
| 中国陆地生态系统服务价值空间分布数据 | — | 参考数据 | P2 |

> 🆕 **需新建 Schema 类型 `NatureReserve`**:
> ```python
> @dataclass
> class NatureReserve(SpatialFeature):
>     reserve_name: str = ""      # 保护区名称
>     reserve_type: str = ""      # 保护区类型 (自然保护区/风景名胜区/森林公园/地质公园/水源保护区)
>     protection_level: str = ""  # 保护级别 (国家级/省级/市县级)
>     area_ha: float = 0.0
>     established_year: int = 0   # 设立年份
> ```
>
> 注: `NatureReserve` 区别于 `EcologicalRedline`——红线是规划控制线，保护区是法定边界实体。

### 2.10 农业专项（3 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **中国农田生产潜力数据集** | `FarmlandProductivity` 🆕 | 耕地保护目标划定的科学依据 | P1 |
| **中国农田熟制空间分布数据集** | `CroppingSystemZone` 🆕 | 耕地等级评定 | P1 |
| 中国净第一性生产力NPP数据 | — | 栅格参考，不建独立类型 | P2 |

### 2.11 灾害/地质（2 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **地震地质数据** | `GeologicalHazardPoint` / `HazardControlLine` | 已有类型，金田村40点补充验证 | P2 |
| **台风路径数据** | — | 线状事件数据，可用通用Feature承载 | P2 |

### 2.12 基础设施（3 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **全国各年度兴趣点POI数据** | `CurrentFacility` | 已有类型，外部补充验证 | P1 |
| **城市建筑底面轮廓和高度空间分布数据** | `CurrentBuilding` | 已有类型，无数据 | P1 |
| 中国1995/2008/2012/...道路数据 | `CurrentRoad` | 已有类型，外部补充 | P1 |

### 2.13 不需要的全国平台数据集（16 项）

| 数据集 | 理由 |
|--------|------|
| 西南石漠化重点分布区 / 黄土高原空间范围 / 三峡库区范围边界 | 与广东省无关 |
| 内蒙古锡林格勒-Rapideye / 湖南郴州资源星 / 甘肃白银资源3号 / 北京SPOT 5 | 空间不匹配 |
| 东北亚自然地理背景数据 / 台湾资源环境数据 | 不同区域/体系 |
| 全球国家行政边界数据 | 国家边界对村规划无意义 |
| CMIP6全球/中国未来气候情景数据 | 未来气候预估对15年规划期限意义有限 |
| 全球气象站点小时尺度观测数据 | 小时尺度太细 |
| 中国100万植被/草地/地貌数据 | 1:100万比例尺村域仅1-2像素 |
| 城市内部土地覆被高分辨率遥感监测数据 | 城市尺度非村庄 |

---

## 三、广东省平台数据集 → Schema 映射

### 3.1 核心控制线（4 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **广东省三区三线专题图** | `ThreeZone` + `ThreeLine` + `FarmlandProtection` + `EcologicalRedline` + `UrbanDevBoundary` | KG实体已定义，无空间数据。**最关键获取项** | **P0** |
| **广东省永久基本农田保护图斑** | `FarmlandProtection` | 已有类型+GDB 88图斑，省级数据可验证 | **P0** |
| **广东省生态保护红线** | `EcologicalRedline` | 已有类型+GDB 5图斑，省级数据验证 | **P0** |
| **广东省城镇开发边界** | `UrbanDevBoundary` | 已有类型，无数据 | **P0** |

> ⚠️ **墨卡托 vs 非墨卡托重复**: 永久基本农田和城镇开发边界各有两个版本。
> 墨卡托投影(EPSG:3857)面积变形大，不适合精确面积计算。
> 非墨卡托版本大概率是 CGCS2000 地理坐标(EPSG:4490)，与项目坐标系一致。**取非墨卡托版本**。

### 3.2 国土变更调查（5 地类）

| 数据集 | 映射 Schema | 优先级 | 备注 |
|--------|-----------|--------|------|
| **2023年度国土变更调查耕地** | `CurrentLandUseParcel` (DLBM=1100 验证) | **P1** | 三调后最新耕地现状 |
| **2023年度国土变更调查园地** | `CurrentLandUseParcel` (DLBM=1200 验证) | **P1** | 园地现状验证 |
| **2023年度国土变更调查水域** | `WaterFeature` | **P1** | 可替代全国河流水系数据集 |
| **林地** | `CurrentLandUseParcel` (DLBM=1340/1350 验证) | **P1** | 生态空间划定基准 |
| **2023年度国土变更调查草地** | `CurrentLandUseParcel` (DLBM=1400 验证) | **P1** | 草地现状验证 |

> ⚠️ **重复**: "2023年度国土变更调查" 与 "2023年度**全国**国土变更调查" 大概率是同一套数据的不同命名。
> 确认后只取一个。同样，5个地类各有墨卡托和非墨卡托两个版本，各取非墨卡托版本。

### 3.3 灾害/地质（4 个数据集）

| 数据集 | 映射 Schema | 状态 | 优先级 |
|--------|-----------|------|--------|
| **广东省地质灾害隐患点专题图** | `GeologicalHazardPoint` | 已有类型+GDB 40点，省级补充 | **P0** |
| **地质灾害易发分区** | `HazardControlLine` | 已有类型，无数据 | **P1** |
| 广东省50万水文地质图 | `HydrogeologyZone` 🆕 | **需新建类型** | P1 |
| 广东省50万基础地质图 | — | 参考数据，不建类型 | P2 |

> ⚠️ **重复**: `地质灾害易发区（墨卡托）` vs `地质灾害易发分区` → 取非墨卡托
>
> 🆕 **需新建 Schema 类型 `HydrogeologyZone`**:
> ```python
> @dataclass
> class HydrogeologyZone(SpatialFeature):
>     zone_type: str = ""          # 水文地质分区类型
>     aquifer_type: str = ""       # 含水层类型 (孔隙水/裂隙水/岩溶水)
>     water_richness: str = ""     # 富水性等级 (丰富/中等/贫乏)
>     groundwater_depth: float = 0.0  # 地下水位埋深 (m)
> ```

### 3.4 影像（3 个数据集）

| 数据集 | 映射 Schema | 优先级 | 备注 |
|--------|-----------|--------|------|
| **广东省2023年影像电子地图** | `DOMInput` | **P0** | 最新年份基准 |
| **90-2023多时相影像电子地图** | `DOMInput` | **P1** | 长时序变化检测，一次性覆盖多时段 |
| 广东省2015-2022各年度影像(8个) | `DOMInput` | P2 | 已被多时相覆盖，按需补个别年份 |

> ⚠️ **重复**: 影像电子地图出现 10 次（2015-2023各年度 + 90-2023多时相 + 广州90年代）。
> 优先 #14 多时相产品，按需补 2023 年单年度。广州90年代空间不匹配，不需要。

### 3.5 设施/POI（1 个数据集）

| 数据集 | 映射 Schema | 优先级 | 备注 |
|--------|-----------|--------|------|
| **公厕** | `CurrentFacility` (facility_type="公厕") | **P1** | 直接对应 `ANNOTATION_LABEL_TYPE_MAP["卫"]` |

### 3.6 不需要的广东省平台数据集（6 项）

| 数据集 | 理由 |
|--------|------|
| 广东省地质旅游点 / 红色革命专题 | 旅游/文化规划走文本路径(parse → OpSeq) |
| 南粤古驿道线路 | 村域尺度价值有限，除非金田村恰好在古驿道沿线 |
| GDCORS基准站 / 测绘资质单位 | 测绘行政管理数据，与村庄规划无关 |
| 广州市90年代影像电子地图 | 广州市≠梅州市，空间范围不匹配 |

---

## 四、Schema 扩展需求汇总

### 4.1 需新建空间类型（7 个）

| # | 新类型 | 几何 | 所属组 | 驱动数据集 | 优先级 |
|---|--------|------|--------|-----------|--------|
| 1 | `SoilType` | 面 | 新建 Group F (自然资源) | 中国土壤类型/质地/土系志 | P1 |
| 2 | `SoilErosion` | 面 | 新建 Group F | 中国土壤侵蚀/水蚀风蚀模数 | P1 |
| 3 | `Watershed` | 面 | 扩展 Group E (DLG) | 中国三级流域/九大流域片 | P1 |
| 4 | `NatureReserve` | 面 | 扩展 Group D (规划要素) | 自然保护区边界 | P1 |
| 5 | `HydrogeologyZone` | 面 | 新建 Group F | 广东省50万水文地质图 | P1 |
| 6 | `PopulationGrid` | 栅格 | 栅格类型 | 中国人口空间分布公里网格 | P1 |
| 7 | `GDPGrid` | 栅格 | 栅格类型 | 中国GDP空间分布公里网格 | P2 |

### 4.2 需扩展现有类型（1 个）

| 类型 | 扩展内容 | 驱动数据集 |
|------|---------|-----------|
| `AdminArea` | + `admin_level: str` (village/town/county/city/province) + `parent_code: str` | 全国行政村/乡镇/区县/地市/省级边界 |

### 4.3 可选新建类型（6 个，可作为参考数据不入 KG）

| 类型 | 驱动数据集 | 决策条件 |
|------|-----------|---------|
| `AgriculturalZone` | 中国九大农业区划/农业自然区划 | 若参与 KG 耕地保护推理则必建 |
| `CroppingSystemZone` | 中国农业熟制区划/农田熟制 | 同上 |
| `ClimateZone` | 中国气候区划 | 纯参考可不建 |
| `VegetationZone` | 中国植被区划 | 纯参考可不建 |
| `FarmlandProductivity` | 中国农田生产潜力 | 若用于耕地等级评定则必建 |
| `ContourLine` | 已存在 ✅ | DEM派生或DLG获取 |

---

## 五、数据集获取优先级总清单

### 🔴 P0 — 立即获取（12 项）

| # | 平台 | 数据集 | Schema 类型 | 用途 |
|---|------|--------|-----------|------|
| 1 | 广东 | 广东省三区三线专题图 | `ThreeZone`/`ThreeLine`/`FarmlandProtection`/`EcologicalRedline`/`UrbanDevBoundary` | 村庄规划核心控制框架 |
| 2 | 广东 | 广东省永久基本农田保护图斑 | `FarmlandProtection` | 不可建设硬边界 |
| 3 | 广东 | 广东省生态保护红线 | `EcologicalRedline` | 不可建设硬边界 |
| 4 | 广东 | 广东省城镇开发边界 | `UrbanDevBoundary` | 三条控制线之一 |
| 5 | 广东 | 广东省地质灾害隐患点专题图 | `GeologicalHazardPoint` | 安全防灾必需 |
| 6 | 广东 | 广东省2023年影像电子地图 | `DOMInput` | 最新DOM，现状判读基准 |
| 7 | 全国 | 全国2024年行政村边界数据 | `AdminArea` | 规划单元空间定义 |
| 8 | 全国 | 中国多年度区县行政区划边界 | `AdminArea` 🔧 | 12位行政代码基准 |
| 9 | 全国 | 多时期乡镇行政区划边界 | `AdminArea` 🔧 | 镇级上位规划锚定 |
| 10 | 全国 | 全国分省12.5m DEM（ALOS） | `DEMInput` | 坡度/坡向/建设适宜性/洪涝分析 |
| 11 | 全国 | 哨兵10米分辨率多光谱遥感影像 | `DOMInput` | 现状地类判读 + NDVI |
| 12 | 全国 | 中国河流水系空间分布数据 | `WaterFeature` | 水系矢量独立图层 |

### 🟡 P1 — 尽快获取（20 项）

| # | 平台 | 数据集 | Schema 类型 |
|---|------|--------|-----------|
| 13 | 全国 | 中国坡度空间分布数据 | `TerrainAnalysisResult` |
| 14 | 全国 | 中国地形坡向空间分布数据 | `TerrainAnalysisResult` |
| 15 | 全国 | 中国地形起伏度空间分布数据 | `TerrainAnalysisResult` |
| 16 | 全国 | 中国人口空间分布公里网格数据集 | `PopulationGrid` 🆕 |
| 17 | 全国 | 中国土壤类型空间分布数据 | `SoilType` 🆕 |
| 18 | 全国 | 中国土壤质地空间分布数据 | `SoilType` 🆕 |
| 19 | 全国 | 中国土壤侵蚀类型和程度空间分布数据 | `SoilErosion` 🆕 |
| 20 | 全国 | 中国土壤水蚀和风蚀模数数据 | `SoilErosion` 🆕 |
| 21 | 全国 | 中国三级流域空间分布 | `Watershed` 🆕 |
| 22 | 全国 | 中国九大农业区划 | `AgriculturalZone` 🆕 |
| 23 | 全国 | 中国农业熟制区划 | `CroppingSystemZone` 🆕 |
| 24 | 全国 | 中国农业自然区划 | `AgriculturalZone` 🆕 |
| 25 | 全国 | 自然保护区边界数据 | `NatureReserve` 🆕 |
| 26 | 全国 | 中国农田生产潜力数据集 | `FarmlandProductivity` 🆕 |
| 27 | 全国 | 中国2025年土地利用现状遥感监测数据 | `CurrentLandUseParcel` |
| 28 | 全国 | 中国多时期土地利用遥感监测数据集 | 变化检测 |
| 29 | 广东 | 2023年度国土变更调查耕地 | `CurrentLandUseParcel` |
| 30 | 广东 | 2023年度国土变更调查水域 | `WaterFeature` |
| 31 | 广东 | 林地 | `CurrentLandUseParcel` |
| 32 | 广东 | 地质灾害易发分区 | `HazardControlLine` |
| 33 | 广东 | 广东省50万水文地质图 | `HydrogeologyZone` 🆕 |
| 34 | 广东 | 公厕 | `CurrentFacility` |

### 🟢 P2 — 条件获取（10 项）

| # | 平台 | 数据集 | Schema 类型 |
|---|------|--------|-----------|
| 35 | 全国 | 中国植被区划 | `VegetationZone` 🆕 (可选) |
| 36 | 全国 | 中国气候区划 | `ClimateZone` 🆕 (可选) |
| 37 | 全国 | 中国GDP空间分布公里网格数据集 | `GDPGrid` 🆕 |
| 38 | 全国 | 地震地质数据 | `GeologicalHazardPoint` |
| 39 | 全国 | 台风路径数据 | 通用Feature |
| 40 | 全国 | 全国各年度兴趣点POI数据 | `CurrentFacility` |
| 41 | 全国 | 城市建筑底面轮廓和高度空间分布数据 | `CurrentBuilding` |
| 42 | 全国 | 中国1995-2012道路数据 | `CurrentRoad` |
| 43 | 全国 | 中国土系志土壤属性数据(2010) | `SoilType` 🆕 |
| 44 | 广东 | 90-2023多时相影像电子地图 | `DOMInput` |

---

## 六、重复数据集清单

| 重复主题 | 出现次数 | 涉及平台 | 推荐选择 |
|----------|---------|---------|---------|
| **DEM** | 5次 | 全国 | **ALOS 12.5m** (SRTM 30m备选) |
| **Landsat** | 9次 | 全国 | **Landsat 8-9 C2 L2 + 长时间序列产品** |
| **高分系列** | 4次 | 全国 | **GF-1 16m + GF-2 原始影像** |
| **行政区划** | 5个层级 | 全国 | **行政村 + 区县** 优先，其余编码推导 |
| **水系** | 5次 | 全国 | **中国河流水系 + 三级流域** |
| **土壤** | 5次 | 全国 | **土壤类型 + 土壤质地 + 土壤侵蚀** |
| **国土变更调查** | 10次 (5地类×2投影) | 广东 | 各取**非墨卡托**版本 |
| **永久基本农田** | 2次 (墨卡托/非墨卡托) | 广东 | **非墨卡托**版本 |
| **城镇开发边界** | 2次 (墨卡托/非墨卡托) | 广东 | **非墨卡托**版本 |
| **地质灾害易发区** | 2次 (墨卡托/非墨卡托) | 广东 | **非墨卡托**版本 |
| **地质灾害隐患点** | 2次 (专题图/墨卡托) | 广东 | **专题图版本** |
| **影像电子地图** | 10次 (2015-2023各年+多时相) | 广东 | **2023年 + 多时相** |
| **2023国土变更 vs 2023全国国土变更** | 5地类命名变体 | 广东 | 确认后**只取一个** |

---

## 七、数据获取后的 Schema 实施顺序

```
Phase 1 — P0 数据到位后（Schema 核心入库）:
  ├── AdminArea 扩展 admin_level + parent_code 字段
  ├── FarmlandProtection → KG Builder add_protection_zones()
  ├── EcologicalRedline → KG Builder add_protection_zones()
  ├── UrbanDevBoundary → KG Builder add_protection_zones()
  ├── ThreeZone / ThreeLine → KG 实体创建 (ontology已有)
  ├── DEMInput → TerrainAnalyzer 实现 slope/aspect/suitability
  ├── DOMInput → 现状地类判读 + 建筑轮廓提取
  ├── WaterFeature → 独立图层替换 DLBM 推断
  └── GeologicalHazardPoint → KG Builder add_natural_features()

Phase 2 — P1 数据到位后（新建类型 + KG 入库）:
  ├── 新建 SoilType / SoilErosion / Watershed / NatureReserve / HydrogeologyZone
  ├── 新建 PopulationGrid / GDPGrid 栅格类型
  ├── HazardControlLine → KG Builder add_control_lines()
  ├── CurrentBuilding → 从 DOM 提取或建筑轮廓数据导入
  ├── CurrentFacility → 从 POI + 公厕数据补充
  └── AgriculturalZone / CroppingSystemZone → 参考数据层

Phase 3 — P2 数据到位后（参考数据 + 全链路贯通）:
  ├── 可选: ClimateZone / VegetationZone / FarmlandProductivity 类型
  ├── TerrainProfile → SpatialContext 全链路贯通
  └── 长时序变化检测 → 规划逻辑验证
```

---

## 八、相关文件

| 文件 | 变更 |
|------|------|
| `backend/app/modules/gis/schema/spatial_types.py` | 新建 SoilType/SoilErosion/Watershed/NatureReserve/HydrogeologyZone; 扩展 AdminArea |
| `backend/app/modules/gis/schema/raster_types.py` | 新建 PopulationGrid/GDPGrid |
| `backend/app/modules/gis/schema/__init__.py` | 导出新类型 |
| `backend/app/modules/kg/builder.py` | add_protection_zones/add_control_lines/add_natural_features/add_terrain |
| `backend/app/modules/kg/query.py` | 新增查询模板 (get_protected_parcels_detail 等) |
| `backend/app/modules/gis/spatial_context.py` | _compute_terrain_profile 实现 |
| `backend/app/agent/gis/parse/agent.py` | explore 阶段注入 KG 查询 |
| `docs/gis/schema对接kg，parse.md` | 本文档实施依据 |

---

## 九、参考标准

| 标准 | 用途 |
|------|------|
| GB/T 2260 | 中华人民共和国行政区划代码 (12位编码基准) |
| GB/T 21010-2017 | 土地利用现状分类 (现状DLBM编码) |
| GB/T 17296 | 中国土壤分类与代码 |
| GB/T 13923-2022 | 基础地理信息要素分类与代码 (DLG要素) |
| 自然资发〔2023〕234号 | 用地用海分类 (YDYHFLDM) |
| 广东省村庄规划编制基本技术指南(试行)(2019) | 村庄规划数据库技术规范 |
| 《实用性村庄规划编制手册》(李巍等) §2.1-2.5 | 数据获取与GIS实验依据 |
