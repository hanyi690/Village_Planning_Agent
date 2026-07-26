# Spatial Ops - 空间计算唯一层

> **定位**: 系统中**所有**空间计算的唯一发生地。BBox、距离、面积、方向、邻接、过滤--凡是涉及几何运算的，只在此模块内实现。
> **依赖**: `Schema` (类型契约) + `app.utils` (geojson/area/crs 工具)
> **不依赖**: Agent / KG / Tools / Parsing（反向依赖禁止）
> **Updated: 2026-07-25**

---

## 一、核心原则

**所有空间计算只在 `spatial_ops/` 内发生。**

| 层 | 允许做什么 | 禁止做什么 |
|---|---|---|
| PARSE Agent | 调用 `spatial_ops` 函数获取空间锚定 | 内联计算 BBox / 距离 / 面积 |
| EXECUTE Agent | 调用 `spatial_ops` 函数做空间验证 | 内联做几何运算 |
| KG | 存储和查询空间锚定（BSM 列表、BBox 字面量） | 计算 BBox / 过滤地块 / 算距离 |
| Converter | 纯字段映射（Pydantic ↔ dataclass） | 任何计算 |
| Parsing | 文本提取（regex / markdown / LLM） | 任何空间计算 |

违反此原则的代码（如 PARSE Agent 内联计算 BBox、KG 内调用 shapely）都是架构缺陷。

---

## 二、两大职责

spatial_ops 承担系统中两类空间计算：

### 职责 A: KG 输入计算（bundle -> ContextBlock + ParcelRelations -> KG）

```
VillageBundle
    │
    ├── compute_context_blocks(bundle) -> List[ContextBlock]
    │     8 种空间认知卡片: VILLAGE_META / LANDUSE_DIST / NATURAL_VILLAGES /
    │     FACILITIES / SPATIAL_RELATIONS / CONSTRAINTS / ZONE_ADJACENCY / TERRAIN
    │     每张卡片是 PARSE prompt 注入和 KG L1+L2 构建的输入
    │
    └── compute_parcel_relations(parcels, roads) -> ParcelRelations
          三层空间关系: touches(L1拓扑邻接) / nearby(L2近邻) / connected(L3路网连通)
          KG 通过 _add_parcel_relations 消费，零几何计算
    │
    ▼
KG.build_from_blocks(blocks, bundle, parcel_relations)
    -> Layer 1 (现状实体) + Layer 2 (约束规则)
```

### 职责 B: PARSE 空间接地（preference -> candidate_bsms + bbox -> ZoneTarget）

```
PARSE Agent format_targets 阶段
    │
    │ LLM 产出 ZoneTarget(spatial_preference_description="村北靠近刘村")
    │
    ▼
spatial_ops.grounding.ground_zone_spatial_preference(...)
    │
    ├── resolve_directional_bbox(center, direction="北") -> BBox
    ├── query_parcels_in_bbox(bundle.parcels, bbox) -> List[BSM]
    ├── query_excluded_parcels(context_blocks, "farmland_protection") -> List[BSM]
    └── compute_proximity_weights(parcels, reference_center, 500) -> Dict[BSM, float]
    │
    ▼
ZoneTarget 填充: candidate_bsms / candidate_bbox / excluded_bsms / proximity_weights
```

**职责 A 服务于 KG 构建（L1+L2 输入），职责 B 服务于 PARSE 空间锚定（L3 输入）。两者都在 spatial_ops 内完成，KG 和 PARSE 只消费结果。**

---

## 三、模块结构

### 当前（v4.6+）

```
backend/app/modules/spatial_ops/
├── __init__.py               # 公开 API: compute_context_blocks + build_spatial_index + grounding
├── context.py                # 职责 A: ContextBlock 计算（8 种空间认知卡片）
├── geometry.py               # 职责 A: 几何操作 (centroid, area, near_point, parcel_relations)
├── relations.py              # 职责 A: 空间关系 (方向、邻接)
├── grounding.py              # [NEW 待实现] 职责 B: 空间接地 -- PARSE 专用
└── bridge.py                 # [NEW v4.6] 职责 C: 空间桥接 -- EXECUTE 专用
```

### 职责分布

