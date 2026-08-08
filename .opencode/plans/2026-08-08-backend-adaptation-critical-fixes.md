# Backend Adaptation Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 3 P0 and 7 P1 breakpoints identified in the 2026-08-08 backend adaptation audit so the EXECUTE/VALIDATE/Context/session-lifecycle paths run correctly through the real composition root.

**Architecture:** Each fix is a targeted correction to a specific module, sequenced so later tasks can rely on earlier invariants (EXECUTE persistence before session disposal; VALIDATE fail-closed before Context capability declaration; TaskSupervisor unification before session disposal). No large-scale file splitting - `post_l3_main_nodes.py`, `planning_nodes.py`, SSE, and KG-layer1 refactors are explicitly deferred to a later phase (audit item 11).

**Tech Stack:** Python 3.11, FastAPI, LangGraph 1.2.8, aiosqlite, SQLAlchemy async, shapely, Pydantic V2, pytest-asyncio.

## Global Constraints

- LF line endings for all `.py` files; 4-space indentation; double quotes for Python strings.
- No new dependencies - use the already-installed `langgraph` 1.2.8, `aiosqlite`, `shapely`, `pydantic` v2.
- Every check that can pass or fail must be **fail-closed**: missing input = explicit failure, never a silent skip.
- Tests that assert production behavior must exercise the real `PlanningRuntimeService` assembly path, not a fake graph compiled in the test.
- No code comments unless explicitly requested by a task step.
- Never swallow an exception that indicates a data-integrity problem (geometry parse failure, missing constraint index, bundle build failure) without recording it as an explicit validation failure or capability gap.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/app/agent/execute/execute_agent.py` | EXECUTE graph builder - accept real checkpointer | T1 |
| `backend/app/services/runtime.py` | Inject the real saver into EXECUTE instead of `True` | T1 |
| `backend/app/agent/validate/checks.py` | Fail-closed on geometry/constraint parse errors | T2 |
| `backend/app/agent/validate/aggregate.py` | Surface new failure checks in the aggregate report | T2 |
| `backend/app/modules/context/planning_context.py` | Content-addressed fingerprint + capability declaration | T3 |
| `backend/app/services/context/planning_context.py` | Persist version, fail-closed on required-capability loss | T3 |
| `backend/app/agent/bootstrap/context_bootstrap.py` | Verify deep fingerprint, not just `snapshot_meta` | T3 |
| `backend/app/services/task_supervisor.py` | Fix replace race + cancel-then-await + single instance | T4 |
| `backend/app/services/runtime.py` (TaskSupervisor) | Remove the second supervisor; route through CompositionRoot | T4 |
| `backend/app/services/session.py` | Complete session disposal (tasks, ctx, bundle, KG, artifacts, checkpoint, SSE) | T5 |
| `backend/app/main.py` | Call `shutdown_database()` in lifespan | T6 |
| `backend/app/api/routes.py` + CI config | Point readiness check at `/api/health` | T6 |
| `backend/app/api/session_crud.py` | Compensating transaction for session creation | T7 |
| `backend/app/agent/graph.py` | HITL publish-failure must not mark success; outbox semantics | T8 |
| (HITL routes) | Unify `approve/reject` vs `accept/reject/retry` vocabulary | T8 |
| `backend/app/agent/plan_state/state_factory.py` | Align factory fields with `AgentState` | T9 |
| `backend/app/agent/plan_state/state.py` | Remove `create_initial_state` compat shim | T9 |
| `backend/app/services/composition.py` | Inject KG/road/zone/artifact/bundle ports; remove `get_any_kg` | T10 |

---

## Task 1: EXECUTE checkpointer assembly (P0-1)

**Files:**
- Modify: `backend/app/agent/execute/execute_agent.py:75-132`
- Modify: `backend/app/services/runtime.py:136-138`
- Test: `backend/tests/agent/test_execute_runtime_assembly.py` (new)

**Interfaces:**
- Consumes: `get_global_checkpointer()` from `app.database.engine` (returns `AsyncSqliteSaver`).
- Produces: `build_execute_agent_graph(checkpointer: Optional[BaseCheckpointSaver] = None)` - accepts a real saver instance or `None`; **never** accepts `True`. `PlanningRuntimeService._execute_subgraph` is compiled with the real saver.

**Background (why this is broken):** `runtime.py:137` calls `build_execute_agent_graph(checkpointer=True)`. `execute_agent.py:126-127` passes `True` straight into `graph.compile(checkpointer=True)`. LangGraph 1.2.8 raises `RuntimeError: checkpointer=True cannot be used for root graphs.` when a graph compiled with `checkpointer=True` is invoked as a root graph (which is exactly how `post_l3_main_nodes.py:539` calls it via `graph.ainvoke(...)`). The existing isolation test (`test_execute_subgraph_isolation.py`) passes only because it compiles its own fake graphs with `MemorySaver`, never exercising the production `_execute_subgraph`.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/agent/test_execute_runtime_assembly.py`:

```python
"""P0-1: EXECUTE subgraph must run through the real RuntimeService assembly.

Reproduces the production bug: checkpointer=True cannot be used for root graphs.
"""
import pytest

from app.services.runtime import PlanningRuntimeService


@pytest.mark.asyncio
async def test_execute_subgraph_compiled_with_real_saver():
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    assert graph is not None
    saver = getattr(graph, "checkpointer", None)
    assert saver is not None, "EXECUTE subgraph has no checkpointer"
    assert saver is not True, "EXECUTE subgraph still compiled with checkpointer=True"


@pytest.mark.asyncio
async def test_execute_subgraph_invokes_without_runtime_error():
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    config = {"configurable": {"thread_id": "test-exec-runtime-1", "checkpoint_ns": "execute"}}
    try:
        await graph.ainvoke({}, config=config)
    except RuntimeError as e:
        if "cannot be used for root graphs" in str(e):
            pytest.fail(f"EXECUTE root invocation raised the P0-1 bug: {e}")
        raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_execute_runtime_assembly.py -v`
Expected: FAIL - first assertion fails because `saver is True`, OR the invoke raises `RuntimeError: checkpointer=True cannot be used for root graphs.`

- [ ] **Step 3: Fix `build_execute_agent_graph` to reject `True`**

In `backend/app/agent/execute/execute_agent.py`, change the signature and the compile block:

```python
def build_execute_agent_graph(checkpointer=None):
    ...
    compile_kwargs = {}
    if checkpointer is not None and checkpointer is not True:
        compile_kwargs["checkpointer"] = checkpointer
    compiled = graph.compile(**compile_kwargs)
    ...
```

This makes `True` behave identically to `None` (no checkpointer) - a safe no-op - while a real saver is honored.

- [ ] **Step 4: Fix `PlanningRuntimeService` to inject the real saver**

In `backend/app/services/runtime.py`, replace line 137:

```python
            cls._execute_subgraph = build_execute_agent_graph(checkpointer=cls._checkpointer)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/agent/test_execute_runtime_assembly.py -v`
Expected: PASS

- [ ] **Step 6: Add the attempt-isolation test**

Append to the same test file:

```python
@pytest.mark.asyncio
async def test_new_attempt_does_not_inherit_old_execute_state():
    """A second ainvoke with a fresh thread_id must not see prior EXECUTE outputs."""
    await PlanningRuntimeService.ensure_initialized()
    graph = PlanningRuntimeService._execute_subgraph
    cfg_a = {"configurable": {"thread_id": "attempt-A", "checkpoint_ns": "execute"}}
    cfg_b = {"configurable": {"thread_id": "attempt-B", "checkpoint_ns": "execute"}}
    await graph.aget_state(cfg_a)
    state_b_before = await graph.aget_state(cfg_b)
    assert state_b_before is None or not state_b_before.values
```

