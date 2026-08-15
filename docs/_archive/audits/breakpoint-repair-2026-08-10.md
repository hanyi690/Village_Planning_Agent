# 第一轮断点修补记录（2026-08-10）

## 范围

本记录追加于既有审计之后，不覆盖历史执行记录。修补目标是本地闭环与安全边界：SELECT 候选边界、后台任务生命周期、artifact 父版本恢复和确定性空间交付。

## 已修补

1. 空 `target_ref` 不再打开全局候选池。设施目标没有 `candidate_bsms` 时保持 `unplaced`，并保留稳定原因码；缺证据继续进入 HUMAN/RETRY。
2. L1/L2/L3 摘要后台任务统一纳入 `TaskSupervisor`，支持按 session 取消并等待，异常保留日志。
3. artifact manifest 记录父 artifact 的 `revision:checksum`。恢复计划遇到父版本变化或缺少旧父元数据时保守失效，从最早失效阶段重跑；待处理 HUMAN interrupt 优先。
4. 增加真实主图的确定性空间交付测试，使用本地 `MemorySaver` 与 `FilesystemArtifactStore`，不依赖远端 provider。

## 验证

- `python -m pytest -o addopts='' -q backend/tests/core`：42 passed
- `python -m pytest -o addopts='' -o timeout=1800 -o faulthandler_timeout=0 -q backend/tests/e2e/test_planning_chain_e2e.py backend/tests/e2e/test_unified_graph_replay_e2e.py`：27 passed
- `python -m pytest -o addopts='' -o timeout=1800 -o faulthandler_timeout=0 -q backend/tests/e2e/test_deterministic_spatial_delivery_e2e.py`：1 passed

真实 MiniMax 运行与人工反馈验收不在本条本地验证结果中，待上述断点稳定后单独记录。

## 真实 MiniMax 闭环追踪（2026-08-10）

真实 provider 运行已完成 L1/L2/L3、PARSE、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER，并生成真实 `planning_preview.png`、`planning_map.html`、RenderLayers 与 DeliveryManifest。人工输入严格按返回请求处理：L3 缺少 `【INSTRUCTION】` 时确认继续但不补造空间证据；GROUND/SELECT 无候选目标逐项写入 `deferred_target_ids`。

本次真实输入的最终 DeliveryManifest 为 `diagnostic_only`，不是 PASS：输入报告产生大量没有位置证据的规划干预，且旧 checkpoint 在连续 HUMAN 恢复后出现 137 个延期 ExecutionPlan task 与 125 条 DeferralLedger 记录不一致。为保持交付契约，新增 DELIVER 边界的显式 ledger reconciliation，将缺少台账链接的已有 deferred task 记录为 `execution_plan_deferred_ledger_reconciliation`，不将其当作已交付；后续真实复跑需验证该修补后的 `partial` 结果。

同时修复了连续 HUMAN 闸门回路：`human_review_apply` 返回既有 `human_review` 路由时现在回到 `human_review_prepare`，重新生成事件并清除消费标记；验收驱动在 checkpoint 写入滞后时会重新读取官方 review payload。

当 `allocated_geojson` 为空而现状 landuse 可用时，DELIVER 现在输出带 `planning_status=unchanged_preserved` 和 `planning_provenance=current_landuse_no_verified_change` 的 `planned_landuse`，明确表达“无已证实变更”，不生成虚假规划分配。

## 真实复跑后的新增断点（2026-08-10）

在启用 MiniMax 并将全局并发限制为 3 后，最新 session 已真实完成全部阶段并生成地图文件。交付结果仍为 `diagnostic_only`，唯一阻断原因为“用地平衡表不闭合”；planned landuse 和 DeferralLedger 已正确生成。

定位发现 DELIVER 的 `_build_planned_view` 仅使用对象属性读取 L1 地块。真实 session 的序列化输入是字典，导致现状保留地块面积全部读为 0。已增加对象/字典双形态读取并加入回归测试；未放宽用地平衡门槛。

修补后复跑继续走通真实 MiniMax 主图和人工恢复，但暴露出第二层证据断点：8 个规划 parcel 没有现状 BSM，也没有 `derived_from_bsms`，将其计入法定 planned balance 会凭空增加面积。现已只将可证明替换的规划 parcel 纳入平衡；无来源 parcel 保留在上游 HUMAN/延期审计中。另修正 `DeferralLedger` 的 artifact 类型映射，避免交付时因 `deferralledger` 未注册而丢失持久化。

当前本地验证：core `44 passed`；确定性空间交付闭环 `1 passed`；真实 MiniMax 修补后运行已到 DELIVER，但本次运行发生在第二层过滤补丁之前，不能据此宣称真实 `PASS`，需下一次真实复跑确认。

GROUND HUMAN 回环修复后，针对真实 session 的 105 个 unresolved target 隔离调用成功；全量延期现在把 ground gate 推进为显式 PASS 并进入 SELECT，部分延期仍保持 HUMAN。真实 MiniMax 复跑已越过原 GROUND 回环，进入后续 L2/L3；本次因 L3 provider 输出耗时超出验收窗口，未产生新的最终 DeliveryManifest，不能据此宣称完成。

## 后续真实验收追踪（2026-08-11）

新增 VALIDATE 语义：当人工延期后 ExecutionPlan 已无未延期空间任务时，`parcels_present` 与 `changeset_flags` 不再错误阻断；仍有活动任务时保持原契约。新增同一 `issue_fingerprint` 重复时转 HUMAN，避免无进展 EXECUTE 重试循环。

真实 MiniMax 复跑证据：

- 一次复跑已完成 PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER，并生成真实渲染与 DeliveryManifest；阶段报告 checksum 补丁前曾因重复 VALIDATE 指纹验收失败。
- 随后的真实复跑验证了阶段报告 checksum 已补齐，但 DeliveryManifest 仍因真实用地平衡偏差保持 diagnostic-only。
- 最新一次 MiniMax 输出在 GROUND HUMAN 恢复接口处失败，未进入交付；不能将其视为业务 PASS。现有 HITL/replay 回归 `59 passed`，本地 core `45 passed`。

## 真实 MiniMax 闭环验收（2026-08-11，面积契约修补后）

第二轮真实 MiniMax 主图已完成 L1/L2/L3（12/12）、PARSE、GROUND、SELECT、EXECUTE、VALIDATE、RECONCILE、DELIVER；人工恢复均使用可审计的“继续但不把未解析村名视为坐标/BSM”反馈。真实测试结果为 `2 passed`。

本轮修复了 `area_sqm` 被启发式当作公顷的问题：输入契约字段为平方米，执行、parcel_ops 和 zone allocator 现统一按 `area_sqm / 10000` 计算。修补后土地平衡闭合偏差为 `0.02%`，`DeliveryGate PASS`。

真实产物：`render/planning_map.html`（16,263 bytes）、`render/planning_preview.png`（31,177 bytes）、RenderLayers 2 层且含 2 个 FeatureCollection features、PlannedState artifact、DeliveryManifest `partial`。manifest 的 `expected_spatial_output_count=7`、`deferral_count=145`、`land_balance_closed=true`、`zones_complete=true`；`partial` 来自真实延期目标，不是放宽硬门槛，`statutory_complete=false`。

pytest 外层仍出现既有 `session-timeout: 90.0 sec exceeded` 提示，但最终断言为 `2 passed`，服务正常清理退出；该提示保留为执行记录，不改写为 PASS。
