# spatial_ops.zoning — 词汇表驱动自定义功能分区

## 职责边界

- 基于词汇表 + 规划意图生成 L4 FunctionalZone 自定义功能分区。
- `custom_zone_generator.py`：`CustomZoningGenerator`。输入 parcels + intent
  （vocabulary / custom_zone_targets）+ 三线图层，输出带 provenance 的
  FunctionalZone feature；支持 BSM 直接指定、规则自动选地块（`_select_by_rules`
  走统一 expr_eval DSL）、面积目标对齐（`_truncate_by_area`）与补足
  （`_supplement_by_area`，命中不足时补至 ±30%）；建设类分区做三线图斑级拦截。
- `vocab_rules.py`：规则 DSL 统一——`rule_to_condition(TypingRule) -> Condition`、
  `parcel_to_context(parcel) -> MappingContext`、`evaluate_rules`（any-of 语义）。
  消除 generator 中重复的 _eval_rule 双实现。
- `vocab_context.py`：地块多因子上下文（B3）——`build_parcel_contexts`：
  dlbm/area_ha/slope_deg(DEM 栅格坡度)/road_distance_m/zone_membership/poi_hits；
  因子缺失降级（slope=999、road=99999）。
- `custom_planning.py`：将词汇表生成器输出整合为村庄级唯一、互斥、覆盖完整的
  规划分区图层——`build_custom_zone_allocation_inputs`（含"待确认分区"补齐）、
  `build_custom_planning_zone_layer`（合并/去飞地/去重叠）、
  `validate_custom_planning_zone_layer`（重叠与连续性校验）。

## 输入输出契约

- 输入：parcels（dict，含 bsm/geometry/dlbm/area_ha）、intent（vocabulary_name
  或 session 级 vocabulary + custom_zone_targets）、three_lines。
- 输出：L4 FunctionalZone feature dict（entity_type="FunctionalZone"，
  pln:* 命名空间，含 provenance）；`generate_with_validation` 返回
  (zones, ProvenanceAudit)。
- 契约类型来自 `app.modules.schema.contracts.custom_zone_contracts`
  （Vocabulary/VocabularyCategory/CustomZoneTarget/TypingRule）与
  `expr_eval.Condition/MappingContext`。

## 依赖方向

- 依赖 `app.modules.schema`（contracts、vocabularies.loader、
  encodings.dicts.expr_eval、provenance）与 shapely。
- 本包内部：generator ← rules ← context；custom_planning 消费 generator 输出。
- 被 L4 合成链与 allocation 消费。

## 禁止行为

- 禁止绕过 expr_eval 手写规则求值逻辑。
- 禁止在未命中任何规则时静默分配地块到主题分区（须走"待确认分区"）。
- 禁止将三线保护地块并入建设类功能分区。
- 禁止修改输入 parcels / bundle（只读生成）。
