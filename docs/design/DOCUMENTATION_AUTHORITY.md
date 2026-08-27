# Documentation Authority

> Status: CURRENT
> Authority: Canonical ownership map for active design/current-runtime documents, retention boundaries, and cleanup decisions produced by the 2026-08-27 convergence plan.

This file resolves documentation conflicts before any rewrite or cleanup work. When two documents disagree, prefer the higher-authority owner below and update that owner rather than creating another dated status page.

## Canonical owners

| Scope | Canonical owner | Role |
|---|---|---|
| Documentation governance | `design/DOCUMENTATION_AUTHORITY.md` | Defines which documents are authoritative, supporting, historical, or cleanup-only. |
| Cleanup and retention decisions | `design/DOCUMENT_CLEANUP_MANIFEST.md` | Exact path inventory for `KEEP` / `UPDATE` / `ARCHIVE` / `DELETE-CANDIDATE`. |
| Overall target architecture and efficiency principles | `design/00_SYSTEM_DESIGN.md` | Target architecture, main chain, efficiency principles, and completion framing. |
| Canonical contracts and cross-stage invariants | `design/01_CONTRACTS_AND_INVARIANTS.md` | Ownership, invariants, stage boundaries, and contract classes. |
| Evidence retrieval and grounding design | `design/02_EVIDENCE_AND_GROUNDING.md` | Primary normative retrieval and grounding design. |
| Planning and execution design | `design/03_PLANNING_EXECUTION.md` | Target planning, approval, execution, and delivery flow. |
| Acceptance and efficiency gates | `design/04_EVALUATION_AND_ACCEPTANCE.md` | Acceptance criteria, evaluation gates, and regression expectations. |
| Migration ledger | `design/05_MIGRATION.md` | Only target-to-current migration ledger. |
| Observed current implementation | `architecture/CURRENT_RUNTIME.md` | Current code paths, runtime evidence, and known `PARTIAL` / `GAP` boundaries. |
| Current API/state projection | `architecture/API_AND_STATE.md` | Current HTTP/SSE/state ownership and external projections. |
| Current operations and release checks | `architecture/OPERATIONS.md` | Startup, degradation, diagnostics, and release-oriented operational checks. |
| Accepted architecture decisions and history | `adr/*.md` | Decision history and accepted architectural constraints; ADR 007 remains historical, ADR 008 remains accepted. |

## Supporting but non-authoritative materials

| Location | Status in the surface | Why it stays |
|---|---|---|
| `docs/contracts/` | KEEP | Generated or contract-adjacent artifacts; field-level external contract, not narrative design authority. |
| `docs/reference/` | KEEP | Stable lookup material such as terminology, bibliography, and domain field references. |
| `docs/guides/` and `docs/frontend/` | KEEP | Task-oriented guides and developer onboarding, not normative design. |
| `docs/reports-weekly/` | ARCHIVE after verification | Historical run evidence and weekly snapshots; useful provenance, not current design. |
| `docs/superpowers/` | KEEP for active work, otherwise ARCHIVE | Planning prompts, execution reports, and temporary convergence artifacts. They support traceability but do not define the current architecture. |
| Top-level source/reference markdown in `docs/` | KEEP | Domain input or imported source material, not system-design authority. |

## Operating rules

1. `docs/design/00` through `docs/design/05` are the only target-design authority set.
2. `docs/architecture/` documents only observed current behavior. Target claims do not belong there.
3. `docs/design/05_MIGRATION.md` is the only migration/status ledger between target and current implementation.
4. `docs/superpowers/`, `docs/reports-weekly/`, and future `docs/_archive/` entries are historical or process evidence only. Active navigation may link to them only as historical context.
5. Pydantic contracts, generated OpenAPI, and repeatable tests remain the field-level authority. Design docs describe ownership, boundaries, and invariants instead of duplicating full schema tables.
6. Retired design paths that no longer exist in the active tree stay out of active navigation; if they must be mentioned for cleanup work, the mention belongs in the cleanup manifest and task reports only.

## Reference inventory summary

- `KEEP`: the canonical design set, current architecture set, accepted ADRs, generated contracts, stable reference docs, and source-domain materials.
- `UPDATE`: `docs/README.md`, `docs/design/README.md`, and `docs/architecture/README.md` because they must point to this authority map and stop implying that historical plans are part of the active design surface.
- `ARCHIVE`: completed `docs/superpowers` plans/reports and `docs/reports-weekly` snapshots once later cleanup tasks create the archive index.
- `DELETE-CANDIDATE`: low-value execution briefs and already-absent legacy design paths that survive only as historical names in plans, reports, or guardrail tests.

## Historical notes that matter now

- The current repository no longer has a second active design tree under `docs/design/modules/`; surviving mentions are historical only.
- Earlier status-ledger design pages were replaced by the current split between `architecture/CURRENT_RUNTIME.md` and `design/05_MIGRATION.md`.
- Older superpowers plans remain useful as execution provenance, but they must not appear in navigation as if they were the current design.
