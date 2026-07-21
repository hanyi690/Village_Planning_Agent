/金田村 GIS 数据说明

数据来源：`docs/references/村庄规划总图/金田村村庄规划工程文件.zip`
解压后包含 3 个子目录，各有独立的 GDB + MXD 工程。

数据已迁移至 `data/gis/jintian/`，详见 `data/gis/jintian/metadata.json`。

---

## 一、源数据结构

```
金田村村庄规划工程文件/
├── 1.村庄用地现状图/
│   ├── 图层.gdb          ← 现状 GDB
│   └── 村庄用地现状图.mxd
├── 2.村庄规划总图/
│   ├── 图层.gdb          ← 规划 GDB
│   └── 村庄规划总图.mxd
└── 3.村庄建设项目布局规划图/
    ├── 03金田村建设项目布局规划图.dwg        ← AutoCAD 原始工程
    └── ImageToStl.com_03金田村...布局规划图.dxf  ← DXF 转换产物
```

### 1.1 三部分与 data/gis/jintian/ 的对应关系

| 工程文件部分 | 格式 | 导出目标 | 是否标准 | 说明 |
|-------------|------|---------|---------|------|
| 1.村庄用地现状图 | ArcGIS GDB | `current/` | ✅ 标准 | 完整字段、规范编码、符合广东省技术规范 |
| 2.村庄规划总图 | ArcGIS GDB | `planned/` | ✅ 标准 | 完整字段、规范编码、符合广东省技术规范 |
| 3.建设项目布局规划图 | AutoCAD DWG/DXF | `project/` + `reference/` | ❌ 非标准 | CAD 实体无属性、无编码字段（详见 §2.3） |

> **规范定位**：广东省技术指南规定基本成果为"一图一表一规则"（总图+项目表+管制规则），1、2 两部分对应"一图"的数据库，第 3 部分属于可选丰富成果。当前系统已实现 1、2 的自动生成，第 3 部分的自动生成列为 P2 设计目标（详见 OUTPUT_ARCHITECTURE.md §6.1）。

## 二、GDB 图层与字段

### 2.1 现状 GDB（1.村庄用地现状图/图层.gdb）

| GDB 图层名                             | 导出文件                            | 几何                   | 要素数        | 核心字段                                  |
| -------------------------------------- | ----------------------------------- | ---------------------- | ------------- | ----------------------------------------- |
| JT_行政区划_PBL_20220925               | current/boundary.geojson            | MultiPolygon           | 1             | BSM, YSDM                                 |
| PY_行政区划界线_LJJ_20220925           | current/admin_boundary_line.geojson | MultiLineString        | 561           | BSM, YSDM                                 |
| **JT_现状地类图斑_LJJ_20221018** | **current/landuse.geojson**   | **MultiPolygon** | **660** | **BSM, YSDM, DLBM, DLMC, DLMJ, BZ** |
| JT_农村居民点外道路_LJJ_202201004      | current/road.geojson                | MultiLineString        | 131           | Shape_Length                              |
| JT_现状注记_LJJ_20221216               | current/annotation.geojson          | Point                  | 34            | BSM, YSDM                                 |

### 2.2 规划 GDB（2.村庄规划总图/图层.gdb）

