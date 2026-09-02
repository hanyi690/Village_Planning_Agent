# infrastructure/kg 知识图谱适配

> 本 README 以 `backend/app/infrastructure/kg/` 实际代码为准（核验日期 2026-08-15）。
> 旧文档中的 `app/infrastructure/kg` / `app.kg` 路径已不存在；本包是 KG 的唯一实现位置。

## 定位

规划知识图谱（PlanningKG）的构建、存储、查询与富化适配：把已准入 DATA catalog 的
空间事实投影为 RDF 图（rdflib）+ SemanticMemoryStore，提供 SPARQL/
模板查询给分析/接地/执行阶段使用。

## 目录职责

| 目录/文件 | 职责 |
|---|---|
| `builder/` | KGBuilder 组合式构建：`base.PlanningKG`、`builder.KGBuilder`、`registry`（BuildContext/BuilderSpec）、`layer1_core`/`layer1_extended`/`layer1_control_lines`、`layer2`/`layer3`/`layer4`、`entity_cluster_topology`、`enrichment` 挂载点 |
| `service.py` | `build_knowledge_graph_data`：从 bundle 构建 KG 数据 |
| `manager.py` | 会话级 KG 生命周期、缓存与 DATA digest 绑定 |
| `manager.py` | `KGManager` + `CacheKey.compute_layer1_cache_key` + LRU 缓存 |
| `queries/` | 查询层：`contracts`、`semantic`、`cognition`、`execute_queries`、`spatial_ref`、`sparql`；顶层 `__init__` 导出 `query_kg`/`get_entity_context`/`get_parcel_semantic_context` 等 |
| `enrichment/` | 富化：`bindings`、`descriptions`、`relations`、`report_entity_enrichment` |
| `gazetteer/` | 地名词典适配 |
| `adapters/` | `gazetteer_adapter`/`semantic_query_adapter`/`spatial_query_adapter`（实现 contracts/ports） |
| `ontology.py` | `PLN`/`GEO` 命名空间、EntityTypes、Relations、SemanticPredicates、GeoPredicates |
| `memory.py` | `SemanticMemoryStore`（关系量化属性） |
| `interface.py` | `open_kg_session`/`query_session_sparql`/`query_session_template`/`require_session_kg`/`close_kg_session`（stage-0 稳定边界） |
| `dlq.py` | 死信队列分类（DlqCategory/DlqEntry/DlqReport） |
| `process_worker.py` | 构建进程 worker |

## 边界规则

- KG 只存空间实体及其关系；几何计算在 `app/spatial/`，KG 只存计算结果。
- RDF 存纯关系，量化细节存 `SemanticMemoryStore`。
- KG 是事实/意图/成果的语义索引，不是工作流状态容器，也不是所有空间计算的替代品。
