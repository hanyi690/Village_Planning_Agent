# 当前规划领域边界

> 本文是实现映射；目标不变量见
> [`../design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md)。

| 阶段 | 当前实现入口 | 允许消费 | 禁止行为 |
|---|---|---|---|
| L1/L2/L3 | `workflow/layers/`、`domain/assessment/`、`domain/objectives/`、`domain/program/` | typed context、evidence、claims 和阶段 refs | 直接写空间成果或把报告正文当作事实 |
| TARGET_PROJECTION | `workflow/stages/target_projection.py` | `PlanningProgram` artifact | 重新解析 Markdown、猜分类、直接选地 |
| GROUND | `workflow/stages/ground.py`、`domain/ground/` | `SpatialReferenceSpec`、KG/空间证据和 workspace | 以名称或第一个候选绕过歧义 |
| SELECT | `workflow/stages/select.py`、`domain/{demand,suitability,allocation}/` | grounding、约束、目标和候选证据 | 生成未绑定坐标或静默丢弃未安置原因 |
| EXECUTE | `workflow/stages/execute.py`、`domain/materialization/` | `ExecutionPlan`、selection refs、workspace | 重选址、重分类、从报告文本补输入 |
| VALIDATE | `workflow/stages/validate.py`、`domain/validation/` | execution refs、context 和规则 | 吞掉错误后继续交付 |
| RECONCILE | `workflow/stages/reconcile.py`、`domain/delivery/` | claims、target、selection、changeset、planned state | 仅修改渲染结果来掩盖规划不一致 |
| DELIVER | `workflow/stages/deliver.py`、`domain/delivery/` | 唯一 `DeliverySpatialSnapshot` | 各自选择 current/planned 来源 |

所有阶段通过 `contracts/` 和 artifact refs 交换结果。目录职责不等于完成状态，具体
`CURRENT/PARTIAL/GAP` 查看实现状态台账。
