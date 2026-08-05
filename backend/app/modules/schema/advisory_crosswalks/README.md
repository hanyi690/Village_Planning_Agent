# Schema Advisory Crosswalks — 跨系统建议映射（隔离）

> **定位**：跨编码体系的**建议性**映射表与查询函数（DLBM→zone_type、DLBM→planning_zone、GHYTBM→VNE、zone_type→planning_zone…），与同系统 code sets **物理隔离**。
> **Wave A.1 约束**：映射式规划链 **FAIL-CLOSED** 默认关闭，仅比较测试可显式开启；输出必须标记为非规划结果。

---

## 职责边界

**负责**：
- `crosswalks.py`：跨系统映射表 + 查询函数（从 `encodings.code_sets` 隔离出来，避免 cross-system 推导泄漏进同系统 code sets）
- `legacy.py`：显式 legacy 开关（`legacy_enabled` / `require_legacy` / `LegacyBlocked` / `legacy_marker`）
- `registry.py`：advisory-only 建议引擎（DLBM → zone_type / planning_zone / primary_zone，供参考与 prompt 表）

**不负责**：
- 不参与默认规划链（绝不用现状地类推导规划决策）
- 不暴露给 LLM（`lookup.py` 工具已移除 `map_code`）
- 不做同系统 code→name 定义（那是 `encodings/code_sets.py`）

---

## 输入/输出契约

**导出**（`advisory_crosswalks/__init__.py`）：`DLBM_TO_ZONE_TYPE` / `DLBM_TO_PLANNING_ZONE` / `ZONE_TYPE_TO_DLBMS` / `GHYTBM_TO_VNE` 等映射 + `legacy_enabled` / `require_legacy` / `LegacyBlocked` / `legacy_marker`。

**数据**：YAML 数据位于 `advisory_crosswalks/yaml/`，由 `DictionaryCenter` 扫描，`get_center().get(...)` / `get_mapping(...)` 可查。

---

## 依赖方向

```
advisory_crosswalks/ → schema/encodings（少量同系统 code sets）、schema/provenance、app.utils
   ▲ 被 data/encoding_detector 等显式 advisory 场景消费
```

- 允许：`schema` 内部、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`（工具层 `lookup.py` 已不暴露跨系统映射）

---

## 禁止行为

- 把 cross-system 推导混入 `encodings/code_sets.py`（隔离是本目录存在的意义）
- 默认链使用 advisory 映射推导规划决策（必须 FAIL-CLOSED，需 `legacy_enabled`）
- 把映射表喂给 LLM / prompt（LLM 只接受同系统 lookup）
- 新增映射不登记 `__init__.py` 导出（`DictionaryCenter` 扫描依赖此约定）