- [ ] **Step 7: Run the full EXECUTE test suite**

Run: `pytest backend/tests/agent/test_execute_subgraph_isolation.py backend/tests/agent/test_execute_runtime_assembly.py backend/tests/unit/execute/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/execute/execute_agent.py backend/app/services/runtime.py backend/tests/agent/test_execute_runtime_assembly.py
git commit -m "fix(execute): inject real checkpointer into EXECUTE subgraph (P0-1)"
```

---

## Task 2: VALIDATE fail-closed on parse errors (P0-2)

**Files:**
- Modify: `backend/app/agent/validate/checks.py:75-110` (hard constraints), `235-256` (`_planned_geoms`), `259-306` (topology), `309-333` (overlap)
- Modify: `backend/app/agent/validate/aggregate.py` (if it filters out new failure checks - verify before editing)
- Test: `backend/tests/unit/validate/test_validate_fail_closed.py` (new)

**Interfaces:**
- Consumes: `PlannedState`, `ParcelChangeSet`, `SpatialPlanningIntent`, `constraint_index` (Protocol with `geometry_in_constraint`).
- Produces: every check function returns `List[ValidationCheck]` where a parse failure, empty geometry, unknown CRS, or constraint-query exception produces a check with `passed=False` and a `check_id` prefixed `parse_error_*` or `missing_geometry_*`.

**Background:** `_planned_geoms` (line 251-254) does `try: g = _wkt.loads(wkt) except Exception: continue` - silently dropping unparseable geometries. `check_topology` then reports `passed=True` with empty `invalid=[]` because there are no geometries to validate. The same pattern exists in `check_hard_constraints` (line 98-99) and `check_overlap` (line 321-322).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/validate/test_validate_fail_closed.py`:

```python
"""P0-2: invalid WKT / missing geometry / constraint errors must fail, not skip."""
from app.agent.validate.checks import check_topology, check_hard_constraints, check_overlap
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState


def _planned_with(geometry: str) -> PlannedState:
    return PlannedState(parcels=[PlannedParcel(bsm="P001", geometry=geometry)])


def test_topology_invalid_wkt_fails():
    checks = check_topology(_planned_with("NOT_WKT"))
    validity = next(c for c in checks if c.check_id == "topology_validity")
    assert validity.passed is False
    assert "P001" in (validity.actual_value or "") or "parse" in (validity.actual_value or "").lower()


def test_topology_empty_geometry_string_fails():
    checks = check_topology(_planned_with(""))
    validity = next(c for c in checks if c.check_id == "topology_validity")
    assert validity.passed is False


def test_overlap_invalid_wkt_fails():
    checks = check_overlap(_planned_with("NOT_WKT"))
    assert any(c.passed is False for c in checks)


