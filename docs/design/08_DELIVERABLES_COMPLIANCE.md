# 成果合规性（一图一表一规则 + GDB 汇交）

> **产出可解释、可汇交的村庄规划成果包：一图一表一规则 + GDB 数据库。**
> 对应 `00_SYSTEM_DESIGN` 第零部分（官方标准对齐）展开。

---

## 1. 成果结构：一图一表一规则

依据《广东省村庄规划编制指引》（试行）四阶段工作流，系统产出三件套：

```
┌─────────────────────────────────────────────────┐
│  一图: 村庄规划总图                               │
│  - 现状图（5 现状层）                             │
│  - 规划总图（7 规划层）                           │
│  - 国标配色（GB/T 21010 + GB/T 50280-98）        │
│  - MapLibre 渲染 + GDB 导出                      │
├─────────────────────────────────────────────────┤
│  一表: 用地指标表                                 │
│  - 现状/规划用地面积对比                          │
│  - 按地类/分区/三区聚合                           │
│  - metrics.py 聚合计算                           │
├─────────────────────────────────────────────────┤
│  一规则: 村庄建设规划管制规则                      │
│  - DB4407/T 105-2023 6 大类管制规则模板           │
│  - [PLANNED] 未实现                              │
└─────────────────────────────────────────────────┘
```

---

## 2. GDB 12 层注册表

`modules/schema/output/gdb.py` 的 `GDB_LAYER_REGISTRY` 定义 12 层（5 现状 + 7 规划）：

### 2.1 命名规范

```
{prefix}_{description}_{feature_type_code}_{date}

prefix:              村级行政区划代码前2字符（金田村: "JT"）
description:         图层描述（中文）
feature_type_code:   PBL=面 / LJJ=线 / DMM=点
date:                YYYYMMDD
```

### 2.2 现状要素层（5 层）

| gdb_key | 图层名 | 几何 | 内部图层 | 说明 |
|---------|--------|------|----------|------|
| admin_area | {p}_行政区划_PBL_{d} | MultiPolygon | boundary | 规划村范围 GHCFW |
| admin_boundary_line | {p}_行政区划界线_LJJ_{d} | MultiLineString | boundary | 行政区划界线 |
| current_landuse | {p}_现状地类图斑_LJJ_{d} | MultiPolygon | function_zone | 基期年现状地类图斑 |
| current_road | {p}_农村居民点外道路_LJJ_{d} | MultiLineString | infrastructure | 现状道路 |
| current_annotation | {p}_现状注记_LJJ_{d} | Point | annotation | 现状注记 |

### 2.3 规划要素层（7 层）

| gdb_key | 图层名 | 几何 | 内部图层 | 说明 |
|---------|--------|------|----------|------|
| planned_landuse | {p}_期末地类_LJJ_{d} | MultiPolygon | function_zone | 目标年期末地类图斑 QMDLTB |
| ecological_redline | {p}_生态保护红线_LJJ_{d} | MultiPolygon | ecological_redline | 生态保护红线 |
| farmland_protection | {p}_永久基本农田保护红线_LJJ_{d} | MultiPolygon | farmland_protection | 永久基本农田 |
| historical_protection | {p}_历史文化保护线_LJJ_{d} | MultiPolygon | historical_protection | 历史文化保护线 |
| construction_zone | {p}_有条件建设区_LJJ_{d} | MultiPolygon | construction_zone | 有条件建设区 |
| space_control_zone | {p}_建设用地管制区_LJJ_{d} | MultiPolygon | space_control_zone | 管制分区 JSYDGZQ (510/520/530/540) |
| land_use_zone | {p}_土地用途分区_LJJ_{d} | MultiPolygon | land_use_zone | 土地用途分区 TDYT |
| hazard_points | {p}_地质灾害点_LJJ_{d} | Point | facility_point | 地质灾害点 |
| planned_annotation | {p}_注记_LJJ_{d} | Point | annotation | 规划注记 |
| planned_road | {p}_农村居民点外道路_LJJ_{d} | MultiLineString | infrastructure | 规划道路 |

### 2.4 内部图层 -> GDB 映射

`INTERNAL_LAYER_TO_GDB_KEYS`（一个内部图层可映射多个 GDB 层）：

