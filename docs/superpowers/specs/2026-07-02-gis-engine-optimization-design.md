# GIS 布局引擎优化设计：算法质量 + 全栈测试

**日期**: 2026-07-02
**版本**: v1.0
**状态**: 设计评审中
**对应设计文档**: `docs/GIS_LAYOUT_ARCHITECTURE_V2.md`

---

## 1. 背景与动机

Village_Planning_Agent 的 GIS 布局引擎采用 Trinity Architecture（Planning KG + Agentic Pipeline + Spatial Generator），已完成 P3 阶段核心功能实现。但与设计文档 `GIS_LAYOUT_ARCHITECTURE_V2.md` 的规格相比，存在以下关键差距：

| 设计要求                   | 当前实现                                           | 差距                           |
| -------------------------- | -------------------------------------------------- | ------------------------------ |
| MIP 目标函数含空间紧凑性项 | 仅有面积偏差 + DLBM 偏好                           | 缺少邻接约束、紧凑性、变化惩罚 |
| 13 种 KG 实体类型          | 仅实现 Parcel/Zone/Constraint 3 种                 | 缺少 10 种实体                 |
| 11 种 KG 关系类型          | 仅实现 adjacent_to/within_zone/constrained_by 3 种 | 缺少 8 种关系                  |
| 空间紧凑度验证指标         | 无                                                 | 缺失                           |
| 邻接同类率验证             | 无                                                 | 缺失                           |
| 前端 E2E 自动化测试        | 无                                                 | 缺失                           |
| CI/CD 自动化               | 无                                                 | 缺失                           |

**优化目标**：重新设计 MIP 模型，补全 KG 实体与关系，加严验证指标，建立全栈测试体系。

---

## 2. MIP 重新设计

### 2.1 当前问题分析

当前 `MIPZoneAllocator`（`mip_allocator.py`，350行）的目标函数：

```python
minimize = AREA_WEIGHT * Σ(dev_pos_z + dev_neg_z) + Σ x[i][z] * preference_cost[i][z]
```

问题：

1. **无邻接约束**：660 个地块的 ~3000-5000 条邻接关系完全未纳入模型
2. **无空间紧凑性**：分区可能产生碎片化分布
3. **无变化惩罚**：现状保持仅为 DLBM 偏好的隐式效果，不够显式
4. **求解结果**：邻接同类率可能低于 50%，分区边界不光滑

### 2.2 新目标函数

```
minimize =
    α * Σ(dev_pos_z + dev_neg_z)                    // 面积偏差 (α=10.0)
  + β * Σ x[i][z] * preference_cost[i][z]          // DLBM 偏好 (β=1.0)
  + γ * Σ x[i][z] * change_penalty[i][z]           // 现状保持 (γ=0.3)
  - δ * Σ_{adj(i,j)} Σ_z y[i][j][z]               // 邻接同类奖励 (δ=0.5)
```

其中：

- `dev_pos_z`, `dev_neg_z`：区域 z 的面积正/负偏差（已有）
- `preference_cost[i][z]`：DLBM 偏好代价矩阵（已有，来自 `DLBM_ZONE_PREFERENCE`）
- `change_penalty[i][z]`：变化惩罚，0 当 z 与 current_zone 兼容，`penalty_weight` 否
- `y[i][j][z]`：辅助变量，=1 当 parcel_i 和 parcel_j 都分配到 zone_z

### 2.3 邻接约束线性化

二次项 `x[i][z] * x[j][z]` 不能直接在 MIP 中使用，需要线性化：

```python
# 对每对相邻地块 (i, j) 和每个区域类型 z：
y[i][j][z] <= x[i][z]                              # 线性化约束 1
y[i][j][z] <= x[j][z]                              # 线性化约束 2
y[i][j][z] >= x[i][z] + x[j][z] - 1               # 线性化约束 3
y[i][j][z] ∈ {0, 1}                                # 二元变量
```

目标函数中 `-δ * y[i][j][z]` 使得同类邻接获得奖励。

### 2.4 模型规模估算

| 配置               | Binary Vars    | Constraints     | 预估求解时间 |
| ------------------ | -------------- | --------------- | ------------ |
| 当前               | 660×7 = 4,620 | ~1,500          | 5-10s        |
| +邻接约束(软)      | +3,000~5,000   | +9,000~15,000   | 15-30s       |
| +变化惩罚          | 0              | 0               | +0s          |
| **完整方案** | ~8,000~10,000 | ~12,000~17,000 | 20-35s       |

