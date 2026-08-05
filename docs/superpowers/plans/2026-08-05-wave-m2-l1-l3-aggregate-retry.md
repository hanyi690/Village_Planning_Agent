# Wave M2 Implementation Plan: L1/L2/L3 Aggregate Wiring + Gate Retry + Legacy Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Wire L1/L2/L3 aggregates as post-layer-completion nodes (separate from completion_check to respect interrupt invariant). Expand post-L3 chain gate routing to full retry loops for all 6 gates. Migrate parse_agent.py helpers to proper modules and delete the legacy file (826 lines). Horizontalize explore_node into a gate-driven service. Produce Graphify dependency graph for review package.

**Architecture:** A new `layer_aggregate` node is added between `layer_completion_check` and `after_analysis`. When a layer completes, `completion_check` sets `layer_just_completed` flag. The `layer_aggregate` node reads the flag, calls the corresponding `l1_aggregate`/`l2_aggregate`/`l3_aggregate`, writes `{ref, gate_decision, review_id}` to state. `after_analysis` then reads the gate decision: PASS -> advance phase; EXPLORE -> dispatch evidence retrieval + rework; L1/L2/L3 -> re-dispatch dimension workers; HUMAN -> END. Post-L3 chain: expand the 6 binary `_route_after_*` functions to route-specific targets with retry-count caps (max 3 -> HUMAN). parse_agent.py migration: `_extract_instruction_tables` -> `parsing/tables.py`; `parse`/`parse_async`/`ParseResult` -> `parsing/text_parser.py`; `resolve_spatial_anchors` -> already delegated to `spatial_ops/resolver.py`; binding helpers -> `kg/enrichment` (already forwarded). Delete `parse_agent.py` + `prompts.py` + legacy `explore_node`. Re-run graphify via subagent skill.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, pytest. Tests run from `backend/`.

## Global Constraints
- LF line endings, 4-space indent, double quotes, no trailing whitespace
- Tests run from `backend/` (`python -m pytest tests/unit/ -q`)
- Do NOT commit pre-existing uncommitted files under `docs/`
- Additive contracts: do NOT delete existing fields
- Keep `bootstrap/graph.py` 6-node topology unchanged (only internal wiring changes)
- Conservative State: add new fields, deprecate old
- Branch: `refactor/phase1-planning-context` (continuing after Wave M1)

---

### Task 1: layer_aggregate node + graph wiring

**Files:**
- Create: `backend/app/agent/bootstrap/layer_aggregate_node.py`
- Create: `backend/tests/unit/bootstrap/test_layer_aggregate_node.py`
- Modify: `backend/app/agent/plan_state/completion_node.py` (set `layer_just_completed` flag)
- Modify: `backend/app/agent/plan_state/state.py` (add `layer_just_completed: Optional[int]` field)
- Modify: `backend/app/agent/bootstrap/graph.py` (add node, rewire edges)

**Interfaces:**
- `async def layer_aggregate_node(state: dict) -> dict` - reads `layer_just_completed` (1/2/3); calls `l1_aggregate`/`l2_aggregate`/`l3_aggregate`; returns `{*_ref, *_gate_decision, *_review_id, layer_just_completed: None}` (clears flag)
- `completion_node.py`: on layer completion detection (after interrupt, before SSE), set `layer_just_completed: layer`
- `graph.py`: add `layer_aggregate` node; wire `layer_completion_check -> layer_aggregate` (replace direct `layer_completion_check -> after_analysis`)

- [ ] **Step 1: Write failing test** - layer_aggregate_node calls l1_aggregate when layer_just_completed=1; clears flag; returns ref+gate+review
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** node + state field + completion_node flag + graph wiring
- [ ] **Step 4: Run test to verify it passes** + graph compiles
- [ ] **Step 5: Commit**: `feat(wave-m2): layer_aggregate node wires L1/L2/L3 aggregates`

---

### Task 2: Gate-aware after_analysis router

**Files:**
- Modify: `backend/app/agent/conversation_router/edges.py`
- Create: `backend/tests/unit/test_after_analysis_gate_aware.py`

**Interfaces:**
- When `layer_just_completed` was set (now cleared by aggregate node, but gate decision is on state):
  - Gate PASS -> existing phase advance logic
  - Gate EXPLORE -> return `"explore"` (triggers evidence retrieval)
  - Gate L1/L2/L3 (rework) -> `Send("analyze_dimension", {**state, "is_revision": True, ...})` for rework dimensions
  - Gate HUMAN -> END
- When no gate decision (pre-completion): existing dimension dispatch logic

