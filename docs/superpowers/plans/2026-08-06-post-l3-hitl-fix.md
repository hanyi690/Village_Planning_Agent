# Post-L3 HITL Resume Fix Plan (P0/P1/P2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the post-L3 HITL semantic break: resume decisions (approve/reject) are discarded (graph routes unconditionally to END), GET endpoint returns empty items on first interrupt, resume path never emits `completed`, `as_node` references a deleted node, and no SSE pause event is emitted. After the fix a real frontend can drive the full lifecycle: pause -> show pending items -> approve (force-pass forward) / reject (back to conversation) -> continue -> completed.

**Architecture:** The main graph `create_unified_planning_graph` (graph.py) is the single source of truth. `human_review_node` (graph.py:181-207) interrupts on HUMAN gates; its conditional edge (graph.py:176 `lambda state: END`) must become a real router reading `human_review_decisions`. The paused stage must be recorded so `approve` can force that stage's gate to PASS and forward to the next stage; `reject` appends a feedback `HumanMessage` and routes to `conversation`.

**Tech Stack:** Python 3.12, LangGraph 1.2.8, Pydantic V2, pytest, FastAPI. LF line endings, 4-space indent, Python double quotes.

## Design Decisions (user-confirmed)

- **approve = force-pass forward**: set the paused stage's gate to PASS and route to the next-stage node
- **reject = back to conversation**: append a HumanMessage feedback then route to `conversation`
- **Dead `*_ref` channels**: document as audit-only this round; no loaders (crash recovery is Deferred)
- **Doc location**: `docs/superpowers/plans/2026-08-06-post-l3-hitl-fix.md`

## Diagnostic Basis (verified during review, with file:line)

| Defect | Location | Root cause |
|---|---|---|
| resume routes unconditionally to END | `graph.py:176` `lambda state: END` | never reads `human_review_decisions`; standalone chain resume semantics not ported |
| paused stage not recorded at interrupt | `graph.py:196-202` interrupt payload | no `paused_stage` field; `_collect_human_items` does not surface the gate_attr |
| GET returns empty items on first interrupt | `human_review_routes.py:34` | reads `state.human_review_items` (not yet written at interrupt), not `snapshot.tasks[*].interrupts[*].value` |
| resume never emits `completed` | `runtime.py:278-290` | lacks the `deliver_gate==PASS` check from `_execute_planning:817-822` |
| `as_node` references deleted node | `post_l3_resume.py:143` | `as_node="gis_agent"`, not a registered main-graph node |
| no SSE pause event | `graph.py:181-207` | `human_review_node` publishes nothing before interrupt; `send_layer_paused` has zero call sites |

## Confirmed implementation facts (for agents)

- `_collect_human_items` (`post_l3_main_nodes.py:599-624`) iterates hardcoded gate attrs `("parse_gate","ground_gate","select_gate","validate_gate","reconcile_gate","deliver_gate")` and `break`s at first HUMAN gate but discards which attr.
- `collect_human_review_items` (`post_l3_main_nodes.py:646-651`) wraps `_collect_human_items`, falls back to `_retry_exhaustion_items` (lines 627-643).
- Gate state channel names are exactly `{stage}_gate` (state.py:231-257); there is **no** `execute_gate` (execute has no gate; graph.py:168 unconditional edge).
- **No** stage->forward-target constant exists anywhere; each `route_after_*` hardcodes its PASS target (parse->ground, ground->select, select->execute, validate->reconcile, reconcile->deliver, deliver->END). Must be introduced.
- `human_review_node` (graph.py:181-207) is `async`, reads `error_feedback` + gate channels, calls `interrupt({human_review_items, error_feedback, reason})`, returns `{human_review_items, human_review_decisions}` after resume.
- `conversation` is a registered node (graph.py:129). `conversation_node` (conversation_router/node.py:76-110) reads `messages`/`phase`/`project_name`/`config`; routes to it work with standard AgentState. If `messages` is empty, `after_conversation` (edges.py:30-45) returns END - so append a HumanMessage on reject.
- `_gate_route` (`post_l3_main_nodes.py:33-40`) treats `feedback_route in (None, "")` as PASS. Force-pass = `GateDecision(stage, passed=True, feedback_route=None, pending_requests=[], evidence_requests=[])` serialized via `_dump` (line 134).
- `aget_state` (runtime.py:150-156) returns a `StateSnapshot`; interrupt payload path is `snapshot.tasks[i].interrupts[j].value` (a dict). `/status` (session_routes.py:865-884) already detects interrupts this way.
- `_execute_planning` completion check (runtime.py:817-822): `final_state["phase"]=="completed"` and `deliver_gate.feedback_route=="PASS"` -> `await cls._append_event(session_id, create_completed_event(session_id))`. Resume tail (runtime.py:277-290) must mirror it.
- `resume_from_interrupt` (runtime.py:202-290) uses `Command(resume=...)`, per-session `asyncio.Lock` (line 227), streams `['values','checkpoints']`.
- `as_node="gis_agent"` (post_l3_resume.py:143) is invalid; valid main-graph nodes include `conversation`/`parse`/`ground`/`select`/`execute`/`validate`/`reconcile`/`deliver`/`human_review`; use `"human_review"`.
- SSE async pattern used by worker nodes: `from app.services.sse import sse_manager; await sse_manager.publish(session_id, {...})`.