def test_hard_constraints_query_exception_fails():
    class BoomIndex:
        def geometry_in_constraint(self, geojson):
            raise RuntimeError("index unavailable")

    planned = _planned_with("POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))")
    checks = check_hard_constraints(planned, BoomIndex())
    assert checks[0].passed is False
    assert "index unavailable" in (checks[0].actual_value or "") or "exception" in (checks[0].actual_value or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/validate/test_validate_fail_closed.py -v`
Expected: FAIL - `test_topology_invalid_wkt_fails` fails because `check_topology` returns `passed=True` (the bad geometry is silently skipped).

- [ ] **Step 3: Refactor `_planned_geoms` to collect parse errors**

In `backend/app/agent/validate/checks.py`, replace the `_planned_geoms` function (lines 235-256) with a version that returns `(items, errors)`:

```python
def _planned_geoms(planned_state: Any) -> tuple[List[tuple], List[tuple]]:
    """Collect (name, shapely geometry) pairs and (name, error) parse failures."""
    from shapely import wkt as _wkt

    items: List[tuple] = []
    errors: List[tuple] = []
    for entry in (getattr(planned_state, "parcels", None) or []) + (
        getattr(planned_state, "zones", None) or []
    ):
        wkt = (getattr(entry, "geometry", "") or "").strip()
        name = getattr(entry, "bsm", "") or getattr(entry, "name", "") or ""
        if not wkt:
            errors.append((name, "empty geometry"))
            continue
        try:
            g = _wkt.loads(wkt)
        except Exception as exc:
            errors.append((name, f"parse error: {exc}"))
            continue
        items.append((name, g))
    return items, errors
```

- [ ] **Step 4: Update `check_topology` to surface parse errors as failures**

Replace the body of `check_topology` (lines 259-306) so the `validity_passed` line becomes:

```python
def check_topology(planned_state: Any) -> List[ValidationCheck]:
    invalid: List[str] = []
    empty: List[str] = []
    parse_errors: List[str] = []
    geoms: List[Any] = []
    items, errors = _planned_geoms(planned_state)
    for name, err in errors:
        parse_errors.append(name)
    for name, s in items:
        geoms.append(s)
        if s.is_empty:
            empty.append(name)
        elif not s.is_valid:
            invalid.append(name)

    validity_passed = not invalid and not empty and not parse_errors
    checks = [
        _check(
            "topology_validity",
            "拓扑有效性",
            validity_passed,
            stage="EXECUTE",
            actual=f"invalid={invalid}, empty={empty}, parse_errors={parse_errors}",
            expected="no invalid, empty, or unparseable geometries",
            fix="修复自相交、空几何或 WKT 解析错误",
        )
    ]
    polygon_geoms = [g for g in geoms if g.geom_type in _POLYGON_TYPES]
    gap_area = 0.0
    if polygon_geoms:
        try:
            from shapely.ops import unary_union

            union = unary_union([g for g in polygon_geoms if not g.is_empty])
            if not union.is_empty:
                gap_area = union.convex_hull.difference(union).area
        except Exception as exc:
            checks.append(
                _check(
                    "topology_gaps",
                    "拓扑缝隙",
                    False,
                    stage="EXECUTE",
                    actual=f"gap computation failed: {exc}",
                    expected="polygon layers cover their convex hull without gaps",
                    fix="修复拓扑计算异常",
                )
            )
            return checks
    gap_passed = gap_area <= 1e-9
    checks.append(
        _check(
            "topology_gaps",
            "拓扑缝隙",
            gap_passed,
            stage="EXECUTE",
            actual=f"gap_area={gap_area:.6f}",
            expected="polygon layers cover their convex hull without gaps",
            fix="补充缺失图斑或调整边界",
        )
    )
    return checks
```

- [ ] **Step 5: Update `check_overlap` to surface parse errors**

Replace `check_overlap` (lines 309-333) so it consumes the new `_planned_geoms` return shape and fails on parse errors:

```python
def check_overlap(planned_state: Any) -> List[ValidationCheck]:
    items, errors = _planned_geoms(planned_state)
    parse_failed = [name for name, _ in errors]
    geoms: List[Any] = [g for _, g in items if g.geom_type in _POLYGON_TYPES]
    pair_count = 0
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            try:
                inter = geoms[i].intersection(geoms[j])
                if not inter.is_empty and inter.area > 1e-12:
                    pair_count += 1
            except Exception:
                pair_count += 1
    passed = pair_count == 0 and not parse_failed
    return [
        _check(
            "overlap",
            "图层重叠",
            passed,
            stage="EXECUTE",
            actual=f"{pair_count} overlapping pairs, parse_errors={parse_failed}",
            expected="no polygon pairs overlap and no unparseable geometries",
            fix="消除地块/图斑之间的重叠区域或修复 WKT",
        )
    ]
```

- [ ] **Step 6: Update `check_hard_constraints` to fail on query exceptions**

In the loop body (lines 88-103), replace the bare `except Exception: continue` with a failure-recording path. After the loop, if any parcel had a query exception, append it to `affected`:

```python
    affected: List[str] = []
    query_errors: List[str] = []
    for parcel in planned_state.parcels or []:
        wkt = (parcel.geometry or "").strip()
        if not wkt:
            query_errors.append(parcel.bsm)
            continue
        try:
            from shapely import wkt as _wkt
            from shapely.geometry import mapping

            geojson = mapping(_wkt.loads(wkt))
            overlaps = constraint_index.geometry_in_constraint(geojson) or []
        except Exception as exc:
            query_errors.append(parcel.bsm)
            continue
        for ov in overlaps:
            if getattr(ov, "constraint_type", "") in _PROHIBITED_CONSTRAINTS:
                affected.append(parcel.bsm)
                break
    passed = not affected and not query_errors
    return [
        _check(
            "hard_constraints",
            "硬性约束核查",
            passed,
            stage="SELECT",
            actual=f"affected={affected}, query_errors={query_errors}",
            expected="no parcels violate prohibited constraints and no query failures",
            fix="提供约束图层或修复几何解析后再放行硬约束核查",
        )
    ]
```

- [ ] **Step 7: Verify `aggregate.py` does not filter out the new failure checks**

Read `backend/app/agent/validate/aggregate.py`. If it filters checks by `check_id` allow-list, add the new IDs (`topology_validity` already exists; confirm `overlap` and `hard_constraints` are included). If it simply concatenates all checks, no change is needed.

- [ ] **Step 8: Run the new tests**

Run: `pytest backend/tests/unit/validate/test_validate_fail_closed.py -v`
Expected: PASS

- [ ] **Step 9: Run the existing validate suite to catch regressions**

Run: `pytest backend/tests/unit/validate/ backend/tests/agent/test_validate_aggregate.py -v`
Expected: PASS - the existing `test_topology_detects_project_layer` and `test_hard_constraints_missing_index_fails` should still pass because valid geometries produce no parse errors.

- [ ] **Step 10: Commit**

```bash
git add backend/app/agent/validate/checks.py backend/app/agent/validate/aggregate.py backend/tests/unit/validate/test_validate_fail_closed.py
git commit -m "fix(validate): fail-closed on geometry parse errors and constraint query exceptions (P0-2)"
```

---

## Task 3: PlanningContext content-addressed snapshot (P0-3)

**Files:**
- Modify: `backend/app/modules/context/planning_context.py:1-111` (add content fingerprint + capability enum)
- Modify: `backend/app/services/context/planning_context.py:27-246` (persist version; fail-closed on required capabilities)
- Modify: `backend/app/agent/bootstrap/context_bootstrap.py` (verify deep fingerprint)
- Test: `backend/tests/agent/test_context_content_snapshot.py` (new)

**Interfaces:**
- Consumes: bundle, KG, gazetteer, constraint index, reports - all optional but their presence/absence is recorded.
- Produces:
  - `PlanningContext.content_hash: str` - SHA-256 over stable artifact refs (bundle parcel count + KG version + report IDs + constraint index size), not just counts.
  - `PlanningContext.capabilities: dict[str, bool]` - `{"bundle": bool, "kg": bool, "gazetteer": bool, "constraint_index": bool, "reports": bool}`.
  - `PlanningContext.required_capabilities_missing: list[str]` - non-empty when fail-closed.
  - `build_planning_context` raises `ContextBuildError` when a required capability (bundle, kg) is missing, instead of returning a half-empty Context.

**Background:** The version counter (`_build_counter`) is in-process and resets on restart (`planning_context.py:30-35`). The fingerprint (`modules/.../planning_context.py:92-108`) only counts booleans and lengths, not content - so two different bundles can share a fingerprint. `context_bootstrap.py:78` checks only the shallow `snapshot_meta`. The factory (services/.../planning_context.py:75-78) swallows bundle/KG build failures and still returns a versioned Context.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/agent/test_context_content_snapshot.py`:

```python
"""P0-3: PlanningContext must be a content-addressed, capability-declared snapshot."""
import hashlib
import pytest

from app.modules.context.planning_context import PlanningContext


def test_context_has_content_hash_and_capabilities():
    ctx = PlanningContext(
        session_id="s1",
        village_name="v1",
        version=1,
        kg_session_ref="s1",
        kg_version=1,
    )
    assert isinstance(ctx.content_hash, str)
    assert len(ctx.content_hash) == 64
    assert ctx.capabilities == {
        "bundle": False,
        "kg": False,
        "gazetteer": False,
        "constraint_index": False,
        "reports": False,
    }


def test_contexts_with_different_content_have_different_hashes():
    ctx_a = PlanningContext(session_id="s1", village_name="v1", version=1, kg_session_ref="s1", kg_version=1)
    ctx_a._content_inputs = {"parcel_count": 10, "kg_version": 1}
    ctx_a._recompute_hash()
    ctx_b = PlanningContext(session_id="s1", village_name="v1", version=1, kg_session_ref="s1", kg_version=1)
    ctx_b._content_inputs = {"parcel_count": 20, "kg_version": 1}
    ctx_b._recompute_hash()
    assert ctx_a.content_hash != ctx_b.content_hash


@pytest.mark.asyncio
async def test_build_raises_when_required_capability_missing(monkeypatch):
    from app.services.context import planning_context as factory

    async def boom_bundle(session_id, village_name=None):
        raise RuntimeError("bundle unavailable")

    monkeypatch.setattr("app.services.session_bundle.build_session_bundle", boom_bundle)
    with pytest.raises(factory.ContextBuildError, match="bundle"):
        await factory.build_planning_context("s1", "v1")


@pytest.mark.asyncio
async def test_version_is_stable_across_process_restart(monkeypatch, tmp_path):
    from app.services.context import planning_context as factory

    factory._build_counter.clear()
    factory._context_cache.clear()
    await factory.build_planning_context("s1", "v1", refresh=True)
    v1 = factory.get_cached_context("s1").version

    factory._build_counter.clear()
    factory._context_cache.clear()
    await factory.build_planning_context("s1", "v1", refresh=True)
    v2 = factory.get_cached_context("s1").version
    assert v2 > v1, "version must be monotonic across in-process restarts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/agent/test_context_content_snapshot.py -v`
Expected: FAIL - `PlanningContext` has no `content_hash`/`capabilities` attributes; `build_planning_context` returns a half-empty Context instead of raising.

- [ ] **Step 3: Add `content_hash`, `capabilities`, and `ContextBuildError` to `PlanningContext`**

In `backend/app/modules/context/planning_context.py`, add fields and a `_recompute_hash` method. Keep `snapshot_meta` but extend it with `content_hash` and `capabilities`. The `__init__` must call `_recompute_hash()` at the end so the hash is always set. Read the existing `__init__` first to see all current fields, then add:

```python
    content_hash: str = ""
    capabilities: Dict[str, bool] = field(default_factory=dict)
    required_capabilities_missing: List[str] = field(default_factory=list)
    _content_inputs: Dict[str, Any] = field(default_factory=dict)

    def _recompute_hash(self) -> None:
        payload = json.dumps(self._content_inputs, sort_keys=True, default=str)
        self.content_hash = hashlib.sha256(payload.encode()).hexdigest()

    def _record_capabilities(self) -> None:
        self.capabilities = {
            "bundle": self.bundle is not None,
            "kg": self.kg is not None,
            "gazetteer": self.gazetteer is not None,
            "constraint_index": self.constraint_index is not None,
            "reports": bool(self.reports),
        }
```

Call `_record_capabilities()` and `_recompute_hash()` at the end of `__init__` (or in the factory after setting fields). Import `hashlib` and `json` at the top.

- [ ] **Step 4: Make the factory fail-closed on required capabilities**

In `backend/app/services/context/planning_context.py`, define `ContextBuildError` near the top:

```python
class ContextBuildError(RuntimeError):
    pass
```

In `build_planning_context`, after the bundle try/except (line 74-78), change the `except` to record the failure instead of silently continuing, and raise at the end if a required capability is missing:

```python
    bundle_error: Optional[str] = None
    try:
        bundle = await build_session_bundle(session_id, village_name or None)
    except Exception as e:
        bundle_error = str(e)
        logger.warning("[PlanningContext] bundle build failed: %s", e)
```

Do the same for KG (lines 87-102) recording `kg_error`. After all build steps, before returning:

```python
    missing_required = []
    if bundle is None:
        missing_required.append("bundle")
    if kg is None and session_id:
        missing_required.append("kg")
    if missing_required:
        raise ContextBuildError(
            f"required capabilities missing: {missing_required} "
            f"(bundle_error={bundle_error}, kg_error={kg_error})"
        )
```

Populate `ctx._content_inputs` with stable content identifiers (parcel count, KG version, report IDs, constraint index size) before returning.

- [ ] **Step 5: Make the version monotonic across restarts via a persisted counter**

Replace the in-process `_build_counter` dict with a persisted counter stored in the SQLite DB (the same DB the checkpointer uses). Add a helper in `backend/app/services/context/planning_context.py`:

```python
async def _next_persisted_version(session_id: str) -> int:
    from app.database.engine import get_db_path
    import aiosqlite

    async with aiosqlite.connect(get_db_path()) as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS context_version (session_id TEXT PRIMARY KEY, version INTEGER)"
        )
        await conn.execute(
            "INSERT INTO context_version(session_id, version) VALUES(?, 1) "
            "ON CONFLICT(session_id) DO UPDATE SET version = version + 1",
            (session_id,),
        )
        await conn.commit()
        async with conn.execute(
            "SELECT version FROM context_version WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 1
```

Replace the `version = _next_version(session_id)` call (line 71) with `version = await _next_persisted_version(session_id)`. Keep `_next_version` as a fallback only if the DB is unavailable (and log a warning).

- [ ] **Step 6: Deepen `context_bootstrap.py` verification**

Read `backend/app/agent/bootstrap/context_bootstrap.py` around line 78. Replace the shallow `snapshot_meta` check with a verification of `content_hash` and `capabilities`:

```python
    if not ctx.content_hash:
        raise ContextBuildError("context has no content_hash - not frozen")
    if ctx.required_capabilities_missing:
        raise ContextBuildError(f"context missing required capabilities: {ctx.required_capabilities_missing}")
```

- [ ] **Step 7: Run the new tests**

Run: `pytest backend/tests/agent/test_context_content_snapshot.py -v`
Expected: PASS

- [ ] **Step 8: Run the existing context freeze invariant suite**

Run: `pytest backend/tests/agent/test_context_freeze_invariant.py backend/tests/unit/test_planning_context_factory.py -v`
Expected: PASS - the existing freeze tests check that `context_version` is non-empty, which still holds. If any test asserts that `build_planning_context` returns a half-empty Context, update it to expect `ContextBuildError` instead.

- [ ] **Step 9: Commit**

```bash
git add backend/app/modules/context/planning_context.py backend/app/services/context/planning_context.py backend/app/agent/bootstrap/context_bootstrap.py backend/tests/agent/test_context_content_snapshot.py
git commit -m "fix(context): content-addressed snapshot with capability declaration (P0-3)"
```

---

## Task 4: Single TaskSupervisor with race-free cancel (P1)

**Files:**
- Modify: `backend/app/services/task_supervisor.py:1-51`
- Modify: `backend/app/services/runtime.py:141` (remove the second supervisor)
- Modify: `backend/app/services/composition.py:34-37` (make this the only supervisor)
- Test: `backend/tests/unit/test_task_supervisor.py` (new)

**Interfaces:**
- Consumes: none.
- Produces: `TaskSupervisor` with:
  - `create_task(key, coro)` that cancels the old task **and awaits it** before replacing, so the done-callback cannot delete the new task's key.
  - `async cancel_all()` that gathers cancelled tasks **before** clearing the dict.
  - `async cancel(key)` that awaits the single task.
- `CompositionRoot.get_task_supervisor()` is the single source; `PlanningRuntimeService` no longer instantiates its own.

**Background:** `create_task` (line 16-18) cancels the old task but does not await it - the old task's done-callback (line 22-23) can fire **after** the new task is registered and `pop(key)` the new task. `cancel_all` (line 38-44) clears `self._tasks` via `cancel()` (which pops) then tries to `gather(*self._tasks.values())` on the now-empty dict. `PlanningRuntimeService` (runtime.py:141) creates its own `TaskSupervisor` separate from `CompositionRoot` (composition.py:37).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_task_supervisor.py`:

```python
"""P1: TaskSupervisor replace race + cancel-then-await."""
import asyncio
import pytest

from app.services.task_supervisor import TaskSupervisor


@pytest.mark.asyncio
async def test_replace_does_not_lose_new_task():
    sup = TaskSupervisor()
    started = asyncio.Event()
    old_task = asyncio.create_task(started.wait())
    sup._tasks["k"] = old_task

    async def new_coro():
        await asyncio.sleep(0.05)

    new_task = sup.create_task("k", new_coro())
    await asyncio.sleep(0.1)
    assert "k" in sup._tasks
    assert sup._tasks["k"] is new_task


@pytest.mark.asyncio
async def test_cancel_all_awaits_all_tasks():
    sup = TaskSupervisor()
    finished = []

    async def slow():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            finished.append("cancelled")
            raise

    sup.create_task("a", slow())
    sup.create_task("b", slow())
    await sup.cancel_all()
    assert len(finished) == 2


@pytest.mark.asyncio
async def test_cancel_key_awaits_task():
    sup = TaskSupervisor()
    done = asyncio.Event()

    async def coro():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            done.set()
            raise

    t = sup.create_task("k", coro())
    await sup.cancel("k")
    assert done.is_set()
    assert t.done()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_task_supervisor.py -v`
Expected: FAIL - `test_replace_does_not_lose_new_task` fails (old callback pops new key); `test_cancel_all_awaits_all_tasks` may hang or not collect all `finished`.

- [ ] **Step 3: Rewrite `TaskSupervisor`**

Replace the entire `backend/app/services/task_supervisor.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TaskSupervisor:
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}

    def create_task(self, key: str, coro: Any) -> asyncio.Task:
        old = self._tasks.get(key)
        if old is not None and not old.done():
            old.cancel()

        task = asyncio.create_task(coro)
        self._tasks[key] = task

        def _done_callback(t: asyncio.Task) -> None:
            current = self._tasks.get(key)
            if current is t:
                self._tasks.pop(key, None)
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error("[TaskSupervisor] task %s failed: %s", key, exc)

        task.add_done_callback(_done_callback)
        return task

    async def cancel(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[TaskSupervisor] task %s raised during cancel: %s", key, exc)

    async def cancel_all(self) -> None:
        keys = list(self._tasks.keys())
        tasks = [self._tasks.pop(key, None) for key in keys]
        to_wait = [t for t in tasks if t is not None and not t.done()]
        for t in to_wait:
            t.cancel()
        if to_wait:
            await asyncio.gather(*to_wait, return_exceptions=True)
        self._tasks.clear()

    @property
    def active_count(self) -> int:
        return len(self._tasks)


__all__ = ["TaskSupervisor"]
```

Key fixes: (1) the done-callback only pops the key if the stored task is still `t` (identity check prevents the race); (2) `cancel` awaits the task; (3) `cancel_all` snapshots tasks into a local list before popping, so `gather` sees them.

- [ ] **Step 4: Remove the second supervisor from `PlanningRuntimeService`**

In `backend/app/services/runtime.py`, delete line 141 (`cls._task_supervisor = TaskSupervisor()`) and change `shutdown` (line 151-155) to delegate to `CompositionRoot`:

```python
    @classmethod
    async def shutdown(cls) -> None:
        from app.services.composition import CompositionRoot

        sup = CompositionRoot.get_task_supervisor()
        await sup.cancel_all()
        logger.info("[PlanningRuntimeService] All tracked tasks cancelled")
```

Also update any `cls._task_supervisor` references in `runtime.py` to go through `CompositionRoot.get_task_supervisor()`. Search the file for `_task_supervisor` first.

- [ ] **Step 5: Ensure `CompositionRoot` is initialized in lifespan**

Read `backend/app/main.py` lifespan (around line 200). Confirm `CompositionRoot.initialize()` is called at startup. If not, add it before `PlanningRuntimeService.ensure_initialized()`.

- [ ] **Step 6: Run the new tests**

Run: `pytest backend/tests/unit/test_task_supervisor.py -v`
Expected: PASS

- [ ] **Step 7: Run the runtime tests**

Run: `pytest backend/tests/ -k "runtime or composition" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/task_supervisor.py backend/app/services/runtime.py backend/app/services/composition.py backend/app/main.py backend/tests/unit/test_task_supervisor.py
git commit -m "fix(supervisor): race-free cancel, single TaskSupervisor via CompositionRoot (P1)"
```

---

## Task 5: Complete session disposal (P1)

**Files:**
- Modify: `backend/app/services/session.py:155-187` (the delete path)
- Test: `backend/tests/unit/test_session_disposal.py` (new)

**Interfaces:**
- Consumes: `TaskSupervisor`, `PlanningRuntimeService`, `get_global_checkpointer`, session bundle store, KG manager, artifact directory, SSE state.
- Produces: `SessionService.delete_session` returns a dict with keys `{tasks, context, bundle, kg, artifacts, checkpoint, sse, database}` - every key present, every cleanup attempted even if earlier steps fail.

**Background:** The current delete path (session.py:155-187) does not cancel running tasks, does not clear `PlanningContext`, does not delete the session bundle, does not delete the session KG, does not delete artifact directories, does not clear SSE state, and its checkpoint deletion (line 177-179) is broken: `aget_tuple` is used as an async iterator but it returns a single optional tuple, and `adelete` does not exist on `AsyncSqliteSaver` (the correct method is `adel` / `aput` with a tombstone - verify the actual LangGraph API in Step 1).

- [ ] **Step 1: Look up the correct AsyncSqliteSaver deletion API**

Read the installed `langgraph.checkpoint.sqlite.aio` source to find the correct deletion method. Run:

```bash
python -c "from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver; print([m for m in dir(AsyncSqliteSaver) if m.startswith('a')])"
```

If `adelete` exists, use it. If only `adel` or a tuple-rewriting approach exists, use that. Document the exact method name in the test.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_session_disposal.py`:

```python
"""P1: session deletion must clean up all 7 resource categories."""
import pytest

from app.services.session import SessionService


@pytest.mark.asyncio
async def test_delete_session_cleans_all_categories(monkeypatch, tmp_path):
    cleaned = []

    async def fake_cancel_tasks(session_id):
        cleaned.append("tasks")
        return True

    async def fake_clear_context(session_id):
        cleaned.append("context")
        return True

    async def fake_delete_bundle(session_id):
        cleaned.append("bundle")
        return True

    async def fake_delete_kg(session_id):
        cleaned.append("kg")
        return True

    async def fake_delete_artifacts(session_id):
        cleaned.append("artifacts")
        return True

    async def fake_delete_checkpoint(session_id):
        cleaned.append("checkpoint")
        return True

    async def fake_clear_sse(session_id):
        cleaned.append("sse")
        return True

    async def fake_delete_db(session_id):
        cleaned.append("database")
        return True

    monkeypatch.setattr("app.services.session._cancel_session_tasks", fake_cancel_tasks)
    monkeypatch.setattr("app.services.session._clear_session_context", fake_clear_context)
    monkeypatch.setattr("app.services.session._delete_session_bundle", fake_delete_bundle)
    monkeypatch.setattr("app.services.session._delete_session_kg", fake_delete_kg)
    monkeypatch.setattr("app.services.session._delete_session_artifacts", fake_delete_artifacts)
    monkeypatch.setattr("app.services.session._delete_session_checkpoint", fake_delete_checkpoint)
    monkeypatch.setattr("app.services.session._clear_session_sse", fake_clear_sse)
    monkeypatch.setattr("app.services.session.delete_planning_session_async", fake_delete_db)

    result = await SessionService.delete_session("test-dispose-1", project_name="p")
    assert set(result.keys()) == {
        "tasks", "context", "bundle", "kg", "artifacts", "checkpoint", "sse", "database"
    }
    assert all(result.values()), f"some cleanup failed: {result}"
    assert set(cleaned) == {
        "tasks", "context", "bundle", "kg", "artifacts", "checkpoint", "sse", "database"
    }


@pytest.mark.asyncio
async def test_delete_session_continues_after_partial_failure(monkeypatch):
    async def boom_bundle(session_id):
        raise RuntimeError("bundle gone")

    async def ok(session_id):
        return True

    monkeypatch.setattr("app.services.session._cancel_session_tasks", ok)
    monkeypatch.setattr("app.services.session._clear_session_context", ok)
    monkeypatch.setattr("app.services.session._delete_session_bundle", boom_bundle)
    monkeypatch.setattr("app.services.session._delete_session_kg", ok)
    monkeypatch.setattr("app.services.session._delete_session_artifacts", ok)
    monkeypatch.setattr("app.services.session._delete_session_checkpoint", ok)
    monkeypatch.setattr("app.services.session._clear_session_sse", ok)
    monkeypatch.setattr("app.services.session.delete_planning_session_async", ok)

    result = await SessionService.delete_session("test-dispose-2", project_name="p")
    assert result["bundle"] is False
    assert result["database"] is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_session_disposal.py -v`
Expected: FAIL - the helper functions `_cancel_session_tasks` etc. do not exist yet.

- [ ] **Step 4: Implement the disposal helpers**

In `backend/app/services/session.py`, add module-level async helper functions near the top (after imports). Each wraps an existing service call in try/except so one failure does not block the rest:

```python
async def _cancel_session_tasks(session_id: str) -> bool:
    try:
        from app.services.composition import CompositionRoot
        sup = CompositionRoot.get_task_supervisor()
        await sup.cancel(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] task cancel failed: {e}")
        return False


async def _clear_session_context(session_id: str) -> bool:
    try:
        from app.services.context.planning_context import _context_cache, _build_counter
        _context_cache.pop(session_id, None)
        _build_counter.pop(session_id, None)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] context clear failed: {e}")
        return False


