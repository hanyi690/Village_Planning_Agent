# SDD ledger — plan: docs/superpowers/plans/2026-08-17-stable-real-run-fixes.md

## Context7 decisions

- Instructor: strict Pydantic response models, bounded validation retries, inspect failed attempts; remove ambiguous `list | str` contracts.
- LangGraph: successful writes/checkpoints survive failed or resumed paths; diagnostic/reconcile must merge, not replace, existing artifact refs.

## Task ledger

| Task | Scope | Status | Implementer | Review |
|---|---|---|---|---|
| 1 | Classification strict batches and retry | completed | Bacon (`01a00d7a-7125-7121-ba79-968b9030aadb`) | pending |
| 2 | Semantic issue partition | completed | Sartre (`01a00d7a-77b6-7dd2-a937-5d4a1babd22a`) | pending |
| 3 | Delivery artifact-ref checkpoint preservation | completed | Bernoulli (`01a00d7a-7ba5-7911-9890-cedd5a58f4dd`) | pending |
| 4 | Grounding equivalent-fact grouping | completed | Halley (`01a00d7a-7fec-7c30-b614-5d8ea0e122d0`) | pending |
| 5 | Broad review and real MiniMax rerun | pending | — | pending |

## Constraints

- Preserve `development_goals=36` by design.
- Do not print, commit, or write API keys to reports.
- Do not reset or discard unrelated dirty worktree changes.
- Each implementation agent may modify only its assigned files.
