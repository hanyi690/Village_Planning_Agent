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

### 当前（v4.4）

```
backend/app/modules/spatial_ops/
├── __init__.py               # 公开 API: compute_context_blocks
├── context.py                # 职责 A: ContextBlock 计算（8 种空间认知卡片）
├── geometry.py               # 职责 A: 几何操作 (centroid, area, near_point, parcel_relations)
└── relations.py              # 职责 A: 空间关系 (方向、邻接)
```

### 目标（v5.0 - 新增 `grounding.py`）

```
backend/app/modules/spatial_ops/
├── __init__.py               # 公开 API: compute_context_blocks + grounding 函数
├── context.py                # 职责 A: ContextBlock 计算（不变）
├── geometry.py               # 职责 A: 几何操作（不变）
├── relations.py              # 职责 A: 空间关系（不变）
└── grounding.py              # [NEW] 职责 B: 空间接地 -- PARSE 专用
```

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

## 五、与 KG 的分工

| 职责 | spatial_ops | KG |
|---|---|---|
| 计算 ContextBlock | ✅ `compute_context_blocks` | ❌ |
| 计算 parcel relations | ✅ `compute_parcel_relations` | ❌ |
| 计算 BBox | ✅ `resolve_directional_bbox` | ❌ |
| 过滤地块 | ✅ `query_parcels_in_bbox` | ❌ |
| 计算距离/权重 | ✅ `compute_proximity_weights` | ❌ |
| 存储邻接关系 | ❌ | ✅ `pln:touches` 三元组 |
| 存储 candidate_bsms | ❌ | ✅ `pln:candidate_bsm` 三元组 |
| 存储 BBox | ❌ | ✅ `pln:candidate_bbox` 字面量 |
| SPARQL 查询 | ❌ | ✅ 查已存储的关系 |

**原则**：spatial_ops 计算 -> KG 存储 -> 下游查询。KG 不做计算，spatial_ops 不做存储。

---

## 六、实施计划

| 阶段 | 任务 | 状态 |
|---|---|---|
| 1 | 创建 `grounding.py` 骨架 + `ZoneSpatialAnchor` 类型 | TODO |
| 2 | 实现 `resolve_directional_bbox` | TODO |
| 3 | 实现 `query_parcels_in_bbox` / `query_excluded_parcels` | TODO |
| 4 | 实现 `compute_proximity_weights` | TODO |
| 5 | 实现 `ground_zone_spatial_preference` 组合接口 | TODO |
| 6 | 在 `__init__.py` 导出 grounding API | TODO |
| 7 | PARSE Agent 调用 grounding API（替换内联计算） | TODO |

---

## 七、相关文档

- `docs/gis/00_SYSTEM_DESIGN.md` - 系统总体设计（四层架构）
- `backend/app/agent/gis/parse/README.md` - PARSE Agent（grounding 的主要消费者）
- `backend/app/modules/kg/README.md` - KG 模块（存储 grounding 产出）
- `backend/app/modules/schema/contracts/parse_contracts.py` - PARSE 契约（含空间锚定字段）