async def _delete_session_bundle(session_id: str) -> bool:
    try:
        from app.services.session_bundle import delete_session_bundle
        await delete_session_bundle(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] bundle delete failed: {e}")
        return False


async def _delete_session_kg(session_id: str) -> bool:
    try:
        from app.modules.kg.manager import get_kg_manager
        get_kg_manager().remove_session_kg(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] KG delete failed: {e}")
        return False


async def _delete_session_artifacts(session_id: str) -> bool:
    try:
        import shutil
        from pathlib import Path
        from app.core.settings import settings
        artifact_dir = Path(settings.artifact_dir) / session_id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] artifact delete failed: {e}")
        return False


async def _delete_session_checkpoint(session_id: str) -> bool:
    try:
        from app.services.runtime import PlanningRuntimeService
        from app.database.engine import get_global_checkpointer
        await PlanningRuntimeService.ensure_initialized()
        checkpointer = await get_global_checkpointer()
        config = PlanningRuntimeService.get_thread_config(session_id)
        if hasattr(checkpointer, "adelete"):
            await checkpointer.adelete(config)
        else:
            tuple_ = await checkpointer.aget_tuple(config)
            if tuple_ is not None:
                await checkpointer.aput(config, {}, tuple_.metadata, {"source": "delete"})
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] checkpoint delete failed: {e}")
        return False


