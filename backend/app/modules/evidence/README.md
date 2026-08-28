# Evidence 业务 Facade

`modules/evidence` 是证据业务语义的 owner，不是 retriever 目录。

业务阶段只创建 `EvidenceRequirement`，声明 statement、scope、用途、允许的
推断级别和成功条件，然后通过 `EvidenceApplication.retrieve()` 请求
`ExplorationResult`。它负责解释什么证据满足什么业务判断、覆盖是否足够、缺口
是否阻塞；它不访问 KG、Bundle、Report、GIS、RAG 或外部 provider。

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
状态必须可重载。
