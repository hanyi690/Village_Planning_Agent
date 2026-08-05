# spatial_ops.grounding — 空间接地（NL 描述 → BSM 候选）

## 职责边界

- 将自然语言空间描述（如"村北""靠近刘村""沿金田河"）接地为具体空间锚定
  （候选地块 BSM + BBox + 邻近度权重），服务 PARSE / EXPLORE / GROUND。
- `grounding.py`：方向→BBox（8 方位）、BBox/近实体地块查询、约束重叠排除、
  邻近度评分、组合接口 `ground_zone_spatial_preference` /
  `ground_facility_spatial_preference` / `ground_linear_spatial_preference`；
  以及 KG 拓扑优先的分派器 `resolve_spatial_description`（toponym /
  directional / linear / constraint / compound 7 类描述）。
- `resolver.py`：`SpatialResolver` 统一入口，绑定 `PlanningContext`，
  提供 `resolve_text` / `resolve_spec`（PARSE 闭集规格）/
  `resolve_anchors` / `bind`；模块级 `resolve_intent_anchors` 供 parse/agent 委托。
- `bundle_binder.py`：`DeterministicBundleBinder` 按 BSM 优先确定性绑定
  bundle 不可变几何，输出 bound_spatial_entities FeatureCollection。

## 输入输出契约

- 输入：`PlanningContext`（bundle/gazetteer/KG/constraint_index/kg_query_fn）。
- `ResolvedSpatialDescription`：candidate_bsms / candidate_bbox / evidence_text /
  query_path / confidence / unresolved_reason。
- `resolve_spec -> ResolvedSpatialRef`（final_bsms/bbox/confidence/provenance）。
- `bind -> FeatureCollection`（binding_status: confirmed/candidate/unresolved）。
- kg_query_fn 由调用方注入，spatial_ops 不直接 import kg。

## 依赖方向

- 依赖 `app.utils`（geo_utils/crs_engine）与 `app.modules.schema` 契约类型。
- 复用 `app.modules.spatial_ops.geometry` 与 `index`（ConstraintIndex）。
- 依赖 `app.modules.context.planning_context.PlanningContext`。
- **禁止** import `app.agent` / `app.services` / `app.api`。

## 禁止行为

- 禁止修改 bundle / gazetteer / KG（只读解析）。
- 禁止写死村庄名或中心点兜底（由调用方注入）。
- 禁止在 KG 候选存在时忽略约束排除/方向精化。
- 禁止直接耦合 LLM 工具层（resolve_place 结果通过参数传入）。
