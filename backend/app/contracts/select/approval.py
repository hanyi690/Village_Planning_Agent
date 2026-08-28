"""Approval-bound inputs that are safe to hand to EXECUTE."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ApprovedExecutionInput(ContractMeta):
    """Immutable binding between an approved scenario and EXECUTE inputs.

    Diagnostic or incomplete scenarios never produce this contract.  A value
    is therefore always an explicit executable approval.
    """

    schema_version: Literal["1.0"] = "1.0"
    approval_id: str = Field(min_length=1)
    scenario_set_ref: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    scenario_ref: str = Field(min_length=1)
    scenario_fingerprint: str = Field(min_length=1)
    problem_fingerprint: str = Field(min_length=1)
    baseline_ref: str = ""
    planning_program_ref: str = ""
    grounding_problem_ref: str = ""
    execution_plan_digest: str = ""
    target_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    context_ref: dict[str, str] = Field(default_factory=dict)
    bundle_snapshot_digest: str = ""
    approval_status: Literal["auto", "human_approved"]
    approved_by: str = ""
    approval_revision: int = Field(default=1, ge=1)
    approval_reason: str = ""
    approved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fingerprint: str = ""

    @property
    def can_execute(self) -> bool:
        return self.approval_status in {"auto", "human_approved"}

    def assert_matches(
        self,
        scenario_set: Any,
        scenario: Any,
        *,
        scenario_set_ref: str = "",
        context_version: str = "",
        bundle_snapshot_digest: str = "",
    ) -> None:
        """Reject stale or substituted planning inputs at the EXECUTE edge."""
        from app.contracts.select.scenario import resolve_formal_scenario_member

        scenario_set, scenario = resolve_formal_scenario_member(
            scenario_set,
            scenario,
        )
        set_id = str(getattr(scenario_set, "set_id", "") or "")
        if self.scenario_set_ref not in {set_id, str(scenario_set_ref or "")}:
            raise ValueError("approved input references a different ScenarioSet")
        if str(getattr(scenario_set, "problem_fingerprint", "") or "") != self.problem_fingerprint:
            raise ValueError("approved input problem fingerprint is stale")
        if str(getattr(scenario, "scenario_id", "") or "") != self.scenario_id:
            raise ValueError("approved input scenario id is stale")
        if str(getattr(scenario, "fingerprint", "") or "") != self.scenario_fingerprint:
            raise ValueError("approved input scenario fingerprint is stale")
        if str(getattr(scenario, "status", "") or "") != "complete":
            raise ValueError("approved input scenario is not complete")
        feasible_ids = {
            str(item)
            for item in list(getattr(scenario_set, "feasible_scenario_ids", None) or [])
        }
        if self.scenario_id not in feasible_ids:
            raise ValueError("approved input scenario is not formally feasible")
        certificate = getattr(scenario_set, "solver_certificate", None)
        if certificate is None or str(getattr(certificate, "status", "") or "") != "feasible":
            raise ValueError("approved input ScenarioSet has no feasible solver proof")
        if (
            not str(getattr(certificate, "backend_id", "") or "").strip()
            or not str(getattr(certificate, "backend_version", "") or "").strip()
            or getattr(certificate, "backend_certificate", None) is None
        ):
            raise ValueError("approved input ScenarioSet has no typed backend proof")
        recommended_id = str(
            getattr(scenario_set, "recommended_scenario_id", "") or ""
        )
        if self.approval_status == "auto" and self.scenario_id != recommended_id:
            raise ValueError("auto approval must select the recommended scenario")
        if (
            self.approval_status == "human_approved"
            and self.scenario_id != recommended_id
            and not self.approval_reason.strip()
        ):
            raise ValueError("human selection outside recommendation requires a reason")
        if context_version and str(self.context_ref.get("version", "")) not in {"", str(context_version)}:
            raise ValueError("approved input context version is stale")
        if bundle_snapshot_digest and self.bundle_snapshot_digest not in {"", str(bundle_snapshot_digest)}:
            raise ValueError("approved input bundle snapshot is stale")

    def assert_execution_plan_matches(self, plan: Any) -> None:
        """Verify immutable plan content and approval/scenario bindings."""
        from app.modules.execute.plan_digest import execution_plan_semantic_digest

        if plan is None:
            raise ValueError("approved input execution plan is missing")
        if not self.execution_plan_digest:
            raise ValueError("approved input execution plan digest is missing")
        if execution_plan_semantic_digest(plan) != self.execution_plan_digest:
            raise ValueError("approved input execution plan digest is stale")
        if str(getattr(plan, "approved_input_fingerprint", "") or "") != self.fingerprint:
            raise ValueError("execution plan approval fingerprint is stale")
        if str(getattr(plan, "scenario_id", "") or "") != self.scenario_id:
            raise ValueError("execution plan scenario id is stale")

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "ApprovedExecutionInput":
        self.target_ids = sorted({item for item in self.target_ids if item})
        self.candidate_ids = sorted({item for item in self.candidate_ids if item})
        self.context_ref = {
            str(key): str(value)
            for key, value in sorted(self.context_ref.items(), key=lambda item: str(item[0]))
            if str(value)
        }
        if self.approval_status == "human_approved" and not self.approved_by.strip():
            raise ValueError("human_approved input requires approved_by")
        if self.can_execute and not self.execution_plan_digest.strip():
            raise ValueError("executable approval requires execution_plan_digest")
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at", "approved_at"})
            self.fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return self


__all__ = ["ApprovedExecutionInput"]
