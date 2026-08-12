# KG Enrichment — 报告 → KG 多级语义增强

> **定位**：把维度报告（L1 现状 / L2 意图 / L3 项目）的语义回流进 KG，为实体与关系生成**可注入描述与量化注记**。
> **Updated: 2026-08-05**

---

## 职责边界

**负责**（三个 wave 对应三层回流）：
- **L1（wave1）**：村名 → gazetteer 绑定（Flash 双确认 + 空间校验）→ `EntityAnnotation(cluster_uri)`；批量实体描述快照
- **L2（wave2）**：功能分区实体注解 + 关系注记
- **L3（wave3）**：项目/功能区实体注解
- **按需**：`describe_entity` 动态合成（属性 + 邻接注入）

**不负责**：
- 不构建 KG 基础实体（那是 `builder/`）
- 不做查询（那是 `queries/`）
- 不 import agent 编排逻辑（逻辑迁自 `parse/agent.py extract_bindings`，现已在模块内）

---

## 输入/输出契约

**入口**（`enrichment/__init__.py` 导出）：

| 函数 | 说明 |
|---|---|
| `extract_bindings` / `run_wave` | 报告实体绑定（`bindings.py` 为兼容转发，新代码用 `report_entity_enrichment`） |
| `describe_entity` / `describe_parcels` | 动态实体描述 / 批量地块描述（`descriptions.py`） |
| `annotate_cluster_relations` / `annotate_parcel_protection` | 关系语义注记（`relations.py`） |

**文件清单**：

| 文件 | 职责 |
|---|---|
| `report_entity_enrichment.py` | 多级增强入口（L1 村名绑定 + L2/L3 表格语义注解） |
| `bindings.py` | 兼容转发（旧路径 `extract_bindings`） |
| `descriptions.py` | 动态三源注入：属性 + 邻接关系 + 静态要素；`describe_parcels` 批量快照 |
| `relations.py` | `RelationAnnotation` 批量生成（聚类 sfWithin / 地块 located_in / 设施 serves） |

**输出**：`EntityAnnotation` / `RelationAnnotation`（写入 `SemanticMemoryStore`，`kg/memory.py`）。

---

## 依赖方向

```
enrichment/ → modules/kg（memory / builder / gazetteer）、schema/contracts、app.utils
   ▲ 被 KG builder / L1 回流节点 / agent 语义增强节点消费
```

- 允许：`modules/kg` 内部、`schema/contracts`、`app.utils`
- 禁止：`agent` / `services` / `api` / `tools`（仅作为被调用方，不反向 import）

---

## 禁止行为

- 在 enrichment 内做几何计算（算力在 `spatial_ops`，KG 只存结果）
- 直接改 RDF 三元组承载量化属性（数值必须进 `SemanticMemoryStore`）
- 新代码走 `bindings.py` 兼容路径（应使用 `report_entity_enrichment`）
- LLM 判定（Flash）不配合空间校验即写入绑定（村名绑定必须双确认）
