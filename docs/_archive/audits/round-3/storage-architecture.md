# 存储架构综合设计与参考调研

> 日期：2026-08-12
> 目的：针对用户问题"KG 和 bundle 数据的存储有参考吗？考虑项目所有数据存储"，综合 LangGraph 官方设计 + RDFLib 持久化实践 + 当前代码实测，给出分层存储架构决策。

## 1. 现状实测（严重问题）

### 1.1 单一大 DB 17.4GB（P0）
`data/database/village_planning.db`（17.4GB）混合：
- LangGraph `checkpoints` 表 ~11.5GB + `writes` 表 ~5.3GB（**16.8GB，占 96%**）
- 业务表：`planning_bundles`(49行/536MB)、`dimension_reports`、`run_events`、`planning_sessions`、`uploaded_files`、`step_reports`、`context_version`(raw sqlite 创建)
- WAL 17.4GB 文件 = 备份/压缩灾难；checkpoint 增长无 retention

### 1.2 KG 完全不持久化（P0，用户焦点）
- Session KG 是**纯内存 RDFLib** `Graph()`（`app/modules/kg/builder/base.py:26-33`）
- `to_turtle()` 只用于进程池 IPC 和塞进 workflow state 字符串，**从不写 `.ttl`/`.nt` 文件**
- **每次进程重启/resume 都从 bundle 重建整个 KG**（O(n²) parcel relations），仅靠进程内 Layer-1 LRU（进程死了就丢）
- 唯一持久化 KG 数据：`data/kg_memory/{session_id}_round_*.json`（语义标注 round）
- KG 可变、无 triple digest、无内容寻址——与 CAS artifact 层形成鲜明对比

### 1.3 Bundle 无 digest 校验（P0，用户焦点）
- `planning_bundles` 表存 536MB `bundle_json` TEXT，有 `sha256` 列但 `load_bundle`/`deserialize`（`app/infrastructure/storage/bundle_store.py:114-132`）**从不校验存储的 sha256 与内容是否一致**
- 大 blob 存 SQLite TEXT 列（不适合大对象）

### 1.4 Session 删除不清理全部存储（P1）
未清理：`_EVIDENCE_CACHE`、`_PROVIDER_FAILURE_SESSIONS`、`data/kg_memory/*.json`、**CAS artifact store**（`.run-tmp/blobs|descriptors|runs/<session>/...` 全不删，只用相对 `.run-tmp` rmtree session 子目录）

### 1.5 进程全局单例 vs spawn worker（P1）
KGManager、context cache、bundle cache、event hub 均进程全局；KG 构建在子进程重建全图只为序列化 turtle。

### 1.6 上传文件存 DB 列（P1）
GeoJSON→JSON 列、文档→TEXT 列；无文件系统后端。

## 2. 外部参考（exa + context7）

### 2.1 LangGraph 官方（context7）
- **Checkpointer = 权威 per-superstep 状态日志（WAL 模拟）**；**state schema 规则**：只放 routing + LLM 推理 artifacts，大对象用 ID 引用，单 checkpoint >50KB 应外置。
- **两套存储分离**：checkpointer（LLM 工作上下文，可变、可压缩）vs **你自己的 append-only 表**（UI/审计源，永删）——"UI 不应从 checkpointer 读"。
- **长期记忆** = `BaseStore`（PostgresStore/InMemoryStore，namespace key-value，跨线程）。KG 语义记忆可映射到此模式，但 KG 三元组不是简单 KV，需 RDF 持久化。

### 2.2 RDFLib 持久化（exa）
- **`rdflib-sqlalchemy`**：SQLAlchemy 后端的 RDFLib store，支持 SQLite/MySQL/PostgreSQL，按 asserted/type/quoted 分区建表 + 索引。把内存 KG 持久化的**自然路径**。
- **`brickschema.PersistentGraph`**：`PersistentGraph("sqlite:///mygraph.sqlite")` 直接 SQLite 存 RDF 图；`VersionedGraphCollection` 提供 undo/redo、checkout 版本、事务提交钩子。
- **uderia 双架构**：SQLite 持久化层 + NetworkX 内存算法层（懒加载 + 写失效缓存）——正是本项目的模式，只是缺 SQLite 持久化层。
- **RDF vs property graph**（Neo4j）：RDF 适合语义/本体/互操作（本项目 03_KG_SEMANTIC_BRIDGE 正是语义桥接，RDF 合理）；property graph 适合应用开发。

