# 后端蓝图迁移问题登记

> 日期：2026-08-12  
> 分支：`codex/refactor-backend-blueprint`  
> 目的：先固定真实运行证据，再区分可直接修复的问题与必须迁移到蓝图后解决的问题。本文不是完成声明；登记项未关闭前，后端不视为最终简洁态。

## 1. 真实交付核对

核对对象：

`F:/project/Village_Planning_Agent/.run-tmp/real-llm-41545f0093904940b7d0a47315103664/db6118ac-2efe-4cc5-9168-489444fb0f54/`

| 事实 | 结果 | 判断 |
|---|---:|---|
| current landuse | 660 features | 真实数据层输入 |
| complete planned landuse | 660 features | 与 current 一一对应 |
| `change_status=preserved` | 660 | 本次没有 ParcelChange |
| `ParcelChangeSet.changes` | 0 | 没有地类/地块变更可显示 |
| planned project point | 17 | 真实规划项目定位点 |
| planned facility | 16 | 真实公共服务设施点 |
| planning preview | 已生成 | 单张 PNG，现状/规划两个面板 |
| planning map | 已生成 | HTML 中有 17/16 点图层和图层开关 |
| snapshot status | `partial` | 不能宣称法定完整 |

文件核验：

- [planning_preview.png](../../.run-tmp/real-llm-41545f0093904940b7d0a47315103664/db6118ac-2efe-4cc5-9168-489444fb0f54/render/planning_preview.png)：右侧规划面板显示 17 个红色项目点、16 个蓝色设施点；顶部显示“地类变更 0 个（全部保留现状）”。
- [planning_map.html](../../.run-tmp/real-llm-41545f0093904940b7d0a47315103664/db6118ac-2efe-4cc5-9168-489444fb0f54/render/planning_map.html)：包含 `规划项目定位点`、`公共服务设施` 和 `完整期末地类（含未修改地块）` 图层；点位使用小尺寸 marker，点击后可读属性。
- `complete_planned_landuse.geojson` 的 SHA-256 前缀为 `b87181ad062ef71e`；项目点和设施点来自 snapshot 的 source layers，不是 renderer 临时注入。

结论：当前“看不见规划变化”的根因不是 PNG/HTML 丢了数据，而是这次真实 EXECUTE 没有产生任何 `ParcelChange`。点位确实存在，但点位不是地块规划变更，不能用来冒充已落地的地类规划。

## 2. 问题与处置

### MIG-001：真实 L3 目标缺少显式 ClassificationDecision

- **现象**：真实 L3 有 67 个 polygon/parcel 目标缺少显式分类决定；EXECUTE 不能从名称、`dlbm`、KG 或 crosswalk 推导规划编码，因此 `ParcelChangeSet` 为 0。
- **影响**：规划面只剩完整现状地块，用户会误认为“规划没有执行”。
- **当前处理**：已禁止 acceptance 自动 `approve + defer_unresolved_spatial_references` 绕过分类；没有外部明确分类决定时保持 HUMAN/partial。
- **蓝图迁移**：由 `TARGET_PROJECTION -> HUMAN ClassificationDecision -> EXECUTE` 完成；LLM 只提交 claim/proposal，分类决定必须是人工/审查后的 typed artifact。
- **关闭标准**：真实 checkpoint resume 后，至少一个合法分类决定进入 `ParcelChangeSet`，规划 GeoJSON、土地平衡、PNG、HTML、StepReport 的变更数一致，并能定位到项目。

### MIG-002：规划项目点存在，但默认视觉强调不足

- **现象**：17 个项目点和 16 个设施点真实存在；HTML 使用小点符号，远视图下密集点会难以识别，PNG 只能证明点位存在，不能替代交互定位。
- **影响**：前端或用户把“未看到点”误判为“没有项目”。
- **当前处理**：HTML 图层开关、点图层数量、PNG 顶部计数和图例已接线；点位仍保持小尺寸以避免覆盖地块。
- **蓝图迁移**：前端 `GetMapLayerCollection` 必须把 `layer_id/count/legend/style/feature properties` 作为公开投影；点击点位打开 `project_ref/target_id/name/provenance`，不能依赖 PNG 目测。
- **关闭标准**：前端通过稳定 API 能按图层开关、按点位查询属性，并能从点位跳转到对应 intervention/target；不得依赖 HTML 内嵌脚本解析。

### MIG-003：`workflow_progress` 仍是迁移期复合状态

