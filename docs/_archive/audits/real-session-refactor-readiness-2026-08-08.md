# Real Session 重构后执行前审计

日期：2026-08-08

本记录明确区分“静态修复”与“真实执行证据”。本轮已经启动一次真实 LLM + 真实 GIS Session；该次运行在 GROUND 进入 HUMAN，未伪称为完整成功。

## 已修复的实现断点

| 断点 | 当前修复 | 证据 |
|---|---|---|
| PARSE 丢弃无 BSM 空间规格 | 保留原始规格并把缺证据交给 GROUND Gate | `post_l3_main_nodes.py` |
| L1/KG 事实链不可见 | L1 StepReport 增加 `kg_evidence_produced`；L2/L3 增加父 artifact 输入引用 | `l1_observe/aggregate.py`、`l2_strategize/aggregate.py`、`l3_plan/aggregate.py` |
| ArtifactRef 重启后身份不完整 | manifest/ref 往返 `context_fingerprint` 与 `checksum`，加载时交叉校验 | `artifact_store.py`、`artifact_runtime.py` |
| DELIVER 没有真实文件渲染 | DELIVER 生成 session-scoped PNG 与自包含 HTML；渲染缺失阻断 PASS | `post_l3_main_nodes.py` |
| P1 运行产物互相污染或被 pytest 删除 | 使用 `BACKEND_RUN_TMP_DIR`，每次真实测试创建唯一工作区目录 | `run_paths.py`、`test_real_llm_session_full.py` |
| POST 后立即读状态造成竞态 | 真实测试增加 45 秒 checkpoint 轮询 | `test_real_llm_session_full.py` |
| graph replay 通过后 pytest 不退出 | replay fixture 注入已编译 EXECUTE 子图，禁止测试路径隐式初始化全局 AsyncSqliteSaver；并为 replay 使用唯一 run tmp | `test_unified_graph_replay_e2e.py` |
| graph 构建触发重型 transformers/torch 导入 | conversation router 延迟导入 prompt、tool 和 runnable 类型，仅在实际对话节点调用时加载 | `conversation_router/node.py` |
| L1/KG 没有消费上传 GIS 的中文 extra 属性 | GIS 特征是 Pydantic `extra=allow`，村名可能位于 `地质灾害点名称` 等别名字段；绑定扫描此前只看 `name/label` | `report_entity_enrichment._feature_text` 现在读取 `_raw`、`model_dump(by_alias=True)` 与额外字段，并保留原始证据 |
| 缓存 context 在 L1 完成后丢失 location facts | `_require_context` 只在进程重启时重新 hydrate；正常缓存命中时 GROUND 看到空 `location_facts` | 每次 post-L3 context load 都从 `l1_snapshot` ref hydrate，并重新执行证据型 GIS village binding；`post_l3_main_nodes.py` |
| L1 enrichment 早于 L1Snapshot 持久化 | `layer_completion_check` 在 `layer_aggregate` 前执行 enrichment，真实运行只能看到旧 context | enrichment 已移动到 `layer_aggregate` 在 typed L1Snapshot 写入之后；真实日志证明 `L1Snapshot stored` → `materialized 5 named village bindings` |
| 真实 GIS 关系计算触发 Windows native access violation | GeoPandas/pandas 扩展数组直接承载无效环并执行向量化谓词；另一路 cross-layer 仍重复使用 GeoPandas | `compute_parcel_relations` 与 `compute_cross_layer_relations` 均改为 `make_valid` + 标量 Shapely 谓词 + `STRtree` 索引；原始输入只读保留并继续审计 |
| LLM provider 账务/配置错误导致维度无限重派发 | LLM 异常返回消息但未增加 `completed_dimensions`，`after_analysis` 按未完成维度再次派发 | 写入 `fatal_error`，路由立即 `END`，Runtime 标记 Session failed；不把外部账户拒绝伪装成业务 HUMAN Gate | `test_llm_provider_failure_stops_dimension_redispatch` |
| `cd backend` 启动时根目录 `.env` 未加载/旧文件覆盖部署 key | `settings.py` 只调用无路径的 `load_dotenv()`；且 `override=True` 会让 stale workspace key 覆盖进程环境 | 应用启动入口固定为 `cd backend && python -m uvicorn ...`；部署环境必须优先于文件配置 | `settings.py` 显式解析当前目录与项目根 `.env`，优先级为进程环境 > cwd `.env` > 根 `.env`；从 backend cwd 验证读取与覆盖行为 | `test_settings_env_resolution.py`；当前根 key 本身仍返回 DashScope `invalid_api_key` |
| 并行维度在 provider 已拒绝后继续发起请求 | 同一层 fan-out 已启动多个维度，首个 provider 错误不能阻止后续波次 | 增加按 Session 的 provider circuit breaker；首个错误后后续维度只产生 `llm_provider_circuit_open`，不再调用模型；新 Session 初始化时显式 reset | `test_llm_provider_circuit_breaker_is_session_scoped` |
| L3 生成项目但没有空间指令 | 真实 PlanningProgram 中多个 intervention 的 `spatial_requirements={}`，`spec_mapper` 无法生成 `SpatialReferenceSpec`，EXECUTE 只能报告无规划区目标 | L3 只提供粗粒度、来源可核验的空间引用；GROUND/SELECT 再做地块级定位，禁止猜坐标或把村名名单当项目位置 | 空间维度 prompt 增加强制位置规则；L3 compiler 对缺失 `【INSTRUCTION】` 和缺失空间引用写入 error；G3 gate 在进入 PARSE 前路由 `L3` | `test_l3_without_instruction_or_spatial_reference_fails_closed`、`test_l3_instruction_table_produces_coarse_spatial_spec` |
| HUMAN retry 绕过业务上限 | HUMAN `retry` 直接回到暂停阶段，达到计数上限后仍可继续重跑 | 业务 Gate 重试必须由显式计数控制；终态供应商错误不得重派发 | `max_retries=0` 不再回退为默认 3；HUMAN retry 达上限写入 `BUSINESS_RETRY_EXHAUSTED` 并终止 | `test_business_retry_limit_zero_escalates_without_retry`、`test_human_retry_exhaustion_becomes_terminal_failure` |
| 同一 HUMAN 中断被客户端重复提交 | resume 请求返回前，轮询客户端仍看到旧的 `paused_stage`，可能重复 POST 相同决定 | LangGraph interrupt 只能对同一 checkpoint resume 一次；恢复节点会重放但不应重复消费决定 | 增加 `human_review_resume_consumed`；API 对已消费 checkpoint 返回 409；真实测试等待新 HUMAN checkpoint 或终态后再提交 | `test_duplicate_human_resolve_is_rejected`、`test_real_llm_session_full.py` 的有界恢复循环 |
| `/render-layers` 读取旧 PlannedState | 多次 EXECUTE/人工修订会产生多个 content-addressed PlannedState，目录顺序不代表最终写入顺序 | 交付读取必须按 artifact manifest 的版本/写入时间选择最新合法产物 | 按 `ArtifactRef.stored_at` 选择最新 PlannedState，再派生图层 | `test_render_endpoint_selects_latest_planned_state_ref` |
| Markdown 阶段报告只有摘要/引用，人工无法追溯原始输入和完整产物 | 报告显示计数但没有真实上传文件元数据或 ArtifactStore payload 入口 | 审计摘要可截断内容，但必须保留 checksum 和可追溯的权威 payload | 增加真实输入文件元数据区段，并为每个 artifact 输出相对 `payload.json` 链接；完整 GeoJSON 仍不复制进报告 | `test_stage_report_links_authoritative_artifact_payload`、`STAGE_REPORT_LINK_OK` |
| MVP 真实 GIS 含无效环 | `ecological_protection.geojson` 1 个、`landuse.geojson` 5 个无效 geometry；若直接进入向量化空间运算可能触发 native crash | 上传审计保留原始索引/原因；适配器边界用 `make_valid` 后再做标量谓词，无法修复则 fail-closed | 全部 10 个 GeoJSON、1662 个 feature 已通过只读审计，6 个 invalid 被记录，未修改源文件 | `test_mvp_fixture_invalid_geometry_is_recorded_not_crashing` |