| GDB 图层名                           | 导出文件                                 | 几何                   | 要素数        | 核心字段                                                                                                   |
| ------------------------------------ | ---------------------------------------- | ---------------------- | ------------- | ---------------------------------------------------------------------------------------------------------- |
| JT_行政区划_PBL_20220925             | planned/boundary.geojson                 | MultiPolygon           | 1             | BSM, YSDM                                                                                                  |
| **JT_期末地类_LJJ_20221212**   | **planned/landuse.geojson**        | **MultiPolygon** | **582** | **BSM, YSDM, DLBM, GHYTBM, GHYTMC, GHFLBM, QMDLBM, QMGHFLBM, DLMJ, XZQHDM, XZQHMC, TBH, MS, LYYSDM** |
| JT_农村居民点外道路_LJJ_20221108     | planned/road.geojson                     | MultiLineString        | 170           | Shape_Length                                                                                               |
| JT_注记_LJJ_20221216                 | planned/annotation.geojson               | Point                  | 71            | BSM, YSDM                                                                                                  |
| JT_地质灾害点_LJJ_20221212           | planned/geological_hazard_points.geojson | Point                  | 40            | 名称, 纬度, 经度, 类型, 大小                                                                               |
| JT_有条件建设区_LJJ_20221212         | planned/construction_zone.geojson        | MultiPolygon           | 139           | BSM, YSDM, BH, XZQHDM, XZQHM, LX, MJ                                                                       |
| JT_永久基本农田保护红线_LJJ_20221212 | planned/farmland_protection.geojson      | MultiPolygon           | 88            | YSDM, XZQHDM, XZQHMC, BSM, JBNT_MJ                                                                         |
| JT_生态保护红线_LJJ_20221212         | planned/ecological_protection.geojson    | MultiPolygon           | 5             | OBJECTID, 区县, 地市, MJ                                                                                   |
| JT_历史文化保护线_LJJ_20221212       | planned/historical_protection.geojson    | MultiPolygon           | 3             | BUFF_DIST, ORIG_FID                                                                                        |

### 2.3 DXF 项目数据（3.村庄建设项目布局规划图 → project/ + reference/）

DXF 转换后提取为 GeoJSON，存放在 `data/gis/jintian/project/`。与 GDB 数据不同，DXF 图层是 CAD 制图概念（图形+图层名），不携带属性编码。

**project/ 文件内容**：

| 文件 | 要素数 | 图层 | 说明 |
|------|--------|------|------|
| polygons.geojson | 945 | 房屋(723), 基本农田(91), 图例(72), 建设项目红线(24), 保留公服(15), TX-图框(8), 新增公服(7), 污水处理池(4), 村界(1) | 仅 `layer`+`type` 两个属性 |
| lines.geojson | 138 | 引线(63), TX-图框(31), 规划道路(24), 新增公服(10), 建设项目红线(5), 图例(4), 保留公服(1) | 仅 `layer`+`type` |
| annotation.geojson | 78 | TX-图框, 图例 | 含 `text` 字段（46 个建设项目名称） |
| points.geojson | 0 | — | 空 |

**reference/ 文件内容**：

| 文件 | 说明 |
|------|------|
| convert.script | LibreCAD DWG→DXF 转换脚本 |
| project_layout.svg | 布局规划图渲染产物（含图例、标注） |
| project_layout_clean.svg | 去除背景的清洁版 |

**与标准 GDB 数据的核心差异**：

| 维度 | current/planned (标准) | project (非标准) |
|------|----------------------|-----------------|
| 源格式 | ArcGIS File GDB | AutoCAD DWG/DXF |
| 数据模型 | 要素类 (Feature Class)，有严格字段定义 | CAD 实体 (Entity)，无属性表 |
| 属性结构 | BSM/YSDM/DLBM/GHYTBM 等规范字段 | 仅有 `layer`（图层名）和 `type`（几何类型） |
| 编码体系 | 附录5/土规/GB/T 21010 编码 | 无编码，仅有中文图层名 |
| 用途 | 规划计算引擎的正规输入 | 可视化参考 + 布局图生成的 ground truth |

> **annotation 中的项目名称**是规划师人工标注的建设项目，如"田园民宿"、"南药科普体验园"、"污水处理池"等，对应近期建设项目表中的具体项目。这些名称与 PARSE Agent 解析出的 `SpatialOperation.project_name` 语义等价。

---

## 三、导出缺漏分析

### 3.1 现状地类图斑：缺 GHYTBM / GHFLBM / GHYTMC

**现象**：`current/landuse.geojson` 只有 8 个字段（BSM, BZ, DLBM, DLMC, DLMJ, SHAPE_Area, SHAPE_Length, YSDM），而规划层有 16 个字段。

**原因**：这是**正常现象**，不是导出缺漏。

根据各省村庄规划数据库标准（云南省 DB14/T 2979-2024、湖南省 DB43/T 3555-2026 等）：