- [ ] **Step 1: Write failing test** - gate PASS -> advance; gate EXPLORE -> "explore"; gate L1 -> Send rework; gate HUMAN -> END
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** gate-aware routing in after_analysis
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m2): gate-aware after_analysis router (EXPLORE/L1/L2/L3/HUMAN)`

---

### Task 3: EXPLORE dispatch from gates

**Files:**
- Modify: `backend/app/agent/explore/service.py` (add `retrieve_evidence_for_gate`)
- Modify: `backend/app/agent/bootstrap/layer_aggregate_node.py` or `after_analysis` (call evidence service on EXPLORE)
- Create: `backend/tests/unit/bootstrap/test_gate_explore_dispatch.py`

**Interfaces:**
- `retrieve_evidence_for_gate(gate_decision, session_id, village_name) -> ExplorationResult` - translates `PendingRequest` items to `ExplorationRequest`
- When gate returns EXPLORE: call evidence service, inject result into state, re-dispatch dimension workers

- [ ] **Step 1: Write failing test** - gate EXPLORE triggers retrieve_evidence_for_gate
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** evidence-for-gate service + wiring
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m2): EXPLORE dispatch from L1/L2/L3 gates`

---

### Task 4: PostL3ChainState retry fields

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_state.py`
- Create: `backend/tests/unit/bootstrap/test_post_l3_state_retry_fields.py`

**Interfaces:**
- Add: `retry_counts: Dict[str, int]` (keyed by stage name)
- Add: `max_retries: int = 3`
- Add: `explore_cache: Dict[str, Any]` (cache evidence results across retries)
- Add: `human_review_items: List[Dict[str, Any]]` (accumulated HUMAN items)

- [ ] **Step 1: Write failing test** - retry_counts defaults to {}; max_retries=3; explore_cache={}
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** state fields
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m2): PostL3ChainState retry fields (retry_counts, max_retries, explore_cache)`

---

### Task 5: Post-L3 chain retry loops (6 gates)

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_chain.py`
- Modify: `backend/app/agent/bootstrap/post_l3_nodes.py` (add retry-aware gate helpers)
- Create: `backend/tests/unit/bootstrap/test_post_l3_chain_retry.py`

**Interfaces:**
- Expand all 6 `_route_after_*` functions to return route-specific targets:
  - `_route_after_parse`: PASS->"ground", REPAIR->"parse" (retry), REVISE->"parse" (retry), HUMAN->"human_end"
  - `_route_after_ground`: PASS->"select", EXPLORE->"ground" (retry with evidence), HUMAN->"human_end"
  - `_route_after_select`: PASS->"execute", RETRY_GROUND->"ground" (retry), HUMAN->"human_end"
  - `_route_after_validate`: PASS->"reconcile", RETRY_EXECUTE->"execute" (retry), RETRY_SELECT->"select" (retry), RETRY_GROUND->"ground", RETRY_L3->"end" (can't loop back to L3 in chain), RETRY_PARSE->"parse", HUMAN->"human_end"
  - `_route_after_reconcile`: PASS->"deliver", RETRY_L3->"end", RETRY_EXECUTE->"execute" (retry), HUMAN->"human_end"
  - `_route_after_deliver`: PASS->"end", RETRY_VALIDATE->"validate" (retry), HUMAN->"human_end"
- Each retry checks `retry_counts[stage] >= max_retries -> "human_end"`; otherwise increments counter
- Update `add_conditional_edges` mapping dicts with all route targets

- [ ] **Step 1: Write failing test** - parse REPAIR retries up to max then HUMAN; validate RETRY_EXECUTE loops back to execute; deliver RETRY_VALIDATE loops to validate
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** retry routing
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m2): post-L3 chain retry loops (6 gates, max 3 -> HUMAN)`

---

### Task 6: HUMAN route interrupt handling

**Files:**
- Modify: `backend/app/agent/bootstrap/post_l3_nodes.py` (add `_handle_human_route` helper)
- Modify: `backend/app/agent/bootstrap/post_l3_chain.py` (add `human_review` node)
- Create: `backend/tests/unit/bootstrap/test_human_route_interrupt.py`

**Interfaces:**
- `_handle_human_route(state, stage, gate)`: populates `human_review_items` from gate.pending_requests, logs
- `human_review` node: writes items to state, returns `{"human_review_items": [...]}`

- [ ] **Step 1: Write failing test** - HUMAN route populates human_review_items
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** human_review node + handler
- [ ] **Step 4: Run test to verify it passes**
- [ ] **Step 5: Commit**: `feat(wave-m2): HUMAN route interrupt handling (human_review_items)`

---

### Task 7: Migrate parse_agent.py helpers

**Files:**
- Modify: `backend/app/modules/parsing/tables.py` (add `extract_instruction_tables`)
- Create: `backend/app/modules/parsing/text_parser.py` (move `parse`, `parse_async`, `ParseResult`)
- Modify: `backend/app/modules/spatial_ops/resolver.py` (add `resolve_spatial_anchors` thin wrapper)
- Modify: `backend/app/agent/explore/agent.py` (update import)
- Modify: `backend/app/agent/execute/vocab_extractor.py` (update import)
- Modify: `backend/app/api/gis_test_routes.py` (update import)
- Modify: `backend/app/agent/select/__init__.py` (update re-exports)
- Create: `backend/tests/unit/parsing/test_text_parser.py`
- Create: `backend/tests/unit/parsing/test_extract_instruction_tables_migrated.py`

