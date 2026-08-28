# TARGET_PROJECTION

This module compiles the authoritative L3 `PlanningProgram` into typed spatial
references and persists the projection consumed by GROUND.  It does not own
retriever routing, raw GIS access, context assembly, or execution geometry.

## Public boundary

`TargetProjectionApplication.run()` requires the canonical
`artifact_refs.planning_program` reference and a matching context version. It
returns a `TargetProjectionRunResult` whose authoritative output is the
reloaded `IntentCompilationResult`, plus `target_projection` and
`target_projection_gate` references.

## Internal implementation map

- `stage.py`: production stage orchestration and artifact/gate completion.
- `requirement_compilation.py`: target admission and grounding requirements.
- `target_identity.py` and `admission.py`: stable identity and closed target
  family admission.
- `intent_graph_compiler.py` and `planning_task_graph_compiler.py`: typed
  intent/relation/task projections.
- `lineage.py`, `relation_catalog.py`, and `validation.py`: lineage and
  relation validation.

The result contains explicit pending/deferred diagnostics when a claim lacks
the evidence or identity needed for grounding. A rough spatial L3 claim is
compiled into one pending grounding item carrying its claim id, current L1
snapshot reference, and source fact references; this is an intake record, not
an admitted executable target. TARGET_PROJECTION does not resolve
natural-language locations and never creates geometry. It also does not
consume the L1 location-resolution sidecars as an identity shortcut: L1
mentions are resolved by GROUND's independent pre-planning entry point, while
this stage only compiles the current `PlanningProgram` into requests for the
post-L3 GROUND entry point. GROUND must preserve pending status until
authoritative inputs are complete.

When a claim produces concrete `pending_grounding_specs` or
`pending_grounding_requests`, the projection gate permits the partial artifact
to advance to GROUND with reason `passed_with_pending_grounding`. A truly empty
projection or a structural admission error still fails closed.