| 内部图层 | GDB keys |
|----------|----------|
| boundary | admin_area, admin_boundary_line |
| function_zone | current_landuse, planned_landuse |
| infrastructure | current_road, planned_road |
| ecological_redline | ecological_redline |
| farmland_protection | farmland_protection |
| historical_protection | historical_protection |
| construction_zone | construction_zone |
| space_control_zone | space_control_zone |
| land_use_zone | land_use_zone |
| facility_point | hazard_points |
| annotation | current_annotation, planned_annotation |
| planning_zone | （无 GDB 映射，仅渲染） |
| development_axis | （无 GDB 映射，仅渲染） |

### 2.5 字段富化

`enrich_gdb_fields`（gdb.py:444）为 GeoJSON 补齐 GDB 必填字段：
- Rule 1: copy_from（从另一字段复制，如 SDDLBM <- DLBM）
- Rule 2: from_param（从函数参数填充，如 XZQHDM）
- Rule 3: lookup（查表，如 DLMC <- DLBM_TO_DLMC[DLBM]）
- Rule 4: YSDM 特殊（按 gdb_key 查 YSDM_DEFAULTS）
- Rule 5: Shape_ 字段（几何计算，导出时填充）
- Rule 6: explicit default（规则显式默认值）

---

## 3. 编码体系

### 3.1 六大编码系统

| 编码系统 | 全称 | 用途 | 标准 |
|----------|------|------|------|
| GB/T21010 | 土地利用现状分类 | 三调国标编码 | GB/T 21010-2017 |
| TUGUI | 土规数据库标准 | 土规用地编码 | 土规数据库规范 |
| APPENDIX5 | 附录5规划用途编码 | 规划用途编码 | 自然资发〔2023〕234号 |
| GHFLBM | 规划分类编码 | 规划分类编码 | 土规数据库规范 |
| YDYHFL | 用地用海分类 | 用地用海分类 | 自然资发〔2023〕234号 |
| VNE | V/N/E 三分类 | 村庄规划用地分类 | 住建部(2014) |

### 3.2 编码映射

`encodings/dicts/mappings/` 下 13 个 YAML 映射文件：

| 映射文件 | 源 -> 目标 |
|----------|-----------|
| gbt21010_to_zone_types_gbt50137 | GB/T21010 -> 用地类型(GB50137) |
| gbt21010_to_zone_types_appendix5 | GB/T21010 -> 用地类型(附录5) |
| gbt21010_to_three_categories | GB/T21010 -> 三区(生态/农业/建设) |
| gbt21010_to_primary_zones | GB/T21010 -> 一级分区 |
| gbt21010_to_planning_zones | GB/T21010 -> 规划分区(6类) |
| sddlm_to_ydyhfldm | 三调地类码 -> 用地用海分类码 |
| dlbm_to_ghytbm | DLBM -> GHYTBM |
| ghflbm_to_zone_types_appendix5 | GHFLBM -> 用地类型(附录5) |
| ghflbm_to_tdytfqdm | GHFLBM -> 土地用途分区码 |
| appendix5_to_zone_types_appendix5 | 附录5 -> 用地类型(附录5) |
| vne_to_zone_types_appendix5 | VNE -> 用地类型(附录5) |
| vne_to_three_categories | VNE -> 三区 |
| planning_zones_to_primary_zones | 规划分区 -> 一级分区 |
| planning_zones_to_control_code | 规划分区 -> 管制码 |

### 3.3 字段编码填充

`planned_landuse` 层同时携带多编码体系字段：

| GDB 字段 | 编码系统 | 说明 |
|----------|----------|------|
| DLBM | TUGUI | 基期地类编码 |
| QMDLBM | TUGUI | 期末地类编码 |
| GHFLBM | GHFLBM | 规划分类编码 |
| QMGHFLBM | GHFLBM | 期末规划分类编码 |
| GHYTBM | APPENDIX5 | 规划用途编码 |
| GHYTMC | APPENDIX5 | 规划用途名称 |
| SDDLBM | (复制自DLBM) | 三调地类编码 |

---

## 4. 国标配色

