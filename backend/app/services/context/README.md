# Services Context — 规划上下文工厂

> **定位**：应用层（`app.services`）的**会话规划上下文工厂**——`build_planning_context`，把领域模块（bundle / KG / gazetteer / constraint index / anchors / reports）组装进版本化 `PlanningContext` 并缓存。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**（单一异步构建路径）：
- 构建会话权威 `PlanningContext`：bundle + 会话 KG + gazetteer + constraint index + village anchors + reports，**构建一次跨 EXPLORE / PARSE / GROUND / LAYOUT 复用**
- 进程内缓存（`_context_cache: {session_id -> PlanningContext}`）+ 单调版本计数（`_build_counter`，每次 rebuild `version+1`）
- 注入依赖倒置端口：`KGGazetteerAdapter` / `KGSpatialQueryAdapter` / `DataBundleAssemblyAdapter` → `PlanningPorts`
- 失效：`invalidate_planning_context` 丢弃缓存，下次构建为全新版本

**不负责**：
- 不定义 `PlanningContext` 数据结构（那是 `modules/context/planning_context.py`）
- 不做领域计算（全部委托 modules：`services.session_bundle` 构建 bundle、`services.session_kg` 确保 KG、`spatial_ops.build_constraint_index` 约束索引、`kg.queries.sparql.query_kg` 锚点）

---

## 输入/输出契约

| 入口 | 签名 | 输出 |
|---|---|---|
| `build_planning_context` | `(session_id, village_name="", refresh=False, include_reports=True)` | 版本化 `PlanningContext`（永不为 None，字段可空） |
| `get_cached_context` | `(session_id)` | 缓存 context 或 None |
| `invalidate_planning_context` | `(session_id)` | None（清缓存 + 版本计数） |

**设计要点**：bundle 缓存在 `session_bundle`；session KG 在 `KGManager` 幂等；本工厂只组装派生部分（gazetteer / constraint index / anchors / kg_query_fn / ports）。`include_reports=False` 用于纯空间引导（跳过 DB I/O）。

---

## 依赖方向

```
services/context → modules/context（PlanningContext）、modules/ports（PlanningPorts）
                → services/session_bundle、services/session_kg、services/report_store
                → modules/kg（manager / gazetteer / adapters / queries）、modules/spatial_ops、modules/data（bundle_assembly_adapter）
```

- 允许：`modules/*`、`services/*`、`app.utils`
- 禁止：`api` / `tools`（作为应用层粘合，它协调 modules，但领域模块不得反向依赖它）

---

## 禁止行为

- 在工厂内实现领域算法（bundle/KG/索引构建必须委托 modules）
- 让领域模块 import 本服务（方向是 services → modules）
- 缓存无版本控制（消费者须按 `version` 建键）
- 任何一步失败即抛异常阻断主流程（设计为：失败告警 + 字段留空 + 返回 context）
