# spatial_ops.conflict — 跨维度冲突检测与优先级消解

## 职责边界

- `detector.py`：基于语义限定符的跨维度冲突检测（`ConflictDetector`），
  检测三类冲突：
  1. 指标冲突 `detect_metric_conflicts`（同一概念+同一语义、值不同，超过
     相对阈值 DEFAULT_RELATIVE_THRESHOLD=0.05 即报）。
  2. 约束违建 `detect_constraint_violations`（PLANNED_TARGET 超出
     CONSTRAINT_UPPER/LOWER）。
  3. 空间结构冲突 `detect_spatial_conflicts`（spatial_structure 与 industry
     的区划数量不一致 >=2）。
  通过 `CROSS_DIMENSION_METRICS` 注册表判断哪些字段跨维度代表同一规范概念。
- `resolver.py`：按维度优先级消解（`ConflictResolver`）——指标冲突取高优先级
  维度值；约束违建自动下调到约束值或标记人工复核；空间冲突取高优先级维度结构。
  优先级见 `METRIC_PRIORITY` / `SPATIAL_PRIORITY`。

## 输入输出契约

- 输入：`summaries = {dimension_key: {"metrics": {...}, "summary": ...}}`
  （支持扁平与嵌套两种格式）。
- `detect_all -> ConflictReport`：metric_conflicts / constraint_violations /
  spatial_conflicts，含 `has_conflicts` / `summary()`。
- `resolve(ConflictReport) -> ResolutionReport`：metric/constraint/spatial
  三类 resolution，`resolved_values` 汇总消解后指标值。
- 依赖 `app.modules.parsing.semantics`（CROSS_DIMENSION_METRICS/FieldRef/
  MetricConcept/ValueSemantics/get_comparable_fields）。

## 依赖方向

- detector 被 resolver 消费；两者被 L2/L3 维度汇总链消费。
- 依赖 `app.modules.parsing.semantics` 与 `app.modules.schema`。
- 不依赖 agent / services / api 层。

## 禁止行为

- 禁止比较语义不同的字段（须按 ValueSemantics 分组后比较）。
- 禁止自动修改原始维度汇总（消解只输出建议值，不写回输入）。
- 禁止对 constraint 违建直接放行（必须 adjust 或 flag_for_review）。
- 禁止在 resolver 中引入新的冲突判定逻辑（只消解 detector 输出）。
