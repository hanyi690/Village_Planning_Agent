# 02 L2：规划认知

## 1. 业务问题

L2 回答“基于现状应该解决什么问题、采用什么策略”。它负责问题、目标、需求、指标、适宜性、策略、优先级和冲突。

## 2. 输入与输出

输入：`L1Snapshot`、规划任务、规划配置和 EvidencePacket。

输出：`L2DecisionSet`，包含 objectives、demand、metrics、suitability、strategies、priorities、conflicts、evidence_requirements 和 L1 ref。

## 3. 子图

```text
load L1 fact table → identify problems → build objectives
→ demand/suitability reasoning → strategy/priority
→ detect evidence gap → immediate evidence completion
→ validate decisions → assemble L2DecisionSet
```

## 4. 边界

L2 可以说“优先完善养老服务”“应优先使用建设边界内空间”，但不能指定具体 parcel、geometry、candidate、scenario 或 execution task。`demand`、`objectives`、`suitability` 和 `strategy` 属于 L2；`allocation` 的正式求解属于 SELECT。

## 5. LLM 与验收

给模型的是 L1 facts、问题和配置的表格 projection；每次只生成问题、目标、策略或冲突中的一种。真实验收是 `L1Snapshot → L2DecisionSet`，每个目标可回溯事实或配置，L2 可被 L3 消费。

