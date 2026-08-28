"""Business-owned Evidence facade.

Stage modules declare requirements and scope here.  Retrieval planning,
provider routing, source access, fusion, caching and degradation stay inside
``infrastructure.evidence_runtime``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.evidence.evidence_contracts import (
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement


class EvidenceContext(BaseModel):
    """Minimal stage context accepted by the evidence business boundary."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    village_name: str = ""
    run_id: str = ""
    stage: str = ""
    dimension_key: str = ""
    purpose: str = ""
    request_type: str = "evidence_gap"
    project_wide: bool = False
    context_refs: tuple[str, ...] = ()

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        *,
        stage: str = "",
        purpose: str = "",
        request_type: str = "evidence_gap",
    ) -> "EvidenceContext":
        config = state.get("config") or {}
        return cls(
            session_id=str(state.get("session_id") or ""),
            village_name=str(config.get("village_name") or state.get("village_name") or ""),
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            stage=stage or str(state.get("active_stage") or ""),
            dimension_key=str(state.get("dimension_key") or ""),
            purpose=purpose,
            request_type=request_type,
            project_wide=bool(state.get("project_wide_evidence")),
            context_refs=tuple(str(item) for item in state.get("context_refs") or () if str(item)),
        )


def _as_requirements(
    requirement: EvidenceRequirement | Iterable[EvidenceRequirement],
) -> tuple[EvidenceRequirement, ...]:
    if isinstance(requirement, EvidenceRequirement):
        return (requirement,)
    return tuple(requirement)


def _request_for(
    requirements: tuple[EvidenceRequirement, ...],
    context: EvidenceContext,
    *,
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> ExplorationRequest:
    if not requirements:
        raise ValueError("EvidenceFacade requires at least one EvidenceRequirement")
    spatial = any(item.kind == "spatial" or item.scope for item in requirements)
    request_type = context.request_type or ("spatial_lookup" if spatial else "evidence_gap")
    return ExplorationRequest(
        run_id=context.run_id or context.session_id,
        request_type=request_type,
        query="; ".join(item.statement for item in requirements),
        context_refs=list(context.context_refs),
        stage=context.stage,
        dimension_key=context.dimension_key,
        query_purpose=context.purpose,
        entity_scope=list(dict.fromkeys(
            scope for item in requirements for scope in item.scope
        )),
        project_wide=context.project_wide,
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
        requirements=list(requirements),
    )


class EvidenceApplication:
    """Own requirement meaning while delegating all retrieval execution."""

    async def retrieve_dimension_context(
        self,
        dimension_key: str,
        config: Any,
        state: Mapping[str, Any],
        *,
        trace_sink: dict[str, Any] | None = None,
        excluded_fact_refs: Iterable[str] | None = None,
    ) -> tuple[str, Any | None]:
        """Build the bounded analysis projection for one current dimension.

        Dimension workers provide the business dimension and current state;
        the evidence runtime owns query planning, routing, provider access,
        fusion, and prompt projection.
        """

        from app.infrastructure.evidence_runtime.facade import (
            retrieve_dimension_context,
        )

        return await retrieve_dimension_context(
            dimension_key,
            config,
            dict(state),
            trace_sink=trace_sink,
            excluded_fact_refs=excluded_fact_refs,
        )

    def collect_authoritative_source_features(
        self,
        context: Any,
    ) -> dict[str, list[object]]:
        """Return current-session source features through the Evidence boundary."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            collect_authoritative_source_features,
        )

        return collect_authoritative_source_features(context)

    def describe_source_features(
        self,
        source_features: dict[str, list[object]],
    ) -> tuple[list[Any], int]:
        """Describe source features for deterministic semantic binding."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            source_descriptors,
        )

        return source_descriptors(source_features)

    def install_source_semantic_snapshot(self, context: Any, snapshot: Any) -> None:
        """Install an accepted, current-session semantic overlay."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            install_source_semantic_snapshot,
        )

        install_source_semantic_snapshot(context, snapshot)

    def accepted_semantic_decisions(self, snapshot: Any) -> dict[str, Any]:
        """Return only accepted decisions from a persisted semantic snapshot."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            accepted_semantic_decisions,
        )

        return accepted_semantic_decisions(snapshot)

    async def classify_source_semantics(
        self,
        context: Any,
        *,
        enabled: Any = None,
        source_features: dict[str, list[object]] | None = None,
        classifier: Any = None,
    ) -> Any:
        """Classify current source semantics without exposing runtime routing."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            classify_source_semantics,
        )

        return await classify_source_semantics(
            context,
            enabled=enabled,
            source_features=source_features,
            classifier=classifier,
        )

    def install_intent_layer(self, kg: Any, intent: Any) -> None:
        """Install the accepted target intent into the current KG projection."""

        from app.infrastructure.evidence_runtime.source_semantic import (
            install_intent_layer,
        )

        install_intent_layer(kg, intent)

    async def retrieve(
        self,
        requirement: EvidenceRequirement | Iterable[EvidenceRequirement],
        context: EvidenceContext,
        *,
        spatial_spec: Any = None,
        candidate_offset: int = 0,
        candidate_limit: int = 12,
    ) -> ExplorationResult:
        requirements = _as_requirements(requirement)
        request = _request_for(
            requirements,
            context,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )
        from app.infrastructure.evidence_runtime.facade import retrieve_evidence as run_runtime

        return await run_runtime(
            request,
            session_id=context.session_id,
            village_name=context.village_name,
            spatial_spec=spatial_spec,
        )


EvidenceFacade = EvidenceApplication


# Transport adapters for existing API/workflow request shapes.  New business
# stages use EvidenceFacade.retrieve so requirement semantics stay explicit.
from app.infrastructure.evidence_runtime.facade import (  # noqa: E402
    _EVIDENCE_CACHE,
    clear_session_evidence_cache,
    gate_evidence_digest,
    render_evidence_prompt_section,
    retrieve_evidence,
    retrieve_evidence_for_gate,
    retrieve_evidence_for_gate_sync,
)

__all__ = [
    "EvidenceApplication",
    "EvidenceFacade",
    "EvidenceContext",
    "clear_session_evidence_cache",
    "gate_evidence_digest",
    "render_evidence_prompt_section",
    "retrieve_evidence",
    "retrieve_evidence_for_gate",
    "retrieve_evidence_for_gate_sync",
    "_EVIDENCE_CACHE",
]
