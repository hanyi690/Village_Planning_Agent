# P2-5: Single StateFactory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge to a SINGLE state constructor. Both production and tests call the same `StateFactory`. Test differences are expressed via parameters or fixture overlays, not separate constructors. Eliminate `PlanningRuntimeService.build_initial_state()` entirely.

**Architecture:** Create a `StateFactory` class with three layers: (1) schema defaults (all fields seeded), (2) runtime config overlay (province, rag_layer_config, streaming), (3) test fixture presets. Both `start_session` and test fixtures call `StateFactory.create(...)`. Delete `build_initial_state`.

**Tech Stack:** Python, LangGraph, pytest

## Global Constraints

- Backend tests from `backend/` directory
- 4-space indent, double quotes
- LF line endings
- Commit only when explicitly asked, at task boundaries

---

### Task 1: Write acceptance tests for unified factory

**Files:**
- Create: `backend/tests/services/test_state_factory.py`

- [ ] **Step 1: Write tests**

```python
"""Acceptance: single StateFactory for production and tests."""
import pytest
from app.agent.plan_state.state_factory import StateFactory


def test_factory_seeds_all_post_l3_fields():
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
    )
    required = [
        "specs", "parse_gate", "ground_gate", "select_gate",
        "validate_gate", "reconcile_gate", "deliver_gate",
        "artifact_refs", "context_version", "context_ref", "context_fingerprint",
        "bootstrap_context_done", "human_review_items", "paused_stage",
        "retry_counts", "max_retries", "error_feedback", "pending_requests",
    ]
    missing = [f for f in required if f not in state]
    assert not missing, f"Missing fields: {missing}"


def test_factory_seeds_production_extras():
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
        province="GD", rag_layer_config={1: True, 2: False, 3: True},
    )
    assert state["config"]["province"] == "GD"
    assert state["config"]["rag_layer_config"] == {1: True, 2: False, 3: True}
    assert "reports" in state
    assert "_streaming_enabled" in state


def test_factory_mutable_defaults_not_shared():
    s1 = StateFactory.create(session_id="s1", project_name="p", village_data="{}",
                              task_description="t", constraints="c")
    s2 = StateFactory.create(session_id="s2", project_name="p", village_data="{}",
                              task_description="t", constraints="c")
    s1["artifact_refs"]["test"] = "x"
    assert "test" not in s2["artifact_refs"], "Mutable defaults must not be shared"


def test_factory_config_no_duplicate_facts():
    """config should not duplicate top-level fact fields."""
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
    )
    # context_version is a top-level field, not in config
    assert "context_version" not in state["config"]
```

- [ ] **Step 2: Run to verify fail**

Run: `cd backend && python -m pytest tests/services/test_state_factory.py -v`
Expected: FAIL - `StateFactory` doesn't exist

- [ ] **Step 3: Commit failing test**

```bash
git add backend/tests/services/test_state_factory.py
git commit -m "test: add StateFactory acceptance tests"
```

---

### Task 2: Create StateFactory and delete build_initial_state

**Files:**
- Create: `backend/app/agent/plan_state/state_factory.py`
- Modify: `backend/app/services/runtime.py` (replace build_initial_state calls with StateFactory.create)
- Modify: `backend/app/agent/plan_state/state.py` (have create_initial_state delegate to StateFactory)
- Modify: all call sites of `build_initial_state`

- [ ] **Step 1: Create StateFactory**

Create `backend/app/agent/plan_state/state_factory.py`:

