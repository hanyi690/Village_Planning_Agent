# Context Runtime

This is the single context construction runtime for all business stages. It
owns context versioning, snapshot identity, projections, table rendering,
field/row/character budgets, and context cache invalidation.

Business modules provide stage, dimension, purpose, and typed inputs. They do
not concatenate reports, trim tokens, or render provider prompts themselves.
`manager.py` builds the versioned `PlanningContext`, `projection_builder.py`
creates bounded projections, `table_renderer.py` renders finite tables, and
`budgets.py` enforces limits. `runtime.py` defines the runtime context model.
Stage-specific projection modules may declare their typed rows and allowed
columns, but must use `build_bounded_table()` for the final row/character
budget and table wire format. They must not call the low-level renderer with
an ad-hoc shape or implement a second trimming policy.

The context fingerprint and source snapshot digest are carried across every
stage artifact boundary. A version mismatch is a hard failure so a resumed
stage cannot silently consume a different input snapshot.
