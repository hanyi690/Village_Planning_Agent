"""Durable staging record for the EXECUTE atomic commit boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class ExecutionStaging(ContractMeta):
    """CAS-persisted staging snapshot, never a formal PlannedState by itself."""

    schema_version: Literal["1.0"] = "1.0"
    staging_id: str = Field(min_length=1)
    approved_input_ref: str = ""
    execution_plan_ref: str = ""
    staged_parcel_changeset_ref: str = ""
    staged_spatial_changeset_ref: str = ""
    staged_planned_entity_set_ref: str = ""
    staged_planned_representation_set_ref: str = ""
    staged_execution_trace_ref: str = ""
    staged_delivery_spatial_snapshot_ref: str = ""
    staged_planned_state_ref: str = ""
    staged_layout_configs_ref: str = ""
    # Generic DATA is the default.  Legacy BSM staging must be an explicit
    # caller decision so omitted fields cannot silently reintroduce parcel
    # prerequisites.
    compatibility_mode: Literal["legacy_bsm", "generic_data", "not_applicable"] = "not_applicable"
    worker_task_ids: list[str] = Field(default_factory=list)
    failed_task_ids: list[str] = Field(default_factory=list)
    status: Literal["staged", "committed", "aborted"] = "staged"
    commit_id: str = ""
    diagnostics: list[str] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def canonicalize_and_fingerprint(self) -> "ExecutionStaging":
        self.worker_task_ids = sorted({item for item in self.worker_task_ids if item})
        self.failed_task_ids = sorted({item for item in self.failed_task_ids if item})
        self.diagnostics = sorted({item for item in self.diagnostics if item})
        if self.status in {"staged", "aborted"} and self.commit_id:
            raise ValueError(f"{self.status} staging cannot have commit_id")
        if self.status == "committed" and not self.commit_id:
            raise ValueError("committed staging requires commit_id")
        if self.status == "committed":
            required_refs = {
                "approved_input_ref": self.approved_input_ref,
                "execution_plan_ref": self.execution_plan_ref,
                "staged_planned_state_ref": self.staged_planned_state_ref,
                "staged_layout_configs_ref": self.staged_layout_configs_ref,
                "staged_delivery_spatial_snapshot_ref": (
                    self.staged_delivery_spatial_snapshot_ref
                ),
            }
            if self.staged_spatial_changeset_ref:
                required_refs["staged_spatial_changeset_ref"] = self.staged_spatial_changeset_ref
                required_refs["staged_planned_entity_set_ref"] = self.staged_planned_entity_set_ref
                required_refs["staged_planned_representation_set_ref"] = self.staged_planned_representation_set_ref
                required_refs["staged_execution_trace_ref"] = self.staged_execution_trace_ref
            if self.compatibility_mode == "legacy_bsm":
                required_refs["staged_parcel_changeset_ref"] = self.staged_parcel_changeset_ref
            missing = [name for name, value in required_refs.items() if not value]
            if missing:
                raise ValueError(
                    "committed staging requires " + ", ".join(missing)
                )
        if not self.fingerprint:
            payload = self.model_dump(mode="json", exclude={"fingerprint", "created_at"})
            self.fingerprint = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return self


__all__ = ["ExecutionStaging"]