```python
"""Single canonical state factory for production and tests.

All state construction goes through this factory. Test fixtures use the
same factory with different parameters; no separate test-only constructor.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.bootstrap.phase_machine import PlanningPhase
from app.core.settings import BUSINESS_RETRY_LIMIT


class StateFactory:
    @staticmethod
    def create(
        session_id: str,
        project_name: str,
        village_data: str,
        task_description: str = "制定村庄总体规划方案",
        constraints: str = "无特殊约束",
        image_ids: Optional[List[str]] = None,
        village_name: str = "",
        province: str = "",
        city: str = "",
        county: str = "",
        township: str = "",
        planning_period: str = "2022-2035年",
        enable_review: bool = False,
        stream_mode: bool = True,
        step_mode: bool = False,
        rag_enabled: bool = True,
        rag_layer_config: Optional[Dict[int, bool]] = None,
        disable_tools: bool = False,
        uploaded_files: Optional[List[Dict]] = None,
        user_uploaded_gis_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if rag_layer_config is None:
            rag_layer_config = {1: rag_enabled, 2: False, 3: rag_enabled}
        else:
            for layer in [1, 2, 3]:
                if layer not in rag_layer_config:
                    rag_layer_config[layer] = rag_enabled

        return {
            "session_id": session_id,
            "project_name": project_name,
            "messages": [],
            "phase": PlanningPhase.INIT.value,
            "current_wave": 1,
            "config": {
                "village_data": village_data,
                "village_name": village_name or project_name,
                "province": province,
                "city": city,
                "county": county,
                "township": township,
                "planning_period": planning_period,
                "task_description": task_description,
                "constraints": constraints,
                "rag_enabled": rag_enabled,
                "rag_layer_config": rag_layer_config,
                "knowledge_cache": {},
            },
            "image_ids": image_ids or [],
            "uploaded_files": uploaded_files or [],
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "reports": {"layer1": {}, "layer2": {}, "layer3": {}},
            "dimension_summaries": {},
            "sse_events": [],
            "feedback": None,
            "step_mode": step_mode,
            "previous_layer": 0,
            "metadata": {"published_layers": [], "version": 0, "last_signal_timestamp": None},
            "need_revision": False,
            "revision_target_dimensions": [],
            "human_feedback": "",
            "is_revision": False,
            "revision_impact_tree": None,
            "revision_completed_dims": {},
            "revision_feedback": None,
            "last_revised_dimensions": [],
            "pending_reports": [],
            "layer_char_counts": {},
            "user_uploaded_data": user_uploaded_gis_data or {},
            "user_uploaded_data": user_uploaded_gis_data or {},
            "_landuse_metrics": {},
            "intent_targets": {},
            "explore_instructions": {},
            "report_summary_index": {},
            "gis_analysis_results": {},
            "_streaming_enabled": stream_mode,
            # Context + artifact refs
            "pending_requests": [],
            "context_version": "",
            "context_ref": {"session_id": session_id, "version": ""},
            "context_fingerprint": "",
            "bootstrap_context_done": False,
            "artifact_refs": {},
            "layer_just_completed": None,
            "l1_gate_decision": None,
            "l2_gate_decision": None,
            "l3_gate_decision": None,
            "l1_snapshot_ref": None,
            "l2_strategy_ref": None,
            # post-L3 HITL
            "post_l3_pending_review": [],
            "post_l3_thread_id": "",
            "post_l3_status": "",
            "post_l3_decisions": None,
            # post-L3 chain
            "specs": [],
            "parse_gate": None,
            "ground_gate": None,
            "land_design_briefs": [],
            "select_gate": None,
            "execution_errors": [],
            "layout_configs": [],
            "validate_gate": None,
            "reconcile_gate": None,
            "deliver_gate": None,
            "export_result": None,
            "upstream_gates": [],
            "retry_counts": {},
            "max_retries": BUSINESS_RETRY_LIMIT,
            "error_feedback": {},
            "human_review_items": [],
            "human_review_decisions": None,
            "human_review_event_id": "",
            "human_review_pause_published": False,
            "paused_stage": None,
        }
```

- [ ] **Step 2: Update create_initial_state to delegate**

In `backend/app/agent/plan_state/state.py:261`, replace the function body:

```python
def create_initial_state(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    image_ids: Optional[List[str]] = None,
    village_name: str = "",
) -> Dict[str, Any]:
    """Create initial state (delegates to StateFactory)."""
    from app.agent.plan_state.state_factory import StateFactory
    return StateFactory.create(
        session_id=session_id,
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints,
        image_ids=image_ids,
        village_name=village_name,
    )
```

- [ ] **Step 3: Update runtime.py to use StateFactory, delete build_initial_state**

In `backend/app/services/runtime.py`, replace all `build_initial_state(...)` calls with `StateFactory.create(...)` and delete the `build_initial_state` method.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/services/test_state_factory.py tests/ -v --tb=short -x`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/plan_state/state_factory.py backend/app/agent/plan_state/state.py backend/app/services/runtime.py
git commit -m "refactor: single StateFactory, delete build_initial_state"
```