> 求解时间预估基于 CBC solver 在 660 parcels 上的实测基准。如果超 30s，启用 `timeLimit=25` + gap tolerance 放宽策略。

### 2.5 邻接图数据结构

**新建文件**: `backend/app/services/modules/gis/layout/optimizer/adjacency_graph.py`

```python
class AdjacencyGraph:
    """地块邻接图：基于空间连接 + 距离过滤"""

    def __init__(self, parcel_db: Dict[str, Dict], max_distance_m: float = 30.0):
        self.adjacency_dict: Dict[str, Set[str]] = {}   # {composite_key: {neighbor_keys}}
        self.parcel_to_idx: Dict[str, int] = {}
        self.idx_to_parcel: Dict[int, str] = {}
        self._build_from_parcels(parcel_db, max_distance_m)

    def _build_from_parcels(self, parcel_db, max_distance_m):
        """使用 Shapely 空间连接检测边界共享/距离 < max_distance_m 的地块对"""
        # 1. 构建地块几何索引
        # 2. 使用 STRtree 或 sjoin 检测相邻对
        # 3. 过滤距离 > max_distance_m 的对
        # 4. 构建 adjacency_dict + 索引映射

    def get_adjacent_pairs(self) -> List[Tuple[str, str]]:
        """返回所有邻接对（去重，i < j）"""

    def get_neighbors(self, parcel_key: str) -> Set[str]:
        """返回指定地块的所有邻居"""

    def get_edge_count(self) -> int:
        """返回邻接边总数"""

    def to_index_pairs(self) -> List[Tuple[int, int]]:
        """返回索引化的邻接对列表，供 MIP 使用"""
```

### 2.6 接口兼容性

`solve()` 方法新增可选参数，**不传时退化为当前行为**：

```python
def solve(
    self,
    landuse_geojson: Dict[str, Any],
    targets: Dict[str, float],
    constraints: Optional[List[Dict]] = None,
    kg=None,
    # --- 新增参数 ---
    adjacency_graph: Optional[AdjacencyGraph] = None,   # 邻接图
    adjacency_weight: float = 0.5,                       # 邻接同类奖励权重
    change_penalty_weight: float = 0.3,                  # 变化惩罚权重
) -> Dict[str, Any]:
```

当 `adjacency_graph is None` 时，跳过邻接约束和变化惩罚，行为与当前完全一致。

---

## 3. KG 完整实现

### 3.1 13 种实体类型

**新建文件**: `backend/app/services/modules/gis/layout/kg/ontology.py`

| 实体类型      | URI                   | 属性                                  | 来源                  |
| ------------- | --------------------- | ------------------------------------- | --------------------- |
| Parcel        | `pln:Parcel`        | bsm, dlbm, dlmc, area_ha, geometry    | landuse_geojson       |
| Zone          | `pln:Zone`          | zone_type, target_area_ha             | planning report       |
| Constraint    | `pln:Constraint`    | operator, value, field, source        | KG extraction         |
| Indicator     | `pln:Indicator`     | name, target_value, unit              | planning report       |
| Project       | `pln:Project`       | project_id, name, version             | L3 reports            |
| Village       | `pln:Village`       | name, total_area_ha, population       | boundary data         |
| Regulation    | `pln:Regulation`    | regulation_id, legal_basis, scope     | legal docs            |
| LandUsePlan   | `pln:LandUsePlan`   | plan_id, valid_period, status         | planning report       |
| Facility      | `pln:Facility`      | facility_type, status, service_radius | FacilityPlacer output |
| Axis          | `pln:Axis`          | axis_type, geometry                   | AxisBuilder output    |
| Road          | `pln:Road`          | road_name, road_type, RN              | road_geojson          |
| WaterBody     | `pln:WaterBody`     | water_name, water_type                | landuse_geojson       |
| BuildingGroup | `pln:BuildingGroup` | building_count, total_area            | construction_zone     |

### 3.2 11 种关系类型