---

## Task 1: Record paused stage + PASS-gate helper

**Target:** `_collect_human_items` returns the stage name; new `_pass_gate` constructor.

**File:** `backend/app/agent/bootstrap/post_l3_main_nodes.py`

**Changes:**

1. Add module constants (near `_RETRY_ROUTES`, ~line 30):
```
_STAGE_FORWARD_TARGET = {
    "parse": "ground",
    "ground": "select",
    "select": "execute",
    "validate": "reconcile",
    "reconcile": "deliver",
    "deliver": "__end__",
}
_GATE_CHANNELS = (
    "parse_gate", "ground_gate", "select_gate",
    "validate_gate", "reconcile_gate", "deliver_gate",
)
```

2. Add `_pass_gate(stage)` helper (~line 40):
```
def _pass_gate(stage: str) -> GateDecision:
    return GateDecision(
        stage=stage, passed=True, feedback_route=None,
        pending_requests=[], evidence_requests=[],
    )
```
(import `GateDecision` from `app.modules.schema.contracts.workflow_contracts` if not already imported)

3. Change `_collect_human_items` (line 599-624) to return `Tuple[Optional[str], List[Dict]]` instead of `List[Dict]`. Record the matched `gate_attr`; return `(stage, items)` on match where `stage = gate_attr.replace("_gate","")`; return `(None, [])` otherwise.

4. Change `collect_human_review_items` (line 646-651) to return `Tuple[Optional[str], List[Dict]]`: `(stage, items)` from `_collect_human_items` when stage is not None, else `(None, retry_items)` from `_retry_exhaustion_items`.

**Tests** (`tests/agent/test_post_l3_main_nodes.py`):
- [ ] `test_collect_human_items_returns_stage_from_dict_gate`: select HUMAN gate (dict form) -> `("select", [<items>])`
- [ ] `test_collect_human_items_returns_none_when_no_human_gate`: no HUMAN gate -> `(None, [])`
- [ ] `test_pass_gate_construction`: `_pass_gate("select")` has `feedback_route is None` and `passed is True`

**Verify:** `python -m pytest tests/agent/test_post_l3_main_nodes.py -q` (timeout 60s)

---

## Task 2: human_review_node carries stage + emits SSE pause event

**Target:** interrupt payload carries `paused_stage`; SSE pause event before interrupt.

**Files:** `backend/app/agent/bootstrap/graph.py` (line 181-207), `backend/app/agent/plan_state/state.py`

**Changes:**

1. `human_review_node` unpacks `(paused_stage, items) = post_l3_main_nodes.collect_human_review_items(state)`.

2. Interrupt payload adds `"paused_stage": paused_stage`.

3. Return dict adds `"paused_stage": paused_stage` (and `None` on the no-items path).

4. Before `interrupt()` (when items non-empty), publish SSE event:
```
session_id = state.get("session_id")
if session_id:
    try:
        from app.services.sse import sse_manager
        await sse_manager.publish(session_id, {
            "type": "human_review_paused",
            "session_id": session_id,
            "paused_stage": paused_stage,
            "items_count": len(items),
            "timestamp": datetime.now().isoformat(),
        })
    except Exception:
        logger.warning("[main:human_review] SSE publish skipped")
```
(`datetime` import: `from datetime import datetime`)

5. No-items path returns `{"human_review_items": [], "paused_stage": None}`.

**AgentState** (`state.py`): add `paused_stage: Optional[str] = None` channel near `human_review_decisions`, and seed it in `create_initial_state`.

**Tests** (`tests/agent/test_unified_graph_replay.py` extension):
- [ ] `test_hitl_interrupt_payload_carries_paused_stage`: select HUMAN gate -> interrupt payload `paused_stage == "select"`
- [ ] `test_hitl_resume_records_paused_stage`: after resume, `result["paused_stage"] == "select"`

