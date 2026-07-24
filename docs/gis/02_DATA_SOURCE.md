# 金田村 GIS 数据源规范

> **Status: [CURRENT]** | **Type: Reference Documentation** | **Updated: 2026-07-24**
> **Scope**: 金田村实测数据 - GDB图层、字段结构、数据版本、与KG Builder对接
> **References**: BIBLIOGRAPHY.md §B9-10
> **Related**: 02_OUTPUT_ARCHITECTURE.md
> **Data module**: 数据源管理架构见 `backend/app/modules/data/README.md`（金田村 current/planned 文件通过 file_vector driver 配置进入 Catalog，字段编码校验经 `gis/schema/ingestion.py`）
>
> 数据来源：`docs/references/村庄规划总图/金田村村庄规划工程文件.zip`
> 数据已迁移至 `data/gis/jintian/`，详见 `data/gis/jintian/metadata.json`。

---

## 一、源数据结构

工程文件含 3 个子目录：

| 部分 | 格式 | 导出目标 | 是否标准 | 说明 |
|------|------|---------|---------|------|
| 1.村庄用地现状图 | ArcGIS GDB | `current/` | ✅ | 完整字段、规范编码、符合广东省技术规范 |
| 2.村庄规划总图 | ArcGIS GDB | `planned/` | ✅ | 同上 |
| 3.建设项目布局规划图 | AutoCAD DWG/DXF | `project/` + `reference/` | ❌ | CAD实体无属性编码（见 §3） |

> 广东省技术指南规定基本成果为"一图一表一规则"，1、2 对应"一图"数据库，第 3 部分属可选丰富成果。

---

## 二、GDB 图层与字段

### 2.1 现状 GDB（current/）

| GDB 图层 | 导出文件 | 几何 | 要素数 | 核心字段 |
|---------|---------|------|-------|---------|
| JT_行政区划_PBL | boundary.geojson | MultiPolygon | 1 | BSM, YSDM |
| PY_行政区划界线_LJJ | admin_boundary_line.geojson | MultiLineString | 561 | BSM, YSDM |
| **JT_现状地类图斑_LJJ** | **landuse.geojson** | **MultiPolygon** | **660** | **BSM, YSDM, DLBM, DLMC, DLMJ, BZ** |
| JT_农村居民点外道路_LJJ | road.geojson | MultiLineString | 131 | Shape_Length |
| JT_现状注记_LJJ | annotation.geojson | Point | 34 | BSM, YSDM |

### 2.2 规划 GDB（planned/）

| GDB 图层 | 导出文件 | 几何 | 要素数 | 核心字段 |
|---------|---------|------|-------|---------|
| JT_行政区划_PBL | boundary.geojson | MultiPolygon | 1 | BSM, YSDM |
| **JT_期末地类_LJJ** | **landuse.geojson** | **MultiPolygon** | **582** | **BSM, YSDM, DLBM, GHYTBM, GHYTMC, GHFLBM, QMDLBM, QMGHFLBM, DLMJ** |
| JT_农村居民点外道路_LJJ | road.geojson | MultiLineString | 170 | Shape_Length |
| JT_注记_LJJ | annotation.geojson | Point | 71 | BSM, YSDM |
| JT_地质灾害点_LJJ | geological_hazard_points.geojson | Point | 40 | 名称, 纬度, 经度, 类型, 大小 |
| JT_有条件建设区_LJJ | construction_zone.geojson | MultiPolygon | 139 | BSM, YSDM, BH, XZQHDM, LX, MJ |
| JT_永久基本农田保护红线_LJJ | farmland_protection.geojson | MultiPolygon | 88 | YSDM, XZQHDM, BSM, JBNT_MJ |
| JT_生态保护红线_LJJ | ecological_protection.geojson | MultiPolygon | 5 | OBJECTID, 区县, 地市, MJ |
| JT_历史文化保护线_LJJ | historical_protection.geojson | MultiPolygon | 3 | BUFF_DIST, ORIG_FID |

### 2.3 编码体系（关键认知）

现状层和规划层的 DLBM 使用**不同编码体系**（GDB 原始数据如此，非导出问题）：

