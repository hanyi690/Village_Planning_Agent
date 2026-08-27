"""Central registry for cross-boundary contracts.

The repository intentionally keeps domain models close to their owning
module.  This registry is the small, stable index that prevents those models
from becoming anonymous provider/API payloads.  It records ownership and
boundary role without importing every model at application import time, which
keeps the domain modules free of registry cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ContractRole = Literal[
    "llm_output",
    "domain",
    "artifact",
    "api",
    "event",
    "render",
]


@dataclass(frozen=True)
class ContractRegistration:
    """Stable identity for one model at a cross-module boundary."""

    key: str
    role: ContractRole
    owner: str
    model_path: str
    version: str
    description: str


CONTRACT_REGISTRY: dict[str, ContractRegistration] = {
    "l1.observe": ContractRegistration(
        key="l1.observe",
        role="llm_output",
        owner="assessment",
        model_path="app.domain.assessment.observation_draft:L1ObservationProviderOutput",
        version="1",
        description="Validated L1 observation projection for one dimension.",
    ),
    "l1.report": ContractRegistration(
        key="l1.report",
        role="llm_output",
        owner="assessment",
        model_path="app.domain.assessment.observation_draft:L1ReportOutput",
        version="1",
        description="L1 human-facing report synthesis from validated observations.",
    ),
    "l2.decision": ContractRegistration(
        key="l2.decision",
        role="llm_output",
        owner="objectives",
        model_path="app.contracts.domain.l2_contracts:L2DecisionSet",
        version="2",
        description="Closed-set L2 objectives, metrics, strategies and gaps.",
    ),
    "l2.report": ContractRegistration(
        key="l2.report",
        role="llm_output",
        owner="objectives",
        model_path="app.contracts.domain.l2_contracts:L2ReportOutput",
        version="2",
        description="L2 human-facing report synthesis from validated decisions.",
    ),
    "l3.claims": ContractRegistration(
        key="l3.claims",
        role="llm_output",
        owner="program",
        model_path="app.domain.program.claim_draft:L3RoughClaimOutput",
        version="2",
        description="Stable L3 provider claims envelope; runtime catalog closure is local.",
    ),
    "l3.intent_summary": ContractRegistration(
        key="l3.intent_summary",
        role="llm_output",
        owner="program",
        model_path="app.domain.program.claim_draft:L3IntentSummaryOutput",
        version="1",
        description="L3 short human-facing intent summary from rough claims.",
    ),
    "program.unit_repair": ContractRegistration(
        key="program.unit_repair",
        role="llm_output",
        owner="program",
        model_path="app.contracts.llm.program_contracts:UnitResolutionBatch",
        version="1",
        description="Field-scoped unit repair proposal before deterministic application.",
    ),
    "llm.closed_set": ContractRegistration(
        key="llm.closed_set",
        role="llm_output",
        owner="llm",
        model_path="app.contracts.llm.closed_set_contracts:CandidateDecision",
        version="1",
        description="Shared candidate identity, digest and membership kernel.",
    ),
    "program.classification": ContractRegistration(
        key="program.classification",
        role="llm_output",
        owner="program",
        model_path="app.domain.program.classification_generator:_ClassificationProposalBatch",
        version="1",
        description="Closed-set target classification proposal batch.",
    ),
    "program.semantic_repair": ContractRegistration(
        key="program.semantic_repair",
        role="llm_output",
        owner="program",
        model_path="app.domain.program.semantic_repair:ProgramSemanticRepairCandidate",
        version="2",
        description="Verified program semantic repair proposal.",
    ),
    "ground.candidate_selection": ContractRegistration(
        key="ground.candidate_selection",
        role="llm_output",
        owner="grounding",
        model_path="app.contracts.spatial.spatial_reference_contracts:CandidateSelectionProposal",
        version="1",
        description="One closed-set grounding decision; never a final planning choice.",
    ),
    "ground.candidate_selection_batch": ContractRegistration(
        key="ground.candidate_selection_batch",
        role="llm_output",
        owner="grounding",
        model_path="app.contracts.spatial.spatial_reference_contracts:CandidateSelectionBatchProposal",
        version="1",
        description="Batch closed-set grounding decisions for one shared round.",
    ),
    "select.scenario_selection": ContractRegistration(
        key="select.scenario_selection",
        role="llm_output",
        owner="select",
        model_path="app.contracts.spatial.spatial_reference_contracts:CandidateSelectionProposal",
        version="1",
        description="Advisory closed-set reasoning over solver-produced scenario cards.",
    ),
    "evidence.source_semantic": ContractRegistration(
        key="evidence.source_semantic",
        role="llm_output",
        owner="evidence",
        model_path="app.contracts.evidence.source_semantic_contracts:SourceFeatureSemanticProposalBatch",
        version="1",
        description="Closed-set source feature semantic proposal.",
    ),
    "ground.query_spec": ContractRegistration(
        key="ground.query_spec",
        role="llm_output",
        owner="grounding",
        model_path="app.contracts.spatial.spatial_reference_contracts:SpatialReferenceSpec",
        version="1",
        description="Typed query intent before deterministic evidence retrieval.",
    ),
    "ground.place_mentions": ContractRegistration(
        key="ground.place_mentions",
        role="llm_output",
        owner="grounding",
        model_path="app.spatial.grounding.flash_mention_extractor:SemanticPlaceEntitySet",
        version="1",
        description="Typed place mentions; not geometry or final location.",
    ),
    "materialization.vocabulary": ContractRegistration(
        key="materialization.vocabulary",
        role="llm_output",
        owner="materialization",
        model_path="app.domain.materialization.vocab_extractor:_VocabularyOutput",
        version="1",
        description="Closed vocabulary and rule proposal before deterministic compile.",
    ),
    "rag.document_metadata": ContractRegistration(
        key="rag.document_metadata",
        role="llm_output",
        owner="rag",
        model_path="app.infrastructure.rag.utils.metadata_extractor:DocumentTypeProposal",
        version="1",
        description="Bounded display/index metadata proposal.",
    ),
    "rag.query_batch": ContractRegistration(
        key="rag.query_batch",
        role="llm_output",
        owner="rag",
        model_path="app.contracts.llm.rag_contracts:RagQueryBatch",
        version="1",
        description="Bounded query proposals before deterministic retrieval.",
    ),
    "rag.outline_levels": ContractRegistration(
        key="rag.outline_levels",
        role="llm_output",
        owner="rag",
        model_path="app.infrastructure.rag.context:OutlineLevelBatch",
        version="1",
        description="Stable heading identities and bounded outline levels.",
    ),
    "display.summary": ContractRegistration(
        key="display.summary",
        role="llm_output",
        owner="ingestion",
        model_path="app.data.ingestion.summary_generator:BaseDimensionSummary",
        version="1",
        description="Display-only dimension summary; never planning authority.",
    ),
    "artifact.delivery_manifest": ContractRegistration(
        key="artifact.delivery_manifest",
        role="artifact",
        owner="delivery",
        model_path="app.contracts.artifacts.delivery_manifest_contracts:DeliveryManifest",
        version="2",
        description="Authoritative delivery gate and deliverable manifest.",
    ),
    "api.public_event": ContractRegistration(
        key="api.public_event",
        role="event",
        owner="api.v1",
        model_path="app.api.v1.contracts:PublicEvent",
        version="1",
        description="Stable public SSE/event-sync discriminated union.",
    ),
    "api.map_layers": ContractRegistration(
        key="api.map_layers",
        role="api",
        owner="api.v1",
        model_path="app.api.v1.contracts:MapLayerCollection",
        version="1",
        description="Stable map-layer projection consumed by the renderer.",
    ),
}


def get_contract_registration(key: str) -> ContractRegistration:
    """Return a registered contract or fail fast on a misspelled boundary."""

    normalized = str(key or "").strip()
    try:
        return CONTRACT_REGISTRY[normalized]
    except KeyError as exc:
        raise KeyError(f"unregistered contract key: {normalized!r}") from exc


def contract_context(key: str, model: type[Any] | None = None) -> dict[str, Any]:
    """Return safe identity metadata for logs, checkpoints and certificates."""

    registration = get_contract_registration(key)
    result: dict[str, Any] = {
        "contract_key": registration.key,
        "contract_role": registration.role,
        "contract_owner": registration.owner,
        "contract_version": registration.version,
        "contract_model_path": registration.model_path,
    }
    if model is not None and hasattr(model, "model_json_schema"):
        from app.contracts.llm.decision_contracts import schema_digest

        result["schema_digest"] = schema_digest(model)
    return result


def validate_contract_registry() -> None:
    """Validate registry invariants without importing the registered models."""

    if set(CONTRACT_REGISTRY) != {
        item.key for item in CONTRACT_REGISTRY.values()
    }:
        raise ValueError("contract registry keys and registration keys diverged")
    for key, registration in CONTRACT_REGISTRY.items():
        if key != registration.key or not registration.version.strip():
            raise ValueError(f"invalid contract registration: {key!r}")


validate_contract_registry()


__all__ = [
    "CONTRACT_REGISTRY",
    "ContractRegistration",
    "ContractRole",
    "contract_context",
    "get_contract_registration",
    "validate_contract_registry",
]
