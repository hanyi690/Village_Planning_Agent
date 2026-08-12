# Context — 会话规划上下文（纯数据）

> **定位**：一个会话的**版本化事实权威**——`PlanningContext` dataclass（`modules/context/planning_context.py`），纯数据容器，无业务逻辑、无 I/O。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**：持有并对外提供单个规划会话的权威事实视图：
- `bundle`（会话级 `VillageBundle`，可能为 None）
- `kg` + `kg_session_ref` + `kg_version`（会话 KG 与变更版本号）
- `gazetteer` / `constraint_index`（村名地名册 / 约束索引）
- `village_anchors`（预计算的 `get_village_anchors` 行）
- `reports` + `report_summary_index`（L1/L2/L3 报告内容与摘要索引）
- `kg_query_fn`（绑定会话 KG 的查询函数，供 `spatial_ops` 使用而不 import KG）
- `ports`（注入的 `PlanningPorts`，见 `ports/README.md`）

**不负责**：
- 不构建任何数据（构建工厂在 `app.services.context.planning_context`）
- 不做 LLM 调用 / 数据库读写 / 几何计算
- 不持有 agent / LangGraph State
- 不注册单例 / 不管理生命周期（缓存由调用方 `services/context` 管理）

---

## 输入/输出契约

**输入**：由 `app.services.context.build_planning_context(session_id, village_name, refresh, include_reports)` 构建并注入。

**输出**（`PlanningContext` 属性，均只读/惰性访问）：

| 属性 | 类型 | 说明 |
|---|---|---|
| `session_id` / `village_name` | `str` | 会话标识 / 已解析村名（绝不用 "jintian" 兜底） |
| `version` | `int` | 单调构建版本，每次 rebuild +1 |
| `bundle` | `VillageBundle \| None` | 会话数据束 |
| `kg` / `kg_session_ref` / `kg_version` | — | 会话 KG 与变更版本（缓存失效键） |
| `gazetteer` / `constraint_index` | — | 地名册 / 约束索引（可能 None） |
| `village_anchors` | `list[dict]` | 预计算锚点 |
| `reports` / `report_summary_index` | `dict` | `{dim_key: {content, instruction, ...}}` / `{dim_key: {summary, ...}}` |
| `kg_query_fn` | `Callable \| None` | `(template_name, **params) -> list[dict]` |
| `ports` | `PlanningPorts` | 注入的依赖倒置端口 |

**便捷 API**：`has_workspace` / `has_kg` / `current_parcels()`（现状地块列表）/ `snapshot_meta()`（无几何的可序列化元数据）。`SessionDataSnapshot` 与 `SpatialWorkspace` 属于 data/spatial owner；Artifact descriptor 不注入 PlanningContext。

**版本化规则**：消费者凡缓存派生几何/查询结果，**必须按 `version` 建键**，防止陈旧 context 被误当作新 context。

---

## 依赖方向

```
services/context（工厂，构建+缓存+绑定）
        │  注入
        ▼
modules/context.planning_context.PlanningContext
        │  依赖
        ├── modules/ports.planning_ports（PlanningPorts）
        └── （持有 kg / bundle / gazetteer / constraint_index / ports 引用，但不 import 其实现层）
```

- 允许：`app.modules.ports`、标准库 + `dataclasses` + `typing`
- 禁止：`app.agent` / `app.services` / `app.api` / `app.tools` —— **模块头注释即强制此规则**

---

## 禁止行为

- 在 `context/` 内 import `app.agent` / `app.services` / `app.api`（构建逻辑只允许在 `services/context` 侧）
- 让 context 参与业务计算 / 变更自身状态（它不是缓存服务，只是数据容器）
- 不按 `version` 建键缓存派生结果（会引入陈旧事实）
- 依赖 `kg_query_fn` 时捕获 `None`（KG 未就绪时静默降级，不抛异常）