| 图层 | 字段 | 编码体系 | 示例 |
|------|------|---------|------|
| 现状层 | DLBM | **附录5** | 2121=宅基地, 1100=耕地 |
| 规划层 | DLBM | **土规数据库标准** | 2030=农村居民点, 0110=水田 |
| 规划层 | QMDLBM | **土规数据库标准** | 2030, 0310 |
| 规划层 | GHYTBM | **附录5** | 2121=宅基地 |

> 四个编码体系独立定义，见 `backend/app/modules/gis/schema/dicts/`：
> `gbt21010.yaml` / `tugui.yaml` / `appendix5.yaml` / `ydyhfldm.yaml`
>
> 现状层 DLBM 用附录5、规划层 DLBM 用土规，这是正常设计--规划层关注规划分类，现状层关注现状分类。

---

## 三、DXF 项目数据（project/）

DXF 转换后提取为 GeoJSON，与 GDB 数据不同：CAD 图层是制图概念，不携带属性编码。

| 文件 | 要素数 | 说明 |
|------|-------|------|
| polygons.geojson | 945 | 房屋(723)/基本农田(91)/图例(72)/建设项目红线(24)等，仅 `layer`+`type` 属性 |
| lines.geojson | 138 | 引线(63)/规划道路(24)/新增公服(10)等 |
| annotation.geojson | 78 | 含 `text` 字段（46 个建设项目名称） |

> annotation 中的项目名称（如"田园民宿"、"南药科普体验园"）对应 PARSE Agent 解析的 `SpatialOperation.project_name`。

---

## 四、已知数据问题

| 问题 | 原因 | 影响 | 处理 |
|------|------|------|------|
| 现状层缺 GHYTBM/GHFLBM | 正常：现状层只用 DLBM，规划编码字段仅规划层有 | 无 | - |
| 现状层 SDDLBM 从 DLBM 复制 | 导出生成，值=附录5编码 | 无 | 代码已确认现状层用附录5 |
| 规划层 80/582 要素 GHFLBM 为空 | GDB 原始未填写 | 可补全 | GHFLBM_TO_GHYTBMS 反向映射 |
| 规划层缺 DLMC | 正常：规划层用 GHYTMC 代替 | 无 | - |
| 现状层缺 YDYHFLDM | 金田村编制于2022年，早于234号文 | 数据时代差异 | 基数转换函数补全(P3) |
| DLBM 尾部空格 | 1个要素 "2122 " | 读取正常 | 代码 `.strip()` |
| Shape_Area 大小写不一致 | 现状 `SHAPE_Area`，规划 `Shape_Area` | 读取需兼容 | 统一为 `Shape_Area` |

> 重新导出推荐 ogr2ogr（保留全字段、UTF-8、自动 CGCS2000->WGS84）：
> `ogr2ogr -f "GeoJSON" -dsco COORDINATE_PRECISION=15 -lco RFC7946=YES out.geojson in.gdb layer_name`

---

## 五、编码覆盖

- 现状层 DLBM：16 个唯一值，**100%** 有 zone_type 映射
- 规划层 GHYTBM：15 个唯一值，**100%** 有 zone_type + V/N/E 映射
- 规划层 GHFLBM：11 个唯一值 + 80 空，非空值 **100%** 覆盖（空值通过 GHYTBM 反查）

> 详细编码值表见 `backend/app/modules/gis/schema/dicts/` 各 YAML 字典。
> Schema 完整技术文档见 [SCHEMA_REFERENCE.md](SCHEMA_REFERENCE.md)。

---

## 六、参考标准

| 标准 | 用途 |
|------|------|
| GB/T 21010-2017 | 现状地类编码 (DLBM) |
| 三调工作分类 | 村庄规划专用编码 (2121-2126 等 21xx) |
| 自然资发〔2023〕234号 | 用地用海分类 (YDYHFLDM) |
| 住建部《村庄规划用地分类指南》 | V/N/E 分类 |
| DB14/T 2979-2024 / DB43/T 3555-2026 | 山西/湖南村庄规划数据库规范（字段结构参考） |
| DB61/T 1852-2024 | 陕西基数转换规范 (SDDLBM->YDYHFLDM) |
