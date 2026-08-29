# Documentation Authority

> Status: CURRENT
> Authority: Canonical ownership map for active design/current-runtime documents, retention boundaries, and cleanup decisions produced by the 2026-08-27 convergence plan.

This file resolves documentation conflicts before any rewrite or cleanup work. When two documents disagree, prefer the higher-authority owner below and update that owner rather than creating another dated status page.

## Canonical owners

| Scope | Canonical owner | Role |
|---|---|---|
| Documentation governance | `design/DOCUMENTATION_AUTHORITY.md` | Defines which documents are authoritative, supporting, historical, or cleanup-only. |
| Cleanup record | `design/DOCUMENT_CLEANUP_MANIFEST.md` | Exact record of removed legacy, historical, and generated material; it is not a runtime input. |
| Overall target architecture and efficiency principles | `design/00_SYSTEM_DESIGN.md` | Target architecture, main chain, efficiency principles, and completion framing. |
| Cognitive world model and dynamic GIS semantics | `design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` | Cross-stage authority for source data, schema cognition, entity resolution, multi-representation geometry, Session KG, entity retrieval, and GROUND implementation boundaries. |
| Cognitive world model migration sequence | `design/08_COGNITIVE_WORLD_MODEL_MIGRATION.md` | Normative task ordering, compatibility gates, tests, rollback, and retirement criteria; it does not report current completion status. |
| Module implementation specification | `design/09_MODULE_IMPLEMENTATION_SPEC.md` | Concrete Data/provider-cache/Cognition-KG/Evidence/GROUND/SELECT/EXECUTE/DELIVER contracts and the gap to a renderable planning result. |
| Module-level executable design | `design/10_MODULE_LEVEL_EXECUTABLE_DESIGN.md` | Normative module boundaries, Context/Structured Runtime ownership, tabular LLM protocol, dependency products, ref namespaces, gap propagation, and module acceptance gates. |
| L1 fact construction | `design/01_CONTRACTS_AND_INVARIANTS.md` | L1 facts, source lineage, fact types, and structured-output boundaries. |
| L2 planning cognition | `design/02_PLANNING_COGNITION.md` | Problems, objectives, demand, suitability, strategy, and L2 output. |
| L3 planning intent | `design/03_PLANNING_INTENT.md` | Claims, PlanningProgram, lineage, and pre-grounding boundaries. |
| Evidence | `design/04_EVIDENCE.md` | Retrieval, KG/Bundle fusion, evidence reasoning, coverage, and gap closure. |
| Projection and grounding | `design/05_PROJECTION_AND_GROUND.md` | Target compilation and iterative spatial grounding. |
| Select, execute, and code architecture | `design/06_SELECT_EXECUTE_AND_CODE.md` | Scenario selection, approved execution, post-processing, and target code tree. |
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
| Historical execution material | DELETED | Old plans, reports, snapshots, and session context were removed because they are not current design or runtime input. |
| Top-level source/reference markdown in `docs/` | KEEP | Domain input or imported source material, not system-design authority. |

## Operating rules

1. `docs/design/00` through `docs/design/10` form the target-design authority set. `00` through `06` remain the primary business-flow reading order; `07` is the cross-stage cognitive world-model and dynamic-GIS authority, `08` is its implementation sequence, `09` is the cache/data integration specification, and `10` is the module-level executable baseline.
2. `docs/architecture/` documents only observed current behavior. Target claims do not belong there.
3. `docs/design/05_MIGRATION.md` is the only migration/status ledger between target and current implementation. `08_COGNITIVE_WORLD_MODEL_MIGRATION.md` prescribes the migration sequence but must not be read as evidence that any task is complete.
4. Historical plans, reports, archive directories, and generated audit snapshots are deleted; they are never workflow inputs.
5. Pydantic contracts, generated OpenAPI, and repeatable tests remain the field-level authority. Design docs describe ownership, boundaries, and invariants instead of duplicating full schema tables.
6. Retired design paths that no longer exist in the active tree stay out of active navigation; if they must be mentioned for cleanup work, the mention belongs in the cleanup manifest and task reports only.

## Reference inventory summary

- `KEEP`: the canonical design set, current architecture set, accepted ADRs, generated contracts, stable reference docs, and source-domain materials.
- `UPDATE`: `docs/README.md`, `docs/design/README.md`, and `docs/architecture/README.md` because they must point to this authority map and stop implying that historical plans are part of the active design surface.
- `DELETED`: legacy implementation paths, old test surfaces, historical execution material, and generated audit/runtime residue listed in `DOCUMENT_CLEANUP_MANIFEST.md`.

## Historical notes that matter now

- The current repository no longer has a second active design tree under `docs/design/modules/`; surviving mentions are historical only.
- Earlier status-ledger design pages were replaced by the current split between `architecture/CURRENT_RUNTIME.md` and `design/05_MIGRATION.md`.
- Older plans and session material are not retained; current design and actual fresh-run evidence are the only sources for implementation decisions.