| 职责 | 模块 | 消费者 | 本质 |
|---|---|---|---|
| A: KG 输入计算 | `context.py` + `geometry.py` + `relations.py` | KG builder | bundle → spatial cognition → KG entities |
| B: PARSE 空间接地 | `grounding.py` | PARSE agent | text → BBox/BSM candidates → ZoneSpatialAnchor |
| C: EXECUTE 空间桥接 | `bridge.py` | EXECUTE agent | KG BSM → bundle geometry → spatial verification |

---

## 四、grounding.py 设计（新增）

### 4.1 设计依据

| 学术范式 | 来源 | 在 grounding.py 中的体现 |
|---|---|---|
| Spatial Grounding | Spatial-Agent (arxiv 2601.16965) | "村北" -> BBox + candidate_bsms |
| Candidate Proposal + Evaluation | LLM-Grounder (arxiv 2309.12311) | KG 查询提议候选 -> spatial_ops 过滤 |
| SUBCOND ≺ COND ≺ SUPPORT ≺ MEASURE | Spatial-Agent 功能角色优先级 | 过滤 -> 排除 -> 邻近 -> 输出 |

### 4.2 API 设计

```python
# ── 方向接地 ──

def resolve_directional_bbox(
    center: Tuple[float, float],
    direction: str,
    radius_m: float = 1000,
) -> Optional[Tuple[float, float, float, float]]:
    """将"村北""南侧"等方向描述解析为 BBox。

    Args:
        center: 参考点坐标 (lon, lat)
        direction: 方向描述 ("北", "南", "东", "西", "东北", ...)
        radius_m: 搜索半径（米）

    Returns:
        (min_lon, min_lat, max_lon, max_lat) 或 None
    """


# ── 地块过滤 ──

def query_parcels_in_bbox(
    parcels: List[CurrentLandUseParcel],
    bbox: Tuple[float, float, float, float],
) -> List[str]:
    """返回质心在 BBox 内的地块 BSM 列表。"""


def query_parcels_near_entity(
    parcels: List[CurrentLandUseParcel],
    entity_center: Tuple[float, float],
    max_distance_m: float = 500,
) -> List[str]:
    """返回距实体中心指定距离内的地块 BSM 列表。"""


def query_excluded_parcels(
    context_blocks: List[ContextBlock],
    zone_type: str,
) -> List[str]:
    """从 ContextBlock 提取约束区内重叠地块 BSM（排除集）。

    Args:
        zone_type: "farmland_protection" / "ecological_redline" / ...
    """


# ── 邻近度评分 ──

def compute_proximity_weights(
    parcels: List[CurrentLandUseParcel],
    reference_center: Tuple[float, float],
    max_distance_m: float = 500,
) -> Dict[str, float]:
    """计算地块到参考点的邻近度评分 (0.0-1.0)。

    距离越近权重越高，用于 MIP 目标函数。
    """


# ── 面积计算 ──

def compute_target_area(
    area_ratio: float,
    total_area_ha: float,
) -> float:
    """area_ratio * total_area_ha -> target_area_ha。"""


# ── 组合接口 ──

def ground_zone_spatial_preference(
    preference_desc: str,
    place_mappings: Dict[str, dict],
    context_blocks: List[ContextBlock],
    bundle: VillageBundle,
) -> "ZoneSpatialAnchor":
    """组合调用：将 ZoneTarget 的空间偏好描述接地为完整空间锚定。

    这是 PARSE Agent 在 format_targets 后调用的唯一入口。
    内部组合 resolve_directional_bbox + query_parcels_in_bbox +
    query_excluded_parcels + compute_proximity_weights。

    Returns:
        ZoneSpatialAnchor(
            candidate_bsms=[...],
            candidate_bbox=(...),
            excluded_bsms=[...],
            proximity_weights={...},
        )
    """
```

### 4.3 数据流

