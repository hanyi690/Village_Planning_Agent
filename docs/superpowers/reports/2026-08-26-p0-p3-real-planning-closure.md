# P0 → P1 → P2 → P3 真实规划闭环收口报告

日期：2026-08-26
工作区：`F:\project\Village_Planning_Agent`
原始真实会话：`7ad20404-6e3d-4ce2-b343-bc2409a3c38f`

## 结论

P1/P2/P3 的主体实现确实已经存在，本轮没有把它们从头重复执行；本轮工作是围绕既有实现完成收口、补齐共同契约、修复真实 replay 暴露出的确定性问题，并用新的隔离运行目录重新验收。

当前结论如下：

- 完整真实程序 replay 通过，并在真实的 L3 分类边界停住；没有伪造分类决策、GROUND 候选或 delivery 输出。
- 真实但输入不闭合的范围 replay 通过受控失败；`target_projection` 的业务重试上限为 3 次，随后稳定进入 `diagnostic_only`。
- fresh-root-road acceptance 通过；同一 target projection 第二次进入 GROUND 时复用已提交的 CAS 结果，digest 保持稳定。
- P0/P1/P2/P3 定向合同测试 76 个全部通过；全量 `compileall` 和 `git diff --check` 通过。
- P3 golden benchmark 和 recorded replay matrix 均通过，且重新计算出的 fingerprint 与既有 manifest 证据一致。

这说明“完全重开 Codex session”不是解决 replay 的必要手段。真正需要隔离的是业务运行的 `session_id`、CAS/run root、checkpoint 和 named refs；同时 stage replay 必须按父 artifact digest 做幂等复用或 fail-closed。

## 本轮收口内容

### P0/P1 汇合契约

1. `PhysicalProject` 的装配键现在包含 typed physical-object refs；同一 package 只有在明确指向不同实体时才拆分，普通 prose `location_hints` 不再被误当作实体身份。
2. source binding 会把合法的 64 位 snapshot ref 传播到 `source_snapshot_digest`；非 digest 的 ref 不会被猜测成内容 fingerprint。
3. `RelationReadiness` 把语义无效、缺 object、缺 parameter、缺 snapshot、缺 evaluator、backend 不支持与 candidate-dependent `pending_selection` 分开。候选尚未选定不再被错误地等同于 relation evaluator 缺失。
4. solver readiness、GROUND gate、subproblem compiler 和 master coordinator 统一消费这套 readiness 语义；typed problem 不完整时不得 PASS。
5. GROUND gate 的 problem readiness 使用 typed `DecisionFingerprint`，避免同一 HUMAN 请求被旧的 inline gate 或旧 fingerprint 误复用。
6. `target_projection` 的 `L3` retry 进入正式计数与耗尽判断；不再因业务 route 未纳入 retry budget 而无限回放。

### P2 后端和 global master

1. topology/layout solver backend 已注册到 solver portfolio，要求 typed endpoints、evaluator/kind、candidate/domain、geometry 和 CRS 具备可验证输入。
2. `candidate_ids_by_target` 从 subproblem compiler 传入 global master；master 会对跨 target 的硬 relation、reference feature 和 physical-project duplicate/selection conflict 做统一检查。
3. relation evaluator aliases、topology kind validation、global relation tests 和 topology backend tests 已加入定向回归。

### P3 与 replay 边界

1. P3 benchmark 输出 source binding、candidate completeness、relation readiness、solver readiness、feasibility、human escalation 和 output accounting，并带 manifest/report fingerprint。
2. recorded provider 只使用原始 CAS 的 source segments、quotes 和 segment IDs；它没有放宽生产 source validator，也没有伪造 source semantic classification。
3. 未闭合真实范围不再被测试名称或旧 CAS 结果称为“closed”；验收明确要求它进入 bounded diagnostic。
4. GROUND 在检测到已有 `grounding_result` 且其 `parent_digests.target_projection` 与当前 projection digest 完全一致时复用已提交 artifact。投影变化或 EXPLORE retry 不复用。
5. GROUND 和 SELECT 都收敛为单一 stage completion helper，避免早退分支制造第二份 completion contract。

## 新 replay 证据

### 完整真实程序

测试：

```text
backend/tests/acceptance/test_recorded_real_root_graph_replay.py
  -k full_program_preserves_classification_boundary
```

结果：`1 passed`，耗时约 171.98 秒。

最新运行目录：

```text
F:\project\Village_Planning_Agent\.run-tmp\recorded-real-full-2b4a0284
```

该 replay 使用原始 session `7ad20404-6e3d-4ce2-b343-bc2409a3c38f` 的 CAS source lineage，保留 195 个 L1 facts、4 组 L2 decision sets 和 196 个 L3 claims。最终停在 typed `classification_decision_required` HUMAN 边界；没有进入 target projection 之后的 GROUND、SELECT 或 delivery，也没有自动填入分类决策。

### 真实但不闭合的范围

测试：

```text
backend/tests/acceptance/test_recorded_real_root_graph_replay.py
  -k incomplete_scope_stops_bounded_diagnostic
```

结果：`1 passed`，耗时约 140.21 秒。

最新运行目录：

```text
F:\project\Village_Planning_Agent\.run-tmp\recorded-real-closed-62e00947
```

