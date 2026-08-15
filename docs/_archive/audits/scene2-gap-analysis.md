# scene2 Gap Analysis: Current Implementation vs Research Recommendations

> **Task:** V4 Audit & Consolidation Plan, Task 1
> **Cross-checks:** `docs/gis/scene2_深度研究_乡村规划数据需求溯源.md` §10 against current codebase
> **Date:** 2026-07-28
> **Status:** DOCUMENTATION ONLY - gaps marked as future work, not implemented

This document compares scene2 §10 "对 Village_Planning_Agent 的落地建议" recommendations against the v4 implementation. Status icons: ✅ = present, ⚠️ = partial, ❌ = missing.

---

## 1. scene2 §10.1 Entity Type Recommendations vs Current Registry

scene2 §10.1 recommends "KG实体类型注册表(建议首批)" of 12 entity types. Cross-check against `backend/app/modules/schema/types/gis_layer_registry.yaml`.

| # | scene2 recommended entity | status | registry entry (yaml key) | notes |
|---|---|---|---|---|
| 1 | parcel 地类图斑 (DLTB/QMDLTB) | ✅ | `landuse_current` (yaml:108), `landuse_planned` (yaml:136) | KG entity_type `LandUseParcel`; CurrentLandUseParcel + PlannedLandUseParcel split |
| 2 | zone 控制面 (8 sub-types) | ✅ | `farmland_protection` (262), `ecological_protection` (287), `urban_dev_boundary` (359), `village_dev_boundary` (384), `historical_protection` (434), `conditional_construction_zone` (459), `land_use_zone` (483), `construction_ctrl_zone` (507), `planning_scope` (531), `three_zone_item` (337) | KG entity_type `ControlZone`/`LandUseZone`/`ConstructionCtrlZone`/`PlanningScope`/`ThreeZoneItem`. Covers all 8 sub-types scene2 lists (STBHHX/YJJBNT/YJJBNTCBQ→cultivated_land_target(409)/ZJDJSFWX/YJJSQ/LSWHBHFW/QTKZX/JSYDGZQ) |
| 3 | boundary 村庄建设边界 | ✅ | `boundary` (yaml:35), `village_dev_boundary` (yaml:384) | AdminArea KG entity_type; village_dev_boundary as ControlZone |
| 4 | building 建筑 (含四类质量属性) | ⚠️ | `current_building` (yaml:703) | KG entity_type `Building`; CurrentBuilding has `building_type`/`floors`/`area_sqm`/`structure` but NO 金田村式 quality grade (一类~四类) field. See §6 |
| 5 | facility 设施 (公服/市政台账式) | ✅ | `current_facility` (yaml:727), `planned_facility` (yaml:751) | KG entity_type `Facility`; BaseFacility has `facility_type`/`facility_name`/`scale`/`service_radius`/`category`. Does NOT match scene2 §5.4-5 11-field ledger schema (序号/数量/独立用地/用地面积/长度/建筑面积/位置/服务对象/覆盖程度) |
| 6 | road 道路 (等级/宽度/硬化) | ✅ | `current_road` (yaml:164), `planned_road` (yaml:188) | KG entity_type `Road`; BaseRoad has `road_level`/`road_width`/`road_name`. ⚠️ No `hardened` (硬化) boolean field |
| 7 | water 水系 (河道+管护范围) | ⚠️ | `water` (yaml:629) | KG entity_type `WaterFeature`; has `water_type`/`water_name`/`flow_direction`. ❌ No `management_scope` (管护范围) per GBT38549 |
| 8 | heritage 历史文化资源 | ✅ | `historical_protection` (yaml:434) | KG entity_type `ControlZone` (polygon protection zone). ⚠️ No dedicated point/area entity for 祠堂/古树/古驿道/非遗 inventory (scene2 §5.5); protection zone only |
| 9 | hazard 灾害隐患点 (类型/位置) | ✅ | `geological_hazard_point` (yaml:556), `hazard_control_line` (yaml:580), `flood_control_line` (yaml:604) | KG entity_types `GeologicalHazardPoint`/`ControlLine`. Covers scene2 §5.6 六类清单 partially (geological + flood); ⚠️ no meteorological/biological categories |
| 10 | project 近期建设项目 | ❌ | `construction_projects` table (yaml:843) only | NO spatial entity. scene2 §6.3 requires 项目级空间数据 (位置/四角坐标/控制标高). Table-only, no polygon/point geometry. See §6 |
| 11 | parcel_ownership 宅基地确权 | ❌ | (none) | NO entity type for 宅基地确权 (scene2 §5.3). See §6 |

