# L1 Finalization Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define, persist, validate, and consume a single `L1ProductManifest` so the L1 observation snapshot, L1-GROUND binding result, World Model projection, and final L1 gate form one reloadable final-view boundary for L2 and L3.

**Architecture:** Keep the existing immutable `L1ObservationSnapshot`, `GroundedEntityBindingSnapshot`, `L1WorldProjectionSnapshot`, World Model snapshot, and `l1_gate` artifacts unchanged as source artifacts. Add a lightweight reference-only `L1ProductManifest` artifact after L1-GROUND completes; a finalization service reloads and validates all child artifacts, derives stable row/gap digests and product status, and persists the manifest. L2 and L3 continue to require their existing upstream gates but additionally load the manifest and reject any non-ready or mismatched final view.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, existing CAS `store_artifact`/`load_artifact` runtime, pytest, existing workflow state and artifact references.

## Global Constraints

- This change is limited to L1 and its direct upstream/downstream alignment; do not modify WM v0.5, EV-02, or EV-03 behavior.
- Do not copy complete facts or bindings into the manifest; it is a reference envelope only.
- Preserve immutable observation, binding, projection, and gate artifacts; never load and overwrite an existing L1 artifact to finalize it.
- `L1ProductManifest.status` is a product status (`ready | partial | human_required | blocked`), not a workflow route instruction.
- L2 and L3 must fail closed when the manifest is missing, stale, not `ready`, or does not close over the exact L1-GROUND transition.
- Keep existing `l1_snapshot` compatibility for Evidence and legacy lineage fields; add the manifest as the final-view authority rather than deleting existing refs.
- Use 2-space indentation for frontend only and 4-space indentation for Python; preserve repository LF endings and existing Python double-quote style.
- Run focused tests after each task; do not claim the repository-wide pytest command is green when unrelated reference-test collection still fails.

---

### Task 1: Add the immutable L1ProductManifest contract and registry coverage

**Files:**
- Create: `backend/app/contracts/l1/product_manifest.py`
- Modify: `backend/app/contracts/l1/__init__.py`
- Test: `tests/test_l1_product_manifest.py`

**Interfaces:**
- Consumes: `ArtifactRef` and the existing target fields in `docs/design/01_CONTRACTS_AND_INVARIANTS.md`.
- Produces: `L1ProductManifest(ContractMeta)` with reference-only fields and `L1ProductStatus` literals for finalization and downstream validation.

- [x] **Step 1: Write failing contract tests**

Add tests that construct a manifest with valid `ArtifactRef` objects and assert:

```python
def test_manifest_is_reference_only_and_has_target_statuses():
    manifest = L1ProductManifest(
        observation_product_ref=ref("l1_snapshot"),
        l1_snapshot_ref=ref("l1_snapshot"),
        binding_snapshot_ref=ref("l1_bindings"),
        world_projection_ref=ref("l1_world_projection"),
        world_model_snapshot_ref=ref("world_model_current_snapshot"),
        world_model_snapshot_digest="wm-digest",
        fact_row_digest="facts-digest",
        binding_row_digest="bindings-digest",
        status="ready",
    )
    assert manifest.status == "ready"
    assert not hasattr(manifest, "fact_records")
    assert not hasattr(manifest, "bindings")
```

Also test that `status="explore"`, extra payload fields, and an empty required reference are rejected by Pydantic.

- [x] **Step 2: Run the focused tests and verify they fail**

Run:

```text
python -m pytest tests/test_l1_product_manifest.py -q
```

Expected: collection or import failure because `L1ProductManifest` does not yet exist.

- [x] **Step 3: Implement the contract**

Create `L1ProductManifest` as a `ContractMeta` root contract with these fields:

```python
class L1ProductManifest(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    observation_product_ref: ArtifactRef
    l1_snapshot_ref: ArtifactRef
    binding_snapshot_ref: ArtifactRef
    world_projection_ref: ArtifactRef
    world_model_snapshot_ref: ArtifactRef
    world_model_snapshot_digest: str = Field(min_length=1)
    fact_row_digest: str = Field(min_length=1)
    binding_row_digest: str = Field(min_length=1)
    open_gap_refs: tuple[str, ...] = ()
    terminal_gap_refs: tuple[str, ...] = ()
    status: Literal["ready", "partial", "human_required", "blocked"] = "blocked"
```