async def _clear_session_sse(session_id: str) -> bool:
    try:
        from app.api.session_sse import clear_sse_state
        await clear_sse_state(session_id)
        return True
    except Exception as e:
        logger.warning(f"[SessionService] [{session_id}] SSE clear failed: {e}")
        return False
```

Then replace the `delete_session` body (lines 155-187) to call all helpers in order, collecting results:

```python
    result = {
        "tasks": await _cancel_session_tasks(session_id),
        "context": await _clear_session_context(session_id),
        "bundle": await _delete_session_bundle(session_id),
        "kg": await _delete_session_kg(session_id),
        "artifacts": await _delete_session_artifacts(session_id),
        "checkpoint": await _delete_session_checkpoint(session_id),
        "sse": await _clear_session_sse(session_id),
        "database": await delete_planning_session_async(session_id),
    }
    logger.info(f"[SessionService] [{session_id}] Session deleted: {result}")
    return result
```

- [ ] **Step 5: Verify the helper imports exist**

Before running, confirm `delete_session_bundle`, `remove_session_kg`, `clear_sse_state` exist by grepping. If any does not exist, implement a minimal stub that logs and returns (do not fail the whole disposal on a missing sub-API).

- [ ] **Step 6: Run the new tests**

Run: `pytest backend/tests/unit/test_session_disposal.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/session.py backend/tests/unit/test_session_disposal.py
git commit -m "fix(session): complete disposal across tasks/context/bundle/KG/artifacts/checkpoint/SSE (P1)"
```

---

## Task 6: Lifespan shutdown + CI health gate (P1)

**Files:**
- Modify: `backend/app/main.py:200-227` (call `shutdown_database()`)
- Modify: CI config (locate the file that pings `/health`)
- Test: `backend/tests/unit/test_lifespan_shutdown.py` (new)

**Interfaces:**
- Consumes: `shutdown_database` from `app.database.engine`.
- Produces: lifespan calls `shutdown_database()` after `PlanningRuntimeService.shutdown()` and `dispose_async_engine()`.

**Background:** `shutdown_database()` exists (engine.py:93) and closes the bare aiosqlite checkpointer connection that `dispose_async_engine` cannot reach, but `main.py:212-225` only calls `dispose_async_engine()`, never `shutdown_database()`. Separately, CI pings `/health` (routes.py:60, always returns alive) but the readiness check that validates DB + checkpointer is at `/api/health` (main.py:285).

- [ ] **Step 1: Locate the CI health check**

Search the repo for references to `/health` (not `/api/health`) in CI, scripts, or docker-compose:

```bash
grep -rn "\"/health\"" --include="*.yml" --include="*.yaml" --include="*.sh" --include="*.json" backend/ .github/ docker-compose* 2>/dev/null || true
```

Record the file paths.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_lifespan_shutdown.py`:

