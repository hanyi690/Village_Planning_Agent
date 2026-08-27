# 01 L1：现状事实构建

## 1. 业务问题

L1 回答“村庄现在有什么可证明的事实”。它把报告、Bundle、KG、GIS、上传资料和外部权威资料转化为带来源、证据和推理等级的事实。L1 的权威结果是事实，不是报告文字。

## 2. 输入与输出

输入：`SessionDataSnapshot`、来源索引、Bundle、KG、GIS、EvidenceRequirement。

输出：`L1Snapshot`，并附属 `L1FactCatalog`、`L1ObservationSnapshot`、`L1BindingSnapshot`。

fact 必须包含：`fact_id`、`subject_ref`、`predicate`、`value`、`source_refs`、`evidence_refs`、`inference_level`、`confidence`、`uncertainty`、`status`。

## 3. 子图

```text
load snapshot → retrieve report/Bundle/KG/GIS
→ observe source pages → infer fact candidates
→ validate source/provenance → detect gap/conflict
→ immediately retrieve resolvable gap
→ re-evaluate facts → assemble L1Snapshot
```

fact 类型：`observed`、`derived`、`inferred`、`conflicted`、`pending`。KG/Bundle 结合推理可以形成 `inferred_fact`，但不能冒充直接观察事实。

## 4. LLM 事务与 context

每次只做 observation、fact candidate、冲突判断或 gap classification 之一。输入为有限表格：

```text
| source_ref | subject | statement/value | source_type | evidence_ref |
|---|---|---|---|---|
```

模型不直接写 `L1Snapshot`；由 parser、validator 和 assembler 生成最终 artifact。

## 5. 边界和验收

L1 不生成规划目标、地块选择、scenario 或执行任务。验收要求真实输入生成可重载 `L1Snapshot`，事实可追溯，KG/Bundle 推理可标记，能解决的 gap 已立即尝试，并且 L2 只通过公开 contract 消费。

