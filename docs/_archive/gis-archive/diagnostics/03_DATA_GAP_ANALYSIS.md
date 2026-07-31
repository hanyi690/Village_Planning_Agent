# 系统数据缺口分析：专业教材要求 vs 系统现状

> **Status: [DIAGNOSTIC]** | **Type: Gap Analysis** | **Updated: 2026-07-24**
> **Scope**: 空间数据缺口根因分析 - DEM/地名/遥感影像等P0/P1缺口
> **References**: BIBLIOGRAPHY.md §A3, §B11
> **Related**: 02_OUTPUT_ARCHITECTURE.md §4, diagnostics/02_RELIABILITY_ASSESSMENT.md
> **Data module**: 数据分类原则（空间/文本进入方式）、缺漏根因、DEM 选型已迁入 `backend/app/modules/data/README.md` 附录A；本文档保留 DEM 派生分析与详细缺口清单
>
> 依据: 《实用性村庄规划编制手册》（李巍等）第2章"综合现状调查与分析"
> 范围: 聚焦广东省，区分空间数据（需严谨模型）和文本数据（已有parse路径）

---

## 一、空间数据缺口（需建数据模型）

### P0 - 影响核心规划决策

| 数据 | 规划影响 | 系统现状 | 数据源 |
|------|---------|---------|--------|
| DEM | 坡度>25°禁建/坡向->居民点布局/建设适宜性/洪涝风险 | 🔴 缺失 | GDEMV3/ALOS/天地图 |
| 地名地址 | 空间锚定（parse锚定断裂->坐标匹配） | 🔴 缺失 | 天地图API/中国国家地名信息库 |
| 遥感影像(DOM) | 现状判读/房屋轮廓/地类识别 | 🔴 缺失 | Landsat 8/Sentinel/天地图 |

### P1 - 补充空间参考

| 数据 | 规划影响 | 系统现状 | 数据源 |
|------|---------|---------|--------|
| 宅基地确权 | 空间位置/面积/权属->交叉验证 | 🔴 缺失 | 农村地籍调查 |
| 公益林 | 生态空间划定/保护等级 | 🔴 缺失 | 林业部门 |
| 基础地理信息(DLG) | 水系/铁路/地名注记9类要素 | 🔴 缺失 | 全国地理信息资源目录 |
| 地理国情普查 | 地表覆盖/地理国情 | 🔴 缺失 | 自然资源部 |

> 文本数据缺口（社会经济/历史文化/设施需求等）已通过规划文本 -> parse -> OpSeq/Constraint 路径覆盖，
> 不建空间数据模型。详见 `backend/app/modules/data/README.md` 附录A.1。

---

## 二、DEM 派生分析（6 种）

依据李巍手册 §2.5 GIS实验三"地形分析"：

| 分析操作 | 输入 | 输出 | 规划决策影响 | 实现状态 |
|---------|------|------|------------|---------|
| 高程分析 | DEM | 高程分级图 | 村庄海拔->产业选择/居民点布局 | 🔴 未实现 |
| 坡度分析 | DEM | 0-6°/6-15°/15-25°/>25°四级 | >25°禁止建设，6-15°限制建设 | 🔴 未实现 |
| 坡向分析 | DEM | 8方向分类 | 南坡优先居住，北坡避让 | 🔴 未实现 |
| 焦点统计 | DEM+矢量地块 | 地块级高程/坡度均值 | 每个地块标注地形属性 | 🔴 未实现 |
| 建设适宜性评价 | DEM+土壤+水文 | 适宜/较适宜/一般/不适宜 | 建设边界划定 | 🔴 未实现 |
| 洪涝风险分析 | DEM+水系 | 淹没范围(10/20/50年一遇) | 禁建区划定 | 🔴 未实现 |

### 技术实现参考

```python
# 建议模块: app/modules/gis/analysis/terrain.py
class TerrainAnalyzer:
    def load_dem(self, dem_path: str) -> str           # 加载DEM
    def compute_slope(self, dem_path: str) -> str       # DEM->坡度栅格
    def compute_aspect(self, dem_path: str) -> str      # DEM->坡向栅格
    def classify_slope(self, slope_path: str) -> str    # 坡度->四级分类
    def zonal_stats(self, raster_path, parcels) -> list # 焦点统计->地块属性
    def construction_suitability(self, ...) -> str       # 综合建设适宜性
    def flood_risk(self, dem_path, water_path) -> str   # 洪涝淹没范围
```

依赖库：rasterio + numpy + scipy

> DEM 数据源选择（ALOS/GDEM/SRTM 精度与配置）见 `backend/app/modules/data/README.md` 附录A.4。

---

## 三、广东省技术指南隐含数据需求对照

| 指南原文 | 隐含数据 | 系统现状 | 优先级 |
|---------|---------|---------|--------|
| 三调数据成果 | DLTB + CJDCQ | ✅ 已有(660地块) | - |
| 最新土地变更调查数据 | 年度变更 | ❌ 缺失 | P2 |
| 数字线划地图(DLG) | 等高线/高程点/水系 | ❌ 缺失 | P1 |
| 1:2000地形图 | DEM/等高线 | ❌ 缺失 | **P0** |
| 国土数字正射影像图(DOM) | 卫星/航拍影像 | ❌ 缺失 | **P0** |
| 农村地籍调查数据 | 宅基地确权 | ❌ 缺失 | P1 |
| 地理国情普查及监测数据 | 地表覆盖/国情 | ❌ 缺失 | P1 |

> 缺漏根因与教训（三层参考缺一不可）见 `backend/app/modules/data/README.md` 附录A.5。