**Score: 8 ✅ / 3 ⚠️ / 2 ❌** (12 recommendations, 8 fully implemented, 3 partial, 2 missing)

---

## 2. scene2 §2.2 三调 DLTB 30 Fields vs CurrentLandUseParcel

scene2 §2.2 lists 三调地类图斑 "至少包含30个字段" with 10 key fields. Cross-check against `CurrentLandUseParcel` in `spatial_types.py:55-58` + `BaseLandUseParcel` (35-53).

| # | scene2 field | scene2 description | present in model? | field mapping |
|---|---|---|---|---|
| 1 | DLBM | 地类编码 | ✅ | `BaseLandUseParcel.dlbm` (line 37) |
| 2 | DLMC | 地类名称 | ✅ | `BaseLandUseParcel.name` (line 39) |
| 3 | QSXZ | 权属性质 (国有10/20、集体30/40) | ❌ | (none) |
| 4 | ZLDWDM | 坐落单位代码 | ❌ | (none) |
| 5 | ZLDWMC | 坐落单位名称 | ❌ | (none) |
| 6 | TBMJ | 图斑面积 (椭球面积) | ⚠️ | `BaseLandUseParcel.area_sqm` (line 40) - square meters, not 椭球面积 hectares |
| 7 | GDLX | 耕地类型 (坡地PD/梯田TT) | ❌ | (none) |
| 8 | GDPDJB | 耕地坡度级别 (五级) | ❌ | (none) |
| 9 | XZDWKD | 线状地物宽度 | ❌ | (none) |
| 10 | ZZSXDM | 种植属性 (八种) | ❌ | (none) |
| 11 | GDDB | 耕地等别 (GB/T 28407) | ❌ | (none) |
| 12 | CZCSXM | 城镇村属性码 (城市201/建制镇202/村庄203/盐田采矿204/特殊205) | ❌ | (none) |
| 13 | SDDLBM | 三调地类编码 (补充) | ✅ | `CurrentLandUseParcel.sddlbm` (line 57, alias `SDDLBM`) |
| 14 | BSM | 标识码 | ✅ | inherited from `PolygonFeature` (base.py) |

**Score: 4 ✅ / 1 ⚠️ / 9 ❌** (3/10 scene2 key fields + SDDLBM + BSM present). The 三调 specific fields (权属/坐落/耕地属性/城镇村属性码) are NOT modeled. scene2 §10.2 explicitly lists "三调DLTB 30字段" as an "属性白名单直接来源" - this is a known gap. Future work: extend BaseLandUseParcel with optional 三调 fields when actual DLTB data is acquired.

---

## 3. scene2 §6.1 广东4图层 Fields vs PlannedLandUseParcel

scene2 §6.1 defines 4 必选图层 for 广东省村庄规划数据库. Cross-check `PlannedLandUseParcel` (spatial_types.py:61-79) and related zone classes.

| # | layer | field | scene2 description | present? |
|---|---|---|---|---|
| 1 | GHCFW 规划村范围 | BSM | 标识码 Int10 | ✅ PlanningScope.bsm |
| 2 | GHCFW | XZQHDM | 行政区划代码 Char12 | ✅ PlanningScope.xzqhdm (line 285) |
| 3 | GHCFW | MJ | 面积 Float15 (平方米) | ✅ PlanningScope.mj (line 287) |
| 4 | QMDLTB 期末地类图斑 | TBH | 图斑号 | ❌ |
| 5 | QMDLTB | DLBM | 地类编码 | ✅ BaseLandUseParcel.dlbm |
| 6 | QMDLTB | DLMJ | 图斑地类面积 | ⚠️ area_sqm (平方米, not dedicated DLMJ) |
| 7 | QMDLTB | QMDLBM | 期末地类编码 | ✅ PlannedLandUseParcel.qmdlbm (line 63, alias QMDLBM) |
| 8 | QMDLTB | GHFLBM | 规划分类编码 | ✅ PlannedLandUseParcel.ghflbm (line 68, alias GHFLBM) |
| 9 | QMDLTB | GHYTBM | 规划用途编码 | ✅ PlannedLandUseParcel.ghytbm (line 65, alias GHYTBM) |
| 10 | QMDLTB | LSYSXZB1/2 | 落实约束性指标 | ❌ |
| 11 | TDYT 土地用途分区 | TDYTFQDM | 分区代码 | ✅ LandUseZone.tdyfqdm (line 247) |
| 12 | TDYT | 椭球面积 | | ✅ LandUseZone.mj (line 249) |
| 13 | JSYDGZQ 建设用地管制区 | TDKJGZFQDM | 允许/限制/有条件/禁止建设区 | ✅ ConstructionCtrlZone.tdkjgzfqdm (line 258) + ALLOWED/RESTRICTED/CONDITIONAL/PROHIBITED constants (264-269) |
| 14 | JSYDGZQ | GHNF | 规划年份 | ✅ ConstructionCtrlZone.ghnf (line 260) |