`modules/schema/output/colors.py` 是所有 GIS 颜色定义的单一真相源：

### 4.1 功能区配色（8 类）

| 用地类型 | fill | stroke |
|----------|------|--------|
| 农业用地 | #F5F8DC | #8B7355 |
| 生态绿地 | #68B167 | #2E8B57 |
| 居住用地 | #FFD380 | #B8860B |
| 商业用地 | #FF0000 | #CC0000 |
| 产业用地 | #BB9674 | #8B6914 |
| 公共服务用地 | #4A90D9 | #1E3A5F |
| 交通用地 | #0000FF | #0066CC |
| 水域 | #87CEEB | #4169E1 |

> 依据 GB/T 21010 + GB/T 50280-98 规划配色规范。前端 `gis.ts` 同步。

### 4.2 规划分区配色（6 类）

| 规划分区 | fill | 对应用地类型 |
|----------|------|-------------|
| 生态保护区 | #2E8B57 | 生态绿地 |
| 生态控制区 | #90EE90 | 生态绿地 |
| 农田保护区 | #FFE4B5 | 农业用地 |
| 一般农业区 | #98FB98 | 农业用地 |
| 村庄建设区 | #FF6347 | 居住用地 |
| 林业发展区 | #3CB371 | 生态绿地 |

### 4.3 空间管制区配色

| 管制码 | 名称 | fill |
|--------|------|------|
| 510 | 允许建设区 | #FFE0B2 |
| 520 | 限制建设区 | #C8E6C9 |
| 530 | 有条件建设区 | #FFF9C4 |
| 540 | 禁止建设区 | #FFCDD2 |

---

## 5. 用地指标表

`modules/schema/utils/metrics.py` 实现用地指标聚合：

### 5.1 聚合逻辑

```python
# metrics.py 核心函数
_dlbm_areas(geojson) -> Dict[str, float]   # 按地类码聚合面积
compute_land_use_metrics(geojson) -> Dict   # 用地指标计算
```

面积提取优先级：
1. `area_ha`（已是公顷）
2. `DLMJ`（m²，除以 10000）
3. `MJ`（m²，除以 10000）

规划用地取 `QMDLBM`（期末码），否则回退 `DLBM`（现状码）。

### 5.2 建设用地识别

`CONSTRUCTION_DLBM_CODES` 按用地类型分组：
- 居住用地: 0700, 0701, 0702, 2121, 2030
- 产业用地: 0600, 0601, 0602, 0603, 0610, 0620, 2100, 2124
- 公共服务用地: 0800, 0801, 0802, 0803, 0806, 0810, 0900, 2122, 2125
- 交通用地: 1000, 1001, 1002, 1003, 1004, 1005, 1006, 1040, 2123, 2126, 2200
- 商业用地: 0500

---

## 6. 管制规则

### 6.1 DB4407/T 105-2023 六大类

依据《村庄建设规划管制规则》（DB4407/T 105-2023），6 大类管制规则：

| 类别 | 内容 |
|------|------|
| 用途管制 | 地块允许/限制/禁止的用途 |
| 建设强度管制 | 容积率/建筑密度/绿地率上限 |
| 建筑形态管制 | 建筑高度/退线/间距 |
| 设施配置管制 | 公服/市政设施配建要求 |
| 生态保护管制 | 生态红线/基本农田管控 |
| 历史文化管制 | 文保单位/历史建筑管控 |

### 6.2 实现状态

管制规则模板生成 **`[PLANNED]`** 未实现。当前系统只产出空间布局成果（一图），不产出管制规则文本（一规则）。

---

## 7. 官方标准对齐