| 关系           | URI                    | 域 → 范围                 | 语义         |
| -------------- | ---------------------- | -------------------------- | ------------ |
| adjacent_to    | `pln:adjacent_to`    | Parcel → Parcel           | 空间邻接     |
| within_zone    | `pln:within_zone`    | Parcel → Zone             | 地块归属分区 |
| constrained_by | `pln:constrained_by` | Zone → Constraint         | 受约束       |
| designated_as  | `pln:designated_as`  | Parcel → Zone             | 规划用途指定 |
| protects       | `pln:protects`       | Regulation → Zone         | 法规保护     |
| located_in     | `pln:located_in`     | Parcel/Facility → Village | 空间包含     |
| achieves       | `pln:achieves`       | Project → Indicator       | 项目达标     |
| conflicts_with | `pln:conflicts_with` | Constraint → Constraint   | 约束冲突     |
| derived_from   | `pln:derived_from`   | Indicator → LandUsePlan   | 指标来源     |
| serves         | `pln:serves`         | Facility → Zone           | 设施服务     |
| connects       | `pln:connects`       | Road/Axis → Zone          | 连接关系     |

### 3.3 builder.py 扩展

**修改文件**: `backend/app/services/modules/gis/layout/kg/builder.py`

新增方法：

| 方法                               | 功能                                           | 三元组估算 |
| ---------------------------------- | ---------------------------------------------- | ---------- |
| `_add_village()`                 | Village 实体 + 所有 Parcel 的 located_in       | +660       |
| `_add_project()`                 | Project 实体 + achieves 关系                   | +30        |
| `_add_regulation()`              | Regulation 实体 + protects 关系                | +15        |
| `_add_indicators()`              | Indicator 实体 + derived_from 关系             | +30        |
| `_add_spatial_infrastructure()`  | Facility/Road/WaterBody/Axis + serves/connects | +200       |
| `_add_designated_as_relations()` | 所有 Parcel 的 designated_as                   | +660       |

预期三元组增长：600+ → 1500+

### 3.4 query.py 扩展

**修改文件**: `backend/app/services/modules/gis/layout/kg/query.py`

新增 8 个 SPARQL 模板：

| 模板名                          | 功能                       | 用途               |
| ------------------------------- | -------------------------- | ------------------ |
| `get_all_projects`            | 查询所有规划项目           | Agent 了解项目背景 |
| `get_project_indicators`      | 项目→指标→目标值→实现率 | 验证达标情况       |
| `get_regulation_impacts`      | 法规→约束→影响范围       | Agent 推理依据     |
| `get_facility_serve_areas`    | 设施→服务对象             | 设施布局优化       |
| `get_axis_connections`        | 轴线→连接关系             | 发展轴分析         |
| `get_road_network`            | 道路网络                   | 交通可达性         |
| `get_parcels_by_facility`     | 设施附近地块               | 设施选址           |
| `get_conflicting_constraints` | 冲突约束对                 | 冲突检测           |

### 3.5 Agent Tool 集成

**修改文件**: `backend/app/tools/gis/layout_tools.py`

新增 @tool：

1. **`query_project_indicators`** — 查询项目规划指标及达标情况

   - 参数：`project_name: str`, `indicator_type: str = ""`
   - 返回：指标列表 + 目标值 + 当前值 + 达标率
2. **`calculate_spatial_quality`** — 计算空间品质指标

   - 参数：`output_format: str = "scores"`（scores/detailed/visualization）
   - 返回：紧凑度、邻接同类率、设施覆盖率

---

## 4. 验证指标体系

### 4.1 指标定义

#### 硬约束（强制 100% 达标）

| 指标               | 计算方式                                  | 阈值        |
| ------------------ | ----------------------------------------- | ----------- |
| construction_cap   | `Σ construction_zones.area_ha ≤ 30.5` | ≤ 30.5 ha  |
| farmland_min       | `Σ agriculture.area_ha ≥ 78.83`       | ≥ 78.83 ha |
| ecological_redline | `eco_parcels ∩ construction = ∅`      | 0 违规      |
| protected_parcels  | `count(reassigned_protected_parcels)`   | 0           |
| all_assigned       | `count(unassigned_parcels)`             | 0           |

#### 软约束（达标率目标）