**Interfaces:**
- `parsing/tables.py`: `extract_instruction_tables(text) -> dict` (public; was `_extract_instruction_tables`)
- `parsing/text_parser.py`: `parse(planning_text, village_name) -> ParseResult`, `parse_async(...)`, `ParseResult` dataclass
- `spatial_ops/resolver.py`: `resolve_spatial_anchors(intent, village_name, village_anchors) -> ...` (thin gazetteer-loading wrapper)

- [ ] **Step 1: Write failing test** - migrated functions work at new locations
- [ ] **Step 2: Run test to verify it fails**
- [ ] **Step 3: Implement** migration + import updates
- [ ] **Step 4: Run test to verify it passes** + all callers work
- [ ] **Step 5: Commit**: `refactor(wave-m2): migrate parse_agent helpers to parsing/text_parser + tables + resolver`

---

### Task 8: Delete legacy files

**Files:**
- Delete: `backend/app/agent/select/parse_agent.py` (826 lines)
- Delete: `backend/app/agent/select/prompts.py` (111 lines)
- Delete: `backend/app/agent/explore/node.py` (214 lines, legacy post-L3 bridge)
- Modify: `backend/app/agent/select/__init__.py` (remove parse_agent re-exports)
- Modify: `backend/app/agent/bootstrap/graph.py` (remove `explore` node + `explore -> gis_agent` edge)
- Modify: `backend/app/agent/conversation_router/edges.py` (remove `phase == "completed"` EXPLORE bridge trigger)
- Delete: `backend/tests/integration/test_parse_agent_llm.py` (skipped, references non-existent symbols)
- Update: `backend/tests/unit/test_parse_instruction.py`, `test_parse_table_extraction.py`, `test_parse_extract_bindings.py`, `test_gis_output_contract.py` (update imports to new locations)

- [ ] **Step 1: Verify all imports migrated** - grep for `parse_agent` in app/ should return 0
- [ ] **Step 2: Delete files** + update graph.py + edges.py
- [ ] **Step 3: Update test imports**
- [ ] **Step 4: Run full suite** - verify 0 regressions
- [ ] **Step 5: Commit**: `refactor(wave-m2): delete legacy parse_agent + prompts + explore_node (~1150 lines)`

---

### Task 9: Graphify dependency graph

**Files:**
- Run graphify subagent over `backend/app/`
- Embed `graphify-out/graph.json` + `GRAPH_REPORT.md` into Wave M2 review package `trace_json`
- Create: `backend/tests/unit/test_graphify_artifact.py` (verify graph artifact exists + valid JSON)

- [ ] **Step 1: Run graphify** via subagent skill over post-M2 `backend/app/`
- [ ] **Step 2: Verify** `graphify-out/graph.json` is valid JSON with nodes + edges
- [ ] **Step 3: Write test** verifying artifact
- [ ] **Step 4: Commit**: `docs(wave-m2): graphify dependency graph artifact`

---

### Task 10: Guardrails + full verification

**Files:**
- Modify: `backend/tests/unit/bootstrap/test_no_advisory_crosswalks.py` (verify new layer_aggregate_node)
- Verify: `test_architecture_invariants.py` ALL 8 pass
- Verify: `test_no_advisory_crosswalk_imports.py` violation budget stays 0
- Verify: full suite 0 failures, 0 regressions

- [ ] **Step 1: Update guardrail** if needed
- [ ] **Step 2: Run full suite** - verify 0 failures
- [ ] **Step 3: Commit**: `test(wave-m2): guardrails + full verification`

---

### Task 11: Docs sync (uncommitted)

**Files:**
- Modify: `docs/design/10_IMPLEMENTATION_STATUS.md` (update post-L3 chain row, import boundary, remove legacy parse_agent/explore_node references)
- Modify: `docs/weekly-reports/2026-08-04-wave-roadmap.md` (add Wave M2 delivery note)

- [ ] **Step 1: Update docs**
- [ ] **Step 2: Verify git status** - docs uncommitted
- [ ] **No commit** (docs rule)

---

## Verification
- L1/L2/L3 aggregates wired as post-layer-completion nodes
- Gate decisions drive after_analysis routing (EXPLORE/L1/L2/L3/HUMAN)
- Post-L3 chain has retry loops for all 6 gates (max 3 -> HUMAN)
- parse_agent.py (826) + prompts.py (111) + explore/node.py (214) = ~1150 lines deleted
- Graphify dependency graph artifact produced
- Full suite: 0 failures, 0 regressions
- Guardrails: `app/agent/bootstrap/` + `app/modules/parsing/` zero advisory_crosswalks

## Out of scope (deferred)
- Deleting legacy `gis_*` AgentState fields (conservative: deprecated, not deleted)
- Replacing `analyze_dimension` monolith with layer-specific workers
- Fine-grained VALIDATE retry to specific node back-edges (M2 uses coarse "retry stage" approach)
- Cross-stage evidence cache invalidation
- Consolidating revision cascade fields into `human_review` substructure
