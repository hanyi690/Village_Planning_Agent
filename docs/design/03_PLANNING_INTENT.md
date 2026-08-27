# 03 L3：规划意图

## 1. 业务问题

L3 将 L2 策略表达为可追溯、可编译、尚未执行的规划意图。

## 2. 输入与输出

输入：`L1Snapshot`、`L2DecisionSet`、维度配置和 EvidencePacket。

输出：`PlanningProgram`，包含 claims、planning roles、target hints、fact/evidence refs、location hints、grounding requirements、uncertainty 和 pending claims。

## 3. 子图

```text
load L1/L2 projections → claim draft → normalize claim
→ close fact/evidence refs → detect gap
→ retrieve resolvable evidence → re-evaluate claim
→ deterministic program assembly
```

## 4. 允许和禁止

允许：coarse target family、planning role、action intent、数量/容量意图、location hint、关系需求、接地需求。

禁止：最终 geometry、candidate membership、winner、ScenarioSet、ApprovedExecutionInput、ExecutionPlan、PlannedState。

## 5. LLM 与验收

每次调用只生成一组小 claim 或判断一类 claim 问题。上下文使用 L1/L2 命名表格。真实验收是 `L1Snapshot + L2DecisionSet → PlanningProgram`，每个 claim 有 lineage，不能通过自然语言猜测补全空间对象。