| 指标                         | 公式                                                      | 目标  |
| ---------------------------- | --------------------------------------------------------- | ----- |
| area_deviation_pct           | `\|actual - target\| / target * 100%`                     | < 5%  |
| mip_solve_time               | `solver.wall_time`                                      | < 30s |
| adjacency_compatibility_rate | `same_zone_edges / total_edges`                         | > 70% |
| spatial_compactness_index    | `1 / (1 + cv)` where cv = std/mean of zone parcel areas | > 0.7 |
| facility_coverage_rate       | `covered_area / total_area`                             | > 80% |

### 4.2 邻接同类率

```python
def calc_adjacency_compatibility(
    adjacency_map: Dict[str, Set[str]],
    assignments: Dict[str, str],
) -> float:
    """计算邻接同类率（0-1，越高越好）"""
    same_zone = 0
    total = 0
    for parcel_key, neighbors in adjacency_map.items():
        assigned_zone = assignments.get(parcel_key, "unknown")
        for neighbor_key in neighbors:
            if neighbor_key <= parcel_key:  # 避免重复计数
                continue
            total += 1
            if assignments.get(neighbor_key, "unknown") == assigned_zone:
                same_zone += 1
    return same_zone / total if total > 0 else 0.0
```

### 4.3 空间紧凑度指数

```python
def calc_spatial_compactness(
    parcel_db: Dict[str, Dict],
    assignments: Dict[str, str],
) -> float:
    """计算空间紧凑度指数（0-1，越高越好）"""
    from collections import defaultdict
    import numpy as np

    zone_areas = defaultdict(list)
    for pk, zt in assignments.items():
        zone_areas[zt].append(parcel_db[pk]["area_ha"])

    scores = []
    for areas in zone_areas.values():
        if len(areas) < 2:
            continue
        mean_a = np.mean(areas)
        cv = np.std(areas) / mean_a if mean_a > 0 else 0
        scores.append(1 / (1 + cv))  # 变异系数越小越紧凑

    return float(np.mean(scores)) if scores else 0.5
```

### 4.4 Validator 扩展

**修改文件**: `backend/app/services/modules/gis/layout/validator.py`

新增验证检查项：

- `adjacency_compatibility` — 邻接同类率 > 70%
- `spatial_compactness` — 紧凑度指数 > 0.7
- `facility_coverage` — 设施覆盖率 > 80%

验证级别：

- `error`：硬约束违反
- `warning`：软约束未达标
- `info`：仅供参考的指标

---

## 5. 测试方案

### 5.1 后端新增测试

| 测试文件                           | 用例数 | 覆盖内容                                   |
| ---------------------------------- | ------ | ------------------------------------------ |
| `test_gis_adjacency_graph.py`    | 15     | 邻接图构建、距离过滤、索引映射             |
| `test_gis_mip_optimizer.py`      | 20     | 邻接约束、紧凑性、求解时间、面积偏差、降级 |
| `test_gis_kg_complete.py`        | 15     | 13 实体、11 关系、引用链、三元组数量       |
| `test_gis_validator_extended.py` | 10     | 新增 3 个指标验证                          |
| `test_gis_performance.py`        | 8      | MIP 构建/求解时间、管线时间、KG 查询时间   |

### 5.2 前端 Playwright E2E

| 测试文件                           | 用例数 | 覆盖内容                           |
| ---------------------------------- | ------ | ---------------------------------- |
| `gis_interactions.spec.ts`       | 8      | 地图加载、点击交互、图层切换、缩放 |
| `planning_pipeline.spec.ts`      | 5      | 生成→验证→调整完整流程           |
| `performance_benchmarks.spec.ts` | 3      | 渲染时间、交互响应                 |

**新建配置**: `frontend/playwright.config.ts`

### 5.3 CI/CD

**新建文件**: `.github/workflows/gis-engine-ci.yml`

Jobs：

1. `backend-tests` — pytest + coverage（触发：push/PR）
2. `frontend-tests` — Playwright E2E（触发：push/PR）
3. `performance-benchmark` — 基准测试（触发：push to main）
4. `docker-build` — 镜像构建（触发：push to main）

---

## 6. 实现顺序

