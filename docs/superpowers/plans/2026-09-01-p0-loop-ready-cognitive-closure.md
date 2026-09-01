# P0 / Loop Ready 认知闭环实施计划

> 范围修正（2026-09-02）：本计划的 L1/L1-GROUND/L2 纵向实施不再是当前 MVP 任务。
> 当前只执行 DATA 文件读取与验收探针；本计划保留为历史计划，禁止据此新增 MVP 业务
> 模块或继续推进下游实现。

> 日期：2026-09-01
> 项目：`F:/project/Village_Planning_Agent`
> 目标：在项目声明支持的输入范围内，完成并真实验证 `DATA → Cognition/World Model → Evidence → L1 → L1-GROUND → L1 Final`，并让一个有界 L2 consumer 通过公开 final contract 消费结果。
> 执行方式：当前工作区内执行；不创建分支、不提交、不推送；保留工作区既有改动。

## Global Constraints

- 只实现 DATA、Cognition / World Model bootstrap、Evidence bootstrap/enrichment、L1ObservationSnapshot、L1-GROUND、Cognition proposal validation / WorldModelCommitPort、binding revalidation、L1FinalProduct / L1ProductManifest 和一个有界 L2 consumer probe。
- 不实现完整 L2、L3、Target Projection、Planning Ground、SELECT、EXECUTE 或交付链。
- DATA 只对 capability registry 明确支持的 adapter、格式、geometry kind、CRS 组合负责；支持输入必须经历 `DISCOVERED → CLASSIFIED → PARSING → NORMALIZED → REPRESENTATION_BUILT → CAPABILITY_INDEXED → ADMITTED`；失败必须区分 `UNSUPPORTED`、`INVALID`、`CRS_UNRESOLVED`、`ENCODING_UNRESOLVED`、`GEOMETRY_INVALID`、`POLICY_REJECTED`，并持久化 receipt、DataGap、输入引用和恢复动作。
- 未 `ADMITTED` 的资源不得进入 current resource catalog 或 World Model bootstrap。
- DATA、Evidence、L1、L1-GROUND 只能产生 proposal；只有 Cognition validator 通过 `WorldModelCommitPort` 改变 current World Model。proposal batch 原子提交；stale parent、验证失败、CAS 冲突不得留下部分写入；current view 只包含 accepted assertion；planned graph/intent 不得进入 current query。
- Evidence 物理分离 Requirement、Query、Observation、Candidate、Conclusion；provider attempt 必须保留 `NOT_ATTEMPTED`、`SUCCESS_NONEMPTY`、`SUCCESS_EMPTY`、`PARTIAL`、`MISSING_CAPABILITY`、`FAILED_RETRYABLE`、`FAILED_PERMANENT`、`QUOTA_EXHAUSTED`、`TIMEOUT`、`AUTH_FAILED`；保留 acquisition/semantic/binding confidence 和 source/geometry/legal authority；外源坐标只能是 observation/locator evidence。
- 正式持久化 `L1ObservationSnapshot`、`L1FactRow`、`L1LocationMention`、`L1RelationMention`、`L1GroundingRequest`、`L1Gap`、`L1BindingSnapshot`、`L1FinalProduct` / `L1ProductManifest`；冻结 observation 不得原地修改。
- L1-GROUND 只做 mention-to-entity/scope/relation 绑定；只产生 proposal；LLM 只能从确定性闭集返回 `selected`/`ambiguous`/`abstain`；commit 后必须针对新 World Model snapshot 做 binding revalidation。
- 发现上游缺口时，修复 canonical owner 并重新运行上游 gate；L1/L1-GROUND 不得增加局部 fallback 绕过上游缺口。
- 不创建新的测试文件；必要时只最小修改现有测试。临时验证脚本一次性使用并删除。不得删除仍有活跃调用方的兼容代码；只有在迁移、回归和调用方检查证明无活跃路径后，才删除旧兼容路径/冗余实现。
- 每项结论必须区分 `TARGET`、`IMPLEMENTED`、`RUNTIME_VERIFIED`；数量不代替内容、来源、状态、digest、authority、lineage 和真实下游消费证据。

## Task 1: 建立当前实现矩阵和 fresh probe 基线