- **现状用地（JQXZYD / XZYD）** 的标准字段 = BSM + YSDM + XZQDM + XZQMC + TBBH + DLBM + DLMC + TBMJ + TBDLMJ + SDDLBM + SDDLMC + BZ
- **规划地类图斑（GHDLTB）** 的标准字段 = BSM + YSDM + XZQDM + XZQMC + **GHDLBM** + **GHDLMC** + TBDLMJ + JYXYD + ...

**关键区别**：

- 现状层用地 DLBM 编码，**不包含规划编码字段**
- 规划层用 GHFLBM/GHYTBM 编码，同时保留 DLBM/QMDLBM 作为规划前后对照

## 编码体系说明

现状层和规划层的 DLBM 字段使用**不同的编码体系**（GDB 原始数据如此，非导出问题）：

| 图层 | 字段 | 编码体系 | 示例 |
|------|------|---------|------|
| 现状层 | DLBM | **附录5** (规划用途编码) | 2121=宅基地, 1100=耕地 |
| 规划层 | DLBM | **土规数据库标准** | 2030=农村居民点, 0110=水田 |
| 规划层 | QMDLBM | **土规数据库标准** | 2030, 0310 |
| 规划层 | GHYTBM | **附录5** | 2121=宅基地 |

> 四个编码体系独立定义，见 `backend/app/modules/gis/schema/dicts/`:
> `gbt21010.yaml` (GB/T 21010-2017), `tugui.yaml` (广东省土规数据库标准),
> `appendix5.yaml` (广东省技术指南附录5), `ydyhfldm.yaml` (用地用海分类)

### 3.2 现状地类图斑：SDDLBM / SDDLMC 字段

**现象**：GeoJSON 中已有 SDDLBM 和 SDDLMC 字段，但 GDB 原始数据中不存在。

**原因**：导出时从 DLBM/DLMC 复制生成。值的内容是附录5编码而非 GB/T 21010三调编码。SDDLBM = DLBM（均为附录5）。

**影响**：无。项目代码已确认现状层 DLBM 使用的编码体系为附录5，不依赖 SDDLBM 做基数转换。

### 3.3 现状地类图斑：缺 YDYHFLDM / YDYHFLMC（用地用海分类代码）

**现象**：新标准（234号文之后）的村庄规划数据库要求现状用地同时填写 YDYHFLDM + YDYHFLMC。

**原因**：金田村规划编制于 2022 年，早于 234 号文正式实施，GDB 中可能本就没有此字段。这属于**数据时代差异**，不是导出缺漏。

### 3.4 规划地类图斑：80 个要素 GHFLBM 为空

**现象**：`planned/landuse.geojson` 中 80/582 个要素的 GHFLBM 字段为空字符串。

**原因**：可能是 GDB 原始数据中这些图斑未填写 GHFLBM。GHFLBM 是比 GHYTBM 更粗的规划大类编码，部分小图斑可能只填了 GHYTBM 而未填 GHFLBM。

**影响**：可通过 GHFLBM_TO_GHYTBMS 反向映射补全。

### 3.5 规划地类图斑：DLMC 缺失

**现象**：规划层 16 个字段中没有 DLMC（地类名称），而现状层有。

**原因**：规划层用 GHYTMC 代替了 DLMC。规划层的 DLBM 是基期地类编码（0310=乔木林地），而 GHYTMC 才是规划用途名称（商品林）。这是**正常设计**——规划层关注规划分类而非现状分类。

---

## 四、导出方式与已知问题

### 4.1 导出方式

数据从 GDB 导出为 GeoJSON 的可能方式：

| 方式                        | 命令/操作                                            | 特点                                                     |
| --------------------------- | ---------------------------------------------------- | -------------------------------------------------------- |
| **ArcGIS 要素转JSON** | `arcpy.conversion.FeaturesToJSON`                  | **仅导出可见字段**，需提前在图层属性中显示所有字段 |
| **ogr2ogr**           | `ogr2ogr -f GeoJSON out.geojson in.gdb layer_name` | 导出所有字段，但中文编码需指定 UTF-8                     |
| **QGIS 右键导出**     | 右键图层→导出→保存要素为                           | 灵活但手动操作                                           |

### 4.2 已知编码问题

