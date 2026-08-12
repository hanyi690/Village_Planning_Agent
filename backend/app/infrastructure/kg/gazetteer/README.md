# KG Gazetteer — 村名 → 空间实体解析

> **定位**：KG 子模块中的**地名解析能力**——把村名/地名解析为空间实体（居民点聚类 / 地块集）。agent 层（Binder / EXPLORE / 渲染）只消费本能力，不自行解析。

---

## 职责边界

**负责**：
- 构建与加载村名 gazetteer：`build_gazetteer` / `load_gazetteer` / `save_gazetteer`
- 解析匹配：精确 → `difflib` fuzzy（ratio ≥ 0.6）→ Flash LLM 判定 + **双确认**（LLM 判定 ∧ 空间校验）
- 空间校验：村名特征 vs 聚类地块 dlbm 构成（`spatial_check` / `spatial_score`）
- 持久化：`data/gazetteer/{village}.json` 主文件 + 轮次增量写入 memory 轮次文件

**不负责**：
- 不解析一般自然语言空间描述（方向/BBox 接地是 `spatial_ops/grounding`）
- 不做 POI 地理编码（那是 `data/providers` / `data/catalog`）
- 不构建 KG 实体（那是 `builder/`）

---

## 输入/输出契约

**数据源**（全部系统内）：
1. KG `ResidentialCluster`（SPARQL：聚类名/质心/sfWithin 地块集）
2. bundle 村名注记（point-in-boundary 过滤村外行政村）
3. `SemanticMemoryStore` 注解（L1 语义回流产物：村名→BSM）

**导出 API**（`gazetteer/__init__.py`）：`Gazetteer` / `GazetteerEntry` / `build_gazetteer` / `load_gazetteer` / `save_gazetteer` / `confirm_with_llm` / `spatial_check` / `spatial_score`。

**消费方**：`app.services.context.build_planning_context` 经 `load_gazetteer` 载入；`KGGazetteerAdapter`（`kg/adapters/`）包装为 `GazetteerPort` 注入 `PlanningPorts`。

---

## 依赖方向

```
gazetteer/ → modules/kg（queries.sparql / memory）、schema/contracts、app.utils
   ▲ 被 services/context、kg/adapters、agent 消费
```

- 允许：`modules/kg` 内部、`schema/contracts`、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`；不依赖外部地图 API

---

## 禁止行为

- 在 gazetteer 内做几何计算（空间校验只调用既有空间能力）
- 村名绑定缺少双确认（LLM 判定 ∧ 空间校验）即写入
- 依赖外部地名库/API（地名解析必须基于系统内 KG + bundle 数据）
- 修改持久化格式而不同步轮次增量写入机制（round / diff / supersede）
