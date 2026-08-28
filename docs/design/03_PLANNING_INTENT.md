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

允许：coarse target family、planning role、action intent、数量/容量的文字意图、location hint、关系需求、接地需求。

L3 的 provider wire contract 刻意保持为粗意图字段。LLM 不产出结构化参数块、项目包、候选、实体身份、source binding、坐标或 geometry；数量、面积、容量等复杂字段必须由后续的结构化输入、权威来源或确定性编译补齐，不能从 LLM prose 贸然生成。

禁止：最终 geometry、candidate membership、winner、ScenarioSet、ApprovedExecutionInput、ExecutionPlan、PlannedState。

## 5. LLM 与验收

每次调用只生成一组小 claim 或判断一类 claim 问题。上下文使用 L1/L2 命名表格。真实验收是 `L1Snapshot + L2DecisionSet → PlanningProgram`，每个 claim 有 lineage，不能通过自然语言猜测补全空间对象。若空间 claim 尚不能形成 typed intervention，必须按 claim 生成 pending grounding item，并携带当前 L1 snapshot 与 source input refs，供后续 GROUND 或人工结构化补录处理。

## L3 目标目录与迁移出口

```text
backend/app/modules/l3/
├── application.py
├── claim_generation.py
├── claim_normalization.py
├── claim_validation.py
├── reasoning.py
├── aggregation.py
└── projections.py
```

当前 L3 实现在 `modules/l3/`；目标投影单独集中在 `modules/target_projection/`。迁移出口是：`PlanningProgram` 可真实生成、可重载，并被目标编译阶段消费。
