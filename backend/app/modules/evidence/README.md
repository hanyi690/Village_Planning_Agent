# Evidence 业务 Facade

`modules/evidence` 是证据业务语义的 owner，不是 retriever 目录。

业务阶段只创建 `EvidenceRequirement`，声明 statement、scope、用途、允许的
推断级别、`policy_ref` 和成功条件，然后通过 `EvidenceApplication.retrieve()` 请求
`ExplorationResult`。它负责解释什么证据满足什么业务判断、覆盖是否足够、缺口
是否阻塞；它不访问 KG、Bundle、Report、GIS、RAG 或外部 provider。

当前采集审计链固定为：

```text
EvidenceRequirement
    -> EvidencePolicyRegistry
    -> EvidenceQueryPlanV1
    -> AcquisitionRouteExecutor
    -> ProviderAttempt / ProviderPageRecord
    -> EvidenceObservationSnapshot
    -> EvidenceAcquisitionReceipt
    -> CandidateEvidence / ConflictSet / Coverage / Sufficiency
    -> EvidenceProposalBatch
    -> EvidenceRetrievalArtifact
```

其中 QueryPlan 只声明 requirement、scope、来源 route、分页和预算语义；endpoint、
凭据、网络、lease/fencing 与 raw response 持久化仍属于 DATA/provider acquisition
runtime。`EvidenceAcquisitionReceipt` 只描述采集是否完成，不替代后续
policy-driven sufficiency 判断。EV-03 的 `proposals.py` 只把已通过 sufficiency 的
requirement 编译为 `EntitySupportProposal`、`RelationSupportProposal`、
`PropertyAssertionProposal` 或 `RepresentationSupportProposal`，保留 candidate、
observation/claim、source、policy、authority、valid time、packet digest 与 WM parent
digest。它只通过转换函数生成 Cognition 的 `AssertionProposal` 输入，Evidence 不拥有
decision，也不调用 `WorldModelCommitPort`。

Frozen external cache 使用独立的 `frozen_cache` acquisition attempt；原始
provider 的状态只作为 `origin_*` provenance 保存。即使完整读取一个
`QUOTA_EXHAUSTED` 或 `PARTIAL` 的历史缓存，本次 cache read 也不能被解释为
原始 provider acquisition 已完整，且不会生成本次 PageRecord 或本地执行几何。

实际查询执行集中在
`backend/app/infrastructure/evidence_runtime/`：QueryPlanner、RetrieverRouter、
各来源 retriever、fusion、provenance、coverage、sufficiency、cache 和 provider
降级均由该 runtime 负责。

## 公开入口

```python
result = await EvidenceApplication().retrieve(
    requirements,
    EvidenceContext(
        session_id=session_id,
        stage="L1",
        purpose="snapshot_fact_production",
        request_type="spatial_lookup",
    ),
)
```

`retrieve_evidence` 等符号只为 API/workflow 适配器保留；新的业务阶段不得直接
导入它们。L1/L2/L3 的维度 worker 如需一次性获得当前维度的 bounded analysis
projection，使用 `EvidenceFacade.retrieve_dimension_context()`；该方法仍只暴露
业务维度、当前状态和排除项，query planning、retriever 路由、来源访问与表格投影
均留在 runtime 内部。Evidence 结果可以通过既有 CAS artifact runtime 持久化，
`EvidencePacket` 中的 query fingerprint、来源、locator、coverage 和 unresolved
状态必须可重载。当前采集事实统一使用 `ProviderAttemptStatus`，不得新写宽泛的
`failed` 或 `missing`；Evidence 不再读取或写入旧的 provider-run 状态。
