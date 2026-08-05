# spatial_ops.selection — 候选评分 / 硬过滤 / 落点

## 职责边界

- 为项目/设施/分区目标选择最佳候选地块，输出 PlacementDecision。
- `selection.py`：
  - 面积解析 `compute_area_ha` / `parse_scale_ha`（公顷/万平方米/亩/平方米/
    中文数字）。
  - 大块目标判定 `is_large_block_target`。
  - 硬过滤 `apply_hard_filters`（约束重叠/灾害点邻近/已占用/最小面积）与
    面积过滤 `apply_scale_filter`。
  - 评分 `score_candidates`（legacy 0.5/0.3/0.2 公式或 9 维 PROJECT_WEIGHTS
    加权）与 `rank_candidates`（支持注入自定义 Ranker）。
  - 落点 `place_anchor_point`（大地块贴向参考点边缘）。
  - 组合入口 `select_parcel(target, candidates, ...) -> PlacementDecision`。
- `facility_location.py`：设施 MCLP（最大覆盖选址），
  `solve_maximal_covering`（PuLP 精确解，缺 pulp 退化为
  `greedy_maximal_covering`），`compute_coverage_matrix`（haversine 覆盖矩阵）。

## 输入输出契约

- 数据结构：`SelectionTarget`、`CandidateParcel`（bsm/geometry/dlmc/dlbm/
  area_ha/distance_m）、`Rejection`（bsm+reason+detail）、`ScoredCandidate`、
  `PlacementDecision`（selected_bsm/anchor_point/status: placed|unplaced）。
- MCLP：`DemandPoint(id, lon, lat, weight)`、`FacilityCandidate(candidate_id,
  lon, lat)`；`solve_maximal_covering -> List[str]`（选中候选 id）。
- 所有函数纯函数化，不依赖 Agent 状态。

## 依赖方向

- 依赖 shapely（几何解析/距离）与可选 pulp（MCLP/选址）。
- 依赖 `index` 的 ConstraintIndex 做约束重叠检查。
- 不依赖 agent / services / api 层。

## 禁止行为

- 禁止修改候选地块或 bundle（只读过滤/评分）。
- 禁止在硬过滤之前进行评分排序（约束不可协商）。
- 禁止将未通过 hard_filter 的地块纳入排名。
- 禁止在 pulp 缺失时抛异常（必须退化为贪心）。