**Verify:** `python -m pytest tests/agent/test_unified_graph_replay.py tests/agent/test_post_l3_main_nodes.py -q` (timeout 90s)

---

## Task 3: route_after_human_review router (core P0#1)

**Target:** replace `lambda state: END`; route by approve/reject decision.

**File:** `backend/app/agent/bootstrap/graph.py`

**Changes:**

1. Import `_STAGE_FORWARD_TARGET`, `_pass_gate`, `_dump` from `post_l3_main_nodes`.

2. Add router (~line 115, after other `route_after_*`):
```
def route_after_human_review(state):
    decisions = state.get("human_review_decisions") or {}
    paused_stage = state.get("paused_stage")
    action = decisions.get("action") if isinstance(decisions, dict) else None

    if action == "approve":
        if paused_stage and paused_stage in _STAGE_FORWARD_TARGET:
            return _STAGE_FORWARD_TARGET[paused_stage]
        return END
    if action == "reject":
        return "conversation"
    return END
```
(Note: `_STAGE_FORWARD_TARGET["deliver"]` is `"__end__"`; the router must map that to the `END` sentinel before returning - handle via `return END if target == "__end__" else target`.)

3. Replace graph.py:176:
```
builder.add_conditional_edges(
    "human_review",
    route_after_human_review,
    {
        "parse": "parse", "ground": "ground", "select": "select",
        "execute": "execute", "validate": "validate",
        "reconcile": "reconcile", "deliver": "deliver",
        "conversation": "conversation", END: END,
    },
)
```

4. Gate override on approve: in `human_review_node` return dict, when `paused_stage` set and action=="approve", add `{f"{paused_stage}_gate": _dump(_pass_gate(paused_stage))}`. NOTE: the action is only known AFTER `interrupt()` returns (resume). So compute `action` from the resumed `decisions` before building the return dict, and only include the gate override then.

5. Reject feedback message: when action=="reject", append `HumanMessage(content=decisions.get("feedback","人工驳回，请调整方案"))` to `messages`. Check the `messages` channel reducer in `state.py` first - if it is `add_messages`/append-semantics, return `{"messages":[HumanMessage(...)]}`; if replace-semantics, merge with existing `state.get("messages", [])`. Import `HumanMessage` from `langchain_core.messages`.

**Tests** (`tests/agent/test_unified_graph_replay.py` extension):
- [ ] `test_hitl_approve_forwards_to_next_stage`: select HUMAN -> resume `{"action":"approve"}` -> routes to execute and `select_gate.feedback_route is None`
- [ ] `test_hitl_reject_routes_to_conversation`: select HUMAN -> resume `{"action":"reject","feedback":"换个方案"}` -> routes to conversation and messages contain the feedback
- [ ] `test_hitl_approve_deliver_routes_to_end`: deliver HUMAN -> approve -> END
- [ ] `test_hitl_no_action_routes_to_end`: resume `{}` -> END (fallback)

**Verify:** `python -m pytest tests/agent/test_unified_graph_replay.py -q` (timeout 90s)

---

## Task 4: GET endpoint reads interrupt payload (P0#2)

**Target:** first-interrupt GET returns items from the interrupt payload.

**File:** `backend/app/api/human_review_routes.py` (line 29-44)

**Changes:** `get_human_review` first reads `state.human_review_items`; falls back to `snapshot.tasks[*].interrupts[*].value["human_review_items"]`; also resolves `paused_stage` from state or interrupt payload. Return shape adds `paused_stage`.

**Tests** (`tests/services/test_human_review_routes.py` - new):
- [ ] `test_get_returns_items_from_interrupt_payload`: mock snapshot with interrupts payload -> items + paused_stage returned
- [ ] `test_get_returns_items_from_state_when_present`: state already has human_review_items -> returned from state
- [ ] `test_get_returns_empty_when_no_interrupt`: no interrupt -> empty list

**Verify:** `python -m pytest tests/services/test_human_review_routes.py -q` (timeout 60s)

---

## Task 5: resume_from_interrupt emits completed event (P1#4)

**Target:** after resume, if `deliver_gate==PASS` emit `completed`.

**File:** `backend/app/services/runtime.py` (line 277-290)