- **现象**：根 checkpoint 已切换为精简 `WorkflowState`；`workflow_progress` 已禁止 `extra="allow"`，动态阶段字段只能进入显式 `stage_payload`，但该 payload 仍承载未拆完的旧 stage runtime。
- **影响**：阶段状态、消息、payload、artifact refs 仍可能重复，resume 时存在“控制状态与阶段对象不同步”的风险。
- **处置**：已先收紧 carrier 边界并增加 round-trip 契约测试；不在旧 adapter 上继续添加顶层字段，下一步按蓝图拆为 typed stage artifacts，并把 application projection 作为唯一 API 读取入口。
- **新增进展**：六个新阶段已通过 `StageCompletion` 统一输出；post-L3 root gate 路由和 gate mutation 已切换为 CAS ref，缺失/损坏 fail-closed。L1/L2/L3 inline gate 仍未迁移。
- **关闭标准**：根状态只含控制字段和 refs；不存在 `extra=allow` 的迁移载荷；每个阶段输入输出均可由 typed artifact 和 checkpoint 重放。

### MIG-004：SSE 跨进程 outbox/publisher 尚未完成

- **现象**：`EventRepository` 已保存历史事件和 seq，`EventConnectionHub` 已只保留在线队列；但发布仍由当前进程直接写库并广播，没有独立 outbox/跨进程 publisher。
- **影响**：多 worker 部署时，在线广播仍需要共享发布基础设施；队列溢出只能等待客户端通过持久事件 sync 补偿。
- **当前处理**：旧 `services/sse.py`、`_sessions`、`_pending_events`、关键事件 cache 和 session cleanup 已删除；SSE replay/sync 已统一经过 `RunEventQueryService`。
- **蓝图迁移**：`RunEvent` append-only + outbox/publisher 负责事实投递；`SSEConnectionHub` 只保留在线队列；`Last-Event-ID` 只从持久事件回放。参考 FastAPI SSE 对 `Last-Event-ID`、`id` 和 heartbeat 的定义，以及 LangGraph 对 checkpoint/resume 的同一 cursor 原则。
- **关闭标准**：两进程/重启后的 sync 结果与单进程相同；SSE manager 不保存 session history、seq 或关键业务事实。

### MIG-005：API router/runtime 仍有直接服务耦合

- **现象**：部分 v1 route 仍直接访问 runtime、SSE manager 和 graph；application commands/queries 尚未完全接管。
- **影响**：transport 层知道内部 checkpoint 细节，后续删除 legacy state 会扩大改动面。
- **处置**：保留当前 v1 行为，下一阶段先迁移 `ResumeCheckpoint`、`SubmitHumanDecision`、`GetDeliveryProjection` 和事件订阅用例，再删除直连。
- **关闭标准**：router 不实例化 graph/store/SSE manager；所有公开响应来自 application projection。

### MIG-006：当前环境无法再次执行真实 LLM acceptance

- **现象**：当前 shell 没有可用 provider credential；真实 acceptance 最新执行结果是 `2 skipped`，不能把渲染复核当成新的真实图运行。
- **影响**：本轮代码改动后的 checkpoint reopen/resume 尚未重新取得新的 live evidence。
- **处置**：保留原有已通过证据 `1 passed in 800.03s`；本轮只将 exact persisted snapshot 重新读取、渲染和核对，不虚报为新图运行。
- **关闭标准**：设置真实 provider 和 operator-approved `REAL_CLASSIFICATION_DECISIONS_JSON/PATH` 后，完整跑一次真实 interrupt/checkpoint reopen/resume，并读取新生成 StepReport、PNG、HTML、planned GeoJSON。

## 3. 迁移顺序

本轮迁移回归：非 E2E `131 passed, 14 deselected`；真实 acceptance 因当前环境无 provider credential 为 `2 skipped`，未把旧 run 的渲染复核冒充为新的真实图运行。

1. 先完成 `ClassificationDecision -> TARGET_PROJECTION -> EXECUTE` 的真实人工决定闭环，解决“没有地类变化”的业务结果问题。
2. 将 `workflow_progress` 拆为 typed artifacts，删除旧 stage payload 和宽松 extra 字段。
3. 将 SSE 历史、outbox、在线广播彻底分离，删除进程内关键事件缓存。
4. 将 v1 router 收敛到 application commands/queries。
5. 在有真实 provider 的环境执行完整 checkpoint resume；读取并渲染本次新产物，最后才关闭登记项。

## 4. 外部范式依据

- [FastAPI SSE reference](https://fastapi.tiangolo.com/reference/sse/)：SSE 的 `EventSourceResponse`、`ServerSentEvent`、`id` 和 `retry`。
- [FastAPI SSE tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/)：浏览器断线后用 `Last-Event-ID` 回放。
- [LangGraph human-in-the-loop](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)：持久 checkpointer、稳定 `thread_id`、`interrupt` 与 `Command(resume=...)`。
- [LangGraph functional wait-user-input](https://langchain-ai.github.io/langgraph/how-tos/wait-user-input-functional/)：resume 从 checkpoint 边界重放，已完成 task 结果不重复计算，副作用需要幂等。
