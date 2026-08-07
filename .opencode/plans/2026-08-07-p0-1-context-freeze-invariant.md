# P0-1: Freeze PlanningContext Before First Versioned Artifact

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the invariant: **before ANY versioned artifact (L1Snapshot, L2Strategy, PlanningProgram) is persisted, PlanningContext must be established with a non-empty `context_version`.** The main path is already fixed in `layer_aggregate_node.py:56-60` (bootstrap before aggregate). This plan closes the remaining gaps: (1) bootstrap failure still returns `done=True, version=""` allowing empty-version artifacts; (2) aggregate functions have no self-defense invariant; (3) tests don't lock the critical behavior.

**Architecture:** Three changes: (1) make `bootstrap_context_node` fail-closed (raise on failure instead of returning empty version); (2) add a `require_frozen_context` guard at the top of each aggregate function; (3) add tests covering empty->bootstrap->non-empty flow, bootstrap-failure-blocks-aggregate, and L1 strict-recovery after cache loss.

**Tech Stack:** Python, LangGraph StateGraph, pytest

## Global Constraints

- Backend tests run from `backend/` directory: `cd backend && python -m pytest <path> -v`
- 4-space indent for Python, double quotes
- LF line endings
- No emojis in code or comments
- Commit only when explicitly asked by the user, at task boundaries

---

## Current State (confirmed by audit)

**Already fixed (main path):** `layer_aggregate_node.py:56-60`:
```python
    if not state.get("context_version") or not state.get("context_ref"):
        from app.agent.bootstrap.context_bootstrap import bootstrap_context_node
        context_patch = await bootstrap_context_node(state)
        aggregate_state = {**state, **context_patch}
```
This runs bootstrap before L1/L2/L3 aggregate. Correct.

**Still broken (3 gaps):**

1. **`context_bootstrap.py:67,74`** — failure branches return `{"bootstrap_context_done": True, "context_version": "", "context_fingerprint": ""}`. The layer_aggregate_node then proceeds to call aggregate with empty version, producing unrecoverable artifacts.

2. **No invariant guard in aggregates** — `l1_aggregate`, `l2_aggregate`, `l3_aggregate` all read `context_version = state.get("context_version", "")` and proceed to persist without checking. Direct calls bypass the layer_aggregate_node protection.

3. **Tests pre-seed versions** — `test_layer_aggregate_node.py:27` provides `context_version="v1"`. No test exercises: empty version -> bootstrap -> non-empty artifact ref. No test verifies bootstrap failure blocks aggregate. No test verifies strict recovery after cache loss.

---

### Task 1: Write acceptance tests for all three gaps

**Files:**
- Create: `backend/tests/agent/test_context_freeze_invariant.py`
- Test: same file

**Interfaces:**
- Consumes: `layer_aggregate_node`, `bootstrap_context_node`, `l1_aggregate`, `load_artifact`
- Produces: failing tests proving the 3 gaps

- [ ] **Step 1: Write the failing tests**

