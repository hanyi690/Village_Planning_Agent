# Design documentation

> Status: TARGET
> Authority: Navigation for the canonical target-design set. Governance is owned by `DOCUMENTATION_AUTHORITY.md`; observed behavior is owned by `../architecture/CURRENT_RUNTIME.md`; migration status is owned only by `05_MIGRATION.md`.

`design/` 只定义目标语义、所有权、边界和验收规则，不证明能力已经实现。字段级 authority 是 Pydantic、provider response models、生成 OpenAPI 和可重复测试；设计文档不复制 schema 表。

## Start here

- [DOCUMENTATION_AUTHORITY.md](DOCUMENTATION_AUTHORITY.md)：文档冲突时的 canonical owner map。
- [DOCUMENT_CLEANUP_MANIFEST.md](DOCUMENT_CLEANUP_MANIFEST.md)：后续归档/清理的精确路径清单；本轮不删除文档。
- [00_SYSTEM_DESIGN.md](00_SYSTEM_DESIGN.md)：单一权威语义链、L1/L2/L3 模型事务、报告时点、LLM/确定性边界和完成规则。
- [01_CONTRACTS_AND_INVARIANTS.md](01_CONTRACTS_AND_INVARIANTS.md)：对象分类、provider wire/domain contract 分离、item-level failure atomicity 及 `EFF-01` 至 `EFF-08`。
- [02_EVIDENCE_AND_GROUNDING.md](02_EVIDENCE_AND_GROUNDING.md)：EvidenceGap → EvidenceRequirement、检索、coverage 和 grounding 的主规范。
- [03_PLANNING_EXECUTION.md](03_PLANNING_EXECUTION.md)：方案、审批、物化、验证、对账和交付设计。
- [04_EVALUATION_AND_ACCEPTANCE.md](04_EVALUATION_AND_ACCEPTANCE.md)：正确性与效率 acceptance gates。
- [05_MIGRATION.md](05_MIGRATION.md)：唯一 target-to-current ledger；只在这里记录 `CURRENT`、`PARTIAL`、`GAP`、`RETIRE`、`BLOCKED`。

## Reading paths

- 理解目标：`00` → `01` → `02` → `03` → `04`。
- 核对现状：[CURRENT_RUNTIME.md](../architecture/CURRENT_RUNTIME.md) → [API_AND_STATE.md](../architecture/API_AND_STATE.md) → [OPERATIONS.md](../architecture/OPERATIONS.md)。
- 判断差距：先读目标 owner，再只查 `05_MIGRATION.md`；不要从 historical plan、report 或 ADR 状态措辞推断完成度。
- 理解决策历史：[ADR](../adr/)；ADR 约束设计，但不替代 current-runtime evidence。

不得在 `design/` 新建日期状态页、第二套总体蓝图或重复契约表。新内容必须修改其 canonical owner；历史与执行材料按 cleanup manifest 处理。
