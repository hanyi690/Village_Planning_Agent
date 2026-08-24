# Evaluation and Acceptance

> Status: TARGET
> Authority: Normative benchmark layers, metrics, release evidence and completion gates.

## 1. Evaluation principles

评估必须覆盖“召回—定位—接地—求解—执行—重放”整条链，不能只评估最终回答流畅度。每个 benchmark 固定输入快照、gold/acceptable set、运行配置和评估器版本；结果保存 artifact refs 和 fingerprints。

开放世界任务不使用“召回所有现实证据”作为不可验证目标。评估使用声明语料、来源族和候选全集中的 bounded recall，并单独记录系统是否正确报告范围外缺口。

## 2. Retrieval benchmark

测试集覆盖自然语言改写、精确编号、跨章节证据、矛盾来源、多来源要求和 embedding unavailable。至少记录：

- `claim_recall_at_k`：gold claim 在前 k 个融合结果中的召回；
- `context_precision`：返回上下文中真正支持 requirement 的比例；
- `source_family_coverage`：必需来源族获得有效证据的比例；
- `locator_accuracy`：source/page/span/table/feature locator 精确正确的比例；
- contradiction detection precision/recall；
- requirement sufficiency calibration；
- dense degradation delta：关闭 embedding 后各指标变化和正确降级率。

检索通过不仅要求相关，还要求 locator 可复核、来源角色未混淆、unsupported gap 未被误报为 sufficient。

## 3. Spatial grounding benchmark

测试集覆盖别名、多义地名、行政范围、相对方位、距离/网络时间、拓扑关系、exact/derived/inferred geometry、CRS 转换和 snapshot 漂移。至少记录：

- `entity_top_k_recall`：正确 canonical entity 在前 k 个候选中的比例；
- `locator_accuracy`：实体最终绑定到正确 dataset/layer/feature 的比例；
- `exact_vs_inferred_geometry_error`：几何等级误分类及空间误差；
- candidate recall/precision within declared source universe；
- CRS/unit correctness；
- exclusion reason accuracy；
- unresolved calibration：无法安全接地时是否正确停止。

GROUND 不以 final selection score 验收。它以候选身份、几何、来源、约束测量和缺口报告的正确性验收。

## 4. Planning/solver benchmark

测试集包含可行、多解、Pareto、容量冲突、网络约束、全部不可行和预算终止问题。至少记录：

- `hard_constraint_violation_count`；
- `feasible_scenario_recall`：在可枚举或 gold set 中召回的可行/关键替代比例；
- `optimality_gap_or_bound_status`：最优差距、证明界限或未证明原因；
- Pareto precision/coverage；
- objective vector correctness；
- deterministic fingerprint stability；
- infeasibility explanation accuracy；
- source membership preservation。

一个 winner 即使合法，也不能单独通过多方案验收。至少要证明替代方案和推荐策略被保存，或者明确证明问题只有一个可行方案。

## 5. Execution/replay benchmark

测试集覆盖多 worker、任一 worker 失败、批准后 fingerprint 漂移、重复 resume、旧 artifact、验证失败和交付投影。至少记录：

- `selected_to_materialized_coverage`：被批准选择中成功物化且身份一致的比例；
- unexpected materialization count；
- `lineage_completeness`：必需 artifact/snapshot/digest 边的完整率；
- atomic abort correctness；
- hard constraint recheck agreement；
- `replay_fingerprint_stability`：相同输入重放的关键 fingerprint 稳定率；
- resume idempotency；
- delivery run-root consistency。

## 6. Acceptance levels

| Level | Meaning | Required evidence |
|---|---|---|
| component | 单一服务/契约符合局部行为 | unit/property tests |
| boundary | 两阶段契约、失败和 lineage 正确 | contract/integration tests |
| scenario | 代表性项目快照完成闭环 | deterministic replay artifacts |
| release | 默认配置、退化路径和正式交付通过 | full benchmark report + certificates |

文档、schema 或单元测试存在不代表 release complete。任何标注 CURRENT/PARTIAL/COMPLETE 的能力必须链接代码路径或可重复命令；只有 release 级证据允许声明默认 live 能力完成。

## 7. Complete acceptance

正式 `complete` 至少同时满足：

- zero unresolved hard constraints；
- `hard_constraint_violation_count == 0`；
- `selected_to_materialized_coverage == 100%`；
- required `lineage_completeness == 100%`；
- ValidationCertificate 绑定与批准输入相同的 scenario、baseline、PlannedState 和 snapshot digests；
- ReconciliationReport 没有未处置的目标、候选、选择、执行或交付遗漏；
- 地图、报告和导出均来自同一 run-root；
- 相同输入 replay 的关键 fingerprints 满足稳定性门槛；
- embedding unavailable 时按设计降级，且没有误报检索绝对完整。

不可行问题可通过“诊断完成”验收：SolverCertificate 必须是明确 infeasible/unsat，约束冲突解释可复核，不能创建 `ApprovedExecutionInput`，也不能进入正式执行和交付。允许保留不具备 feasible/recommended 标记的 provisional scenario 行用于部分交付诊断，但它们必须显式带 finding，不能被当作批准输入。

## 8. Regression and evidence retention

每次改变 retrieval fusion、实体解析、候选生成、constraint evaluator、solver、worker、validation 或 artifact lineage，都要重跑对应 benchmark 层。基准结果保存代码 revision、配置摘要、模型/provider 版本、数据 snapshot、随机 seed、证书和失败样例。

阈值由独立 benchmark manifest 版本化，不在本文硬编码未经验证的百分比。release gate 必须同时检查质量下限和退化幅度，禁止用平均分掩盖某个必需来源族、硬约束类型或几何类型完全失效。
