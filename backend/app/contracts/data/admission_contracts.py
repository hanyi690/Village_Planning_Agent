"""Closed contracts for the DATA admission lifecycle."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DataLifecycleState = Literal[
    "DISCOVERED",
    "CLASSIFIED",
    "PARSING",
    "NORMALIZED",
    "REPRESENTATION_BUILT",
    "CAPABILITY_INDEXED",
    "ADMITTED",
    "UNSUPPORTED",
    "INVALID",
    "CRS_UNRESOLVED",
    "ENCODING_UNRESOLVED",
    "GEOMETRY_INVALID",
    "POLICY_REJECTED",
]
DataTerminalState = Literal[
    "UNSUPPORTED",
    "INVALID",
    "CRS_UNRESOLVED",
    "ENCODING_UNRESOLVED",
    "GEOMETRY_INVALID",
    "POLICY_REJECTED",
]


class DataAdmissionRequest(BaseModel):
    """Explicit declaration required before local DATA publication."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    session_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    content: Any | None = None
    normalized_input: Any | None = None
    source_kind: str = ""
    declared_media_type: str = Field(min_length=1)
    declared_encoding: str = "UTF-8"
    declared_crs: str = ""
    adapter_hint: str = Field(min_length=1)
    expected_role: str = Field(min_length=1)
    policy_context: dict[str, Any] = Field(default_factory=dict)
    parent_catalog_ref: Any | None = None


class DataAdmissionReceipt(BaseModel):
    """Immutable evidence of one admission attempt and its terminal state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_ref: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    attempt_ref: str = Field(min_length=1)
    state: DataLifecycleState
    state_at_failure: DataLifecycleState = "ADMITTED"
    reason_code: str = ""
    required_capability: str = ""
    lifecycle: tuple[DataLifecycleState, ...] = ()
    catalog_ref: str = ""
    stage_ref: str = ""
    gate_ref: str = ""
    gate_artifact_ref: str = ""
    gap_ref: str = ""
    observed_metadata: dict[str, Any] = Field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
    recovery_action: str = ""
    retryability: Literal["retryable", "non_retryable"] = "non_retryable"
    owner: str = "data"
    budget_state: dict[str, Any] = Field(default_factory=dict)


class DataAdmissionGap(BaseModel):
    """Immutable recovery record for an admission that cannot proceed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gap_ref: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    attempt_ref: str = Field(min_length=1)
    state_at_failure: DataLifecycleState
    reason_code: str = Field(min_length=1)
    required_capability: str = Field(min_length=1)
    observed_metadata: dict[str, Any] = Field(default_factory=dict)
    input_refs: tuple[str, ...] = ()
    recovery_action: str = Field(min_length=1)
    retryability: Literal["retryable", "non_retryable"]
    owner: str = Field(min_length=1)
    budget_state: dict[str, Any] = Field(default_factory=dict)


class DataAdmissionResult(BaseModel):
    """Typed facade result; publication refs are absent for rejected input."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    receipt: DataAdmissionReceipt
    gap: DataAdmissionGap | None = None
    catalog_ref: Any | None = None
    stage_ref: Any | None = None
    gate_ref: Any | None = None
    receipt_artifact_ref: Any | None = None
    gap_artifact_ref: Any | None = None
    data_run: Any | None = None

    def to_state_patch(self) -> dict[str, Any]:
        """Return only immutable refs for workflow checkpoint publication."""

        run_patch = (
            self.data_run.to_state_patch()
            if self.data_run is not None
            and callable(getattr(self.data_run, "to_state_patch", None))
            else {}
        )
        refs = dict(run_patch.get("artifact_refs") or {})
        for key, value in (
            ("data_admission_receipt", self.receipt_artifact_ref),
            ("data_admission_gap", self.gap_artifact_ref),
        ):
            if value is not None:
                refs[key] = (
                    value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                )
        if refs:
            run_patch["artifact_refs"] = refs
        return run_patch


__all__ = [
    "DataAdmissionGap",
    "DataAdmissionReceipt",
    "DataAdmissionRequest",
    "DataAdmissionResult",
    "DataLifecycleState",
    "DataTerminalState",
]
