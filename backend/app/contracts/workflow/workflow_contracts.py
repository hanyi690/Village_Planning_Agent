"""Workflow control contracts — run requests, routing, gates, and feedback."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta


class StageId(str, Enum):
    BOOTSTRAP = "bootstrap"
    ROUTER = "router"
    L1 = "l1"
    EXPLORE = "explore"
    L2 = "l2"
    L3 = "l3"
    TARGET_PROJECTION = "target_projection"
    GROUND = "ground"
    SELECT = "select"
    EXECUTE = "execute"
    VALIDATE = "validate"
    RECONCILE = "reconcile"
    DELIVER = "deliver"


class PlanningRunRequest(BaseModel):
    run_id: str
    village_name: str
    user_request: str
    inputs: dict = {}
    config: dict = {}


class FeedbackRoute(BaseModel):
    source_stage: str
    target_stage: str
    issue_type: str
    reason: str = ""


class PendingRequest(BaseModel):
    request_id: str
    stage: str
    request_type: str
    context: dict = {}
    created_at: str = ""


class GateDecision(ContractMeta):
    stage: str
    passed: bool
    feedback_route: str | None = None
    pending_requests: list[PendingRequest] = []
    evidence_requests: list[str] = []
    context_version: str = ""
    input_artifact_refs: dict = Field(default_factory=dict)
    input_checksum: str = ""
    output_checksum: str = ""
    issue_fingerprint: str = ""
    previous_issue_fingerprint: str = ""
    progress_made: bool | None = None
    inputs_changed: bool | None = None
    route_reason: str = ""


class RoutingDecision(BaseModel):
    target_stage: str
    reason: str = ""
    payload_refs: list[str] = []


__all__ = [
    "StageId",
    "PlanningRunRequest",
    "FeedbackRoute",
    "PendingRequest",
    "GateDecision",
    "RoutingDecision",
]