- **DLBM 尾部空格**：`current/landuse.geojson` 中 DLBM="2122 " 有尾部空格（1个要素），代码中已做 `.strip()` 处理
- **DLMC 编码**：导出文件为 UTF-8 编码，读取正常
- **Shape_Area vs SHAPE_Area**：现状层用 `SHAPE_Area`，规划层用 `Shape_Area`，字段名大小写不一致

### 4.3 建议的重新导出方法

如果需要重新从 GDB 导出更完整的数据，推荐使用 `ogr2ogr`：

```bash
# 安装 GDAL (conda 或 pip)
conda install -c conda-forge gdal

# 导出单个图层（保留所有字段，UTF-8 编码）
ogr2ogr -f "GeoJSON" \
  -dsco COORDINATE_PRECISION=15 \
  -lco RFC7946=YES \
  -lco WRITE_BBOX=YES \
  current_landuse.geojson \
  "1.村庄用地现状图/图层.gdb" \
  "JT_现状地类图斑_LJJ_20221018"

# 导出所有图层
ogr2ogr -f "GeoJSON" \
  output_dir/ \
  "图层.gdb"
```

**ogr2ogr 优势**：

- 导出所有字段（不受 ArcGIS "仅可见字段" 限制）
- 自动处理 CGCS2000 → WGS84 坐标转换
- UTF-8 编码，中文无乱码
- 坐标精度可控（COORDINATE_PRECISION=15）

**ArcGIS 要素转JSON 注意事项**：

- 必须在 ArcMap/ArcGIS Pro 中先打开图层属性→字段→勾选所有字段为可见
- 或使用字段映射参数显式指定要导出的字段
- `outputToWGS84=GEOJSON` 自动转 WGS84

---

## 五、编码覆盖情况

### 5.1 现状层 DLBM（16 个唯一值）

| DLBM | 含义             | 要素数 | zone_type    |
| ---- | ---------------- | ------ | ------------ |
| 1100 | 耕地             | 175    | 农业用地     |
| 1200 | 园地             | 21     | 农业用地     |
| 1340 | 商品林           | 115    | 生态绿地     |
| 1350 | 生态林           | 17     | 生态绿地     |
| 1400 | 草地             | 21     | 生态绿地     |
| 1510 | 设施农用地       | 5      | 农业用地     |
| 2121 | 宅基地           | 132    | 居住用地     |
| 2122 | 公共服务设施用地 | 19     | 公共服务用地 |
| 2124 | 经营性建设用地   | 28     | 产业用地     |
| 2125 | 景观与绿化用地   | 4      | 公共服务用地 |
| 2126 | 村内交通用地     | 48     | 交通用地     |
| 2200 | 对外交通用地     | 16     | 交通用地     |
| 2270 | 水利设施用地     | 9      | 农业用地     |
| 3100 | 水域             | 48     | 水域         |
| 3200 | 自然保留地       | 2      | 农业用地     |

**覆盖率**：16/16 = 100%（所有现状 DLBM 均有 zone_type 映射）

### 5.2 规划层 GHYTBM（15 个唯一值）

| GHYTBM | 含义             | 要素数 | zone_type    | V/N/E |
| ------ | ---------------- | ------ | ------------ | ----- |
| 1100   | 耕地             | 170    | 农业用地     | E23   |
| 1200   | 园地             | 11     | 农业用地     | E23   |
| 1340   | 商品林           | 115    | 生态绿地     | E23   |
| 1350   | 生态林           | 26     | 生态绿地     | E23   |
| 1500   | 其他农用地       | 2      | 农业用地     | E23   |
| 1510   | 设施农用地       | 4      | 农业用地     | E21   |
| 2121   | 宅基地           | 86     | 居住用地     | V11   |
| 2122   | 公共服务设施用地 | 18     | 公共服务用地 | V21   |
| 2123   | 基础设施用地     | 16     | 交通用地     | V43   |
| 2124   | 经营性建设用地   | 20     | 产业用地     | V31   |
| 2125   | 景观与绿化用地   | 11     | 公共服务用地 | V22   |
| 2126   | 村内交通用地     | 67     | 交通用地     | V41   |
| 2200   | 对外交通用地     | 10     | 交通用地     | N1    |
| 2270   | 水利设施用地     | 8      | 农业用地     | E12   |
| 3100   | 水域             | 18     | 水域         | E11   |

