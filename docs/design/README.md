# Design documentation

> Status: TARGET
> Authority: Navigation for the canonical target-design set. Governance is owned by `DOCUMENTATION_AUTHORITY.md`; observed behavior is owned by `../architecture/CURRENT_RUNTIME.md`; migration status is owned only by `05_MIGRATION.md`.

`design/` 只定义目标语义、所有权、边界和验收规则，不证明能力已经实现。字段级 authority 是 Pydantic、provider response models、生成 OpenAPI 和可重复测试；设计文档不复制 schema 表。

## Start here

- [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md)：文档冲突时的 canonical owner map。
- [DOCUMENT_CLEANUP_MANIFEST.md](DOCUMENT_CLEANUP_MANIFEST.md)：后续归档/清理的精确路径清单；本轮不删除文档。
- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)：全链路业务流程、阶段关系、阶段反馈和共同运行规则。
- [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md)：L1 事实构建、事实类型、契约和结构化输出边界。
- [02_PLANNING_COGNITION.md](02_PLANNING_COGNITION.md)：L2 规划问题、目标、需求、适宜性和策略。
- [03_PLANNING_INTENT.md](03_PLANNING_INTENT.md)：L3 claim、PlanningProgram、lineage 和接地前边界。
- [04_EVIDENCE.md](04_EVIDENCE.md)：Evidence 检索、KG/Bundle 融合、推理、coverage 和 gap 闭合。
- [05_PROJECTION_AND_GROUND.md](05_PROJECTION_AND_GROUND.md)：目标编译和 GROUND 迭代接地子图。
- [06_SELECT_EXECUTE_AND_CODE.md](06_SELECT_EXECUTE_AND_CODE.md)：SELECT、EXECUTE、后处理和目标代码树。
- [05_MIGRATION.md](05_MIGRATION.md)：目标到当前的迁移状态和前后阶段适配记录。

## Reading paths

- 理解目标：`00` → `01` → `02` → `03` → `04` → `05` → `06`。
- 核对现状：[CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md) → [API_AND_STATE.md](../architecture/API_AND_STATE.md) → [OPERATIONS.md](../architecture/OPERATIONS.md)。
- 判断差距：先读目标 owner，再只查 `05_MIGRATION.md`；不要从 historical plan、report 或 ADR 状态措辞推断完成度。
- 理解决策历史：[ADR](../adr/)；ADR 约束设计，但不替代 current-runtime evidence。

不得在 `design/` 新建日期状态页、第二套总体蓝图或重复契约表。新内容必须修改其 canonical owner；历史与执行材料按 cleanup manifest 处理。