## 重构后确定性门禁证据

在未启动真实 LLM 的前提下，执行：

```text
python -m pytest -m "e2e and not slow" -q
```

结果：`74 passed, 1 skipped, 1 deselected in 55.38s`，退出码为 0。期间
`faulthandler_timeout=15` 输出过一次 torch/transformers 导入栈和一个 aiosqlite
worker 栈；该输出发生在测试运行超过 15 秒时，不是失败结果。graph replay 单测在
修复后 `1 passed` 并正常退出。

## 当前真实测试验收契约

真实测试必须同时证明：

1. 上传 `current_report.md` 与全部 fixture GeoJSON；
2. 七个主阶段均有 StepReport；
3. 每阶段有 `context_ref`、`artifact_refs`、输入 checksum、输出 checksum 和输出摘要；
4. `DELIVER` Gate 为 `PASS`；
5. `/render-layers` 返回非空 FeatureCollection；
6. PNG 与 HTML 文件存在且状态为 `completed`。

如果出现 HUMAN、超时或渲染缺失，测试必须报告首个阶段、Gate、输入引用和产物目录，不得将其视为全链成功。

## 第一次真实运行证据（2026-08-08）

运行命令：`python -m pytest backend/tests/e2e/test_real_llm_session_full.py -v -m e2e -s`

