"""Single canonical state factory for production and tests.

All state construction goes through this factory. Test fixtures use the
same factory with different parameters; no separate test-only constructor.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.agent.bootstrap.phase_machine import PlanningPhase
from app.core.settings import BUSINESS_RETRY_LIMIT, RAG_ENABLED


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
        rag_enabled: Optional[bool] = None,
        rag_layer_config: Optional[Dict[int, bool]] = None,
        disable_tools: bool = False,
        uploaded_files: Optional[List[Dict]] = None,
        user_uploaded_gis_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if rag_enabled is None:
            rag_enabled = RAG_ENABLED
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
            "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
            "dimension_key": None,
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
            "uploaded_files": uploaded_files or [],
            "_landuse_metrics": {},
            "intent_targets": {},
            "explore_instructions": {},
            "report_summary_index": {},
            "explore_done": False,
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
            "parse_gate": None,
            "ground_gate": None,
            "select_gate": None,
            "validate_gate": None,
            "reconcile_gate": None,
            "deliver_gate": None,
            "upstream_gates": [],
            "stage_audit": {},
            "retry_counts": {},
            "dimension_retry_counts": {},
            "dimension_retry_limit": max(0, int(os.getenv("DIMENSION_RETRY_LIMIT", "1"))),
            "max_retries": BUSINESS_RETRY_LIMIT,
            "error_feedback": {},
            "human_interrupt": None,
            "human_review_items": [],
            "human_review_decisions": None,
            "human_review_event_id": "",
            "human_review_pause_published": False,
            "human_review_resume_consumed": False,
            "human_deferred_targets": [],
            "human_deferred_select_revision": False,
            "paused_stage": None,
            "fatal_error": None,
        }