## 3. 推荐分层存储架构

### 3.1 四个物理存储区（分离职责）
| 存储区 | 内容 | 位置 | 依据 |
|---|---|---|---|
| **A. LangGraph checkpoints** | `checkpoints`+`writes` | **独立文件** `data/database/checkpoints.db` | 官方"checkpointer 是权威状态日志"，与业务表分离；可独立压缩/retention |
| **B. 业务 SQLite** | sessions/bundles(meta)/reports/events/uploads(meta) | `data/database/village_planning.db` | 官方"你的 append-only 表" |
| **C. CAS 文件 store** | artifact blobs/descriptors/refs；**KG turtle**；**bundle blob**；上传原文件 | `.run-tmp/`（CAS blobs） | 已有；内容寻址 + digest 校验 + 不可变 |
| **D. 长期记忆/语义记忆** | kg_memory rounds、gazetteer、跨 session facts | `data/kg_memory/` → 可映射 LangGraph `BaseStore` | 官方长期记忆 |

### 3.2 KG 持久化决策（用户焦点）
**方案：把 session KG 的 Layer-1 turtle 作为 CAS artifact 持久化，resume 时按 ref 加载而非重建。**

理由：
- 蓝图"KG 只做语义索引，不替代几何引擎"；Layer-1 由 bundle 确定性构建（keyed by `village_name+landuse_hash`），**只需构建一次**
- 会话内变异（intent layer、planned state）已通过 `planning_program`/`planned_state` artifacts 表达，不必落 KG 存储
- 引入 `rdflib-sqlalchemy`/`PersistentGraph` 是更重的持久化（增删改事务），但本系统 KG 是**读多写少、每次 session 重算**——CAS turtle blob 更轻、与现有 artifact 体系一致
- 渐进路径：如未来需要增量更新/跨 session 共享，再升级为 `PersistentGraph("sqlite:///...")`

**决策点**：Layer-1 turtle 存 CAS blob（key `kg_layer1`，parent = bundle ref），`ensure_session_kg` 先查 ref 命中则 from_turtle，未命中则构建后 persist。

### 3.3 Bundle 存储决策（用户焦点）
- `planning_bundles` 表保留**元数据**（session_id、version、sha256、ref），`bundle_json` 大 blob **移到 CAS blob**（`bundle` key）
- `load_bundle` 读取时**校验 sha256 == recomputed**，不一致则 fail-closed 或重建
- 上传文件同样：DB 存 meta，内容入 CAS

### 3.4 Checkpoint 拆分（P0）
- `get_global_checkpointer()` 改为独立 DB 文件 `checkpoints.db`
- 加 retention（按 thread_id 压缩旧 checkpoint，参照官方"run 结束 copy 最终态到 runs 表，prune 中间 checkpoint"）
- 业务表不再被 checkpoint 膨胀

### 3.5 删除清理（P1）
- session delete 补充：`_EVIDENCE_CACHE`、`_PROVIDER_FAILURE_SESSIONS`、`kg_memory/*.json`、CAS refs（`runs/<session_id>/` 下）
- 用 `run_tmp_root()` 而非相对 `.run-tmp`

### 3.6 多进程（P1）
- 进程全局单例标记为 per-loop/session 作用域；KG 构建子进程改为从 CAS blob 读（不重建全图）

## 4. 执行优先级
1. **P0-a** checkpoint 独立 DB + retention（解决 17.4GB）
2. **P0-b** KG Layer-1 turtle 入 CAS + resume 按 ref 加载（解决重建 O(n²)）
3. **P0-c** bundle blob 入 CAS + sha256 校验
4. **P1** session delete 补全清理 + 上传文件入 CAS + 单例作用域

## 5. 不在本次范围
- RDFLib→rdflib-sqlalchemy/PersistentGraph 完整持久化升级（渐进路径，观察 CAS turtle 是否足够）
- Postgres 生产化部署（开发保持 SQLite）
- Chroma 向量库（RAG，独立）