```python
"""Acceptance: PlanningContext must be frozen before any versioned artifact.

Tests:
1. Empty context_version triggers bootstrap; L1 artifact ref has non-empty version.
2. Bootstrap failure blocks aggregate (no artifact produced).
3. L1 strict recovery: save artifact, clear cache, load_artifact succeeds.
4. All three layer artifacts share the same context_version.
"""
import pytest

from app.agent.bootstrap.layer_aggregate_node import layer_aggregate_node


@pytest.mark.asyncio
async def test_l1_aggregate_bootstraps_context_before_persisting(monkeypatch, tmp_path):
    """L1 aggregate with empty context_version must bootstrap first;
    the resulting artifact ref must have non-empty context_version."""
    captured_state = {}

    async def fake_bootstrap(state):
        return {
            "bootstrap_context_done": True,
            "context_version": "1",
            "context_fingerprint": "sha256:abc123",
            "context_ref": {"session_id": state.get("session_id", ""), "version": "1"},
        }

    async def fake_l1(state, *, base_dir=".run-tmp"):
        captured_state.update(state)
        return {
            "l1_snapshot_ref": {
                "artifact_id": "l1-test-v1",
                "context_version": state.get("context_version", ""),
                "module": "l1_observe",
                "run_id": state.get("session_id", ""),
                "artifact_type": "L1Snapshot",
                "revision": "v1",
            },
            "l1_gate_decision": {"stage": "l1", "passed": True, "feedback_route": None},
            "l1_review_id": "rev-l1",
        }

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node", fake_bootstrap
    )
    monkeypatch.setattr("app.agent.l1_observe.aggregate.l1_aggregate", fake_l1)

    state = {
        "session_id": "test-freeze-001",
        "run_id": "test-freeze-001",
        "context_version": "",  # NOT bootstrapped yet
        "layer_just_completed": 1,
    }
    result = await layer_aggregate_node(state)

    # Bootstrap must have run
    assert captured_state.get("context_version") == "1", (
        "L1 aggregate must receive non-empty context_version after bootstrap"
    )
    # The returned ref must carry the bootstrapped version
    ref = result.get("l1_snapshot_ref", {})
    assert str(ref.get("context_version", "")) == "1", (
        "L1 artifact ref must have non-empty context_version matching bootstrap"
    )
    # Context fields must be propagated back to parent state
    assert result.get("context_version") == "1"
    assert result.get("context_ref", {}).get("version") == "1"


@pytest.mark.asyncio
async def test_bootstrap_failure_blocks_aggregate(monkeypatch, tmp_path):
    """If bootstrap fails (returns empty version), aggregate must NOT be called."""
    aggregate_called = False

    async def failing_bootstrap(state):
        # Simulate the current failure behavior: done=True, version=""
        return {
            "bootstrap_context_done": True,
            "context_version": "",
            "context_fingerprint": "",
        }

    async def fake_l1(state, *, base_dir=".run-tmp"):
        nonlocal aggregate_called
        aggregate_called = True
        return {}

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node", failing_bootstrap
    )
    monkeypatch.setattr("app.agent.l1_observe.aggregate.l1_aggregate", fake_l1)

    state = {
        "session_id": "test-fail-001",
        "context_version": "",
        "layer_just_completed": 1,
    }
    # The layer_aggregate_node (or the aggregate itself) must fail-closed
    # when context_version is still empty after bootstrap attempt.
    with pytest.raises((RuntimeError, Exception), match="context"):
        await layer_aggregate_node(state)
    assert not aggregate_called, (
        "Aggregate must not be called when bootstrap failed to produce a context version"
    )


@pytest.mark.asyncio
async def test_l1_aggregate_rejects_empty_context_directly(tmp_path):
    """Calling l1_aggregate directly with empty context_version must fail."""
    from app.agent.l1_observe.aggregate import l1_aggregate

    state = {
        "session_id": "test-direct-001",
        "run_id": "test-direct-001",
        "context_version": "",  # empty
    }
    with pytest.raises((RuntimeError, AssertionError), match="context"):
        await l1_aggregate(state, base_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_all_layer_artifacts_share_same_context_version(monkeypatch, tmp_path):
    """L1Snapshot, L2Strategy, PlanningProgram must all carry the same
    non-empty context_version, established before L1 aggregate."""
    versions = []

    async def fake_bootstrap(state):
        return {
            "bootstrap_context_done": True,
            "context_version": "1",
            "context_fingerprint": "sha256:abc",
            "context_ref": {"session_id": state.get("session_id", ""), "version": "1"},
        }

    async def fake_l1(state, *, base_dir=".run-tmp"):
        v = state.get("context_version", "")
        versions.append(("l1", v))
        return {"l1_snapshot_ref": {"context_version": v}, "l1_gate_decision": {"passed": True}}

    async def fake_l2(state, *, base_dir=".run-tmp"):
        v = state.get("context_version", "")
        versions.append(("l2", v))
        return {"l2_strategy_ref": {"context_version": v}, "l2_gate_decision": {"passed": True}}

    async def fake_l3(state, *, base_dir=".run-tmp"):
        v = state.get("context_version", "")
        versions.append(("l3", v))
        return {"l3_program_ref": {"context_version": v}, "l3_gate_decision": {"passed": True}}

    monkeypatch.setattr(
        "app.agent.bootstrap.context_bootstrap.bootstrap_context_node", fake_bootstrap
    )
    monkeypatch.setattr("app.agent.l1_observe.aggregate.l1_aggregate", fake_l1)
    monkeypatch.setattr("app.agent.l2_strategize.aggregate.l2_aggregate", fake_l2)
    monkeypatch.setattr("app.agent.l3_plan.aggregate.l3_aggregate", fake_l3)

    base_state = {"session_id": "test-share-001", "run_id": "test-share-001", "context_version": ""}

    for layer in [1, 2, 3]:
        state = {**base_state, "layer_just_completed": layer}
        # L1 triggers bootstrap; L2/L3 inherit from state (already set by L1)
        if layer == 1:
            state["context_version"] = ""  # force bootstrap
        else:
            state["context_version"] = "1"  # already bootstrapped
            state["context_ref"] = {"session_id": state["session_id"], "version": "1"}
        await layer_aggregate_node(state)

    for layer_name, version in versions:
        assert version == "1", f"{layer_name} artifact has context_version='{version}', expected '1'"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py -v`