The manifest must not contain `fact_records`, `bindings`, geometry, candidate, goal, target, or execution fields. Export it from the L1 contract package. Confirm the existing artifact key `l1_product_manifest` and stage adapter mapping are reused rather than adding a second key.

- [x] **Step 4: Run the focused tests and compile check**

Run:

```text
python -m pytest tests/test_l1_product_manifest.py -q
python -m compileall -q backend/app/contracts/l1
```

Expected: all manifest contract tests pass.

---

### Task 2: Implement a reload-and-validate L1 finalization service

**Files:**
- Create: `backend/app/modules/l1/finalization.py`
- Modify: `backend/app/modules/l1/__init__.py`
- Test: `tests/test_l1_finalization.py`

**Interfaces:**
- Consumes: workflow state containing `l1_snapshot`, `l1_observations`, `l1_bindings`, `l1_world_projection`, `world_model_snapshot`, `world_model_current_snapshot`, and the persisted final `l1_gate`.
- Produces: `finalize_l1_product(state: Mapping[str, Any]) -> dict[str, Any]`, which persists `l1_product_manifest` and returns an `artifact_refs` patch.

- [x] **Step 1: Write failing finalization tests**

Cover these cases with small in-memory CAS fixtures:

```python
def test_finalize_persists_ready_manifest_with_exact_transition():
    patch = finalize_l1_product(state_with_valid_l1_ground_transition())
    assert patch["artifact_refs"]["l1_product_manifest"]
    manifest = load_artifact(merged_state(state, patch), "l1_product_manifest", L1ProductManifest)
    assert manifest.status == "ready"
    assert manifest.l1_snapshot_ref.digest == refs["l1_snapshot"].digest


def test_finalize_rejects_stale_binding_or_projection():
    state = state_with_valid_l1_ground_transition()
    state["artifact_refs"]["l1_bindings"] = unrelated_binding_ref
    with pytest.raises(ArtifactReplayError):
        finalize_l1_product(state)


def test_finalize_marks_unresolved_ground_gap_partial_or_human_required():
    patch = finalize_l1_product(state_with_explicit_l1_ground_gap())
    manifest = load_manifest(merged_state(state, patch))
    assert manifest.status in {"partial", "human_required"}
    assert manifest.terminal_gap_refs
```

The tests must assert idempotent replay: calling finalization twice with the same refs returns the same manifest ref and does not mutate any child artifact.

- [x] **Step 2: Run tests and verify they fail**

Run:

```text
python -m pytest tests/test_l1_finalization.py -q
```

Expected: import failure for the missing finalization service.

- [x] **Step 3: Implement exact child-artifact validation and digest derivation**

In `finalization.py`:

1. Require all six source refs needed by `validate_l1_world_projection_transition()`.
2. Call `validate_l1_world_projection_transition(dict(state))` so the manifest cannot close over a different World Model child or a different observation/binding/projection artifact.
3. Reload `L1ObservationSnapshot`, `EvidenceObservationSnapshot`, `GroundedEntityBindingSnapshot`, `L1WorldProjectionSnapshot`, `SessionWorldModelSnapshot`, and the persisted `GateDecision` through existing runtime loaders.
4. Verify the manifest input context equals the active state and the final gate context version equals the resulting context version.
5. Calculate `fact_row_digest` from `L1ObservationSnapshot.fact_records` using the existing `semantic_checksum`; calculate `binding_row_digest` from binding rows using the same helper.
6. Derive `open_gap_refs` from snapshot evidence gaps and ground pending requests; derive `terminal_gap_refs` from non-recoverable/human-required gaps and ambiguous/unresolved binding work items using stable IDs.
7. Derive status without turning it into a route: `ready` only when the final gate is passed and there are no open/terminal gaps; `human_required` when the final gate requests human action or a terminal gap is human-required; `partial` when the transition is valid but recoverable gaps remain; `blocked` for invalid/missing finalization inputs.
8. Build a reference-only `L1ProductManifest` and persist it with `store_artifact(state, "l1_product_manifest", "l1", "L1ProductManifest", manifest, parent_keys=("l1_snapshot", "l1_observations", "l1_bindings", "l1_world_projection", "world_model_snapshot", "world_model_current_snapshot", "l1_gate"))`.
9. Return an `artifact_refs` patch containing the manifest ref and a small `l1_finalization` metadata block with status and row/gap digests. Do not copy facts or bindings into state.

- [x] **Step 4: Run focused tests and inspect the persisted ref**

Run:

