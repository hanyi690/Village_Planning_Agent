# EV-02 Policy-Driven Sufficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal

将 Evidence 的 Sufficiency 从当前的通用文本匹配升级为 requirement-specific、policy-driven 的确定性评估。正式链路为：

`Observation → CandidateEvidence → ConflictSet → Coverage → Sufficiency`

评估必须逐项检查 source family、source authority、independent sources、temporal fit、geometry/legal authority、conflict policy、allowed inference、acquisition completeness、provider origin completeness，最后才允许进入 absence policy。EV-02 只产出 Sufficiency 结果及其审计依据，不实现 EV-03 Proposal，也不拥有 WM 写入能力。

## Architecture

- 在 `backend/app/contracts/evidence` 增加稳定的 reasoning contracts，保存候选证据、冲突集合、十项 gate 及 requirement-level sufficiency decision。
- 在 `backend/app/modules/evidence` 增加纯确定性的 policy reasoning evaluator：从 typed observations、facts、sources、acquisition receipt 生成 CandidateEvidence，检测 ConflictSet，按 policy 顺序运行 gates。
- 保留现有 application-facing `SufficiencyDecision` 作为运行时结果载体，但其内容由新的 policy evaluator 产生；不恢复已删除的旧 acquisition/provider compatibility API。
- 让 `EvidenceCoverage` 持久化候选证据、冲突集合和 requirement-level decision，确保之后可以审计“为什么够/为什么不够”。
- 调整 facade 的执行顺序，使 acquisition audit receipt 先完成，再执行 EV-02 Sufficiency；禁止在 receipt 形成前判断 absence。
- 继续由 `CognitionCommitPort` 作为唯一 WM writer；本计划不新增 Evidence → WM 的写入路径。

## Tech Stack

- Python 3、Pydantic v2 contracts、现有 Evidence Application/Facade runtime。
- pytest，使用小型 typed fixtures 覆盖十个 gate 和 absence late gate。
- 现有 SHA-256/canonical serialization 约定，用于 candidate/conflict/decision 的稳定引用。

## Global Constraints

- 不保留历史兼容字段、旧 provider_runs 路径或从 trace 推导 typed attempt 的逻辑。
- policy 是唯一的 requirement-specific 判断来源；LLM、字符串启发式和 facade 不能绕过确定性 gates。
- absence 不是“没有观察”的别名，只能在所有前置 gate、完整采集、完整分页、独立来源和无未解决冲突之后生成。
- 既有非 Evidence 的失败测试不扩大本次范围；本次修改必须保持 Evidence 既有 acquisition audit、frozen cache 和 WM transaction 行为。
- 遵守 TDD：每个行为先写能失败的测试（RED），再实现（GREEN），最后做最小重构并执行回归测试。

## Tasks

- [x] Task 1: Define EV-02 reasoning contracts and write RED contract tests.
  - Add frozen, `extra="forbid"` models for `CandidateEvidence`, `ConflictSet`, `SufficiencyCheck`, requirement-level policy decision, and aggregate reasoning output.
  - Add typed fields to `RequirementCoverage`/`EvidenceCoverage` for candidate refs, conflict refs, gate results, policy identity, and persisted sufficiency decision.
  - Test deterministic references, forbidden legacy-shaped fields, gate ordering metadata, and round-trip serialization.

- [x] Task 2: Build the Observation → CandidateEvidence → ConflictSet compiler and make candidate/coverage tests GREEN.
  - Compile candidates only from typed facts/sources/observation records and preserve source, observation, authority, temporal, spatial, inference, and origin metadata.
  - Use stable requirement/candidate references; do not infer provider attempts from query traces.
  - Detect requirement-scoped value/identity/geometry/temporal/authority conflicts before Sufficiency.
  - Test candidate selection, source-family filtering, independent source identity, and deterministic conflict grouping.

- [x] Task 3: Implement the ten policy-driven Sufficiency gates with RED → GREEN tests.
  - Implement each gate in the formal order and expose pass/fail/not-applicable results.
  - Map source authority, geometry authority, legal authority, temporal fit, inference levels, acquisition receipt completeness, provider origin completeness, and conflict policy from the resolved `EvidencePolicy`.
  - Add requirement-specific tests for authority mismatch, stale evidence, geometry/legal mismatch, disallowed inference, incomplete acquisition, incomplete provider origin, unresolved conflict, and policy-specific independent-source counts.

- [x] Task 4: Implement the late absence gate and integrate EV-02 into application/facade.
  - Permit absence only when the policy allows it and required authoritative sources, complete acquisition, complete provider origin, complete pagination/provider exhaustion, independent-source rule, and conflict closure all pass.
  - Prove that `SUCCESS_EMPTY` alone yields no absence conclusion; distinguish `SUCCESS_EMPTY`, `NOT_ATTEMPTED`, `MISSING_CAPABILITY`, `PARTIAL`, and `QUOTA` through the typed receipt/attempt audit.
  - Finalize the acquisition audit before facade sufficiency evaluation and persist reasoning data in coverage/artifact results.
  - Add an end-to-end fixture for authorized absence and negative fixtures for each incomplete state.

- [x] Task 5: Update design/acceptance documentation and run the full Evidence regression suite.
  - Document the EV-02 contract, gate order, terminal statuses, and late absence rule in `docs/design/04_EVIDENCE.md` and `docs/design/acceptance/03_evidence_acceptance.md`.
  - Run focused policy tests, all Evidence tests, compile checks, and `git diff --check`.
  - Leave the working tree ready for review; do not implement EV-03 or add a WM write path in this change.
