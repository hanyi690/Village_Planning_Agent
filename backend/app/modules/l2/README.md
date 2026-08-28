# L2 STRATEGIZE

L2 consumes only the reloaded `L1Snapshot` artifact. It identifies problems,
builds abstract objectives/demand/suitability/strategies and emits the typed
strategy artifact used by L3. It cannot create parcels, geometry, candidates,
scenarios, approvals or execution tasks.

`L2Application.run()` is the only stage entry point. Its projection is built
with `ContextRuntime` and its evidence requirements go through
`modules.evidence.EvidenceApplication`; L2 does not access KG, Bundle, Report,
RAG or retriever implementations directly.

## Output contract

The authoritative output is `contracts.l2.l2_contracts.L2Strategy`, whose
`decision_sets` contain the typed problem/objective/demand/suitability/strategy
decisions. Each decision keeps its L1 fact references, evidence references,
conflicts, uncertainty, and explicit evidence gaps. `L2Strategy` contains no
candidate id, geometry, scenario, approval input, execution plan, or planned
state.

An `EXPLORE` gate attaches one `RecoveryPointer` to each actionable evidence
gap. The pointer names the gap id, the producing L2 dimension, the current
`l2_strategy` artifact, the consumed `L1Snapshot`/decision inputs, and the
required fact. Recovery therefore returns to the responsible producer input;
it does not replay the whole layer or accept a prose substitute.

`application.L2RunResult.to_state_patch()` exposes only the CAS references for
`l2_strategy` and `l2_gate`. `L2Application.load()` reloads the strategy by
reference, so a downstream stage never treats inline checkpoint JSON as the
authority. Invalid or missing L1 references fail closed.

Evidence gaps remain attached to the strategy and gate as pending recovery
requests, but a usable partial strategy is allowed to advance. Only an empty
strategy, an error-level strategy contradiction, or an invalid upstream
contract blocks L2. An unresolved gap is therefore visible to L3 and
TARGET_PROJECTION as a diagnostic; it does not trigger an unproductive
infinite EXPLORE loop.

## Internal implementation map

- `problem_identification.py`: current-state problem framing.
- `objectives.py`: objective and metric semantics.
- `demand.py` and `demand_model.py`: demand portfolio contracts.
- `suitability.py` and `suitability_*`: suitability computation and policy.
- `strategy.py` and `reasoning.py`: bounded decision production.
- `aggregation.py`: deterministic merge, provenance, gate, and CAS output.
- `validation.py` and `review.py`: closure and human-review projections.

L2 consumes a reloaded L1 fact table and may emit requirements for the shared
Evidence facade. It does not resolve spatial references or choose parcels;
L1 location mentions are resolved by the independent GROUND entry point, while
planning-target resolution starts at TARGET_PROJECTION and the post-L3 GROUND
entry point.

## Verification

Use `python -m compileall -q backend/app`, the production boundary probe, and a
fresh-session L1-to-L2 runtime run when provider budget is intentionally
available. These are executable production probes, not a test-suite entry
point. A historical checkpoint is not an acceptable downstream proof.