Expected: FAIL — test_bootstrap_failure_blocks_aggregate and test_l1_aggregate_rejects_empty_context_directly fail (no fail-closed guard)

- [ ] **Step 3: Commit the failing tests**

```bash
git add backend/tests/agent/test_context_freeze_invariant.py
git commit -m "test: add context-freeze invariant acceptance tests"
```

---

### Task 2: Make bootstrap_context_node fail-closed

**Files:**
- Modify: `backend/app/agent/bootstrap/context_bootstrap.py:65-74`

**Approach:** Instead of returning `done=True, version=""` on failure, raise an exception. The `layer_aggregate_node` already calls bootstrap in a try-free manner; if it raises, the node fails and LangGraph handles the error. This prevents aggregate from ever running with an empty version.

- [ ] **Step 1: Change failure branches to raise**

In `backend/app/agent/bootstrap/context_bootstrap.py`, change lines 65-74:

Current:
```python
    if not session_id:
        logger.warning("[bootstrap] no session_id; skipping context build")
        return {"bootstrap_context_done": True, "context_version": "", "context_fingerprint": ""}

    village_name = str((state.get("config") or {}).get("village_name", ""))
    try:
        context = await build_planning_context(session_id, village_name=village_name or None)
    except Exception as exc:
        logger.error("[bootstrap] context build failed: %s", exc)
        return {"bootstrap_context_done": True, "context_version": "", "context_fingerprint": ""}
```

New:
```python
    if not session_id:
        raise RuntimeError(
            "CONTEXT_BOOTSTRAP_FAILED: no session_id; cannot establish PlanningContext"
        )

    village_name = str((state.get("config") or {}).get("village_name", ""))
    try:
        context = await build_planning_context(session_id, village_name=village_name or None)
    except Exception as exc:
        logger.error("[bootstrap] context build failed: %s", exc)
        raise RuntimeError(
            f"CONTEXT_BOOTSTRAP_FAILED: build_planning_context raised {exc}"
        ) from exc
```

- [ ] **Step 2: Run the bootstrap-failure test**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py::test_bootstrap_failure_blocks_aggregate -v`
Expected: The test's `failing_bootstrap` mock returns empty version; `layer_aggregate_node` must still block aggregate. But wait — the mock bypasses the real bootstrap, so the raise won't fire. We need the layer_aggregate_node to also check after bootstrap returns.

- [ ] **Step 3: Add post-bootstrap fail-closed check in layer_aggregate_node**

In `backend/app/agent/bootstrap/layer_aggregate_node.py:56-60`, after the bootstrap call, add:

```python
    aggregate_state = state
    if not state.get("context_version") or not state.get("context_ref"):
        from app.agent.bootstrap.context_bootstrap import bootstrap_context_node

        context_patch = await bootstrap_context_node(state)
        aggregate_state = {**state, **context_patch}

    # Fail-closed: if context is still not established, do not persist artifacts
    if not aggregate_state.get("context_version") or not aggregate_state.get("context_ref"):
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: cannot persist versioned artifact with empty "
            "context_version. bootstrap_context failed to establish a valid context."
        )
```

- [ ] **Step 4: Run the bootstrap-failure test again**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py::test_bootstrap_failure_blocks_aggregate -v`
Expected: PASS — the mock returns empty version, the post-bootstrap check raises, aggregate is never called

- [ ] **Step 5: Run existing layer_aggregate tests for regressions**

Run: `cd backend && python -m pytest tests/unit/bootstrap/test_layer_aggregate_node.py -v`
Expected: All pass (these tests pre-seed `context_version="v1"` or have `layer_just_completed` set with context already present)

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/bootstrap/context_bootstrap.py backend/app/agent/bootstrap/layer_aggregate_node.py
git commit -m "fix: fail-closed when bootstrap cannot establish context_version