```
Phase 0: MIP 重新设计 (8天)
  0A: 邻接图数据结构 (3天)
  0B: MIP 模型重构 (5天)

Phase 1: KG 完整实现 (11天)  ← 可与 Phase 0 并行
  1A: Ontology 定义 (2天)
  1B: builder.py 扩展 (4天)
  1C: query.py 扩展 (3天)
  1D: Agent Tool 集成 (2天)

Phase 2: 验证指标体系 (7天)  ← 依赖 Phase 0 + Phase 1
  邻接同类率 + 空间紧凑度 + 设施覆盖率

Phase 3: 后端测试 (5天)  ← 依赖 Phase 2

Phase 4: 前端 E2E 测试 (8天)  ← 可与 Phase 1-3 并行

Phase 5: CI/CD (3天)  ← 依赖 Phase 3 + Phase 4
```

**关键路径**: Phase 0(8d) → Phase 2(7d) → Phase 3(5d) → Phase 5(3d) = **23 天**

**并行优化**: Phase 1(KG) 和 Phase 4(前端) 与关键路径并行，实际总工期约 **23 天**。

---




## 7. 关键文件清单

| 操作 | 文件路径                                   | 说明                             |
| ---- | ------------------------------------------ | -------------------------------- |
| 新建 | `layout/optimizer/adjacency_graph.py`    | 邻接图数据结构                   |
| 重构 | `layout/optimizer/mip_allocator.py`      | MIP 邻接约束 + 紧凑性 + 变化惩罚 |
| 新建 | `layout/kg/ontology.py`                  | 13 实体 + 11 关系定义            |
| 扩展 | `layout/kg/builder.py`                   | 新增 6 个 build 方法             |
| 扩展 | `layout/kg/query.py`                     | 新增 8 个 SPARQL 模板            |
| 扩展 | `layout/validator.py`                    | 新增 3 个验证指标                |
| 扩展 | `tools/gis/layout_tools.py`              | 新增 2 个 Agent tool             |
| 新建 | `tests/test_gis_adjacency_graph.py`      | 邻接图测试                       |
| 新建 | `tests/test_gis_mip_optimizer.py`        | MIP 优化测试                     |
| 新建 | `tests/test_gis_kg_complete.py`          | KG 完整性测试                    |
| 新建 | `tests/test_gis_validator_extended.py`   | 验证指标测试                     |
| 新建 | `tests/test_gis_performance.py`          | 性能基准测试                     |
| 新建 | `frontend/e2e/gis_interactions.spec.ts`  | 地图<br />交互 E2E               |
| 新建 | `frontend/e2e/planning_pipeline.spec.ts` | 规划流程 E2E                     |
| 新建 | `frontend/playwright.config.ts`          | Playwright 配置                  |
| 新建 | `.github/workflows/gis-engine-ci.yml`    | CI/CD 配置                       |

---

## 8. 风险与缓解

| 风险                          | 影响 | 可能性 | 缓解措施                                                   |
| ----------------------------- | ---- | ------ | ---------------------------------------------------------- |
| MIP 求解超 30s                | 低   | 中     | CBC timeLimit=25 + gap tolerance 放宽 + fallback to greedy |
| KG 三元组过多影响 SPARQL 性能 | 中   | 低     | 高频查询预索引 + 缓存                                      |
| 邻接线性化约束过多            | 低   | 中     | 限制 max_distance_m 或采样稀疏邻接                         |
| 前端 E2E 测试不稳定           | 高   | 高     | 重试机制 + 隔离测试环境                                    |
| 现有测试回归                  | 高   | 低     | 每个 Phase 完成后运行全量 pytest                           |

---

## 9. 验证方案

### 端到端验证步骤

1. **MIP 质量验证**：`pytest test_gis_mip_optimizer.py -v`

   - 邻接同类率 ≥ 70%
   - 面积偏差 < 5%
   - 求解时间 < 30s
2. **KG 完整性验证**：`pytest test_gis_kg_complete.py -v`

   - 13 种实体全部存在
   - 11 种关系全部存在
   - 三元组数 ≥ 1500
3. **验证指标验证**：`pytest test_gis_validator_extended.py -v`

   - 新增 3 个指标计算正确
4. **性能基准**：`pytest test_gis_performance.py -v`

   - MIP 构建 < 2s，求解 < 30s
   - 完整管线 < 10s
   - KG 查询 < 500ms
5. **前端 E2E**：`npx playwright test`

   - 地图交互和规划流程正常
6. **CI/CD**：推送 PR 触发 GitHub Actions

   - 所有 jobs 通过

### 回归验证

所有现有测试必须继续通过：`pytest tests/ -v`（9 个现有 GIS 测试文件）。