1. 读取并核对 canonical design、acceptance cards、现有 artifact、facade、测试和命令；把每个 P0 gate 标为 `IMPLEMENTED`、`PARTIAL`、`TARGET` 或 `RUNTIME_VERIFIED`，记录到本计划 ledger 和最终报告来源。
2. 复核工作区既有变更，选定 capability registry 已声明支持的真实金田村本地 GeoJSON + UTF-8 Markdown 输入边界；不引入未声明格式/CRS。
3. 建立一次 fresh run 的生产 facade 入口，确认 DATA→Cognition bootstrap→Evidence→L1 现有链路的首个实际失败点；只使用可删除的一次性命令/内存脚本。
4. 运行并记录基线：`python -m compileall -q backend/app`、`python -m pytest tests -q`、`git diff --check` 及相关 acceptance help/probe；不要把历史 artifact 当作本轮运行证据。

## Task 2: DATA admission state machine, capability registry, receipt and recovery

1. 复用现有 `DataResourceCatalog`、`DataApplication`、CAS 和 gate pattern，补齐 canonical DATA contract：声明支持矩阵、七阶段生命周期、六类 fail-closed 状态、可重载 receipt/DataGap/输入引用/恢复动作。
2. 只实现当前 registry 声明的本地 GeoJSON/WGS84 vector slice；不把任意 CRS、未知 geometry、任意文档或 provider 坐标标成支持。
3. 使 admitted-only catalog 成为 Cognition 唯一输入；对未 admitted 资源验证 current catalog 和 bootstrap 均不可见。
4. 实现 DATA artifact 的 CAS reload、digest 校验、重复请求幂等、stale-parent/失败恢复路径；让现有 DATA 相关 tests/probes 继续通过。
5. 删除仅在迁移后确认无调用方的重复 DATA 兼容入口；仍被调用的兼容入口改为薄适配并记录迁移位置。
6. 更新 `docs/architecture/CURRENT_RUNTIME.md` 和 `docs/design/05_MIGRATION.md` 的 DATA 现状/证据。

## Task 3: Cognition proposal validation and atomic WorldModelCommitPort

1. 在现有 cognition contracts/ports 上补齐 proposal、validator、commit result、parent/digest/fingerprint 和 accepted/rejected/superseded 生命周期表达；不得把存储实现暴露成第二领域权威。
2. 复用 `WorldModelKGStore` 的 CAS/transaction pattern，实现 batch-level 原子 commit；验证 stale parent、validation reject、CAS conflict 均无部分 current 写入，重复 fingerprint 可幂等重放。
3. 使 current query 只返回 accepted assertion，隔离 planned/intent；snapshot、parent、digest、proposal fingerprint、commit result 全部可重载。
4. 为后续 L1-GROUND 提供公开 Cognition facade/port；L1-GROUND 不得直接写 KG/RDF/SQL。
5. 删除已经被公开 facade 完全替代且无活跃调用方的重复 writer 兼容路径；保留有活跃调用方的 adapter 并加薄边界。
6. 更新 runtime/migration 文档并完成 WM Gate 自检后再进入 Evidence。

## Task 4: Evidence bootstrap/enrichment and honest provider attempt semantics

1. 扩展现有 Evidence retrieval contracts/artifact store/facade，物理区分 Requirement、Query、Observation、Candidate、Conclusion，加入完整 provider attempt 状态和 acquisition/semantic/binding confidence、source/geometry/legal authority。
2. 让空结果、未尝试、缺能力、可重试失败、永久失败、超时、鉴权失败、配额耗尽分别形成可重载 observation/receipt/gap，不转译成现实不存在。
3. 保持 external provider 坐标为 observation/locator evidence，禁止直接进入本地 execution representation；复用现有 provider/cache tests 和本地真实数据。
4. 实现 Evidence artifact CAS reload、fingerprint 幂等、retry/recovery，并输出可供 L1 消费的公开 bootstrap/enrichment contract。
5. 只删除已确认无调用方的重复 Evidence 兼容逻辑；更新 runtime/migration。

## Task 5: L1ObservationSnapshot and explicit observation rows

