# Schema Provenance — 溯源审计

> **定位**：编码体系溯源（ProvenanceSource）与审计记录（AuditEntry）的类型定义——回答"某个 DLBM/GHYTBM 编码从哪个体系而来"。

---

## 职责边界

**负责**：
- `ProvenanceSource` 枚举：编码来源体系（`GBT21010` / `PRACTICAL_APPENDIX5` / `TUGUI` / `VNE` / `DERIVED_DLBM_TO_GHYTBM` / `DERIVED_DLBM_TO_ZONE_TYPE` 等）
- `ProvenanceAudit` / `AuditEntry`：审计记录模型

**不负责**：
- 不做编码转换 / 映射（那是 `encodings/` 与 `advisory_crosswalks/`）
- 不做解析（模块 `schema/contracts/provenance.py` 的 `Provenance` 是跨层契约，与此不同）

---

## 输入/输出契约

**导出**（`provenance/__init__.py`）：`ProvenanceSource` / `ProvenanceAudit` / `AuditEntry`。

**消费方**：`data/encoding_detector.py`（检测 DLBM 形值属于哪个编码体系 → `ProvenanceSource`）、`advisory_crosswalks`。

---

## 依赖方向

```
provenance/ → 标准库（dataclasses / enum）
   ▲ 被 data/encoding_detector、advisory_crosswalks 消费
```

- 允许：标准库、`app.modules.schema` 内部
- 禁止：`agent` / `services` / `api` / `tools`、`data`、`kg`

---

## 禁止行为

- 把溯源类型与契约 `provenance.py`（跨层 `Provenance`）混用——二者用途不同
- 在溯源模型内放计算逻辑
- 新增编码体系不登记 `ProvenanceSource`（溯源会缺失）