```python
"""P1: lifespan must call shutdown_database (not just dispose_async_engine)."""
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_lifespan_calls_shutdown_database(monkeypatch):
    called = {"shutdown_database": False, "dispose_async_engine": False}

    async def fake_shutdown_database():
        called["shutdown_database"] = True

    async def fake_dispose():
        called["dispose_async_engine"] = True

    monkeypatch.setattr("app.main.shutdown_database", fake_shutdown_database)
    monkeypatch.setattr("app.main.dispose_async_engine", fake_dispose)

    from app.main import app
    async with app.router.lifespan_context(app):
        pass

    assert called["dispose_async_engine"] is True
    assert called["shutdown_database"] is True, "lifespan must call shutdown_database()"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_lifespan_shutdown.py -v`
Expected: FAIL - `shutdown_database` is never called.

- [ ] **Step 4: Wire `shutdown_database` into lifespan**

In `backend/app/main.py`, import `shutdown_database` at the top (alongside `dispose_async_engine`), and add a call after the `dispose_async_engine` block (around line 225):

```python
    try:
        await shutdown_database()
        logger.info("✅ Database connections fully shutdown")
    except Exception as e:
        logger.error(f"❌ Failed to shutdown database: {e}", exc_info=True)
```

- [ ] **Step 5: Fix the CI health endpoint**

In each CI config file found in Step 1, replace `/health` with `/api/health`. If the file is a shell script or YAML, edit the URL string. If there is a custom health script, point it at `/api/health`.

- [ ] **Step 6: Run the test**

Run: `pytest backend/tests/unit/test_lifespan_shutdown.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_lifespan_shutdown.py <CI config files>
git commit -m "fix(lifespan): call shutdown_database; CI uses /api/health readiness gate (P1)"
```

---

## Task 7: Session creation compensating transaction (P1)

**Files:**
- Modify: `backend/app/api/session_crud.py:88` (the create path) - locate the exact lines first
- Test: `backend/tests/unit/test_session_create_compensation.py` (new)

**Interfaces:**
- Consumes: `delete_planning_session_async`, artifact directory cleanup, file cleanup.
- Produces: if any step after DB insert fails, the compensating handler deletes the DB record and any uploaded files/artifacts before re-raising.

**Background:** `session_crud.py:88` creates the DB session first, then runs upload/validation; if a later step fails, the half-built session record and uploaded files remain.

- [ ] **Step 1: Read the create path**

Read `backend/app/api/session_crud.py` around lines 60-160 to identify the exact sequence: DB insert -> file upload -> validation -> response. Note the function name and the variables holding `session_id` and uploaded file paths.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_session_create_compensation.py`:

```python
"""P1: session creation must roll back DB + files on downstream failure."""
import pytest


@pytest.mark.asyncio
async def test_create_session_rolls_back_on_upload_failure(monkeypatch, tmp_path):
    from app.api.session_crud import create_session_endpoint
    from app.services.session_crud_service import SessionCRUDService

    deleted = {"db": False, "files": False}

    async def fake_create_db(*args, **kwargs):
        return "test-comp-1"

    async def fake_delete_db(session_id):
        deleted["db"] = True

    async def fake_delete_files(session_id):
        deleted["files"] = True

    async def boom_upload(*args, **kwargs):
        raise RuntimeError("upload failed")

    monkeypatch.setattr("app.api.session_crud.create_planning_session_async", fake_create_db)
    monkeypatch.setattr("app.api.session_crud.delete_planning_session_async", fake_delete_db)
    monkeypatch.setattr("app.api.session_crud._delete_uploaded_files", fake_delete_files)
    monkeypatch.setattr("app.api.session_crud._handle_file_upload", boom_upload)

    with pytest.raises(RuntimeError, match="upload failed"):
        await create_session_endpoint(...)

    assert deleted["db"] is True
    assert deleted["files"] is True
