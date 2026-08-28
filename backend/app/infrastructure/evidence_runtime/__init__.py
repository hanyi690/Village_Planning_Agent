"""集中式 Evidence Runtime：只负责检索执行，不拥有业务语义。"""

__all__ = [
    "ExternalSearchDecision",
    "ExternalSearchPolicy",
    "retrieve_evidence",
    "retrieve_dimension_context",
    "retrieve_targeted_evidence",
    "render_evidence_prompt_section",
    "retrieve_evidence_for_gate",
    "retrieve_evidence_for_gate_sync",
    "gate_evidence_digest",
    "clear_session_evidence_cache",
    "EvidenceGraph",
]


def __getattr__(name: str):
    if name in {
        "retrieve_evidence",
        "retrieve_dimension_context",
        "retrieve_targeted_evidence",
        "render_evidence_prompt_section",
        "retrieve_evidence_for_gate",
        "retrieve_evidence_for_gate_sync",
        "gate_evidence_digest",
        "clear_session_evidence_cache",
    }:
        from .facade import (
            clear_session_evidence_cache,
            render_evidence_prompt_section,
            retrieve_evidence,
            retrieve_dimension_context,
            retrieve_targeted_evidence,
            retrieve_evidence_for_gate,
            retrieve_evidence_for_gate_sync,
            gate_evidence_digest,
        )

        return {
            "retrieve_evidence": retrieve_evidence,
            "retrieve_dimension_context": retrieve_dimension_context,
            "retrieve_targeted_evidence": retrieve_targeted_evidence,
            "render_evidence_prompt_section": render_evidence_prompt_section,
            "retrieve_evidence_for_gate": retrieve_evidence_for_gate,
            "retrieve_evidence_for_gate_sync": retrieve_evidence_for_gate_sync,
            "gate_evidence_digest": gate_evidence_digest,
            "clear_session_evidence_cache": clear_session_evidence_cache,
        }[name]
    if name in {"ExternalSearchDecision", "ExternalSearchPolicy"}:
        from .external_search_policy import ExternalSearchDecision, ExternalSearchPolicy

        return {
            "ExternalSearchDecision": ExternalSearchDecision,
            "ExternalSearchPolicy": ExternalSearchPolicy,
        }[name]
    if name == "EvidenceGraph":
        from .evidence_graph import EvidenceGraph

        return EvidenceGraph
    raise AttributeError(name)
