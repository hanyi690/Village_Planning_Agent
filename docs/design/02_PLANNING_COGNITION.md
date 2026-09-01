# 02 L2：规划认知

## 1. 业务问题

L2 回答“基于现状应该解决什么问题、采用什么策略”。它负责问题、目标、需求、指标、适宜性、策略、优先级和冲突。

## 2. 输入与输出

输入不是裸 facts，而是同一版本向量下的 <code>L1FinalProduct</code>、
<code>L1BindingSnapshot</code>、current <code>WorldModelSnapshot</code> ref、规划任务、规划配置和
<code>EvidencePacket</code>。Entry Gate 必须验证 observation、binding 与 World Model digest
一致；未接地 mention 只能作为 uncertainty/gap，不能进入确定性空间事实投影。

输出：`L2Strategy` artifact，内部包含各维度的 `L2DecisionSet`，并汇总 objectives、demand、metrics、suitability、strategies、priorities、conflicts、evidence_requirements 和 L1 ref。

## 3. 子图

```text
load L1 fact table → identify problems → build objectives
→ demand/suitability reasoning → strategy/priority
→ detect evidence gap → immediate evidence completion
→ validate decisions → assemble L2DecisionSet
```

Evidence completion is best-effort for ordinary gaps.  If the current source
cannot resolve a requirement, the decision artifact records the concrete gap,
source input and recovery pointer, then continues with a partial result.  Only
an absent artifact, invalid lineage, contradiction, or another hard invariant
may stop the stage; an unresolved fact must not be fabricated or used as a
reason to loop indefinitely.

## 4. 边界

L2 可以说“优先完善养老服务”“应优先使用建设边界内空间”，但不能指定具体 parcel、geometry、candidate、scenario 或 execution task。`demand`、`objectives`、`suitability` 和 `strategy` 属于 L2；`allocation` 的正式求解属于 SELECT。

## 5. LLM 与验收

给模型的是 L1 final facts、已验证 binding、不确定性、问题和配置的命名表格 projection；每次
只生成问题、目标、策略或冲突中的一种。真实验收是
<code>L1FinalProduct + L1BindingSnapshot + WorldModelSnapshot ref → L2DecisionSet</code>，每个
目标可回溯事实、binding、Evidence 或配置，L2 可被 L3 消费。

## L2 目标目录与迁移出口

```text
backend/app/modules/l2/
├── application.py
├── problem_identification.py
├── objectives.py
├── demand.py
├── suitability.py
├── strategy.py
├── reasoning.py
└── aggregation.py
```

当前 L2 的需求、目标和适宜性实现集中在 <code>modules/l2/</code>；SELECT 实现在
<code>modules/select/</code>。迁移出口是：真实 <code>L1FinalProduct + L1BindingSnapshot +
WorldModelSnapshot ref</code> 生成 <code>L2DecisionSet</code>，并由 L3 通过公开 contract 消费。