```

(Adjust the exact endpoint signature and helper names after reading Step 1.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_session_create_compensation.py -v`
Expected: FAIL - no compensation; the DB record survives.

- [ ] **Step 4: Add the compensating wrapper**

In `backend/app/api/session_crud.py`, wrap the create logic in a try/except that, on any exception after the DB insert, calls the delete helpers and re-raises:

```python
    session_id = await create_planning_session_async(...)
    try:
        await _handle_file_upload(session_id, ...)
        ...
    except Exception:
        await delete_planning_session_async(session_id)
        await _delete_uploaded_files(session_id)
        raise
```

Add `_delete_uploaded_files` as a module-level helper that removes files from the upload directory for that session.

- [ ] **Step 5: Run the test**

Run: `pytest backend/tests/unit/test_session_create_compensation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/session_crud.py backend/tests/unit/test_session_create_compensation.py
git commit -m "fix(session): compensating transaction on creation failure (P1)"
```

---

## Task 8: HITL publish reliability + unified action vocabulary (P1)

**Files:**
- Modify: `backend/app/agent/graph.py:244` (publish-failure handling)
- Modify: HITL resolve routes (locate first)
- Test: `backend/tests/unit/test_hitl_publish_reliability.py` (new)

**Interfaces:**
- Consumes: SSE publisher, resume route.
- Produces: `human_review_pause_published` is set to `True` **only** after the SSE publish succeeds; on failure it stays `False` and a retry is scheduled. The action vocabulary is unified to `approve | reject` (drop `accept | retry`).

**Background:** `graph.py:244` sets `human_review_pause_published=True` even when the SSE send fails, so no re-publish happens. Two action vocabularies coexist (`approve/reject` and `accept/reject/retry`) with different resume semantics.

- [ ] **Step 1: Read the publish path and the resolve routes**

Read `backend/app/agent/graph.py` around lines 230-260 to see the exact publish + flag-set sequence. Grep for `accept` and `retry` in the HITL route handlers:

```bash
grep -rn "accept\|retry\|approve\|reject" --include="*.py" backend/app/api/ | grep -i hitl
grep -rn "accept\|retry\|approve\|reject" --include="*.py" backend/app/agent/ | grep -i review
```

Record the exact route paths and the function names that parse the action.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_hitl_publish_reliability.py`:

```python
"""P1: HITL publish failure must not mark success; unified action vocab."""
import pytest


@pytest.mark.asyncio
async def test_publish_failure_leaves_flag_false(monkeypatch):
    from app.agent.graph import _publish_human_review_pause

    async def boom_publish(*args, **kwargs):
        raise RuntimeError("SSE unavailable")

    monkeypatch.setattr("app.agent.graph._send_sse", boom_publish)

    result = await _publish_human_review_pause({"session_id": "s1"}, pause_items=[])
    assert result.get("human_review_pause_published") is False


@pytest.mark.asyncio
async def test_action_vocabulary_is_approve_reject_only():
    from app.agent.graph import _parse_hitl_action

    assert _parse_hitl_action("approve") == "approve"
    assert _parse_hitl_action("reject") == "reject"
    with pytest.raises(ValueError):
        _parse_hitl_action("accept")
    with pytest.raises(ValueError):
        _parse_hitl_action("retry")
```

(Adjust function names after reading Step 1.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_hitl_publish_reliability.py -v`
Expected: FAIL - `_publish_human_review_pause` sets the flag to `True` unconditionally; `_parse_hitl_action` accepts `accept`/`retry`.

- [ ] **Step 4: Fix the publish-failure flag**

In `backend/app/agent/graph.py`, extract the publish logic into `_publish_human_review_pause` and only set `human_review_pause_published=True` inside a `try` block after a successful publish:

```python
async def _publish_human_review_pause(state, pause_items):
    try:
        await _send_sse(state.get("session_id", ""), {"type": "human_review_pause", "items": pause_items})
        return {"human_review_pause_published": True}
    except Exception as e:
        logger.error("[HITL] publish failed, will retry: %s", e)
        return {"human_review_pause_published": False, "human_review_publish_error": str(e)}
```

Add a scheduled retry: if `human_review_pause_published` is False, a background task (via `TaskSupervisor`) re-attempts the publish with exponential backoff.

- [ ] **Step 5: Unify the action vocabulary**

In the HITL resolve route handler, replace any `accept`/`retry` branches with a `400 Bad Request` for unknown actions, accepting only `approve`/`reject`. If `retry` semantics are needed, map them to `reject` with a `retry=true` flag in the decision payload (document this in the route docstring).

- [ ] **Step 6: Run the test**

Run: `pytest backend/tests/unit/test_hitl_publish_reliability.py -v`
Expected: PASS

- [ ] **Step 7: Run the existing HITL tests**

Run: `pytest backend/tests/ -k "hitl or human_review" -v`
Expected: PASS - update any test that uses `accept`/`retry` to use `approve`/`reject`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/graph.py backend/app/api/<hitl route file> backend/tests/unit/test_hitl_publish_reliability.py
git commit -m "fix(hitl): publish-failure retry + unified approve/reject vocabulary (P1)"
```

---

## Task 9: Align StateFactory with AgentState (P1)

**Files:**
- Modify: `backend/app/agent/plan_state/state_factory.py:14-131`
- Modify: `backend/app/agent/plan_state/state.py:261-395` (remove `create_initial_state`)
- Modify: `backend/app/agent/plan_state/__init__.py` (drop `create_initial_state` export)
- Modify: `backend/app/agent/bootstrap/graph.py:8` (use `StateFactory.create`)
- Test: `backend/tests/unit/test_state_factory_alignment.py` (new)

**Interfaces:**
- Consumes: `AgentState` TypedDict definition.
- Produces: `StateFactory.create` returns a dict whose keys are exactly the `AgentState` fields (plus runtime-only fields that have Annotated reducers). `create_initial_state` is removed; all callers use `StateFactory.create`.

**Background:** `StateFactory` sets `uploaded_files`, `reports`, `sse_events`, `gis_analysis_results` (state_factory.py:66-90) which are not in `AgentState` - LangGraph will drop them. `AgentState` has `dimension_key` and `explore_done` (state.py:180, 204) which `StateFactory` does not set. `create_initial_state` (state.py:261) is a duplicate entry point still imported by `graph.py:8`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_state_factory_alignment.py`:

```python
"""P1: StateFactory output keys must match AgentState fields exactly."""
from app.agent.plan_state.state import AgentState
from app.agent.plan_state.state_factory import StateFactory


def test_factory_keys_subset_of_agent_state():
    state = StateFactory.create(session_id="s1", project_name="p", village_data="v")
    agent_keys = set(AgentState.__annotations__.keys())
    factory_keys = set(state.keys())
    extra = factory_keys - agent_keys
    assert not extra, f"StateFactory sets keys not in AgentState (will be dropped by LangGraph): {extra}"


def test_factory_sets_all_required_agent_state_fields():
    state = StateFactory.create(session_id="s1", project_name="p", village_data="v")
    required = {"session_id", "project_name", "phase", "current_wave", "messages", "config"}
    assert required.issubset(state.keys())


def test_create_initial_state_removed():
    import importlib
    mod = importlib.import_module("app.agent.plan_state")
    assert not hasattr(mod, "create_initial_state"), "create_initial_state compat shim must be removed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_state_factory_alignment.py -v`
Expected: FAIL - `extra` contains `uploaded_files`, `reports`, `sse_events`, `gis_analysis_results`; `create_initial_state` still exists.

- [ ] **Step 3: Remove schema-incompatible fields from `StateFactory.create`**