```text
python -m pytest tests/test_l1_finalization.py -q
python -m pytest tests/test_llm_table_protocol.py -q
```

Expected: finalization tests pass and the existing 16 L1 protocol tests remain green.

---

### Task 3: Attach finalization to the existing L1-GROUND completion boundary

**Files:**
- Modify: `backend/app/modules/ground/application.py` near `GroundApplication.materialize_l1_locations()` return path
- Modify: `backend/app/workflow/layers/layer_aggregate_node.py` only if the finalization call must be moved out of the GROUND application for ownership clarity
- Test: `tests/test_l1_ground_finalization_boundary.py`

**Interfaces:**
- Consumes: the existing L1-GROUND output patch after observation sidecar, binding sidecar, World Model current snapshot, projection, and final L1 gate are persisted.
- Produces: the same output patch plus `artifact_refs.l1_product_manifest`; no changes to EV-02/EV-03 or WM v0.5 transaction behavior.

- [x] **Step 1: Write failing boundary tests**

Extend the existing L1-GROUND orchestration test to assert:

```python
async def test_l1_ground_returns_final_manifest_after_commit_and_revalidation(monkeypatch):
    patch = await GroundApplication.materialize_l1_locations(valid_state)
    refs = patch["artifact_refs"]
    assert {"l1_observations", "l1_bindings", "l1_world_projection", "world_model_current_snapshot", "l1_product_manifest"} <= refs.keys()
    manifest = load_artifact({**valid_state, **patch, "artifact_refs": refs}, "l1_product_manifest", L1ProductManifest)
    assert manifest.l1_snapshot_ref.digest == refs["l1_snapshot"].digest
    assert manifest.world_projection_ref.digest == refs["l1_world_projection"].digest
```

Add a negative test proving a changed binding ref after World Model commit cannot result in a manifest.

- [x] **Step 2: Run the boundary tests and verify the new manifest assertion fails**

Run:

```text
python -m pytest tests/test_l1_ground_finalization_boundary.py tests/test_llm_table_protocol.py -q
```

Expected: existing GROUND assertions pass but the new manifest assertion fails until the finalizer is attached.

- [x] **Step 3: Attach finalization after the existing final gate and projection are persisted**

Use the final state assembled immediately before the current return in `materialize_l1_locations()`. Call `finalize_l1_product(current_state_with_final_refs)` only after:

- `l1_observations` and `l1_bindings` are stored;
- the Cognition/World Model commit result has produced `world_model_current_snapshot`;
- `l1_world_projection` has exact parent closure;
- the final `l1_gate` has been persisted;
- `identity_transition_patch` has updated the resulting context and World Model digest.

Merge only the returned artifact ref and finalization metadata into the existing return patch. Preserve the existing `l1_observations`, `l1_bindings`, `l1_world_projection`, `world_model_current_snapshot`, `l1_gate`, and context refs. If finalization raises an artifact lineage error, propagate it; never downgrade it to a semantic gap.

- [x] **Step 4: Run L1-GROUND, protocol, and compile checks**

Run:

```text
python -m pytest tests/test_l1_ground_finalization_boundary.py tests/test_llm_table_protocol.py -q
python -m compileall -q backend/app/modules/l1 backend/app/modules/ground backend/app/workflow/layers
```

Expected: all focused tests pass and L1-GROUND still preserves its existing proposal/commit behavior.

---

### Task 4: Make L2 and L3 consume the manifest as the L1 final-view authority

**Files:**
- Modify: `backend/app/modules/l2/application.py`
- Modify: `backend/app/modules/l3/application.py`
- Modify: `backend/app/modules/l2/__init__.py` only if the request contract export changes
- Modify: `backend/app/modules/l3/__init__.py` only if the request contract export changes
- Test: `tests/test_l1_downstream_final_view.py`

**Interfaces:**
- Consumes: `artifact_refs.l1_product_manifest` and the manifest's exact child refs.
- Produces: `L2RunRequest` and `L3RunRequest` carrying `l1_product_manifest_ref`; both applications reload and validate the manifest before invoking their existing aggregates.

- [x] **Step 1: Write failing downstream tests**

Add tests that prove:

```python
def test_l2_requires_ready_l1_product_manifest():
    state = state_with_l1_snapshot_but_without_manifest()
    with pytest.raises(RuntimeError, match="L1ProductManifest"):
        L2Application().run(state)


def test_l2_rejects_partial_manifest_even_when_l1_snapshot_is_present():
    state = state_with_manifest(status="partial")
    with pytest.raises(RuntimeError, match="ready"):
        L2Application().run(state)


def test_l3_requires_the_same_ready_l1_final_view():
    state = state_with_l2_and_partial_manifest()
    with pytest.raises(RuntimeError, match="L1ProductManifest"):
        L3Application().run(state)
```

Also assert a mismatched manifest child ref is rejected before `l2_aggregate` or `l3_aggregate` is called.

- [x] **Step 2: Run downstream tests and verify they fail**

Run:

```text
python -m pytest tests/test_l1_downstream_final_view.py -q
```

Expected: the current applications proceed from `l1_snapshot` or fail later because they do not yet require the manifest.

- [x] **Step 3: Add manifest request fields and validation**

Update `L2RunRequest` and `L3RunRequest` with `l1_product_manifest_ref: ArtifactRef`, loading it from `artifact_refs["l1_product_manifest"]`. Keep `l1_snapshot_ref` for compatibility and verify it equals `manifest.l1_snapshot_ref`.

Before the existing aggregate call:

1. require the manifest ref;
2. reload `L1ProductManifest`;
3. validate its context version/fingerprint against active state;
4. require `manifest.status == "ready"`;
5. call the finalization validator to prove manifest parent closure and exact child identities;
6. verify the manifest snapshot ref equals the request snapshot ref;
7. only then call existing L2/L3 aggregation.

Do not alter the existing L2 forbidden-field checks or L3 program-boundary checks. Do not change L1, Evidence, or WM transaction code to make downstream tests pass.

- [x] **Step 4: Run direct downstream and regression tests**

Run:

```text
python -m pytest tests/test_l1_downstream_final_view.py tests/test_llm_table_protocol.py tests/test_cognition_round_contract.py tests/test_evidence_acquisition_contracts.py -q
python -m compileall -q backend/app
```

Expected: new final-view tests and all previously passing focused tests remain green.

---

### Task 5: Align the design and runtime documentation with the implemented boundary

**Files:**
- Modify: `docs/design/01_CONTRACTS_AND_INVARIANTS.md`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `docs/architecture/CURRENT_RUNTIME.md`
- Modify: `docs/design/L1_IMPLEMENTATION_AND_UPSTREAM_DOWNSTREAM_COMPARISON.md`
- Modify: `docs/design/README.md` only if the final document index needs a status note

**Interfaces:**
- Consumes: actual contract names, artifact keys, finalization call path, and passing focused tests from Tasks 1–4.
- Produces: no new runtime behavior; documentation that accurately distinguishes implemented manifest/finalization from still-pending dependency-local invalidation and benchmark work.

- [x] **Step 1: Update the canonical lifecycle**

Change the L1 lifecycle description to explicitly show:

```text
L1ObservationSnapshot
  → L1-GROUND
  → Cognition/WM v1 projection
  → post-commit binding revalidation
  → L1ProductManifest
  → L2/L3 final-view-only gate
```

State that the manifest references child artifacts and does not copy complete facts or bindings.

- [x] **Step 2: Update migration status without over-claiming**

Mark `L1ProductManifest` and the unified finalization boundary as implemented only if Tasks 1–4 pass. Keep dependency/subgraph invalidation, complete terminal taxonomy, and benchmark release gates marked `PARTIAL`.

- [x] **Step 3: Run documentation and focused verification**

Run:

```text
git diff --check
python -m pytest tests/test_l1_product_manifest.py tests/test_l1_finalization.py tests/test_l1_ground_finalization_boundary.py tests/test_l1_downstream_final_view.py tests/test_llm_table_protocol.py -q
```

Expected: no whitespace errors and all L1/direct-boundary tests pass. Record any repository-wide collection blockers separately; do not widen this change to unrelated reference dependencies.

---

## Self-review checklist

- [x] No task changes WM v0.5, EV-02, or EV-03 semantics.
- [x] Manifest contains references/digests/status only and no copied facts/bindings.
- [x] Finalization occurs after World Model commit and post-commit binding validation inputs exist.
- [x] Missing/stale/non-ready manifests block L2 and L3 before their aggregates run.
- [x] Existing L1 snapshot lineage remains available to Evidence and legacy consumers.
- [x] Tests cover ready, partial/human, missing, stale, idempotent, and downstream rejection paths.
- [x] Documentation states what is implemented and what remains `PARTIAL`.