这个目录名沿用了测试 session 的历史前缀，但当前测试语义已经明确是 incomplete scope。由于原始 claims 中存在缺少 source binding/snapshot、空 relation endpoints/parameters 或不可验证 source semantic vocabulary 的输入，测试不制造候选或几何，验证结果为：

- `target_projection`、`l1_snapshot`、`l2_strategy`、`planning_program` artifact refs 存在；
- 不存在 `grounding_result`；
- `delivery_status == diagnostic_only`；
- terminal stage 为 `target_projection`；
- terminal reason 为 `business_retry_exhausted`；
- `retry_counts.target_projection == 3`。

### fresh-root-road 幂等 replay

测试：

```text
backend/tests/acceptance/test_fresh_root_road_source_binding.py
```

结果：`1 passed`，最近一次耗时约 6.73 秒。

该测试验证了从 L1 fact 到现有真实道路线的 source binding、target projection 和 GROUND exact line candidate，并两次调用 GROUND。第二次调用复用相同 target projection 父 digest，`grounding_result.digest` 与第一次相同。成功 pytest 临时根目录按仓库 `conftest.py` 的成功清理策略自动删除；持久化的 recorded replay 目录见上文。

## P3 重新计算结果

Golden manifest fingerprint：

```text
sha256:1960ef3a3fd8d75303e94bff0dd79fe6968951e7338429f0ddb5f0e9019c919a
```

结果：`passed`，output accounting：`ok`。

| 指标 | 结果 | 阈值 | 状态 |
| --- | ---: | ---: | --- |
| source binding coverage | 7/8 = 0.875 | 0.875 | passed |
| candidate completeness | 7/8 = 0.875 | 0.875 | passed |
| relation readiness | 4/8 = 0.5 | 0.5 | passed |
| solver readiness | 3/8 = 0.375 | 0.375 | passed |
| feasibility | 3/8 = 0.375 | 0.375 | passed |
| human escalation | 4/8 | — | recorded |

Golden report fingerprint：

```text
sha256:91f9be0f4ee82ee4e1956901794ddecdfa0f9857500dc49ab63e9c56d0ea5c94
```

Recorded replay matrix：`passed`，`live_provider=not_run`。四条 recorded route 全部通过：`success`、`human_required`、`not_groundable`、`solver_deferred`。

Recorded matrix manifest fingerprint：

```text
sha256:64c4b2e4be0784516c6b631aaa27f180e6db01258c875b386f0f2a09db1bc206
```

Recorded matrix fingerprint：

```text
sha256:679230db86b0c524e7ce3f1b660656ee0c0619368cb82ed43763ef72ba50e065
```

## 验证命令

定向闭环回归：

```text
$env:PYTHONPATH='backend'
python -m pytest -c backend/pytest.ini -o addopts='' `
  backend/tests/core/test_gate_route_policy.py `
  backend/tests/core/test_l3_classification_gate.py `
  backend/tests/core/test_p1_closure_contracts.py `
  backend/tests/core/test_p2_closure_contracts.py `
  backend/tests/core/test_p3_closure.py `
  backend/tests/core/test_master_global_relations.py `
  backend/tests/core/test_topology_layout_backend.py `
  backend/tests/core/test_ground_gate_problem_readiness.py `
  backend/tests/core/test_stage_completion_contract.py `
  backend/tests/core/test_artifact_runtime.py `
  backend/tests/core/test_planning_task_graph_ground_execution.py `
  -q --tb=short --maxfail=1
```

结果：`76 passed`。

```text
$env:PYTHONPATH='backend'
python -m compileall -q backend/app backend/tests/core backend/tests/acceptance backend/tests/support
git diff --check
```

结果：均通过。

## 关于“完全重开 session”

完全新建 Codex 对话只能清空模型的对话上下文；它不会自动清理工作区中的 `.run-tmp`、LangGraph checkpoint、CAS blobs、named refs 或 Python process cache。因此它可以减少“模型把旧上下文当成当前状态”的回放，但不能修复确定性的 stage replay bug。

本次实际验证使用的是新的业务 replay session 和隔离 run root，并通过父 artifact digest 证明输入是否相同：

```text
Codex session：只影响对话上下文
业务 session：recorded-real-full-2b4a0284 / recorded-real-closed-62e00947
artifact identity：target_projection digest + grounding_result.parent_digests
```

所以后续遇到同类问题时，优先检查业务 session 的 artifact refs、parent digests、checkpoint cursor 和 named refs；只有在需要清除模型上下文污染时，才另开 Codex session。

## 已知边界

- P3 recorded matrix 明确是 `live_provider=not_run`；它验证 recorded artifact contract，不宣称 live provider 已完成同样的覆盖。
- 原始真实会话中不闭合的 claims 仍然会进入诊断/HUMAN，而不是被强行推进 delivery。这是当前 fail-closed 结果，不是遗漏的“成功用例”。
- `backend/tests/core/test_e2e_stabilization.py` 中仍有旧测试直接调用已经移除的 `validate._auto_defer_blocked_targets` 兼容 hook。当前代码没有恢复该兼容内容；这与本轮 P0/P1/P2/P3 typed contract 和真实 replay 验收无关，但应在后续清理旧测试或正式删除旧测试期望时单独处理。
