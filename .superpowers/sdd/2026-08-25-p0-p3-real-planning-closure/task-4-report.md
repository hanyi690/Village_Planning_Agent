# P0-D 实现报告

日期：2026-08-25

## 范围

本次只收敛 P0-D 最小闭环，并包含 CandidateGeometry/CandidateSite 的直接 schema 边界：

- CandidateGeometry/CandidateSite 移除旧单一 `confidence` 与 `compatibility_diagnostics` 入口；显式 `identity_confidence`、`geometry_confidence`、`suitability_score` 保留为新 schema。
- 缺少显式 grounding 字段的候选进入 `pending`，旧字段或旧 artifact 进入 schema-invalid/校验失败；未迁移其他领域独立语义的 confidence。
- 新增 typed SolverReadiness contract 及 builder，覆盖 target、relation、demand、network、candidate、backend、snapshot、task graph，并输出状态、blocker/source refs 与 fingerprint。
- SELECT 在 suitability/refinement/subproblem compile/optimize 前执行 readiness preflight；硬缺口短路为可解释 gate/HUMAN artifact，ready 才绑定 subproblem/scenario certificate。

## 主要文件

- `backend/app/contracts/spatial/candidate_geometry.py`
- `backend/app/contracts/spatial/grounding_contracts.py`
- `backend/app/domain/ground/aggregate.py`
- `backend/app/domain/allocation/refined_candidate_catalog.py`
- `backend/app/contracts/planning/solver_readiness.py`
- `backend/app/domain/allocation/solver_readiness.py`
- `backend/app/workflow/stages/select.py`
- `backend/app/domain/allocation/select_gate.py`
- `backend/app/domain/allocation/subproblem_compiler.py`
- `backend/app/contracts/planning/scenario.py`
- `backend/app/contracts/planning/solver.py`
- readiness artifact registration and stage adapter wiring
- bounded candidate/artifact/select/readiness tests

## 验证

定向测试：

```text
33 passed, 1 warning in 3.79s
```

命令范围：`test_solver_readiness.py`、`test_typed_candidate_geometry.py`、`test_artifact_runtime.py`、`test_select_gate_deferred_targets.py`、`test_solver_subproblem_decomposition.py`。

覆盖 ready parcel-only、缺 demand/network、缺 relation evaluator/backend、search-scope/candidate-only、旧 confidence schema-invalid、缺显式字段 pending，以及 SELECT preflight 不调用 suitability/optimizer。

另外完成：

- changed-module/backend-test `compileall`：通过
- `git diff --check`：通过

唯一测试告警是环境已有的 pytest cache 目录 `WinError 5`，不影响测试结果。

## 降级与剩余风险

- 本提交没有进行全仓 confidence 迁移；未触及 evidence/anchor 等独立语义，也没有迁移无关历史测试或 replay/support dirty files。
- 旧 CandidateGeometry/CandidateSite artifact 现在按 schema-invalid 失败，缺字段新建对象按 pending 处理；后续阶段仍需按 artifact 生产链逐步迁移未纳入本闭环的历史 fixture/回放数据。
- 当前 readiness 对可选 baseline、task graph、parcel-only demand 等软缺口保留 advisory；真实外部 backend/数据快照完整性仍由后续阶段和环境配置验证。