bootstrap_context_node was returning done=True with empty context_version
on failure, allowing layer aggregates to persist artifacts with empty
versions that are unrecoverable by strict load_artifact. Now bootstrap
raises on failure, and layer_aggregate_node also checks post-bootstrap
that context_version is non-empty before calling any aggregate."
```

---

### Task 3: Add require_frozen_context guard to each aggregate function

**Files:**
- Modify: `backend/app/agent/l1_observe/aggregate.py:157` (add guard after reading context_version)
- Modify: `backend/app/agent/l2_strategize/aggregate.py` (add guard)
- Modify: `backend/app/agent/l3_plan/aggregate.py:245` (add guard)
- Test: `backend/tests/agent/test_context_freeze_invariant.py`

**Approach:** Each aggregate function defends itself by asserting `context_version` is non-empty before persisting. This protects against direct calls that bypass `layer_aggregate_node`.

- [ ] **Step 1: Create a shared guard function**

Create `backend/app/agent/bootstrap/context_guard.py`:

```python
"""Shared invariant guard: context must be frozen before artifact persist."""
from typing import Any, Dict


def require_frozen_context(state: Dict[str, Any]) -> None:
    """Assert that PlanningContext is established before persisting artifacts.

    Validates:
    - context_version is non-empty
    - context_ref.version matches context_version
    - context_ref.session_id matches state session_id
    """
    context_version = str(state.get("context_version", ""))
    if not context_version:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: cannot persist versioned artifact with empty "
            "context_version. bootstrap_context must run first."
        )
    context_ref = state.get("context_ref") or {}
    if not context_ref:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: context_ref is missing or empty. "
            "bootstrap_context must populate context_ref before artifact persist."
        )
    ref_version = str(context_ref.get("version", ""))
    if not ref_version:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: context_ref.version is empty. "
            "bootstrap_context must populate context_ref.version."
        )
    if ref_version != context_version:
        raise RuntimeError(
            f"CONTEXT_VERSION_MISMATCH: context_version={context_version} "
            f"but context_ref.version={ref_version}"
        )
    session_id = state.get("session_id", "")
    if not session_id:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: state.session_id is empty."
        )
    ref_session = str(context_ref.get("session_id", ""))
    if not ref_session:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: context_ref.session_id is empty."
        )
    if ref_session != session_id:
        raise RuntimeError(
            f"CONTEXT_SESSION_MISMATCH: state session_id={session_id} "
            f"but context_ref.session_id={ref_session}"
        )
```

- [ ] **Step 2: Add guard to l1_aggregate**

In `backend/app/agent/l1_observe/aggregate.py`, after line 157 (`context_version = state.get("context_version", "")`), add:

```python
    from app.agent.bootstrap.context_guard import require_frozen_context
    require_frozen_context(state)
```

- [ ] **Step 3: Add guard to l2_aggregate**

In `backend/app/agent/l2_strategize/aggregate.py`, find the equivalent `context_version = state.get(...)` line and add the same guard.

- [ ] **Step 4: Add guard to l3_aggregate**

In `backend/app/agent/l3_plan/aggregate.py`, after line 245, add:

```python
    from app.agent.bootstrap.context_guard import require_frozen_context
    require_frozen_context(state)
```

- [ ] **Step 5: Run the direct-call test**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py::test_l1_aggregate_rejects_empty_context_directly -v`
Expected: PASS — `l1_aggregate` raises `RuntimeError` matching "context"

- [ ] **Step 6: Run the shared-version test**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py::test_all_layer_artifacts_share_same_context_version -v`
Expected: PASS

- [ ] **Step 7: Run full regression**

Run: `cd backend && python -m pytest tests/unit/bootstrap/test_layer_aggregate_node.py tests/core/test_graph_durability.py tests/agent/ -v`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/bootstrap/context_guard.py backend/app/agent/l1_observe/aggregate.py backend/app/agent/l2_strategize/aggregate.py backend/app/agent/l3_plan/aggregate.py
git commit -m "fix: add require_frozen_context guard to all layer aggregates

Direct calls to l1/l2/l3_aggregate can bypass layer_aggregate_node's
bootstrap check. Each aggregate now asserts context_version is non-empty
and context_ref is consistent before persisting any artifact."
```

---

### Task 4: Add L1 strict-recovery regression test

**Files:**
- Modify: `backend/tests/agent/test_context_freeze_invariant.py`

**Interfaces:**
- Consumes: `FilesystemArtifactStore`, `load_artifact`, `L1Snapshot`

- [ ] **Step 1: Write the test**

Add to `test_context_freeze_invariant.py`:

```python
@pytest.mark.asyncio
async def test_l1_strict_recovery_after_cache_loss(tmp_path):
    """Save L1 artifact with valid context, clear in-process cache,
    re-bootstrap, then load_artifact must succeed (version matches)."""
    from app.services.artifact_store import FilesystemArtifactStore
    from app.modules.ports.artifact_store import ArtifactRef
    from app.modules.schema.contracts.l1_contracts import L1Snapshot
    from app.agent.bootstrap.artifact_runtime import store_artifact, load_artifact
    from app.services.context.planning_context import invalidate_planning_context

    store = FilesystemArtifactStore(base_dir=str(tmp_path))

    state = {
        "session_id": "test-recover-001",
        "run_id": "test-recover-001",
        "context_version": "1",
        "context_fingerprint": "sha256:test",
        "context_ref": {"session_id": "test-recover-001", "version": "1"},
        "artifact_refs": {},
    }
    snapshot = L1Snapshot(
        session_id="test-recover-001",
        context_version="1",
        village_name="test",
        planning_period="2022-2035",
        facts=[],
        facts_by_dimension={},
    )
    # store_artifact returns an ArtifactRef; MUST write it back into state
    ref = store_artifact(
        state, "l1_snapshot", "l1_observe", "L1Snapshot",
        snapshot, base_dir=str(tmp_path),
    )
    state["artifact_refs"]["l1_snapshot"] = ref

    # Simulate cache loss: invalidate the in-process PlanningContext cache.
    # In production, a worker restart has the same effect.
    invalidate_planning_context("test-recover-001")

    # Re-bootstrap would rebuild the context with the same version (idempotent).
    # For this test we keep the same state (version "1" is in the checkpoint).
    # load_artifact checks ref.context_version == state.context_version.
    # If the ref is missing from artifact_refs, load_artifact returns None
    # (not an error) - so the ref write-back above is critical.
    loaded = load_artifact(state, "l1_snapshot", L1Snapshot, store=store)
    assert loaded is not None, (
        "load_artifact returned None - artifact_refs may not contain the ref, "
        "or the store path doesn't match. Ensure store_artifact's returned ref "
        "is written back to state['artifact_refs']."
    )
    assert str(loaded.context_version) == "1"
    assert str(loaded.session_id) == "test-recover-001"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && python -m pytest tests/agent/test_context_freeze_invariant.py::test_l1_strict_recovery_after_cache_loss -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/agent/test_context_freeze_invariant.py
git commit -m "test: add L1 strict-recovery regression test"
```

---

### Task 5: Strengthen bootstrap idempotency guard

**Files:**
- Modify: `backend/app/agent/bootstrap/context_bootstrap.py:55`

**Context:** The idempotency guard at line 55 currently short-circuits on `bootstrap_context_done and session_id`. But if `bootstrap_context_done=True` and `context_version=""` (the old failure case, now raised), the guard should NOT short-circuit — it should retry. Since Task 2 changed failure to raise, this is less critical, but the guard should still be strengthened for defense-in-depth.

- [ ] **Step 1: Strengthen the guard**

In `backend/app/agent/bootstrap/context_bootstrap.py:55`, change:

```python
    if state.get("bootstrap_context_done") and session_id:
```

to:

```python
    if state.get("bootstrap_context_done") and state.get("context_version") and session_id:
```

- [ ] **Step 2: Run regression**

Run: `cd backend && python -m pytest tests/unit/bootstrap/ tests/core/test_graph_durability.py tests/agent/ -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/bootstrap/context_bootstrap.py
git commit -m "fix: strengthen bootstrap idempotency to require non-empty version"
```

---

### Task 6: Full regression and audit ledger

- [ ] **Step 1: Run full backend suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All pass

- [ ] **Step 2: Update audit ledger**

Add a row to `docs/audits/backend-breakpoints-2026-08-06.md` documenting:
- The original breakpoint (L1/L2/L3 artifacts saved with empty context_version)
- The existing fix (layer_aggregate_node:56-60 bootstrap before aggregate)
- The additional fixes (fail-closed bootstrap, require_frozen_context guard, tests)

- [ ] **Step 3: Commit**

```bash
git add docs/audits/backend-breakpoints-2026-08-06.md
git commit -m "docs: record context-freeze invariant fix in audit ledger"
```

---

## Documented Debt (not fixed in this plan)

- `aggregate.py:295` (L3): bypasses `store_artifact` helper (no idempotency guard)
- `planning_context.py:92-108`: fingerprint is count-based, not content-based
- `planning_context.py:28-30`: version counter is in-memory, resets on restart
- `aggregate.py:272`: deterministic artifact_id defeats replay detection
- L1/L2 aggregates also bypass `store_artifact` helper (same pattern as L3)

These are tracked for a future "Context/Artifact transaction boundary" plan.
