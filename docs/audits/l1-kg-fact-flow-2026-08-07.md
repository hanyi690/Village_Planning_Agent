# L1 → KG Fact 流审计（2026-08-07）

## 目的

本审计确认真实 session 中，GIS 上传数据先进入 Session KG，KG 的事实被 L1 使用并提升为可恢复的 `L1Snapshot`，随后由 L2 通过 artifact ref 消费；不能只凭“调用过检索函数”认定链路完成。

## 实际生产链

1. `POST /api/sessions` 上传 `current_report.md` 和 `fixtures/mvp_village/gis/*.geojson`。
2. `SessionKG.ensure_session_kg` 构建真实 KG。最近一次真实运行记录了 660 个地块、131 条道路、30 个设施、562 个边界实体、32966 triples；空间关系为 1691 touches、6048 nearby、416 connected、365 road-intersects。
3. L1 各维度通过 `retrieve_evidence → retrieve_from_kg` 消费 KG；StepReport 的 `kg_evidence_consumed` 保存事实、来源和 KG confidence。
4. `l1_aggregate` 再次从当前 session KG 读取证据，把事实提升到 `L1Snapshot.facts`，并将 `session_kg:{session_id}` source ref 一起保存。这样即使远程模型返回没有 Markdown 标题的纯文本，L1 也不会丢失真实 GIS/KG 事实。

## 实际消费链

1. L1Snapshot 写入 `ArtifactStore/{session}/artifacts/l1_observe/.../payload.json`，checkpoint 只保存 `l1_snapshot_ref`。
2. L2 worker 通过该 ref 加载 typed `L1Snapshot`，把完整 facts 放入 L2 prompt 的“L1 已确认事实”段落。
3. L2 StepReport 同时记录 `l1_fact_count`、`l1_snapshot_ref`、KG evidence facts 和 source refs；报告的 Fact lineage 区段按 `KG → L1 → L2` 展示。
4. L3 继续按 artifact ref 加载 L1Snapshot 的 constraints，形成最终 PlanningProgram 的 upstream provenance。

## 已修复断点

| 断点 | 修复 |
|---|---|
| L1 编译器对无标题模型输出产生 0 facts | aggregate 阶段从当前 session KG 提升事实到 L1Snapshot，不覆盖编译器事实 |
| L2 只通过文本/RAG 间接看到 L1 | L2 显式加载 `l1_snapshot_ref`，输入事实和 ref 都审计 |
| EXPLORE 重试耗尽直接 END | 路由改为 HUMAN，保留 pending evidence requests，禁止把未完成运行伪装为成功 |

## 证据位置

- 真实 session Markdown：`backend/.run-tmp/<session_id>/reports/stage-report.md`
- L1Snapshot payload：`backend/.run-tmp/<session_id>/artifacts/l1_observe/`
- L2Strategy payload：`backend/.run-tmp/<session_id>/artifacts/l2_strategize/`
- 代码：`backend/app/agent/l1_observe/aggregate.py`、`backend/app/agent/l2_strategize/worker.py`
## Dependency report presentation boundary (2026-08-07)

- L1/L2/L3 still receive the complete upstream report prose in their prompts.
- Before prompt assembly, `split_instruction()` removes the private
  `【INSTRUCTION】` block; the model therefore sees the report body, not the
  machine-only location table.
- StepReport and `stage-report.md` persist only section names, character
  counts, and a short preview. This is an audit presentation boundary, not a
  reduction of the model input.
- Artifact payloads in Markdown are summarized structurally (counts, keys,
  bounded previews); the typed artifacts remain available in ArtifactStore.

## Dimension scoping

`L1Snapshot.facts_by_dimension` now merges both compiled report facts and the
`fact_statements` actually consumed by that L1 dimension's KG/EXPLORE query.
The flat `facts` list is retained for compatibility. L2 selects only the
configured upstream dimensions from `facts_by_dimension`; it does not inject a
global KG fact pool into every strategy prompt.

The design-required `L1LocationFact` path is now explicit: L1 compiles named
natural villages, roads, and water features with `dimension_key`, source report
reference, source span, role, and confidence into `L1Snapshot.location_facts`.
GROUND receives these facts through the versioned PlanningContext; they are
place evidence only and never a direct candidate or coordinate decision.
### L1 location-fact source correction (2026-08-07)

`L1LocationFact` 的机器来源固定为 L1 报告保存时拆出的 `instruction` 字段，
即模型输出的 `【INSTRUCTION】` 表格（`类型/名称/位置/描述/规模`）。L1 正文不再
被正则扫描生成地点事实，避免把叙述中的偶然地名误当成可定位证据。正文仍按维度
prompt 编译为 `facts`、`constraints`、`evidence_gaps`，并可由 EXPLORE/KG 提供
同维度证据；地点事实进入 `L1Snapshot.location_facts` 后，GROUND 通过
`PlanningContext` 的 ref-only 加载路径消费。

读取链核验：`ReportStore.bulk_save()` 将响应拆为 `DimensionReport.content` 与
`DimensionReport.instruction`；`get_layer_reports_with_sources()` 已同时返回两列；
`l1_aggregate()` 将 `rec["instruction"]` 传给 L1 compiler。此前真正的存储断点是
`bulk_save()` 原地修改 pending dict：第一次立即保存后 `content` 已被拆开，第二次
completion 保存又按空 marker 重置了 `instruction=None`。现已改为幂等保存，且不再
发起结构化修复请求或系统伪造地点；如果仍缺 marker，StepReport 记录协议违例并
fail-closed。

### P1 运行隔离与 L2 gate 断点

真实集成测试原先在仓库级 `.run-tmp` 下运行，重复执行会复用旧的
`session/artifact` 目录。现在核心真实链和真实 LLM 测试都由 pytest
`tmp_path` 提供独立根目录，并在会话执行前切换 cwd；应用默认的相对
`.run-tmp` 会自然落在本次测试目录内。CI 已显式运行
`tests/integration/test_real_llm_session_full.py`；没有凭据时只跳过远程调用，
不会把集成入口从 CI 的收集范围中删除。

最近一次真实 LLM 运行还暴露了 L2 gate 的语义断点：模型把完整策略建议误报为
`EvidenceGap`，但 `required_fact` 为空。该记录没有可执行的缺失事实，若直接
进入 EXPLORE 会在两次重试后错误进入 HUMAN。现在只有带明确 `required_fact`
（或明确“缺/需要/不足/未”描述）的 gap 才路由 EXPLORE；叙述性建议保留在
L2 artifact 和审计中，但不阻塞后续 L3。