| 标准 | 系统对齐 | 实现状态 |
|------|----------|----------|
| 自然资发〔2023〕234号 | 用地用海分类编码（YDYHFL） | `[IMPLEMENTED]` 编码映射 |
| GB/T 21010-2017 | 三调国标编码体系 | `[IMPLEMENTED]` 编码映射；KB `04 技术规范/01 国家层面/04` |
| GB/T 13923-2022 | 10位数字层次码（YSDM） | `[IMPLEMENTED]` gdb.py _default_ysdm |
| DB14/T 2979-2024 | 数据库内容/要素分类/分层 | `[IMPLEMENTED]` GDB_LAYER_REGISTRY 12层 |
| 广东省村庄规划编制指引 | 四阶段工作流/一图一表一规则 | `[PARTIAL]` 一图一表已实现，一规则 PLANNED |
| DB4407/T 105-2023 | 6大类管制规则模板 | `[PLANNED]` 未实现 |
| 住建部(2014) | V/N/E 三分类 | `[IMPLEMENTED]` 编码映射 |
| 三区三线 | 生态/农业/建设空间 + 三线边界 | `[IMPLEMENTED]` KG 三区三线查询 |

### 7.1 知识库已入库标准

MinerU 精准解析入库（2026-08-01），源 PDF 与 .md 全文本+JSON 同步归档：

| 标准号 | KB 路径 | RAG 路径 | 来源 | 模型 |
|---|---|---|---|---|
| GB/T 21010-2017 土地利用现状分类 | `04 技术规范/01 国家层面/04` | `data/RAG_doc/_doc_md/04_技术规范/01_国家层面/GB-T 21010-2017 土地利用现状分类_minerU_parsed.md` | openstd（替换原扫描版） | pipeline |
| TD/T 1027-2010 县级土地利用总体规划数据库标准 | `04 技术规范/01 国家层面/07` | 同上/.../TD-T 1027-2010 县级土地利用总体规划数据库标准_minerU_parsed.md | nrsis | vlm+OCR |
| TD/T 1057-2020 国土调查数据库标准 | `04 技术规范/01 国家层面/08` | 同上/.../TD-T 1057-2020 国土调查数据库标准_minerU_parsed.md | nrsis | vlm+OCR |
| TD/T 1055-2019 第三次全国国土调查技术规程 | `04 技术规范/01 国家层面/09` | 同上/.../TD-T 1055-2019 第三次全国国土调查技术规程_minerU_parsed.md | nrsis | vlm+OCR |
| TD/T 1032-2011 基本农田划定技术规程 | `04 技术规范/01 国家层面/10` | 同上/.../TD-T 1032-2011 基本农田划定技术规程_minerU_parsed.md | nrsis | vlm+OCR |
| GB/T 43214-2023 省级国土空间规划编制技术规程 | `04 技术规范/01 国家层面/11` | 同上/.../GB-T 43214-2023 省级国土空间规划编制技术规程_minerU_parsed.md | openstd | pipeline |
| GB/T 39972-2021 一张图 实施监督信息系统技术规范 | `04 技术规范/01 国家层面/12` | 同上/.../GB-T 39972-2021 ..._minerU_parsed.md | openstd | pipeline |
| 国土调查数据库标准（试行修订稿） | `04 技术规范/01 国家层面/13` | 同上/.../国土调查数据库标准_minerU_parsed.md | 用户 | pipeline |
| 广东省县级国土空间总体规划数据库标准（试行） | `04 技术规范/02 地方层面/01 广东省/03` | `data/RAG_doc/_doc_md/04_技术规范/02_地方层面/01_广东省/广东省县级国土空间总体规划数据库标准_minerU_parsed.md` | 用户 | pipeline |

索引文件：`docs/RAG 知识库/01 索引/standards_index.md`。

### 7.2 知识库爬取脚本（可复用）

- `scripts/fetch_nrsis_standards.py` — 自然资源标准化平台（行业标准 TD/T/DZ/HY）
- `scripts/fetch_openstd_standards.py` — 国家标准全文公开系统（GB/GB/T/GB/Z）
- `scripts/parse_mineru.py` — MinerU 精准解析 v4（PDF/图片/Office → md+json）
- `scripts/ingest_standards.py` — 标准入库（KB 04 技术规范）

### 7.3 仍待补的标准（不入库决策）

- GB 50137-2011 城市用地分类与规划建设用地标准（工程建设标准，不在 openstd；需住建部标准全文公开）
- TD/T 1029-2010 开发区土地集约利用评价规程（与村庄规划无关）
- TD/T 1033-2012 高标准基本农田建设标准 / TD/T 1019-2009 基本农田数据库标准 / TD/T 1017-2008 二调基本农田调查技术规程（已被 1055 三调覆盖）
- TD/T 1083-2023 国土调查数据库更新数据规范（动态更新，不缓存）
- GB/T 21010-2007 土地利用现状分类（已被 2017 版替代）

