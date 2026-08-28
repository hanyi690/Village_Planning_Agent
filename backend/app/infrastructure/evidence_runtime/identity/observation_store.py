"""Durable storage for L1 observations, independent from base KG facts."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json

from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.l1.l1_contracts import LocationScopeMention
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    EvidenceObservationSnapshot,
)
from app.infrastructure.artifacts.runtime import load_artifact, store_artifact


class ObservationStore:
    """Persist and restore L1 observations through the existing CAS boundary."""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = base_dir

    def put_snapshot(
        self,
        state: dict,
        observations: list[EvidenceObservation],
        parent_digest: str = "",
    ) -> ArtifactDescriptor:
        snapshot = EvidenceObservationSnapshot(
            observations=list(observations),
            parent_digest=str(parent_digest or ""),
            provenance_refs=[
                str(item.source_document_ref)
                for item in observations
                if item.source_document_ref
            ],
        )
        raw = store_artifact(
            state,
            "l1_observations",
            "l1_identity",
            "EvidenceObservationSnapshot",
            snapshot.model_dump(mode="json"),
            base_dir=self.base_dir,
        )
        return ArtifactDescriptor.model_validate(raw)

    def load_snapshot(self, state: dict) -> list[EvidenceObservation]:
        snapshot = load_artifact(
            state,
            "l1_observations",
            EvidenceObservationSnapshot,
            base_dir=self.base_dir,
        )
        if snapshot is None:
            return []
        return list(snapshot.observations)

    @staticmethod
    def _scope_mentions(fact: object) -> list[LocationScopeMention]:
        raw = getattr(fact, "scope_mentions", None)
        if raw in (None, "", []):
            raw = getattr(fact, "scopes", None)
        if raw in (None, "", []):
            raw = [
                {"name": value, "role": "natural_village"}
                for value in (getattr(fact, "village_scopes", None) or [])
            ]
            raw.extend(
                {"name": value, "role": "place"}
                for value in (getattr(fact, "place_scopes", None) or [])
            )
        if isinstance(raw, str):
            return []
        result: list[LocationScopeMention] = []
        for item in raw or []:
            try:
                scope = item if isinstance(item, LocationScopeMention) else LocationScopeMention.model_validate(item)
            except Exception:
                continue
            if scope.name.strip():
                result.append(scope)
        return result

    @staticmethod
    def from_location_mentions(facts: list[object]) -> list[EvidenceObservation]:
        """Convert canonical L1 location mentions without inventing fields."""

        observations: list[EvidenceObservation] = []
        for index, fact in enumerate(facts or []):
            name = str(
                getattr(fact, "canonical_name", "")
                or getattr(fact, "normalized_name", "")
                or getattr(fact, "mention", "")
                or ""
            ).strip()
            if not name:
                continue
            source_refs = [
                str(item) for item in (getattr(fact, "source_refs", None) or []) if item
            ]
            evidence_refs = [
                str(item) for item in (getattr(fact, "evidence_refs", None) or []) if item
            ]
            scope_mentions = ObservationStore._scope_mentions(fact)
            identity_payload = {
                "index": index,
                "name": name,
                "entity_type": str(
                    getattr(fact, "entity_type", "")
                    or getattr(fact, "role", "")
                    or ""
                ),
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "geometry_ref": str(getattr(fact, "geometry_ref", "") or ""),
                "scope_mentions": [
                    scope.model_dump(mode="json") for scope in scope_mentions
                ],
            }
            digest = hashlib.sha256(
                json.dumps(identity_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16]
            observations.append(
                EvidenceObservation(
                    observation_id=f"l1-observation:{digest}",
                    mention=name,
                    normalized_name=name,
                    aliases=list(getattr(fact, "aliases", None) or []),
                    observed_type=str(
                        getattr(fact, "entity_type", "")
                        or getattr(fact, "role", "")
                        or ""
                    ),
                    role=str(getattr(fact, "role", "") or "unknown"),
                    spatial_hint=str(getattr(fact, "spatial_hint", "") or ""),
                    relation_mentions=list(
                        getattr(fact, "related_mentions", None) or []
                    ),
                    scope_mentions=scope_mentions,
                    source_span=str(getattr(fact, "source_span", "") or ""),
                    report_section=str(getattr(fact, "dimension_key", "") or ""),
                    source_document_ref=str(
                        getattr(fact, "source_report_ref", "")
                        or (source_refs[0] if source_refs else "")
                    ),
                    source_refs=source_refs,
                    evidence_refs=evidence_refs,
                    confidence=float(getattr(fact, "confidence", 0.0) or 0.0),
                    extraction_method="l1_location_mention",
                    geometry_ref=getattr(fact, "geometry_ref", None),
                )
            )
        return observations

    @staticmethod
    def from_location_facts(facts: list[object]) -> list[EvidenceObservation]:
        """Compatibility alias for callers that still use the old field name."""

        return ObservationStore.from_location_mentions(facts)


__all__ = ["ObservationStore"]
