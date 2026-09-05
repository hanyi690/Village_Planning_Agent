"""Central source-role and provenance normalization for Evidence Runtime."""

from __future__ import annotations

from typing import Any

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource


_SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "data": {
        "evidence_role": "spatial_identity",
        "authority": "geometry_authoritative",
        "supports": ["location_binding", "grounding", "execution_geometry"],
    },
    "gis_layer": {
        "evidence_role": "spatial_identity",
        "authority": "geometry_authoritative",
        "supports": ["location_binding", "grounding", "execution_geometry"],
    },
    "kg": {
        "evidence_role": "spatial_fact",
        "authority": "canonical_kg",
        "supports": ["identity", "topology", "spatial_fact"],
    },
    "l1": {
        "evidence_role": "location_binding",
        "authority": "typed_observation",
        "supports": ["location_binding", "observation"],
    },
    "report": {
        "evidence_role": "planning_background",
        "authority": "advisory",
        "supports": ["context", "claim"],
    },
    "local_text": {
        "evidence_role": "planning_background",
        "authority": "document_context",
        "supports": ["context", "claim", "source_span"],
    },
    "external": {
        "evidence_role": "external_reference",
        "authority": "advisory",
        "supports": ["context", "claim"],
    },
    "integrity": {
        "evidence_role": "integrity_check",
        "authority": "derived_check",
        "supports": ["source_integrity", "coverage_check"],
    },
}


def source_key(source: EvidenceSource) -> tuple[str, str, str, str]:
    return (
        str(source.source_type or "").strip().lower(),
        str(source.reference or "").strip(),
        str(source.evidence_role or "").strip(),
        str(source.authority or "").strip(),
    )


def annotate_sources(
    sources: list[EvidenceSource],
    *,
    context: Any = None,
) -> list[EvidenceSource]:
    """Attach one consistent role/authority interpretation to all sources."""

    bundle_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    l1_snapshot_ref = str(getattr(context, "l1_snapshot_ref", "") or "")
    annotated: list[EvidenceSource] = []
    for source in sources:
        source_type = str(source.source_type or "").strip().lower()
        if source_type == "bundle" and str(source.reference or "").startswith("local-text:"):
            source_type = "local_text"
        elif source_type == "bundle":
            source_type = "data"
        profile = _SOURCE_PROFILES.get(
            source_type,
            {
                "evidence_role": "context",
                "authority": "advisory",
                "supports": ["context"],
            },
        )
        snapshot_ref = str(source.snapshot_ref or "")
        if not snapshot_ref:
            if source_type in {"data", "gis_layer"} and bundle_digest:
                snapshot_ref = f"data:snapshot:{bundle_digest}"
            elif source_type == "l1" and l1_snapshot_ref:
                snapshot_ref = l1_snapshot_ref
        annotated.append(source.model_copy(update={
            "source_type": source_type,
            "evidence_role": (
                profile["evidence_role"]
                if source.evidence_role in {"", "context"}
                else source.evidence_role
            ),
            "authority": (
                profile["authority"]
                if source.authority in {"", "advisory"}
                else source.authority
            ),
            "availability": source.availability or "available",
            "supports": list(dict.fromkeys([
                *list(profile["supports"]),
                *list(source.supports or []),
            ])),
            "snapshot_ref": snapshot_ref,
        }))
    return annotated


def canonicalize_fact_provenance(
    facts: list[EvidenceFact],
    sources: list[EvidenceSource],
    *,
    session_id: str = "",
) -> list[EvidenceFact]:
    """Bind retriever-internal aliases to the current source catalog.

    ``kg:cognition`` and similar labels identify a query result inside a
    retriever; they are not persisted source records.  A fact may cross the
    runtime boundary only when the result also exposes a KG source for the
    same current session.  Unknown aliases remain untouched so the L1
    provenance gate can reject them instead of turning them into invented
    evidence.
    """

    known_refs = {
        str(source.reference).strip()
        for source in sources
        if str(source.reference or "").strip()
    }
    kg_refs = [
        str(source.reference).strip()
        for source in sources
        if str(source.source_type or "").strip().lower() == "kg"
        and str(source.reference or "").strip()
    ]
    if not kg_refs:
        return facts

    session_root = f"world_model:{str(session_id or '').strip()}"
    kg_root = next(
        (
            reference
            for reference in kg_refs
            if reference == session_root or reference.startswith(f"{session_root}#")
        ),
        kg_refs[0],
    )
    if "#" in kg_root:
        kg_root = kg_root.split("#", 1)[0]

    normalized: list[EvidenceFact] = []
    for fact in facts:
        refs: list[str] = []
        changed = False
        for raw_ref in fact.source_refs:
            reference = str(raw_ref or "").strip()
            if not reference or reference in known_refs:
                refs.append(reference)
                continue
            if reference.startswith("kg:"):
                suffix = reference[3:].strip("#:")
                candidate = f"{kg_root}#{suffix}" if suffix else kg_root
                if candidate in known_refs or any(
                    candidate.startswith(f"{known}#") for known in known_refs
                ):
                    refs.append(candidate)
                    changed = True
                    continue
            refs.append(reference)
        if changed:
            normalized.append(fact.model_copy(update={"source_refs": list(dict.fromkeys(refs))}))
        else:
            normalized.append(fact)
    return normalized


__all__ = ["annotate_sources", "canonicalize_fact_provenance", "source_key"]
