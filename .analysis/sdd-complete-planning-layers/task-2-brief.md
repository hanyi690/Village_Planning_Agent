# Task 2 brief: Compile pending spatial intent into typed GROUND requirements

Task 1 preserves valid but ungrounded spatial claims in
`PlanningProgram.pending_grounding_claims`. This task must make those claims
visible to the evidence/grounding boundary without promoting them to
executable interventions.

Implement a typed requirement projection:

1. Extend `IntentCompilationResult` with additive audit fields for
   `pending_grounding_claims` and `claim_dispositions`, and copy the values
   from `PlanningProgram` in deterministic target projection. Keep
   `spatial_reference_specs` limited to admitted executable interventions in
   this task; pending claims must not become target specs or executable
   targets yet.
2. Update `requirements_from_l3(program)` so a pending spatial claim is not
   emitted as `document/text_only`. Its claim requirement must be spatial,
   exact, and source-routed (`artifact`, `report`, `bundle`, `kg`) with
   metadata containing the claim ID, `pending_grounding` status, and missing
   requirement names.
3. Emit typed, auditable requirements for the pending claim's grounding
   prerequisites. Prefer the claim's explicit
   `spatial_requirements.grounding_requirements`, relation templates, and
   typed category/output fields. Use a small closed-set fallback only from
   those typed fields (never regex or free-text parsing): place binding and
   candidate geometry for all spatial targets; parcel membership for parcel/
   polygon outputs; network snapshot for line/road/axis or typed network
   relations; topology for typed topology relations; demand points only when
   explicitly requested by the typed relation/requirements. Missing
   evidence/source lineage and package identity must also produce source
   requirements rather than disappearing.
4. Make the resulting requirement set available on the target-projection
   artifact (`IntentCompilationResult.evidence_requirements`) while retaining
   target-projection requirements for admitted specs. Do not change GROUND
   candidate selection or solver behavior in this task; Task 3 will consume
   these typed pending inputs.
5. Add tests covering: pending facility becomes spatial/exact; explicit
   grounding requirements produce place/candidate/network/parcel/topology/
   demand roles as appropriate; missing package/locator/evidence each leaves
   an auditable requirement; admitted intervention requirements remain
   unchanged; pending claims are copied to target projection but produce no
   spatial reference specs.

Do not add CurrentAsset/DemandRegisterRow/CoverageDecision, regex parsing,
coordinates, WKT, GeoJSON, BSM identities, candidate geometry, or compatibility
aliases. Preserve the existing strict target projection gate and unrelated
dirty-worktree changes.

Report contract: write `.analysis/sdd-complete-planning-layers/task-2-report.md`
with status, files changed, exact focused test commands/results, and explicit
notes on why pending claims remain non-executable.