1. 在现有 L1 aggregation/facade 上补齐冻结、可重载的 `L1ObservationSnapshot` 及 `L1FactRow`、`L1LocationMention`、`L1RelationMention`、`L1GroundingRequest`、`L1Gap`；保持旧 `L1Snapshot` 的活跃调用方兼容，逐步迁移公开入口。
2. 明确 fact ≠ mention ≠ entity，relation mention ≠ verified relation；保存 Evidence/source span/authority/confidence/lineage，禁止对 observation 做原地修改。
3. 当上游 DATA/WM/Evidence gap 未通过 gate 时停止 L1，不增加本地 fallback；真实输入生成非空 fact/mention/gap，并通过 CAS reload 校验 digest/parent closure。
4. 只删除已完成调用方迁移的旧 L1 组装重复路径；更新 runtime/migration。

## Task 6: L1-GROUND proposal, Cognition commit, binding revalidation

1. 在现有 ground candidate resolver/identity sidecar 基础上，定义合法终态 taxonomy：`grounded_exact`、`grounded_feature_set`、`grounded_entity_without_geometry`、`inferred_scope`、`ambiguous_entity`、`ambiguous_representation`、`source_geometry_missing`、`source_semantics_missing`、`evidence_insufficient`、`provider_failed`、`not_spatial_work_item`、`human_required`、`rejected`。
2. 每个 required work item 必须恰好一个终态；LLM 如使用只能消费 deterministic closed candidate set 并返回 selected/ambiguous/abstain，不能创建 refs/coords/geometries/provider request。
3. L1-GROUND 只产生 proposal，通过 Cognition `WorldModelCommitPort` 原子提交；直接写 World Model 的路径必须被 facade 边界阻断或迁移。
4. 针对 commit 后新 World Model snapshot 做 binding revalidation，持久化 old/new snapshot、affected binding、reason 和结果；stale parent/ambiguous/unsupported 路径保留 gap/HUMAN，不伪造绑定。
5. 复用/迁移现有 ground tests/probes，不实现 planning ground/target projection/solver candidate。

## Task 7: L1FinalProduct, L1ProductManifest and bounded L2 consumer

1. 定义并持久化 `L1BindingSnapshot`、`L1FinalProduct`、`L1ProductManifest`，包含 observation/L1 snapshot/binding/WM snapshot refs and digests、fact/binding row digests、open/terminal gaps、status 和 post-commit revalidation evidence。
2. finalization 只接受通过 gate 且已针对新 WM snapshot revalidated 的 binding；每一条 grounding request 都必须有唯一终态；不把 partial/provider failure/人工待决伪装成 ready。
3. 将新 artifact key 接入现有 `ContentAddressedArtifactRepository`、`store_artifact`、stage adapter 和 context refs；所有 artifact 可 reload，重复 finalization 幂等。
4. 实现一个最小公开 L2 consumer/probe，只读取 `L1ProductManifest` / `L1FinalProduct`，检查 refs/digests/gaps 并产生有界消费结果；不得触发完整 L2/L3/planning 链。
5. 清除已迁移且无调用方的旧 final handoff 重复代码；更新 acceptance README、CURRENT_RUNTIME 和唯一 migration ledger。

## Task 8: 全链 fresh runtime verification and final review

1. 用真实金田村支持输入运行新的生产 facade 纵向切片：DATA→WM→Evidence→L1 observation→L1-GROUND→Cognition commit→binding revalidation→L1 final。
2. 逐阶段 reload CAS artifacts，核对内容、来源引用、状态、authority、lineage、digest、parent closure 和失败/恢复信息。
3. 运行 bounded L2 consumer probe；验证它只通过公开 final contract 消费；不得把旧 L2 artifact 作为证据。
4. 运行全量既有 tests、compile、diff check，并核对没有新增回归；清理一次性脚本和本计划 scratch artifacts（不删除项目既有 artifacts）。
5. 复核兼容路径删除范围、未完成项目及 migration 定位；完成最终 whole-branch review，最终报告只包含目标文件要求的九项。

## Expected verification commands

```powershell
$env:PYTHONPATH = 'backend'
python -m compileall -q backend/app
python -m pytest tests -q
git diff --check
python scripts/acceptance/business_stage_boundary_probe.py --help
python scripts/acceptance/l1_facade_probe.py --help
python scripts/acceptance/l1_l2_facade_probe.py --help
```

Fresh runtime commands and artifact paths will be recorded in the SDD ledger and final report after implementation; historical `.run-tmp` artifacts will be labeled historical and never used as fresh proof.