**Changes:** between the stream loop end (line 277) and the `# Send resumed SSE event` block (line 278), insert a mirror of the `_execute_planning` completion check:
```
final_state = await cls.aget_state_values(session_id)
if final_state:
    deliver_gate = final_state.get("deliver_gate") or {}
    deliver_route = deliver_gate.get("feedback_route") if isinstance(deliver_gate, dict) else getattr(deliver_gate, "feedback_route", None)
    if final_state.get("phase") == "completed" and deliver_route == "PASS":
        await cls._append_event(session_id, create_completed_event(session_id))
sse_manager.set_execution_active(session_id, False)
```
(ensure `create_completed_event` is already imported in runtime.py - it is used by `_execute_planning`)

**Tests** (`tests/services/test_runtime_sse.py` extension):
- [ ] `test_resume_emits_completed_when_deliver_pass`: mock final_state phase=completed + deliver_gate PASS -> `_append_event` called with completed event
- [ ] `test_resume_no_completed_when_deliver_not_pass`: deliver_gate not PASS -> no completed event

**Verify:** `python -m pytest tests/services/test_runtime_sse.py -q` (timeout 60s)

---

## Task 6: fix as_node reference (P1#5)

**Target:** `post_l3_resume.py` `as_node` becomes a valid node.

**File:** `backend/app/services/post_l3_resume.py` (line 143)

**Changes:** `as_node="gis_agent"` -> `as_node="human_review"`.

**Tests** (`tests/services/test_post_l3_resume.py` extension):
- [ ] `test_resume_writeback_uses_human_review_node`: assert `aupdate_state` called with `as_node == "human_review"`

**Verify:** `python -m pytest tests/services/test_post_l3_resume.py -q` (timeout 60s)

---

## Task 7: document dead ref channels as audit-only (P2#9)

**Target:** add comments noting `*_ref` channels are audit-only.

**Files:**
- `backend/app/agent/plan_state/state.py`: add single-line comment on `grounding_result_ref`/`site_selection_ref`/`parcel_changeset_ref`/`planned_state_ref` declarations: `# audit-only: persisted for traceability, not reloaded by downstream nodes`
- `backend/app/agent/bootstrap/post_l3_main_nodes.py`: add one line to `_persist_artifact` docstring: refs are audit-only side-effects; no loader exists (crash recovery is a Deferred item)

**Verify:** `python -m pytest tests/agent tests/services -q` (timeout 180s, no regression)

---

## Task 8: end-to-end integration test

**Target:** one test covering the full HITL lifecycle.

**File:** `backend/tests/agent/test_unified_graph_replay.py` extension

**Tests:**
- [ ] `test_hitl_full_lifecycle_approve_completes`: select HUMAN -> interrupt -> GET returns items + paused_stage=select -> resume `{"action":"approve"}` -> graph routes execute->validate->reconcile->deliver PASS->END; assert select_gate forced PASS, deliver_gate PASS, phase=completed
- [ ] `test_hitl_full_lifecycle_reject_to_conversation`: select HUMAN -> interrupt -> resume `{"action":"reject","feedback":"换地块"}` -> routes to conversation; assert messages contain feedback

**Verify:**
```
python -m pytest tests/agent/test_unified_graph_replay.py tests/agent/test_post_l3_main_nodes.py tests/services -q
```
(timeout 180s)

---

## Deferred (not this round)

- **Crash-recovery loaders**: implement `_load_*` for the 4 `*_ref` channels (mirroring `_load_planning_program`) so checkpoints can be rebuilt from the artifact store. This round documents them as audit-only.
- **RETRY_L3 auto-re-entry**: currently validate/reconcile `RETRY_L3` routes to human_review (no post-L3->L3 edge). Needs a new edge + L3 re-entry logic if automatic L3 rework is desired.
- **Retry-counter key convergence**: cross-stage retries from validate bump the `validate` key rather than the target stage key. Bounded today but loose.
- **Frontend adaptation**: frontend must handle the new `human_review_paused` SSE event + `paused_stage` field + approve/reject button semantics.

## Verification Commands

All commands use explicit timeout. **NEVER run full `pytest tests` (hangs on MIP/E2E/DB/LLM suites).**
```
# Unit
python -m pytest tests/agent/test_post_l3_main_nodes.py -q           # timeout 60s
python -m pytest tests/agent/test_unified_graph_replay.py -q         # timeout 90s
python -m pytest tests/services/test_human_review_routes.py -q       # timeout 60s
python -m pytest tests/services/test_runtime_sse.py -q               # timeout 60s
python -m pytest tests/services/test_post_l3_resume.py -q            # timeout 60s

# Regression
python -m pytest tests/agent tests/services -q                       # timeout 180s
python -m pytest tests/unit/bootstrap tests/unit/validate tests/unit/parse -q  # timeout 120s

# Import integrity
python -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('app',quiet=1) else 1)"
```

