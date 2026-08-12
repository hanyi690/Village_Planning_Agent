# 校验、门控与定向反馈

> 本文定义阶段校验和反馈的设计原则。产出驱动自动迭代、多模态证据及其与
> `ValidationReport.adjustments` 的融合，以
> [13_AUTOREPAIR_MULTIMODAL.md](13_AUTOREPAIR_MULTIMODAL.md) 为唯一扩展设计。
> 下文的 `ValidationIssue` 是问题语义视图，不要求新增一套平行业务契约；实现应
> 映射到现有 `ValidationReport`、`GateDecision` 和 artifact provenance。

## 1. 校验不是一个总重试循环

校验结果必须带有缺陷归因：

```python
class ValidationIssue(BaseModel):
    issue_id: str
    stage: Literal['l1', 'l2', 'l3', 'ground', 'select', 'execute', 'delivery']
    code: str
    severity: Literal['warning', 'error', 'blocking']
    message: str
    evidence_ids: list[str] = []
    suggested_action: str | None = None
```

## 2. 定向反馈矩阵

| 缺陷 | 返回阶段 | 说明 |
|---|---|---|
| 事实缺失 | EXPLORE → 原阶段 | 补证据后只重跑受影响维度 |
| L1 事实矛盾 | L1 | 重新汇总事实，不重跑 GIS |
| 策略不符合现状 | L2 | 修改策略或请求新证据 |
| Target 缺字段 | L3 / IntentCompiler | 重新编译意图 |
| 实体歧义 | GROUND / EXPLORE | 不自动猜测 |
| 候选为空 | GROUND 或 L3 | 区分空间解析失败和目标不可实施 |
| 候选冲突 | SELECT | 重新分配或调整评分 |
| 图层算法失败 | EXECUTE | 保留选址决定，重跑 Worker |
| 文本与成果不一致 | L3 Reconcile | 不能只修改渲染结果 |
| 成果规范失败 | DELIVERY | 返回 Validate，不改变规划意图 |

真实 GIS 迭代反馈：候选绑定不能只验证 BSM 存在。SELECT 进入 EXECUTE 前必须执行
候选可实施性硬过滤：几何有效、现状地类不是不可建设水域/生态林、项目目标面积有足够
单地块承载能力；被过滤的 BSM 必须进入 `EliminatedCandidate`，并带有稳定原因码，不能
让 EXECUTE 先生成再由 VALIDATE 才发现。若目标需要多地块合并，应由对应分区分配器
显式声明聚合策略，而不是让普通项目选择器隐式放宽面积约束。

## 3. Gate 行为

Gate 只做三件事：

1. 检查当前 artifact 是否满足进入下一阶段的条件。
2. 生成结构化 `ValidationIssue` 或 `ExplorationRequest`。
3. 决定通过、定向反馈、人工确认或终止。

Gate 不执行领域算法，不拼接报告，不刷新 Bundle。

## 4. 人工确认点

建议保留四个可配置人工确认点：

- L1：事实和证据是否可信。
- L2：目标和策略是否接受。
- L3：详细规划意图是否接受。
- Delivery：成果是否满足交付标准。

GROUND 的多实体歧义和 SELECT 的低置信度选址可以触发局部人工确认，不需要暂停整个会话。

## 5. 文本与成果对账

`RECONCILE` 比较：

- `PlanningProgram` 中的干预是否都被编译，且 `IntentCompilationResult` 中的目标是否都产生了 PlannedState。
- 每个 PlannedState 是否能回溯到目标、候选、决定和证据。
- 规划数量、规模、位置和约束是否仍满足文本要求。
- 渲染图层、GDB 图层和报告中的统计是否一致。