---

## 8. 坐标系统

- **输出坐标系**: WGS84 (EPSG:4326)
- **转换位置**: Data 层（数据进入系统时统一转 WGS84）
- **面积单位**: 公顷（ha），DLMJ 字段为 m²，导出时转 ha
- **几何类型**: MultiPolygon / MultiLineString / Point

---

## 9. 导出与渲染流程

```
EXECUTE 产出 layout_configs (内部图层)
  │
  ▼
_export_gdb_node (layout_pipeline.py:243)
  │ 调用 export_gdb tool
  │ 按 INTERNAL_LAYER_TO_GDB_KEYS 映射到 12 GDB 层
  │ enrich_gdb_fields 补齐必填字段
  │ 导出 GeoPackage (.gpkg)
  │
  ▼
_render_map_node (layout_pipeline.py:256)
  │ 调用 render_map tool
  │ 按 colors.py 配色生成 MapLibre 图层
  │ 返回前端渲染数据
```

---

## 10. 实现状态总览

| 组件 | 状态 | 证据 |
|------|------|------|
| **GDB 12 层注册表** | `[IMPLEMENTED]` | gdb.py:61 GDB_LAYER_REGISTRY |
| GDB 命名规范 | `[IMPLEMENTED]` | gdb.py:43 make_gdb_layer_name |
| 内部图层 -> GDB 映射 | `[IMPLEMENTED]` | gdb.py:331 INTERNAL_LAYER_TO_GDB_KEYS |
| 字段富化 | `[IMPLEMENTED]` | gdb.py:444 enrich_gdb_fields |
| YSDM 默认值 | `[IMPLEMENTED]` | gdb.py:542 _default_ysdm |
| **编码体系** | | |
| 6 编码系统定义 | `[IMPLEMENTED]` | encodings/classification.py |
| 13 映射文件 | `[IMPLEMENTED]` | encodings/dicts/mappings/*.yaml |
| code_sets 用地类型集 | `[IMPLEMENTED]` | encodings/code_sets.py |
| DictionaryCenter 加载 | `[IMPLEMENTED]` | encodings/dicts/loader.py |
| **国标配色** | `[IMPLEMENTED]` | colors.py (单一真相源) |
| 功能区配色(8类) | `[IMPLEMENTED]` | colors.py:14 ZONE_TYPE_COLORS |
| 规划分区配色(6类) | `[IMPLEMENTED]` | colors.py:50 PLANNING_ZONE_COLORS |
| 空间管制区配色(4类) | `[IMPLEMENTED]` | colors.py:104 SPACE_CONTROL_COLORS |
| 设施配色 | `[IMPLEMENTED]` | colors.py:36 FACILITY_TYPE_COLORS |
| **用地指标表** | `[IMPLEMENTED]` | metrics.py |
| 面积聚合 | `[IMPLEMENTED]` | metrics.py:54 _dlbm_areas |
| 建设用地识别 | `[IMPLEMENTED]` | metrics.py:29 CONSTRUCTION_DLBM_CODES |
| **导出与渲染** | | |
| export_gdb 节点 | `[IMPLEMENTED]` | layout_pipeline.py:243 |
| render_map 节点 | `[IMPLEMENTED]` | layout_pipeline.py:256 |
| **管制规则** | `[PLANNED]` | DB4407/T 105-2023 6大类未实现 |
| **坐标系统** | `[IMPLEMENTED]` | WGS84 (EPSG:4326)，Data 层转换 |
| **标准对齐** | | |
| 自然资发〔2023〕234号 | `[IMPLEMENTED]` | YDYHFL 编码 |
| GB/T 21010-2017 | `[IMPLEMENTED]` | 编码映射 |
| DB14/T 2979-2024 | `[IMPLEMENTED]` | GDB 12层 |
| 广东省村庄规划编制指引 | `[PARTIAL]` | 一图一表已实现，一规则 PLANNED |
| DB4407/T 105-2023 | `[PLANNED]` | 管制规则未实现 |