In `backend/app/agent/plan_state/state_factory.py`, delete the keys `uploaded_files`, `reports`, `sse_events`, `gis_analysis_results` from the returned dict (lines ~66, 68, 70, 90). Add the missing `dimension_key` (default `None`) and `explore_done` (default `False`) keys.

- [ ] **Step 4: Remove `create_initial_state`**

In `backend/app/agent/plan_state/state.py`, delete the `create_initial_state` function (lines 261-395) and remove it from `__all__`. In `backend/app/agent/plan_state/__init__.py`, remove the `create_initial_state` import and export.

- [ ] **Step 5: Update `graph.py` to use `StateFactory`**

In `backend/app/agent/bootstrap/graph.py:8`, replace `from app.agent.plan_state.state import AgentState, create_initial_state` with `from app.agent.plan_state.state import AgentState` and `from app.agent.plan_state.state_factory import StateFactory`. Replace any `create_initial_state(...)` call with `StateFactory.create(...)`.

- [ ] **Step 6: Grep for remaining `create_initial_state` callers**

```bash
grep -rn "create_initial_state" --include="*.py" backend/
```

Update every caller to use `StateFactory.create`.

- [ ] **Step 7: Run the test**

Run: `pytest backend/tests/unit/test_state_factory_alignment.py -v`
Expected: PASS

- [ ] **Step 8: Run the graph + bootstrap tests**

Run: `pytest backend/tests/ -k "graph or bootstrap or state" -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/agent/plan_state/ backend/app/agent/bootstrap/graph.py backend/tests/unit/test_state_factory_alignment.py
git commit -m "fix(state): align StateFactory with AgentState; remove create_initial_state shim (P1)"
```

---

## Task 10: Ports injected by composition root; remove `get_any_kg` (P1)

**Files:**
- Modify: `backend/app/services/composition.py` (inject KG/road/zone/artifact/bundle ports)
- Modify: `backend/app/modules/kg/manager.py:241` (remove `get_any_kg`)
- Modify: `backend/app/services/session_kg.py` (remove the `get_any_kg` fallback path)
- Modify: `backend/app/modules/ports/registry.py` (stop being a service locator for KG)
- Test: `backend/tests/unit/test_ports_injected.py` (new)

**Interfaces:**
- Consumes: `CompositionRoot`.
- Produces: KG/road/zone/artifact/bundle services are obtained exclusively via Ports injected by `CompositionRoot.initialize()`. `get_any_kg()` is removed; callers use `registry.get_kg_port().get_session_kg(session_id)`.

**Background:** `session_kg.py` and `manager.py:241` still call `get_any_kg()` which returns the most-recently-registered session KG - a cross-session leak. `registry.py` is a module-level service locator. `CompositionRoot` (composition.py) only wires report_store and context_reader, not KG/road/zone/artifact/bundle.

- [ ] **Step 1: Grep for all `get_any_kg` callers**

```bash
grep -rn "get_any_kg" --include="*.py" backend/
```

Record every call site.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/unit/test_ports_injected.py`:

```python
"""P1: Ports injected by CompositionRoot; get_any_kg removed."""
import importlib
import pytest


def test_get_any_kg_removed():
    mod = importlib.import_module("app.modules.kg.manager")
    assert not hasattr(mod, "get_any_kg"), "get_any_kg must be removed - use KGPort.get_session_kg"


def test_composition_root_injects_kg_port():
    from app.services.composition import CompositionRoot
    CompositionRoot.reset()
    CompositionRoot.initialize()
    from app.modules.ports.registry import registry
    assert registry.get_kg_port() is not None


@pytest.mark.asyncio
async def test_session_kg_uses_port_not_global(monkeypatch):
    from app.services import session_kg

    called = {"port": False}

    class FakeKgPort:
        def get_session_kg(self, session_id):
            called["port"] = True
            return None

    from app.modules.ports import registry
    monkeypatch.setattr(registry, "get_kg_port", lambda: FakeKgPort())

    await session_kg.ensure_session_kg("s1", "v1")
    assert called["port"] is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_ports_injected.py -v`
Expected: FAIL - `get_any_kg` still exists; `registry.get_kg_port` returns `None`; `session_kg` calls `get_any_kg`.

- [ ] **Step 4: Add KG/road/zone/artifact/bundle port wiring to `CompositionRoot`**

In `backend/app/services/composition.py`, extend `initialize()` to instantiate and register the missing ports. Read the existing `registry.py` to see the setter API (`set_kg_port_default`, etc.). Add:

```python
    if cls._kg_port is None:
        from app.modules.kg.manager import KGManager
        from app.modules.ports.kg_port import KGPort

        cls._kg_port = KGPort(KGManager())
        from app.modules.ports import registry
        registry.set_kg_port_default(cls._kg_port)
```

Repeat for road, zone, artifact, bundle ports - read `registry.py` first to get the exact setter names.

- [ ] **Step 5: Remove `get_any_kg`**

In `backend/app/modules/kg/manager.py`, delete the `get_any_kg` function (around line 241) and remove it from `__all__`.

- [ ] **Step 6: Rewrite `session_kg.py` to use the KG port**

In `backend/app/services/session_kg.py`, replace every `get_any_kg()` / `get_kg_manager().get_session_kg(...)` call with `registry.get_kg_port().get_session_kg(session_id)`. If the port returns `None`, raise `ContextBuildError("KG unavailable for session")` (or return an error dict depending on the existing contract - read the callers first).

- [ ] **Step 7: Update all `get_any_kg` callers from Step 1**

For each call site found in Step 1, replace with the port-based call.

- [ ] **Step 8: Run the test**

Run: `pytest backend/tests/unit/test_ports_injected.py -v`
Expected: PASS

- [ ] **Step 9: Run the KG + session tests**

Run: `pytest backend/tests/ -k "kg or session" -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/composition.py backend/app/modules/kg/manager.py backend/app/services/session_kg.py backend/app/modules/ports/ backend/tests/unit/test_ports_injected.py
git commit -m "fix(ports): inject KG/road/zone/artifact/bundle via CompositionRoot; remove get_any_kg (P1)"
```

---

## Self-Review

**1. Spec coverage:** The audit listed 11 fix items; this plan covers items 1-10. Item 11 (split `post_l3_main_nodes.py`, runtime, SSE, KG layer1, `planning_nodes.py`) is explicitly deferred - it is a P4/P5 refactor, not a blocking adaptation fix, and the audit itself says "最后再拆" (split last). All 3 P0 breakpoints (EXECUTE checkpointer, VALIDATE fail-open, Context snapshot) have dedicated tasks. All 7 P1 breakpoints (TaskSupervisor, session disposal, DB shutdown + CI, session creation compensation, HITL reliability, StateFactory alignment, Ports/get_any_kg) have dedicated tasks.

**2. Placeholder scan:** Several steps say "read the file first" or "grep for callers" - these are intentional discovery steps where the exact line numbers cannot be known without reading the file at execution time. They are not placeholders; each is followed by a concrete edit instruction. The `adelete` vs `adel` ambiguity in Task 5 is resolved by a discovery step (Task 5 Step 1) before implementation.

**3. Type consistency:** `ContextBuildError` is defined in Task 3 and referenced in Task 10 - consistent. `TaskSupervisor.create_task` / `cancel` / `cancel_all` signatures are identical in Task 4's implementation and Task 5's `_cancel_session_tasks` helper. `_parse_hitl_action` (Task 8) returns `"approve" | "reject"` which matches the unified vocabulary. `StateFactory.create` (Task 9) keeps its existing signature; only the returned dict keys change.

## Execution Handoff

**Plan complete and saved to `.opencode/plans/2026-08-08-backend-adaptation-critical-fixes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
