"""Evidence business facade and semantic contracts."""

__all__ = ["EvidenceApplication", "EvidenceFacade", "EvidenceContext", "retrieve_evidence"]


def __getattr__(name: str):
    if name in __all__:
        from .application import EvidenceApplication, EvidenceContext, EvidenceFacade, retrieve_evidence

        return {
            "EvidenceApplication": EvidenceApplication,
            "EvidenceFacade": EvidenceFacade,
            "EvidenceContext": EvidenceContext,
            "retrieve_evidence": retrieve_evidence,
        }[name]
    raise AttributeError(name)
