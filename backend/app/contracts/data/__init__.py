"""Data-owned source, representation and capability contracts."""

from .source_contracts import (
    DataCapability,
    DataResourceCatalogSnapshot,
    SpatialRepresentation,
    SourceAdmissionDecision,
    SourceDataset,
    SourceFeature,
    source_local_cognition_ref,
)
from .admission_contracts import (
    DataAdmissionGap,
    DataAdmissionReceipt,
    DataAdmissionRequest,
    DataAdmissionResult,
    DataLifecycleState,
    DataTerminalState,
)
from .dlq import DlqCategory, DlqEntry, DlqReport
from .stage_contracts import DataGapRecord, DataStageSnapshot
from .temporal_role_contracts import (
    SourceTemporalRoleDecision,
    TemporalRoleInputRow,
    TemporalRoleProposal,
    TemporalRoleProposalBatch,
)

__all__ = [
    "DataAdmissionGap",
    "DataAdmissionReceipt",
    "DataAdmissionRequest",
    "DataAdmissionResult",
    "DataLifecycleState",
    "DataTerminalState",
    "SourceDataset",
    "SourceFeature",
    "SpatialRepresentation",
    "DataCapability",
    "SourceAdmissionDecision",
    "DataResourceCatalogSnapshot",
    "DlqCategory",
    "DlqEntry",
    "DlqReport",
    "DataStageSnapshot",
    "DataGapRecord",
    "source_local_cognition_ref",
    "SourceTemporalRoleDecision",
    "TemporalRoleInputRow",
    "TemporalRoleProposal",
    "TemporalRoleProposalBatch",
]
