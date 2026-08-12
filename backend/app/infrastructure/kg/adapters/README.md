# KG Adapters — 端口实现适配器

> **定位**：KG 侧对 `app.modules.ports` 各 Protocol 的**实现**。每个适配器把 KG 子模块包装在端口背后，使 agent / spatial_ops 层只依赖端口接口而非 KG 实现。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：实现由 `modules/ports/` 定义的依赖倒置端口，桥接 KG 能力与消费方。

**不负责**：
- 不定义端口（端口定义在 `ports/`）
- 不做端口之外的业务逻辑（薄适配）
- 不 import `app.agent` / `app.services` / `app.api` / `app.tools`

---

## 输入/输出契约

| 文件 | 类 | 实现端口 | 核心方法 |
|---|---|---|---|
| `gazetteer_adapter.py` | `KGGazetteerAdapter` | `GazetteerPort` | `resolve(run_id, name, fuzzy=False)` → `GazetteerEntryLike \| None`（包装 `kg/gazetteer`） |
| `spatial_query_adapter.py` | `KGSpatialQueryAdapter` | `SpatialQueryPort` | `query_by_bbox` / `query_by_geometry` / `compute_overlap` / `nearest_features` / `resolve_candidates`（包装会话 KG） |

**注入路径**：`app.infrastructure.context.planning_context_factory` 的 `build_planning_context` 在构建 `PlanningPorts` 时实例化这两个适配器（gazetteer 非 None → `KGGazetteerAdapter`；kg 非 None → `KGSpatialQueryAdapter`）。

---

## 依赖方向

```
kg/adapters/ → modules/ports（实现接口）、modules/kg（gazetteer / 会话 KG）、schema/contracts
   ▲ 被 services/context 注入到 PlanningPorts，供 spatial_ops / agent 层消费
```

- 允许：`modules/ports`、`modules/kg` 内部、`schema/contracts`（`GazetteerEntryLike` / `SpatialReferenceSpec` / `CandidateSet`）
- 禁止：`agent` / `services` / `api` / `tools`

---

## 禁止行为

- 在适配器内复刻 KG 业务逻辑（应调用 kg 子模块既有能力）
- 让消费方直接 import 适配器（消费方应只依赖端口类型）
- 适配器持有长生命周期状态 / 单例（实现应可注入、可替换）
