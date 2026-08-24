# Design documentation

> Status: TARGET
> Authority: Navigation for the canonical target-design set; current behavior is documented under `../architecture/`.

`design/` 只描述目标行为和规范不变量；`architecture/` 只描述当前工作树中有代码路径或可重复测试支持的行为。`TARGET` 不能用于证明能力已经实现，`CURRENT` 也不能反向改变目标设计。

- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)：产品结果、三平面架构、权威主链和完成定义。
- [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md)：契约所有权、身份、lineage、门控和不变量。
- [02_EVIDENCE_AND_GROUNDING.md](02_EVIDENCE_AND_GROUNDING.md)：证据要求、混合检索、自然语言空间查询和 GROUND。
- [03_PLANNING_EXECUTION.md](03_PLANNING_EXECUTION.md)：ScenarioOptimizer、ScenarioSet、审批、原子执行和验证。
- [04_EVALUATION_AND_ACCEPTANCE.md](04_EVALUATION_AND_ACCEPTANCE.md)：基准、指标、验收门槛和回归证据。
- [05_MIGRATION.md](05_MIGRATION.md)：当前实现到目标契约的唯一迁移清单。

其他入口：[当前实现](../architecture/README.md)、[ADR](../adr/)、[稳定参考资料](../reference/)、[历史归档](../_archive/)。

不得在 `design/` 根目录新增日期状态页、实施台账或第二套模块蓝图。新的模块级重大设计必须先写 ADR，或者直接修改上述某一份权威文档；字段级 API 不在设计文档复制，以 Pydantic 与生成契约为准。
