# Tools GIS _validation — 布局校验

> **定位**：GIS 布局校验内部子目录——设施选址验证与生态敏感性评估。**薄适配，算法不含规划决策逻辑**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：
- `facility_validator.py`：设施选址验证（`validate_facility_location`）与生态敏感性评估（`assess_ecological_sensitivity`）

**不负责**：
- 不做冲突检测（`_conflict/` 已移除 → `modules/spatial_ops/conflict`）
- 不做完整 8 项 validate_aggregate 检查（那是 `agent/validate/aggregate`，`validate.py` @tool 合并调用）

---

## 输入/输出契约

**导出**（`_validation/__init__.py`）：`validate_facility_location` / `assess_ecological_sensitivity`。

**facility_validator.py 内部**：`_analyze_coverage` / `_check_facility_proximity` / `_check_constraint_zones` / `_check_protection_zones` / `_check_hazard_zones` / `_get_suitability_level` / `_generate_facility_recommendations`；生态侧 `_classify_sensitivity` / `_generate_ecological_recommendations`；`format_validation_result` 格式化。

---

## 依赖方向

```
_validation/ → modules/schema（类型/编码）、app.utils、modules/spatial_ops（约束索引/几何，经端口或直接契约）
   ▲ 被 tools/gis/validate.py（validate_layout @tool）与 API 校验流程消费
```

- 允许：`modules/*`、`app.utils`
- 禁止：`agent` / `services` / `api`；不实现冲突检测算法

---

## 禁止行为

- 在 facility_validator 内复刻冲突检测（统一在 `modules/spatial_ops/conflict`）
- 输出未经格式化的原生 dict 给 LLM（应走 `format_validation_result`）
- 引入规划决策逻辑（本子目录只做校验与评分）
