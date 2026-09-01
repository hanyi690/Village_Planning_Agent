"""Contracts for the DATA-backed cognitive World Model."""

from .assertion import SemanticAssertion
from .changeset import WorldModelChange, WorldModelChangeSet
from .decision import (
    SCHEMA_MAPPING_CODE_CONTRACT_VERSION,
    SchemaMappingDecision,
    SchemaMappingProposal,
    SchemaMappingProposalBatch,
    SourceCollectionProfile,
    SourceFieldProfile,
    SourceSemanticMappingSnapshot,
)
from .entity import EntityPart, LogicalPartProposal, WorldEntity
from .identity_projection import (
    IdentityBindingCommitEnvelope,
    IdentityBindingCommitResult,
)
from .proposals import (
    WorldModelCommitResult,
    WorldModelProposal,
    WorldModelProposalBatch,
)
from .query import (
    EntityQuery,
    IdentityBindingProjectionPage,
    IdentityBindingProjectionRequest,
    IdentityBindingProjectionRow,
    RenderedIdentityBindingProjection,
    RepresentationRequirement,
)
from .representation import SpatialRepresentation
from .snapshot import SessionWorldModelSnapshot
from .stage_contracts import (
    CognitionGapRecord,
    CognitionStageSnapshot,
    L1WorldProjectionSnapshot,
)
from .shadow_diff import CognitionShadowDiff, ShadowDiffItem
from .source import SourceCatalogSnapshot, SourceCollectionSnapshot, SourceFeatureRecord

__all__ = [
    "EntityPart",
    "IdentityBindingCommitEnvelope",
    "IdentityBindingCommitResult",
    "WorldModelCommitResult",
    "WorldModelProposal",
    "WorldModelProposalBatch",
    "LogicalPartProposal",
    "EntityQuery",
    "IdentityBindingProjectionPage",
    "IdentityBindingProjectionRequest",
    "IdentityBindingProjectionRow",
    "RenderedIdentityBindingProjection",
    "RepresentationRequirement",
    "SemanticAssertion",
    "SessionWorldModelSnapshot",
    "CognitionStageSnapshot",
    "CognitionGapRecord",
    "L1WorldProjectionSnapshot",
    "CognitionShadowDiff",
    "ShadowDiffItem",
    "SchemaMappingDecision",
    "SCHEMA_MAPPING_CODE_CONTRACT_VERSION",
    "SchemaMappingProposal",
    "SchemaMappingProposalBatch",
    "SourceCollectionProfile",
    "SourceFieldProfile",
    "SourceCatalogSnapshot",
    "SourceCollectionSnapshot",
    "SourceFeatureRecord",
    "SpatialRepresentation",
    "SourceSemanticMappingSnapshot",
    "WorldEntity",
    "WorldModelChange",
    "WorldModelChangeSet",
]
