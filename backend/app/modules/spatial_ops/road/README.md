# 道路规划服务（services/modules/gis/road）

> 确定性的道路网络构建与道路规划流水线服务。从"现状道路 → 可路由路网 → 需求结构提取 → 空间落位 → 候选走廊生成 → 评分排序 → 与人工方案对比"的 6 阶段流水线。**不读人工规划道路参考**（防泄漏护栏贯穿全部阶段）。

---

## 一、包定位

本包是村庄道路规划的**确定性计算内核**，消费方是 `agent/gis/execute/road/generator.py`（EXECUTE Agent 的道路子任务适配层）。Agent 不直接绘制道路几何，而是：准备结构化空间输入 → 跑 Stage 2.6/3 门控 → 输入足够可信时才调用 Stage 4 自动路由。

```
execute/road/generator.py ──> services/modules/gis/road/（本包）
  RoadTarget intent 契约          确定性 Stage 1-6 流水线
```

核心设计约束：

- **证据驱动**：道路需求必须可追溯到需求表/规划文本/空间约束，拒绝无来源推断
- **位置唯一性**：地点名匹配仅做精确匹配，无法唯一定位时产出 `review_queue` 阻塞人工确认
- **防泄漏**：`allow_evaluation_input=False` 时任何阶段拒绝读取 `planned/road.geojson` 等人工/评估几何
- **路径产物**：每个阶段输出 JSON/GeoJSON 产物 + 摘要 report + 预览图（可回放可审计）

---

## 二、流水线与文件清单

| Stage | 模块 | 输入 → 输出 |
|-------|------|-------------|
| 1 | `network_builder.py` | 现状道路线 → 可路由路网（`RoadNetworkBuilder.build_road_network`，Node/Edge 记录） |
| 2 | `text_structurer.py` | 需求表/规划文本/约束文档 → `demand_points.geojson` + `road_projects.json` + `road_constraints.json` |
| 2.5 | `location_confirmation.py` | Stage2 产物 + 边界 → 人工确认队列 + 浏览器地图（`generate_location_confirmation_workflow` / `apply_location_confirmations`） |
| 2.6 | `planning_nodes.py` | Stage2 + 可选 Explore Binder 产物/KG → 规划实体定位 + 路径规划节点 + `road_planning_requests.json` |
| 2.6 | `kg_rdflib_adapter.py` / `kg_retry.py` | KG retry 请求 → RDFLib 证据 → retry 响应（`RDFLibKGSpatialRetryAdapter` / `build_planning_nodes_with_kg_retry_*`） |
| 2.6 | `stage2_6_validator.py` | Stage2.6 产物的结构契约校验（`validate_stage2_6_outputs`） |
| 3 | `spatial_binder.py` | 需求 + 约束 → GIS 空间绑定（`bind_road_spatial_requirements`，demand/project/endpoint/connector/constraint/unserved 产物） |
| 4 | `planner.py` + `terrain_router.py` | 路网 + 空间绑定 + 边界 + 用地 + 可选 DEM → 网络分析 + 候选走廊生成（`run_stage4_road_planning`，最小成本路由、坡度/工程检查） |
| 5 | `evaluator.py` | Stage4 候选 → 指标计算 + 硬过滤 + 加权评分排序（`score_road_candidates`，8 维权重） |
| 6 | `comparison_evaluator.py` | 算法方案 vs 人工方案（held-out）→ 对比指标表（`compare_road_plans`，仅此处读人工路） |
| demo | `demo_proxy.py` / `demo_terrain.py` / `qgis_package.py` | 隔离演示：代理点位、SRTM 地形网格、QGIS 地图包 |

### 阶段依赖关系

```
Stage1(network) ──> Stage2(text) ──> Stage2.5(人工确认)
                        │                 │
                        └──────> Stage2.6(planning_nodes) <── Explore Binder / KG
                                        │
Stage4(planner) <────── Stage3(spatial_binder) <────── Stage2.5 resolved
      │
Stage5(evaluator) ──> Stage6(comparison, held-out 专用)
```

---

## 三、关键数据结构（`schemas.py`）

全部为 `frozen dataclass` + `validate()` 前置校验，防止误用评估数据与非法参数：

| Config | Result | 用途 |
|--------|--------|------|
| `NetworkBuildConfig` / `NetworkBuildResult` | 路网构建（snap 容差场景、CRS） |
| `Stage2StructureConfig` / `Stage2StructureResult` | Stage2 需求提取 |
| `LocationConfirmationConfig` / `LocationConfirmationResult` | Stage2.5 人工确认 |
| `PlanningNodeBuildConfig` / `PlanningNodeBuildResult` | Stage2.6 规划节点构建 |
| `SpatialBindingConfig` / `SpatialBindingResult` | Stage3 空间绑定 |
| `RoadPlanningConfig` / `RoadPlanningResult` | Stage4 候选走廊（地形/服务/工程参数） |
| `CandidateScoringConfig` / `CandidateScoringResult` | Stage5 评分（权重集合校验） |
| `PlanComparisonConfig` / `PlanComparisonResult` | Stage6 方案对比 |
| `RoadNodeRecord` / `RoadEdgeRecord` | 路网拓扑记录 |

**防泄漏护栏**：`Stage2/2.5/2.6/3/4/5` 的 `validate()` 都检查路径白名单，`/planned/road.geojson`、`/project/lines.geojson` 等后缀在 `allow_evaluation_input=False` 时一律拒绝（`comparison_evaluator` 是唯一合法读取人工方案的地方，且强制校验 `manual_planned_roads_path` 必须是 held-out 路径）。

**指标假设**（Stage5/6）：`default_speed_kmh=20`、`assumed_road_width_m=4.5`、`assumed_unit_cost_yuan_per_m=3000`、`service_buffer_m=300` 等，可在 Config 中覆盖。

---

## 四、CLI 支持

各模块带 `if __name__ == "__main__"` 的 argparse 入口，可用 `python -m app.services.modules.gis.road.<module>` 独立跑单个阶段（如 `python -m app.services.modules.gis.road.network_builder --help`）。`__init__.py` 使用 `__getattr__` 懒加载避免 `python -m` 触发导入告警。

---

## 五、与 Agent 层的关系

`agent/gis/execute/road/generator.py` 是唯一生产消费方（`execute/road/generator.py:16-28`），调用：

- `build_road_network`（Stage1 路网）
- `build_planning_nodes` / `build_planning_nodes_with_kg_retry_*`（Stage2.6，含 KG 重试）
- `bind_road_spatial_requirements`（Stage3 绑定）
- `run_stage4_road_planning`（Stage4 自动路由，输入门控不足时 EXECUTE 显式 unresolved，不再降级到已删除的 `road_planner` fallback）

---

## 六、相关文档

- `app/services/README.md` — services 层总览
- `app/agent/gis/execute/README.md` — EXECUTE Agent（road 子任务节点）
- `docs/_archive/gis-archive/` — 历史 GIS 设计文档（Stage 定义与评测协议来源，已归档）