**覆盖率**：15/15 = 100%（所有规划 GHYTBM 均有 zone_type + V/N/E 映射）

### 5.3 规划层 GHFLBM（11 个唯一值 + 80 空）

| GHFLBM | 含义               | 要素数 | zone_type        |
| ------ | ------------------ | ------ | ---------------- |
| 1110   | 耕地(规划)         | 130    | 农业用地         |
| 1120   | 园地(规划)         | 2      | 农业用地         |
| 1130   | 林地(规划)         | 31     | 生态绿地         |
| 1200   | 草地(规划)         | 11     | 生态绿地         |
| 1310   | 商品林(规划)       | 102    | 生态绿地         |
| 1330   | 生态林(规划)       | 11     | 生态绿地         |
| 1520   | 设施农用地(规划)   | 1      | 农业用地         |
| 1530   | 其他农用地(规划)   | 2      | 农业用地         |
| 2120   | 农村建设用地(规划) | 193    | 居住用地         |
| 2270   | 水利设施用地(规划) | 8      | 农业用地         |
| 3110   | 水域(规划)         | 11     | 水域             |
| (空)   | 未填写             | 80     | 通过 GHYTBM 反查 |

**覆盖率**：11/11 = 100%（非空值全覆盖）

---

## 六、缺漏修复建议

| 优先级 | 问题                    | 修复方案                                                                   |
| ------ | ----------------------- | -------------------------------------------------------------------------- |
| P1     | 80 个要素 GHFLBM 为空   | 通过 GHYTBM→GHFLBM 反向映射自动补全（GHFLBM_TO_GHYTBMS 反查）             |
| P1     | 现状层缺 SDDLBM 字段    | 用 ogr2ogr 重新导出 GDB 验证是否原 GDB 有此字段；若无，DLBM≈SDDLBM 可替代 |
| P2     | DLBM 尾部空格           | 数据清洗时统一`.strip()`（代码已处理）                                   |
| P2     | Shape_Area 大小写不一致 | 统一为`Shape_Area`（GeoJSON 属性键）                                     |
| P3     | 现状层缺 YDYHFLDM       | 通过`convert_sddlbm_to_ydyhfldm()` 基数转换函数补全                      |
| P3     | 缺少村庄建设边界图层    | GDB 原文件可能未包含，需确认原始工程是否有 JT_村庄建设边界 图层            |

---

## 七、Schema 参考

Schema 子包的完整技术文档见 [SCHEMA_REFERENCE.md](SCHEMA_REFERENCE.md)，涵盖：

- 三大正交编码体系 (DLBM/GHYTBM, YDYHFLDM, V/N/E) 的设计原理与互转
- DictionaryCenter YAML 字典中心的 13 个字典详解
- 14 层 GDB 输出架构与广东省规范要求的 4 个必出图层
- QMDLTB 期末地类图斑 20 必填字段与 JSYDGZQ 管制区编码
- 动态分区引擎决策规则与双评价指南对应
- 省级扩展指南

---

## 八、参考标准

| 标准                           | 用途                             | 说明                   |
| ------------------------------ | -------------------------------- | ---------------------- |
| GB/T 21010-2017                | 现状地类编码                     | DLBM 编码体系          |
| 三调工作分类                   | 村庄规划专用编码                 | 2121-2126 等 21xx 编码 |
| 自然资发〔2023〕234号          | 用地用海分类代码                 | YDYHFLDM，基数转换目标 |
| 住建部《村庄规划用地分类指南》 | V/N/E 分类                       | 前端统计口径           |
| DB14/T 2979-2024               | 山西省村庄规划数据库规范         | 字段结构参考           |
| DB43/T 3555-2026               | 湖南省乡镇国土空间规划数据库规范 | 字段结构参考           |
| 云南省村庄规划数据库标准       | 字段结构参考                     | JQXZYD/GHDLTB 标准字段 |
| DB61/T 1852-2024               | 陕西基数转换规范                 | SDDLBM→YDYHFLDM 参考  |