```
PARSE Agent format_targets 阶段
    │
    │ LLM 产出 ZoneTarget(spatial_preference_description="村北靠近刘村")
    │
    ▼
spatial_ops.grounding.ground_zone_spatial_preference(
    preference_desc="村北靠近刘村",
    place_mappings={"刘村": {"center": [116.05, 24.83], "parcel_ids": [...]}},
    context_blocks=[...],
    bundle=village_bundle,
)
    │
    ├── resolve_directional_bbox(center=[116.05, 24.83], direction="北")
    │     -> bbox = (116.04, 24.83, 116.06, 24.85)
    │
    ├── query_parcels_in_bbox(bundle.polygons.landuse_current, bbox)
    │     -> candidate_bsms = ["P001", "P002", "P003"]
    │
    ├── query_excluded_parcels(context_blocks, "farmland_protection")
    │     -> excluded_bsms = ["P100", "P101"]
    │
    └── compute_proximity_weights(parcels, [116.05, 24.83], 500)
          -> proximity_weights = {"P001": 0.9, "P002": 0.6, "P003": 0.3}
    │
    ▼
ZoneTarget 填充:
    candidate_bsms = ["P001", "P002", "P003"]
    candidate_bbox = (116.04, 24.83, 116.06, 24.85)
    excluded_bsms = ["P100", "P101"]
    proximity_weights = {"P001": 0.9, ...}
```

---

## 五、bridge.py 设计（新增）

### 5.1 问题：EXECUTE 如何定位空间数据？

```
EXECUTE Agent 从 KG 查询到:
  ● ParcelNode(bsm="441426211000055682", dlbm="0101", area_ha=1.23)
  ● 但没有 geometry —— KG 不存储几何

EXECUTE 需要:
  1. 根据 BSM 找回几何 → 做 overlap / distance / buffer 分析
  2. 给定 planned_geometry → 找出被覆盖的 L1 地块 BSM 列表
  3. 检查规划方案是否与生态红线/基本农田冲突

现有架构:
  spatial_ops 有 compute_parcel_relations(parcels, roads)
  但这是 KG builder 调用的一次性计算，不是 EXECUTE 可以调用的查询接口
```

### 5.2 解决：SpatialIndex — 运行时空间索引

```
EXECUTE session 启动 → build_spatial_index(bundle) → SpatialIndex
                                    │
                                    ├── get_parcel_geometry(bsm) → GeoJSON
                                    │     BSM → 找回原始几何（单地块）
                                    │
                                    ├── parcels_intersecting(geometry) → List[OverlapResult]
                                    │     给定规划几何 → R-tree 搜索 → 重叠列表
                                    │     Used for: L4↔L1 overlap analysis
                                    │
                                    ├── parcels_within_bbox(bbox) → List[Dict]
                                    │     BBox → 返回地块列表
                                    │
                                    ├── parcels_within_distance(bsm, 200m) → List[Dict]
                                    │     某地块周边 200m 有哪些地块
                                    │     Used for: 邻近分析 / 连片性检查
                                    │
                                    └── get_parcel_attrs(bsm) → Dict
                                        返回 DLBM / 面积 / zone_type 等
```

### 5.3 API 设计

```python
# ── 工厂函数（入口）──

def build_spatial_index(bundle: VillageBundle) -> Optional[SpatialIndex]:
    """从 VillageBundle 构建 R-tree 空间索引。

    EXECUTE agent 在 session 开始时调用一次，后续复用。
    内部读取 bundle.polygons.landuse_current → GeoDataFrame + R-tree。
    """


# ── 空间索引类 ──

class SpatialIndex:
    def get_parcel_geometry(self, bsm: str) -> Optional[Dict]:
        """BSM → GeoJSON geometry dict (EPSG:4326)。"""

    def get_parcel_attrs(self, bsm: str) -> Dict:
        """BSM → {dlbm, area_sqm, zone_type, ...}。"""

    def has_parcel(self, bsm: str) -> bool:
        """BSM 是否在索引中。"""

    def parcels_intersecting(self, geometry: Dict) -> List[OverlapResult]:
        """给定 GeoJSON 几何 → 相交的 L1 地块（按面积降序）。

        OverlapResult:
            bsm: str
            dlbm: str
            overlap_area_sqm: float
            overlap_pct: float       # overlap / parcel.total_area
            parcel_total_area_sqm: float
            current_zone_type: str

        用于:
        - L4 规划地块与 L1 现状地块的 overlap 分析
        - 约束区冲突检测
        - 面积统计
        """

    def parcels_within_bbox(self, bbox: Tuple) -> List[Dict]:
        """BBox → 质心/几何在 BBox 内的 L1 地块。"""

    def parcels_within_distance(self, bsm: str, distance_m: float = 200) -> List[Dict]:
        """BSM → 返回 {bsm, distance_m} 列表（排除自身）。"""
```

