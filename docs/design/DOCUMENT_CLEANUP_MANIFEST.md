# Document Cleanup Manifest

> Status: CURRENT
> Authority: Record of removed legacy code, historical execution material, and generated audit/runtime residue.

本清单只记录已经执行的清理结果。清理对象不属于当前运行时、当前设计输入或业务源数据；不得从这些对象恢复实现，也不得把它们作为会话输入。

## Removed legacy implementation surfaces

以下路径已从工作树移除，当前业务实现归属以 `backend/app/modules/`、`backend/app/infrastructure/`、`backend/app/contracts/` 和 `backend/app/workflow/` 为准：

- `backend/app/domain/`
- `backend/app/evidence/`
- `backend/app/infrastructure/context/`
- `backend/app/contracts/domain/`
- `backend/app/acceptance/`
- `backend/tests/` 及旧测试配置、旧前端测试树
- `backend/_e2e_resume.py`
- `backend/scripts/benchmark_real_evidence.py`
- `backend/scripts/resume_graph_checkpoint.py`
- `backend/scripts/low_memory_spatial_acceptance.py`

`modules/evidence/`、`infrastructure/evidence_runtime/`、`infrastructure/context_runtime/` 和 `infrastructure/structured_runtime/` 不在清理范围，它们是当前设计的正式边界。

## Removed historical or generated material

以下内容已删除，不再作为项目上下文保留：

- `.analysis/`
- `.graphify-review/`
- 根目录 `.graphify_*` 分析快照和 `.codex_incremental_probe.json`
- `.opencode/`
- `.workbuddy/`
- `.tmp/`；`.run-tmp/` 中的旧运行内容已清理。当前运行器会为正在验收的
  session 重新生成被 `.gitignore` 忽略的 CAS/descriptor 临时目录；这些当前
  artifact 不是设计输入，也不得被其他 session 复用。
- `docs/_archive/`
- `docs/superpowers/`
- `docs/reports-weekly/`

## Active documentation only

当前文档权威入口是：

- `docs/design/00_SYSTEM_DESIGN.md` 至 `docs/design/06_SELECT_EXECUTE_AND_CODE.md`
- `docs/design/05_MIGRATION.md`
- `docs/design/DOCUMENTATION_AUTHORITY.md`
- `docs/architecture/`
- `docs/adr/`
- `docs/contracts/`
- `docs/guides/`
- `docs/reference/`

历史运行结果只能作为开发者本轮诊断的临时终端输出，不能写回业务 artifact、不能参与新的运行，也不能替代 fresh run。
