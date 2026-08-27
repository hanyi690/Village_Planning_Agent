# 05 TARGET_PROJECTION 与 GROUND

## 1. TARGET_PROJECTION

输入 `PlanningProgram`，输出 `AdmittedTargetSet` 和 `GroundingRequest`。它建立 target identity、target family、package、claim lineage、geometry/evidence/relation requirements 和 grounding readiness。

```text
PlanningProgram → admission → target identity/family
→ requirement compilation → lineage validation → GroundingRequest
```

它不能从 prose 猜 geometry、候选或执行参数，也不执行空间查询。

## 2. GROUND

GROUND 输入 `GroundingRequest`、L1Snapshot、EvidencePacket、SpatialWorkspace，输出 `GroundedPlanningProblem`。

```text
resolve references → classify resolved/unresolved
→ build context from resolved objects
→ related evidence/spatial retrieval
→ bounded LLM resolution proposal
→ deterministic spatial verify
→ use resolved objects to assist unresolved references
→ repeat within budget → candidates/constraints → problem
```

已解决的对象可提供邻近、拓扑、道路、地址和范围上下文；LLM 只能返回 candidate ref、next query 或 reason code，最终 geometry 必须经过空间确定性校验。

## 3. 输出与验收

`GroundedPlanningProblem` 必须包含 targets、candidates、geometry、relations、constraints、evidence refs、snapshot refs、unresolved、deferred 和 fingerprint。每个 target 必须有接地状态；无数据和无候选必须区分；SELECT 只能消费该闭集。