### 5.4 数据流

```
EXECUTE Agent
    │
    │ 1. 初始化
    │ build_spatial_index(bundle) → SpatialIndex (含 660 个 L1 地块的 R-tree)
    │
    │ 2. 空间查询（任意顺序，任意次数）
    │ idx.parcels_intersecting(planned_geom)
    │   → [OverlapResult(bsm="P001", overlap_pct=85.2, ...), ...]
    │
    │ 3. 约束检查
    │ idx.parcels_intersecting(ecological_redline_geom)
    │   → 检查 overlap_pct 是否 > 0 → 违反约束
    │
    │ 4. 属性回查
    │ idx.get_parcel_attrs("P001")
    │   → {dlbm: "0701", area_sqm: 12345, zone_type: "residential"}
```

---

## 六、三职责分工总表

| 职责 | spatial_ops 模块 | 存储层 | 消费者 |
|---|---|---|---|
| A: KG 输入 | `compute_context_blocks` / `compute_parcel_relations` | KG Layer1+2 | PARSE prompt + KG builder |
| B: PARSE 接地 | `grounding.py` (resolve_bbox, query_parcels, compute_weights) | KG Layer3 | ZoneTarget.candidate_bsms |
| C: EXECUTE 桥接 | `bridge.py` (SpatialIndex: get_geom, parcels_intersecting, within) | 无（运行时内存） | EXECUTE agent 空间验证 |

### 与 KG 的分工

| 职责 | spatial_ops | KG |
|---|---|---|
| 计算 ContextBlock | ✅ `compute_context_blocks` | ❌ |
| 计算 parcel relations | ✅ `compute_parcel_relations` | ❌ |
| 计算 BBox | ✅ `resolve_directional_bbox` | ❌ |
| 过滤地块 | ✅ `query_parcels_in_bbox` / `parcels_intersecting` | ❌ |
| 计算距离/权重 | ✅ `compute_proximity_weights` / `parcels_within_distance` | ❌ |
| 存储邻接关系 | ❌ | ✅ `pln:touches` 三元组 |
| 存储 candidate_bsms | ❌ | ✅ `pln:candidate_bsm` 三元组 |
| 存储 BBox | ❌ | ✅ `pln:candidate_bbox` 字面量 |
| 存储几何 | ❌ | ✅ `pln:bsm` 键（无 geometry，只存键） |
| SPARQL 查询 | ❌ | ✅ 查已存储的关系 |

**原则**：spatial_ops 计算 -> KG 存储 / 运行时索引 -> 下游查询。KG 不做计算，spatial_ops 不做持久化。

---

## 七、实施计划

| 阶段 | 任务 | 模块 | 状态 |
|---|---|---|---|
| 1 | 创建 `grounding.py` 骨架 + `ZoneSpatialAnchor` 类型 | grounding | TODO |
| 2 | 实现 `resolve_directional_bbox` | grounding | TODO |
| 3 | 实现 `query_parcels_in_bbox` / `query_excluded_parcels` | grounding | TODO |
| 4 | 实现 `compute_proximity_weights` | grounding | TODO |
| 5 | 实现 `ground_zone_spatial_preference` 组合接口 | grounding | TODO |
| 6 | 在 `__init__.py` 导出 grounding API | grounding | TODO |
| 7 | PARSE Agent 调用 grounding API | integration | TODO |
| 8 | 创建 `bridge.py` + `SpatialIndex` + `build_spatial_index` | bridge | ✅ DONE |
| 9 | EXECUTE Agent 集成 `build_spatial_index` 进行空间验证 | integration | TODO |

---

## 八、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` - 系统总体设计（四层架构）
- `backend/app/agent/gis/parse/README.md` - PARSE Agent（grounding 的主要消费者）
- `backend/app/modules/kg/README.md` - KG 模块（存储 grounding 产出）
- `backend/app/modules/schema/contracts/parse_contracts.py` - PARSE 契约（含空间锚定字段）