| 项目 | 结果 |
|---|---|
| Session | `129075a7-c3ea-4252-a611-bdc54c069aa4` |
| 运行目录 | `.run-tmp/real-llm-9d6da8ce3e2b44f7a5b7d8f3ed5dbf9b/129075a7-c3ea-4252-a611-bdc54c069aa4/` |
| LLM | L1 12 维度、L2 4 维度、L3 12 维度均实际调用并持久化报告 |
| L1/KG | L1 `facts=9`、`location_facts=46`，KG 预构建 33,266 triples |
| 首个偏离 | PARSE 保留 5 个无 BSM 的村名空间规格；GROUND 重试 3 次后 HUMAN |
| 未执行 | SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER；因此没有合法渲染产物 |
| 原始输入问题 | `ecological_protection.geojson` feature 4：`Ring Self-intersection[116.075681527946 24.8391157538604]`；`landuse.geojson` feature 22/104/258/323 为 `Ring Self-intersection`，feature 343 为 `Nested shells`；上传审计已记录，原始文件未被静默改写 |

Markdown 审计文件：
`.run-tmp/real-llm-9d6da8ce3e2b44f7a5b7d8f3ed5dbf9b/129075a7-c3ea-4252-a611-bdc54c069aa4/reports/stage-report.md`

## 第三次真实 LLM 运行证据：HUMAN 恢复暴露 checkpoint 类型断点（2026-08-08）

| 项目 | 结果 |
|---|---|
| Session | `9a54611c-5158-4c8e-a7e0-f2b7f339a6d2` |
| L1/L2/L3 | 12/12、4/4、12/12，真实远端 LLM 均已完成 |
| HUMAN 恢复 | GROUND 的人工确认已成功恢复到 EXECUTE；EXECUTE 因无显式规划区目标按契约进入 HUMAN |
| 首个实现断点 | 恢复写 checkpoint 时出现 `Type is not msgpack serializable: types.SimpleNamespace` |
| 根因 | EXECUTE 的 parcel adapter 将运行时 `SimpleNamespace` 放入 `parcel_by_bsm`，越过了可持久化状态边界 |
| 修复 | `_checkpoint_safe` 将 `SimpleNamespace` 转为映射；parcel 读取器同时支持映射和属性对象 |
| 交付状态 | 本次运行在修复前失败，未产生可宣称的渲染交付；修复后需重新跑完整真实链路 |

这不是用人工反馈掩盖定位缺失，而是证明 HUMAN resume 本身能进入 EXECUTE，并将真实执行输入边界上的序列化错误暴露出来。

修复后的第四次尝试在 `0a35e226-af40-4d24-99f4-2bdf6466eb5c` 启动并完成了真实上传及部分 L1；随后配置的阿里云模型和 RAG 查询持续返回 `400 Arrearage / Access denied`。该外部账务阻断导致本次尝试无法完成 L1，已停止，不能作为代码失败或闭环成功证据。待模型账户恢复后必须从真实 Session 重新验证 HUMAN→EXECUTE→VALIDATE→RECONCILE→DELIVER。