## Risks / Notes

1. **Approve gate override persistence**: the PASS gate written to state is expected to be re-evaluated if that stage runs again - approve only releases this run.
2. **`messages` reducer semantics**: verify `state.py` before appending HumanMessage on reject; if replace-semantics, merge with existing messages.
3. **Conversation re-entry LLM call**: on reject, conversation_node invokes the LLM; the appended feedback message provides context.
4. **New SSE event type `human_review_paused`**: frontend must handle it; alternatively reuse existing `SSEEventType.PAUSE` if preferred.
5. **`_STAGE_FORWARD_TARGET` END sentinel**: `route_after_human_review` must return the LangGraph `END` sentinel (import from `langgraph.graph`), not the string `"__end__"` - map it inside the router.

---

## Execution Status (2026-08-06)

All 8 tasks complete (subagent-driven). Backend bounded regression: 204 targeted tests green
(tests/agent + tests/services + tests/unit/bootstrap + tests/unit/reconcile + tests/unit/validate + tests/unit/parse),
compileall clean, all touched files LF.

- [x] T1 Record paused stage + PASS-gate helper
- [x] T2 human_review_node carries stage + SSE pause event
- [x] T3 route_after_human_review router (approve force-pass forward / reject to conversation)
- [x] T4 GET endpoint reads interrupt payload
- [x] T5 resume_from_interrupt emits completed event
- [x] T6 fix as_node reference (gis_agent -> human_review)
- [x] T7 document dead *_ref channels as audit-only
- [x] T8 end-to-end HITL lifecycle integration tests

### Key implementation notes
- `route_after_human_review` (graph.py:119-131) maps approve -> next stage via `_STAGE_FORWARD_TARGET` (deliver -> END), reject -> "conversation", else END.
- `human_review_node` (graph.py:202-253) records paused_stage, publishes SSE `human_review_paused`, forces the paused gate to PASS on approve, appends a feedback HumanMessage on reject (messages uses add_messages reducer).
- `collect_human_review_items` now returns (stage, items).
- GET /api/human-review/{id} falls back to snapshot.tasks[*].interrupts[*].value for items/paused_stage on first interrupt.
- resume_from_interrupt mirrors _execute_planning's deliver_gate==PASS completed-event check.
- Verified `messages` uses add_messages (append semantics); `paused_stage` added to AgentState + seeded.

---

## Follow-up Fix: Empty-Resume & Circular-Import (2026-08-06)

Two post-review issues fixed in a follow-up pass:

### Part A - Empty resume payload re-fires interrupt (LangGraph 1.2.9)
`Command(resume={})` is treated as a vacuous interrupt-id map (`all(...)` on empty = True) and re-fires the interrupt; the HTTP call returns 200 but the session stays paused. Defense-in-depth:
- [x] runtime.py resume_from_interrupt: normalize empty resume_data to {"action":"no_op"} + warning (covers all 6 callers incl. session_routes upstream HITL)
- [x] human_review_routes.py ResolveRequest: decisions min_length=1 + explicit 422 guard
- [x] test_human_review_routes.py: test_resolve_rejects_empty_decisions (422), test_resolve_accepts_non_empty_decisions (200)
- [x] test_runtime_sse.py: test_resume_empty_dict_normalized_to_no_op (asserts Command.resume == {"action":"no_op"})

### Part B - Circular import (state.py first-import)
Removing the 7 test workaround lines exposed a SECOND latent cycle (conversation_router <-> bootstrap.graph), now also fixed:
- [x] state.py: phase_machine imports moved lazy into create_initial_state / state_to_ui_status; dead _layer_to_phase removed
- [x] graph.py: conversation_router import moved lazy into create_unified_planning_graph (kills the conversation_router cycle too)
- [x] Removed the `import app.agent.bootstrap.graph` workaround from 7 test files
- [x] NEW tests/agent/test_state_import_isolation.py: subprocess import proves state.py imports standalone

### Verification
- `from app.agent.plan_state.state import AgentState, create_initial_state` -> state-first OK
- `import app.main` -> main OK
- test_after_analysis_gate_aware.py -> 5 passed (was collection ERROR)
- Bounded regression: tests/agent + tests/services + tests/unit -> 1420 passed, 1 pre-existing failure (test_planning_chain_e2e, in lastfailed cache, out of scope)
- compileall clean; all touched files LF