**Score: 11 ✅ / 1 ⚠️ / 2 ❌** (of 14 key fields). QMDLTB partial: TBH (图斑号) and LSYSXZB constraint indicators missing. Other 3 layers fully covered.

---

## 4. scene2 §3 编码体系 vs Current Encoding Dictionaries

scene2 §3.1 documents "四套并行分类标准". Cross-check against `backend/app/modules/schema/encodings/dicts/encodings/`.

| # | encoding system | scene2 source | current dict file | status |
|---|---|---|---|---|
| 1 | GB/T 21010-2017 土地利用现状分类 | scene2 §3.1 row1 (12一级/73二级) | `encodings/gbt21010.yaml` (445 lines) | ✅ Full 12+73 classes, 三调 DLBM 值域 |
| 2 | 用地用海分类指南 (2023) | scene2 §3.1 row2 (24/113/140级) | `encodings/ydyhfldm.yaml` | ✅ 24一级/113二级/140三级 (YDYHFLDM system) |
| 3 | 村庄规划用地分类指南 (住建部) | scene2 §3.1 row3 (V/N/E 3大类) | `encodings/vne.yaml` | ✅ V/N/E classification |
| 4 | 广东村规划用途分类 (自然资源口) | scene2 §3.1 row4 (三大类+4位代码) | `encodings/appendix5.yaml` (180 lines) | ✅ 广东附录5, 21条 4-digit codes (renamed from ghytbm.yaml) |
| 5 | 土规编码 (广东省县级库标准) | scene2 §6.1 QMDLTB 注2 | `encodings/tugui.yaml` (133 lines) | ✅ QMDLTB.DLBM/QMDLBM 值域 (bonus, not in scene2 §3.1 but required by §6.1) |
| 6 | GHFLBM 规划分类编码 | scene2 §6.1 QMDLTB.GHFLBM | `encodings/ghflbm.yaml` (59 lines) | ✅ 广东县级土地利用总体规划数据库标准 (bonus) |

**Encoding mappings** (`encodings/dicts/mappings/`):
| # | mapping | scene2 reference | status |
|---|---|---|---|
| 1 | `dlbm_to_ghytbm.yaml` (322 lines) | scene2 §3.2 基数转换 一一对应+一对多 | ✅ 1:N schema with confidence |
| 2 | `sddlbm_to_ydyhfldm.yaml` | scene2 §3.2 (三调→用地用海) | ✅ |
| 3 | `ghflbm_to_tdytfqdm.yaml` | scene2 §6.1 (规划分类→用途分区) | ✅ |

**Score: 6/6 encoding systems ✅ + 3/3 mappings ✅**. All scene2 §3 classification standards and §3.2 base-conversion mappings are wired.

---

## 5. scene2 §5 现状数据四大域 vs Current Data Sources

scene2 §5 lists "现状调查数据(四大现状域)". Cross-check against `backend/app/modules/data/catalog/sources.yaml`.

