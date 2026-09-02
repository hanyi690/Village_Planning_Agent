"""Data-owned source, representation and capability contracts."""

from .source_contracts import (
    DataCapability,
    DataResourceCatalogIndexSnapshot,
    DataResourceCatalogSnapshot,
    SpatialRepresentation,
    SourceAdmissionDecision,
    SourceDataset,
    SourceFeature,
    source_local_cognition_ref,
)
from .boundary_contracts import BoundaryScopeArtifact, BoundaryScopeMode
from .provider_acquisition_contracts import (
    ProviderName,
    ProviderAcquisitionPlan,
    build_provider_acquisition_plan,
)
from .product_contracts import (
    CapabilityIndexArtifact,
    NormalizedFeatureSnapshot,
    NormalizedResourceArtifact,
    RepresentationSnapshotArtifact,
    SourceFeatureSnapshot,
    SourceSnapshotArtifact,
    compose_catalog,
    normalized_product,
    source_product,
)
from .admission_contracts import (
    DataAdmissionGap,
    DataAdmissionReceipt,
    DataAdmissionRequest,
    DataAdmissionResult,
    DataLifecycleState,
    DataTerminalState,
)
from .remote_admission_contracts import (
    RemoteAdmissionLimits,
    RemoteSourceAdmissionReceipt,
    RemoteSourceAdmissionRequest,
    RemoteSourceKind,
)
from .provider_run_contracts import ProviderRunLease, ProviderRunRecovery
from .production_acceptance_contracts import (
    DataDisasterRecoveryCheck,
    DataProductionAcceptancePolicy,
    DataProductionAcceptanceReport,
    DataSecurityScanResult,
    DataSLOMeasurement,
)
from .invalidation_contracts import DataChangeSet, DataDependencyGraph, DataDependencyNode
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
    "RemoteAdmissionLimits",
    "RemoteSourceAdmissionReceipt",
    "RemoteSourceAdmissionRequest",
    "RemoteSourceKind",
    "ProviderRunLease",
    "ProviderRunRecovery",
    "DataDependencyGraph",
    "DataDependencyNode",
    "DataChangeSet",
    "SourceDataset",
    "SourceFeature",
    "SpatialRepresentation",
    "DataCapability",
    "SourceAdmissionDecision",
    "DataResourceCatalogSnapshot",
    "DataResourceCatalogIndexSnapshot",
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
    "BoundaryScopeArtifact",
    "BoundaryScopeMode",
    "ProviderName",
    "ProviderAcquisitionPlan",
    "build_provider_acquisition_plan",
    "CapabilityIndexArtifact",
    "NormalizedFeatureSnapshot",
    "NormalizedResourceArtifact",
    "RepresentationSnapshotArtifact",
    "SourceFeatureSnapshot",
    "SourceSnapshotArtifact",
    "compose_catalog",
    "normalized_product",
    "source_product",
]