随后进行了一次单请求预检（未创建 Session、未执行 RAG），服务返回 `401 invalid_api_key`。真实集成测试已增加同样的单请求预检：凭据失效时在 Session 创建前立即失败，避免再次产生多维度调用；预检不记录或输出密钥内容。

阶段 Markdown 审计也已增强：对 `l1_snapshot`、`l2_strategy`、`planning_program`、`grounding_result`、`site_selection`、`execution_plan`、`parcel_changeset`、`planned_state`、`validation_report`、`reconciliation_report`、`delivery_manifest` 和 `render_layers` 增加“关键内容（供人工审计）”段落。完整 payload 仍只在 ArtifactStore，报告展示事实/策略/候选/变更/校验/图层的有限样本与计数，避免把大型 GeoJSON 复制进报告。

## 第二次完整真实 LLM 运行证据（2026-08-08）

运行参数显式使用 `--timeout=1800 -o faulthandler_timeout=0`，以免 15 秒诊断打印与长时真实 LLM 调用交叠；默认核心测试的死锁诊断配置未被修改。

| 项目 | 结果 |
|---|---|
| Session | `d2ba8855-ecd5-4f83-9d4d-3330d1830259` |
| 运行目录 | `.run-tmp/real-llm-caaf1606722f49fca84d9b62363a2af3/d2ba8855-ecd5-4f83-9d4d-3330d1830259/` |
| 真实输入 | `current_report.md` + 10 个 fixture GeoJSON；上传审计识别 6 个原始无效要素，未篡改源文件 |
| KG | 33,301 triples；1708 touches、6049 nearby、416 connected、365 road-intersects；cross-layer 关系 1068 条 |
| L1/L2/L3 | L1 12/12、L2 4/4、L3 12/12，全部实际调用配置的远端 LLM；L1→KG enrichment 为 `gis_village_entries=5`、`village_bound=16` |
| 首个偏离 | PARSE 保留 `营仔村`、`田坑村` 两个没有 BSM 绑定或对象级坐标证据的空间引用；GROUND 按契约重试 3 次后进入 HUMAN |
| 未执行 | SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER；没有合法渲染层、PNG 或 HTML，不能伪造交付结果 |

详细报告：
`.run-tmp/real-llm-caaf1606722f49fca84d9b62363a2af3/d2ba8855-ecd5-4f83-9d4d-3330d1830259/reports/stage-report.md`

该运行同时证明两个实现事实：一是 L1 的 KG fact 已被实际消费并形成 5 个 GIS village bindings；二是当前真实 fixture 的输入证据不足以合法定位 `营仔村`、`田坑村`。后者必须通过补充带坐标的原始 GIS 或人工决策解决，不能通过 SELECT fallback、放宽 GROUND 或虚构渲染层掩盖。

该结果把断点收敛到 **L1/KG → GROUND 的村名到 BSM 绑定**，而不是“模型没有输出空间指令”。当前修复正在补齐上传 GeoJSON Pydantic extra 字段（例如 `地质灾害点名称`）的证据读取；对于输入中确实没有坐标或命名几何的村名，仍必须 fail-closed，不能把完整候选池冒充定位结果。

对原始 fixture 的逐要素检查显示：`园寨`、`社前`、`长塘`、`炉池`、`肩丰`在地质灾害点属性中有命名要素；`营仔`、`田坑`等本次 GROUND 规格涉及的村名没有直接命名几何。该差异是数据证据边界，不是通过放宽 Gate 可以合理消除的缺陷。

## 尚未证明的事项

- 当前工作区仍处于大规模测试迁移中，新增 E2E 文件尚未纳入提交状态；
- 真实 Session 已执行，但尚未通过 GROUND，因此尚未取得合法的 PNG/HTML 交付产物；
- 真实 Session 已稳定越过原生几何崩溃断点，但仍因两个输入空间引用缺少坐标证据而在 GROUND fail-closed；
- Graphify 尚未按最终代码重新生成；
- 因此不能宣称真实闭环已经完成。