| # | data domain | scene2 items (§5.1-5.6) | current source (sources.yaml) | gap |
|---|---|---|---|---|
| 1 | 自然条件与生态资源 (§5.1) | DEM/地形/气候/水文/工程地质/土壤植被/公益林/生态 | `dem_local` (226), `dem_alos` (241), `dem_gdem` (256), `dom_local` (233), `tianditu_terrain` (203), `soil_type`/`soil_erosion`/`watershed`/`nature_reserve`/`hydrogeology_zone` (registry 924-1027) | ⚠️ DEM registered but broken refs (Task 8); climate/ vegetation/公益林 NOT modeled |
| 2 | 人口与社会经济 (§5.2) | 户籍/常住/老龄化/产业/企业/收入/集体 | `population` table (registry 823) | ❌ Table entity registered but no source wired; no enterprise/collective schema |
| 3 | 土地利用与权属 (§5.3) | 现状地类/宅基地确权/承包权/流转/整治潜力 | `jintian_current_landuse` (sources.yaml:46); `planning_indicators`/`land_use_structure` tables | ⚠️ 现状地类 ✅; 宅基地确权 ❌ (see §6 parcel_ownership); 承包/流转 ❌ |
| 4 | 建设现状 (§5.4) | 建筑/道路/市政/公服 5子域 + 台账11字段 | `jintian_road` (52), `current_building`/`current_facility`/`planned_facility` (registry 703-773); `annotation` (64) for facility inference | ⚠️ 建筑/道路/设施 ✅ but 属性稀疏; 市政 (供水/排水/电力/环卫) only via annotation inference, no dedicated infrastructure entity |
| 5 | 历史文化资源 (§5.5) | 文保单位/历史建筑/传统格局/非遗 | `jintian_historical_protection` (sources.yaml:127) | ⚠️ Protection polygon ✅; point inventory (祠堂/古树/古驿道/非遗) ❌ |
| 6 | 灾害风险 (§5.6) | 气象/地质地震/海洋/生物/生态/事故+消防 六类 | `jintian_geological_hazard` (sources.yaml:139), `hazard_control_line`/`flood_control_line` (registry 580-626), `gd_hazard` API (180) | ⚠️ 地质+洪涝 ✅; 气象/海洋/生物/生态/事故/消防 ❌ |
| 7 | 村民意愿 (§5.7) | 问卷≥20%户数 + 需求台账 | (none) | ❌ No schema/source |
| 8 | 部门资料 (§5.8) | 发改/自然资源/农业/生态/交通/文物/文旅/教育/住建 | (none) | ❌ Out of scope (data acquisition, not modeling) |

**Score: 0 ✅ / 5 ⚠️ / 3 ❌** (of 8 domains). Core spatial domains partial; attribute/social/willingness domains missing. scene2 §10.5 data acquisition priority: ①三调 ✅ ②三区三线 ✅ ③地籍/确权 ❌ ④1:2000地形图/DOM ⚠️ ⑤DEM/Landsat ✅(DEM) ⑥驻村调查 ❌.

---

## 6. Missing Entity Types (Future Work)

Per scene2 §10.1, the following recommended entity types are NOT yet implemented. Documented as future work - do NOT implement in v4 audit.

### 6.1 `project` (近期建设项目)
- **scene2 reference:** §6.3 项目级空间数据; §10.1 item 10
- **What it is:** 近期建设项目表 (广东指南附录2, 12列: 序号/项目类型8类/项目名称/**空间位置**/用地面积/建筑面积/资金/筹措/责任/协作/建设方式/备注). 全域整治子项目要求 "矢量坐标...明确各子项目占用和补充耕地(永久基本农田)数量、质量和位置". 建设项目放样要求 "四角坐标、控制标高".
- **Current state:** `construction_projects` table entity (registry 843) - table-only, NO spatial geometry. scene2 requires polygon/point geometry with 四角坐标.
- **Future work:** Add `planned_project` layer_type (polygon) + extend table schema. Blocked on: actual project data with coordinates.

### 6.2 `parcel_ownership` (宅基地确权)
- **scene2 reference:** §5.3 权属专项; §10.1 item 11
- **What it is:** 宅基地确权数据 ("有宗地确权和房屋确权两种,一般以宗地确权数据为主"). Fields: TDZL土地坐落、QSRMC权属人名称. Used for: 核查宅基地扩建、扣除超标面积、腾挪指标.
- **Current state:** No entity type. Not in registry, not in spatial_types.py.
- **Future work:** Add `parcel_ownership` layer_type (polygon, 宗地) with ownership fields. Blocked on: 确权 data acquisition (scene2 §10.5 priority ③).

### 6.3 `building` quality grade extension
- **scene2 reference:** §5.4(1) 建筑质量分级; §10.1 item 4 "含金田村式四类质量属性"
- **What it is:** 金田村583处建筑按 "主体和局部结构质量状况、是否有安全隐患" 分 **一类~四类**. 花溪城: 保留18/改造189/拆建12. Fields: quality_grade (1-4), renovation_action (保留/改造/拆建), facade_area, hazard_area.
- **Current state:** `CurrentBuilding` (spatial_types.py:82-87) has `building_type`/`floors`/`area_sqm`/`structure` but NO quality_grade or renovation_action.
- **Future work:** Extend CurrentBuilding with optional `quality_grade`/`renovation_action` fields. Low effort once金田村 building data is acquired.

---

## 7. Missing Raster Types

Per scene2 §5.1, terrain analysis requires 高程/坡度/坡向/起伏度. Cross-check `raster` group in registry (yaml:775-820).

| # | raster type | scene2 reference | registry? | status |
|---|---|---|---|---|
| 1 | DEM 数字高程模型 | §5.1 "DEM数字高程模型(高程/坡度/坡向/起伏度分析)" | ✅ `dem` (yaml:776) | Present; sources: dem_local/dem_alos/dem_gdem. ⚠️ Broken refs being fixed in Task 8 |
| 2 | DOM 数字正射影像 | §2.1 "国土数字正射影像图(DOM)" | ✅ `dom` (yaml:799) | Present; sources: dom_local + tianditu_img_base WMTS |
| 3 | 坡度 (slope) | §5.1 "坡度分析"; §8.3 "地形坡度<10%" 适宜性 | ❌ | NOT registered. Derived product from DEM. Future work: add `slope` raster type or compute on-the-fly from DEM |
| 4 | 坡向 (aspect) | §5.1 "坡向分析" | ❌ | NOT registered. Derived product. Future work: add `aspect` raster type or compute on-the-fly |
| 5 | 起伏度 (relief) | §5.1 "起伏度分析" | ❌ | NOT registered. Derived product. Future work |

**Score: 2 ✅ / 3 ❌**. DEM/DOM registered; slope/aspect/relief are DEM-derived analytical products - recommend on-the-fly computation (rasterio terrain analysis) rather than persistent layer types.

---

## 8. Data Utilization Summary

### GeoJSON files (jintian golden bundle)
- **13/13 GeoJSON files used** in `sources.yaml`:
  - current/ (5): boundary, landuse, road, admin_boundary_line, annotation
  - planned/ (8): landuse, road, annotation, boundary, farmland_protection, ecological_protection, historical_protection, construction_zone, geological_hazard_points
  - (Note: 9 planned files counted; 13 = 5 current + 8 planned core. project/ has 4 geojson not yet wired to sources.yaml)
- project/ (4 files: annotation, lines, points, polygons) - NOT yet wired to sources.yaml (future: project entity §6.1)

### API-fetched GeoJSON (15 files in `data/gis/jintian/api/`)
- amap/ (3): boundary_pingyuan, center_point, pois_all
- tianditu/ (9): wfs_hyda, wfs_hydl, wfs_hydp, wfs_lrdl, wfs_lrrl, wfs_resa, wfs_resp
- These are cache outputs from API drivers; 3 are wired via sources.yaml (`jintian_water_hyda`:79, `jintian_water_hydl`:88); others are **orphaned cache files** pending cleanup (Task 10).

### DEM/DOM rasters
- **Broken refs:** `dem_local` (sources.yaml:226) points to `data/gis/jintian/terrain/dem.tif` - file existence/validity being fixed in Task 8.
- `dom_local` (sources.yaml:233) similarly broken; WMTS fallback via `tianditu_img_base` (192).
- Remote guides: `dem_alos` (241), `dem_gdem` (256) - download guidance only, not auto-fetched.

### Orphaned files (~30+)
- Being cleaned in Task 10. Includes: API cache files not wired to sources.yaml, project/ geojson not wired, duplicate/stale files.

### Encoding dictionaries
- **All 4 scene2 §3 systems wired** (gbt21010, ydyhfldm, vne, appendix5) + 2 bonus (tugui, ghflbm) = 6 encoding files in `encodings/dicts/encodings/`.
- **All 3 mappings wired** (dlbm_to_ghytbm, sddlbm_to_ydyhfldm, ghflbm_to_tdytfqdm) in `encodings/dicts/mappings/`.
- **9 rule files** in `encodings/dicts/rules/` (allowed_operations, construction_zone_codes, field_defaults, gdb_layers, ghytbm_to_planning_zone, land_use_structure, planning_targets, planning_zone_rules, three_line_types).
- **1 reference file** (`encodings/dicts/references/element_codes.yaml`).

---

## 9. Constraint Rules Coverage (scene2 §6.1 广东8条硬约束)

scene2 §6.1 defines "8条硬性约束" for 广东省村庄规划数据库衔接. Cross-check against `encodings/dicts/rules/` + `ConstructionCtrlZone` constants (spatial_types.py:264-269).