## MiniMax 真实运行证据与新增断点（2026-08-08）

MiniMax 预检已通过：`MiniMax-M2.7` 的非流式与流式 OpenAI-compatible 请求均返回内容，未输出密钥。
随后使用真实 `current_report.md` 和 10 个 fixture GeoJSON 创建 Session
`f2b42224-6b15-40df-a8f2-b8cee52771c1`。L1 12/12、L2 4/4、L3 12/12 均实际调用 MiniMax，KG
预构建约 33,301 triples，L1 enrichment 写入 14 个 village bindings；未发生原生几何崩溃。

首个新增实现断点是 provider 边界：RAG 的摘要生成和 KG enrichment 仍显式传递
DashScope `qwen-flash`，导致 MiniMax endpoint 返回 `unknown model`；同时本机失效 DashScope
key 使向量检索持续 401。已修复所有 Flash/GIS/KG/Conversation 调用改走 provider-aware
`create_llm(model=None)`，并为 L3 非 PASS 重工增加 `max_retries` 后 HUMAN 的硬边界。

该次运行在 L3 gate 因真实模型多次省略 `【INSTRUCTION】` 或生成缺少可核验空间引用时被重工；
在修复前手动停止，未宣称 SELECT/EXECUTE/VALIDATE/RECONCILE/DELIVER 或渲染成功。L3 review
保留在：
`.run-tmp/f2b42224-6b15-40df-a8f2-b8cee52771c1/reviews/l3_plan/`，其中的 `summary.md`
记录了具体 `missing_instruction_marker`、`missing_spatial_instruction` 和维度级数量。

## 执行后应保存的位置

## MiniMax 真实 Session 第三次证据（2026-08-08）

Session `9f1cc581-3eb1-402b-b456-795f7f6717d4` 使用真实报告和 10 个 GeoJSON，实际完成：

- L1 `12/12`，L1 Gate `PASS`；PlanningContext `v1`，KG 从 `v1` 升至 `v2`，`village_bound=11`、`gis_village_entries=5`、`anchor_entries=54`。
- L2 `4/4`，L2 Gate `PASS`；KG 升至 `v3`，写入 `semantic_entities=5`。
- L3 首轮 `12/12`，真实 MiniMax 输出已持久化；审查包记录 `missing_instruction_marker`、`missing_spatial_instruction`（settlement_planning 20 项）及若干证据缺口。
- 首轮 L3 失败后旧路由重新分发全部 12 个维度，进程内存升至约 3.2GB；该运行已主动停止，未宣称后续阶段或渲染成功。

新增修复：L3 的协议/空间契约错误不再把整层 12 个维度作为重试单元，而是保留 gate pending requests 直接进入 HUMAN；HUMAN 明确勾选 `acknowledge_unresolved_spatial_references` 后，GROUND 只在审计记录该人工确认的前提下继续使用已解析候选。MiniMax 下可选的 KG 语义确认默认关闭，确定性空间闸门仍为事实绑定依据，可通过 `GIS_ENRICH_LLM_CONFIRM=true` 显式开启。

随后验证该修复的真实 Session 已确实进入 HUMAN，但 E2E 首次版本在 HITL checkpoint 写入与测试轮询之间提前判断“未暂停”，因此未提交人工决定，最终只收集到 L1/L2/L3 审计并失败于缺少 PARSE 以后阶段；这属于测试等待竞态，不是将 HUMAN 当作成功。已将测试改为在 45 秒硬边界内等待 `paused_stage` 或终态后再决定，不再在中间状态退出。

该 Session 的 L3 审查包：
`.run-tmp/9f1cc581-3eb1-402b-b456-795f7f6717d4/reviews/l3_plan/l3-9f1cc581-3eb1-402b-b456-795f7f6717d4-v1/summary.md`

真实测试通过 `BACKEND_RUN_TMP_DIR` 生成唯一目录，典型结构为：

```text
.run-tmp/real-llm-<unique>/
└── <session_id>/
    ├── artifacts/
    ├── reports/stage-report.md
    └── render/
        ├── planning_preview.png
        └── planning_map.html
```