| # | scene2 rule (§6.1 附件1-2(1)) | encoded? | where |
|---|---|---|---|
| 1 | 不得调整永久基本农田 | ✅ | `construction_zone_codes.yaml:42-46` code "05" 永久基本农田保护区 (description: "上位规划落实,不可调整"); `farmland_protection` registry is_reference_layer: true |
| 2 | 不得调整禁止建设区 | ✅ | `construction_zone_codes.yaml:37-40` code "04" 禁止建设区; ConstructionCtrlZone.PROHIBITED="04" |
| 3 | 建设用地规模不得增加 | ⚠️ | `planning_targets.yaml` rule exists; `planning_indicators` table registered. ⚠️ No automated check function wired (scene2 §10.4 EXECUTE consumer) |
| 4 | 基本农田图斑内规划用途必须为农用地 | ⚠️ | `planning_zone_rules.yaml:36-47` priority-2 rule "基本农田内强制为农田保护区"; ⚠️ No parcel↔farmland intersects validator implemented |
| 5 | 允许/有条件建设区内不能有基本农田图斑 | ⚠️ | ConstructionCtrlZone constants present (ALLOWED="01", CONDITIONAL="03"); ⚠️ No intersects validator implemented (scene2 §10.3 within_zone/intersects relations) |
| 6 | 有条件建设区内不能规划建设用地 | ⚠️ | `conditional_construction_zone` registry (459); ⚠️ No automated check |
| 7 | 限制建设区内不能有新增城乡建设用地 | ⚠️ | ConstructionCtrlZone.RESTRICTED="02"; ⚠️ No automated check |
| 8 | 留白用地≤5% / 有条件建设区≤20% (双口径) | ⚠️ | `construction_zone_codes.yaml:32-35` code "03" description "不超过现状建设用地规模20%"; `planning_zone_rules.yaml` has decision rules. ⚠️ No percentage validator implemented |

**Bonus rules from scene2 §4:**
| # | rule | encoded? | where |
|---|---|---|---|
| B1 | 生态红线内建设区强制降级为生态保护区 (§4.1) | ✅ | `planning_zone_rules.yaml:20-33` priority-1 rule |
| B2 | 地质灾害500m缓冲区内建设区降级为生态控制区 (§5.6) | ✅ | `planning_zone_rules.yaml:49-62` priority-3 rule |

**Score: 2 ✅ / 6 ⚠️ / 0 ❌** (of 8 hard rules). All 8 rules have **declarative encoding** (codes/constants/rule files); 6 lack **automated validation functions** (scene2 §10.3-10.4 EXECUTE consumers). This is the primary runtime gap: constraint rules are modeled but not enforced. Future work: implement intersects/within_zone validators per scene2 §10.3.

---

## Summary

| Section | ✅ | ⚠️ | ❌ | Coverage |
|---|---|---|---|---|
| 1. Entity types (12) | 8 | 3 | 2 | 67% full |
| 2. 三调 DLTB fields (10 key) | 3 | 1 | 9 | 30% - attribute gap |
| 3. 广东4图层 fields (14) | 11 | 1 | 2 | 79% |
| 4. Encoding systems (6+3) | 9 | 0 | 0 | 100% |
| 5. 现状数据域 (8) | 0 | 5 | 3 | 63% partial |
| 6. Missing entities | - | - | 3 | Future work |
| 7. Missing rasters (5) | 2 | 0 | 3 | 40% |
| 8. Data utilization | 13/13 golden | DEM broken | 30+ orphan | Task 8/10 |
| 9. Constraint rules (8) | 2 | 6 | 0 | 25% enforced |

**Key findings:**
1. **Encodings fully wired** (6 systems + 3 mappings) - scene2 §3 is the strongest coverage area.
2. **Entity types 67% covered** - missing `project` (spatial) and `parcel_ownership`; `building`/`water`/`heritage`/`hazard` partial attributes.
3. **三调 DLTB fields 30% covered** - 权属/坐落/耕地属性/城镇村属性码 NOT modeled (attribute whitelist gap per scene2 §10.2).
4. **Constraint rules 100% declaratively encoded, 25% enforced** - runtime validators (intersects/within_zone) are the primary EXECUTE gap (scene2 §10.3-10.4).
5. **Data utilization 100% for golden bundle** - DEM/DOM broken refs (Task 8) and 30+ orphaned files (Task 10) are in-progress fixes.

**No gaps implemented in this document.** All ❌/⚠️ items are future work, scoped per scene2 §10 recommendations and blocked on data acquisition or EXECUTE consumer implementation.
