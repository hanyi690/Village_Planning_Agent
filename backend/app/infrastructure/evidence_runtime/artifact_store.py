"""Write-once CAS storage for replayable Evidence retrievals.

Unlike stage outputs, a retrieval is identified by its complete frozen input
fingerprint.  Its dynamic named ref is therefore only a create-if-absent race
arbiter; this module never advances that ref to a newer result.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.retrieval_artifact_contracts import (
    EvidenceRetrievalArtifact,
)
from app.contracts.evidence.retrieval_contracts import (
    EvidenceRetrievalAuthority,
    EvidenceRetrievalReceipt,
)
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.artifacts.repository import (
    ContentAddressedArtifactRepository,
    NamedRefConflict,
)
from app.infrastructure.artifacts.runtime import (
    ARTIFACT_SCHEMA_VERSION,
    ArtifactReplayError,
)


_VOLATILE_FIELDS = frozenset({
    "artifact_id",
    "created_at",
    "dedup_hit",
    "elapsed",
    "elapsed_ms",
    "duration",
    "duration_ms",
    "path",
    "retrieval_ref",
    "retrieved_at",
})


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if str(key) not in _VOLATILE_FIELDS
            and not str(key).endswith("_path")
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _authority_replay_identity(authority: EvidenceRetrievalAuthority) -> dict[str, Any]:
    """Return the business identity used to validate a replay.

    Snapshot refs and context-version labels are physical/runtime handles. A
    World Model rebuild may replace those handles while preserving the same
    current-world business digest; that case must remain a CAS replay hit.
    """

    return {
        "session_id": authority.session_id,
        "workflow_run_id": authority.workflow_run_id,
        "branch_id": authority.branch_id,
        "data_catalog_digest": authority.data_catalog_digest,
        "data_snapshot_digest": authority.data_snapshot_digest,
        "world_model_snapshot_digest": authority.world_model_snapshot_digest,
        "external_cache_digest": authority.external_cache_digest,
        "world_model_mode": authority.world_model_mode,
        "engine": authority.engine,
        "engine_version": authority.engine_version,
        "cache_only_policy": authority.cache_only_policy,
    }


def _ref_identity(ref: ArtifactRef) -> dict[str, str]:
    """Use descriptor/business digests, never a filesystem locator."""

    return {
        "descriptor_digest": ref.descriptor_digest,
        "digest": ref.digest,
        "semantic_digest": ref.semantic_digest,
        "schema_id": ref.schema_id,
        "schema_version": ref.schema_version,
    }


def canonicalize_request(request: ExplorationRequest) -> ExplorationRequest:
    """Return a deterministic request retaining every business requirement field."""

    payload = _jsonable(request)
    payload["context_refs"] = sorted(dict.fromkeys(payload.get("context_refs") or []))
    payload["evidence_gaps_to_resolve"] = sorted(
        dict.fromkeys(payload.get("evidence_gaps_to_resolve") or [])
    )
    payload["questions"] = list(dict.fromkeys(payload.get("questions") or []))
    payload["required_facts"] = list(dict.fromkeys(payload.get("required_facts") or []))
    payload["entity_scope"] = list(dict.fromkeys(payload.get("entity_scope") or []))
    payload["requirements"] = sorted(
        payload.get("requirements") or [],
        key=lambda item: str(item.get("requirement_id") or ""),
    )
    return ExplorationRequest.model_validate(payload)


def retrieval_fingerprint(
    authority: EvidenceRetrievalAuthority,
    request: ExplorationRequest,
    *,
    spatial_spec: Any = None,
    query_plan: Any = None,
) -> str:
    """Fingerprint every source of replay-relevant Evidence behavior."""

    canonical_request = canonicalize_request(request)
    payload = {
        "session_id": authority.session_id,
        "workflow_run_id": authority.workflow_run_id,
        "branch_id": authority.branch_id,
        "data_catalog": {
            "business_digest": authority.data_catalog_digest,
        },
        "data_snapshot": {
            "business_digest": authority.data_snapshot_digest,
        },
        "world_model": {
            "business_digest": authority.world_model_snapshot_digest,
        },
        # Cache digest is deliberately used instead of a cache path or the
        # descriptor's volatile creation timestamp.
        "external_observation_cache_digest": authority.external_cache_digest,
        "world_model_mode": authority.world_model_mode,
        "engine": authority.engine,
        "engine_version": authority.engine_version,
        "cache_only_policy": authority.cache_only_policy,
        "query_plan": {
            "ref": str(getattr(query_plan, "query_plan_ref", "") or ""),
            "fingerprint": str(getattr(query_plan, "plan_fingerprint", "") or ""),
        },
        "canonical_request": canonical_request,
        "candidate_page": {
            "offset": canonical_request.candidate_offset,
            "limit": canonical_request.candidate_limit,
        },
        "spatial_spec_semantic_digest": "sha256:" + _sha256(spatial_spec),
    }
    return _sha256(payload)


def _result_semantics(artifact: EvidenceRetrievalArtifact) -> str:
    """Compare all business output, excluding only explicitly volatile fields."""

    return _sha256({
        "canonical_request": artifact.canonical_request,
        "evidence_bundle": artifact.evidence_bundle,
        "evidence_packet": artifact.evidence_packet,
        "coverage": artifact.coverage,
        "outcome": artifact.outcome,
        "query_plan_ref": artifact.query_plan_ref,
        "observation_snapshot": artifact.observation_snapshot,
        "acquisition_receipt": artifact.acquisition_receipt,
        "page_records": artifact.page_records,
        "provider_attempts": artifact.provider_attempts,
        "confidence_components": artifact.confidence_components,
        "evidence_authority": artifact.evidence_authority,
        "spatial_cognition": artifact.spatial_cognition,
        "proposal_batch": artifact.proposal_batch,
    })


class EvidenceRetrievalArtifactStore:
    """One narrowly scoped write-once registry for dynamic retrieval keys."""

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        workflow_run_id: str,
        branch_id: str,
    ) -> None:
        self.repository = ContentAddressedArtifactRepository(Path(artifact_root))
        self.workflow_run_id = str(workflow_run_id)
        self.branch_id = str(branch_id)
        if not self.workflow_run_id or not self.branch_id:
            raise ArtifactReplayError("retrieval CAS requires workflow run and branch authority")

    @staticmethod
    def key_for(fingerprint: str) -> str:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ArtifactReplayError("retrieval fingerprint must be 64 lowercase hex characters")
        return f"evidence_retrieval__{fingerprint}"

    def _load_descriptor(self, key: str) -> ArtifactRef | None:
        descriptor = self.repository.get_named_ref(
            self.workflow_run_id,
            self.branch_id,
            key,
        )
        if descriptor is not None and (
            descriptor.run_id != self.workflow_run_id
            or descriptor.branch_id != self.branch_id
        ):
            raise ArtifactReplayError("retrieval CAS ref belongs to another run or branch")
        return descriptor

    def _load_and_validate(
        self,
        descriptor: ArtifactRef,
        *,
        fingerprint: str,
        authority: EvidenceRetrievalAuthority,
        candidate: EvidenceRetrievalArtifact | None = None,
    ) -> EvidenceRetrievalArtifact:
        if descriptor.schema_id != "EvidenceRetrievalArtifact":
            raise ArtifactReplayError("retrieval CAS descriptor has an unexpected schema")
        try:
            artifact = EvidenceRetrievalArtifact.model_validate(
                self.repository.get_json(descriptor)
            )
        except Exception as exc:
            raise ArtifactReplayError("retrieval CAS artifact could not be reloaded") from exc
        if artifact.fingerprint != fingerprint:
            raise ArtifactReplayError("retrieval CAS fingerprint mismatch")
        if _canonical_bytes(_authority_replay_identity(artifact.authority)) != _canonical_bytes(
            _authority_replay_identity(authority)
        ):
            raise ArtifactReplayError("retrieval CAS authority mismatch")
        if candidate is not None and _result_semantics(artifact) != _result_semantics(candidate):
            raise ArtifactReplayError("retrieval CAS result conflicts with existing fingerprint")
        return artifact

    def load(
        self,
        *,
        fingerprint: str,
        authority: EvidenceRetrievalAuthority,
    ) -> tuple[EvidenceRetrievalArtifact, EvidenceRetrievalReceipt] | None:
        key = self.key_for(fingerprint)
        descriptor = self._load_descriptor(key)
        if descriptor is None:
            return None
        artifact = self._load_and_validate(
            descriptor,
            fingerprint=fingerprint,
            authority=authority,
        )
        return artifact, EvidenceRetrievalReceipt(
            retrieval_ref=descriptor,
            fingerprint=fingerprint,
            dedup_hit=True,
            query_plan_ref=artifact.query_plan_ref,
            acquisition_receipt_ref=(
                artifact.acquisition_receipt.receipt_ref
                if artifact.acquisition_receipt is not None
                else ""
            ),
        )

    def write_once(
        self,
        artifact: EvidenceRetrievalArtifact,
    ) -> tuple[EvidenceRetrievalArtifact, EvidenceRetrievalReceipt]:
        """Create a dynamic key once; reload and verify a concurrent winner."""

        key = self.key_for(artifact.fingerprint)
        existing = self._load_descriptor(key)
        if existing is not None:
            loaded = self._load_and_validate(
                existing,
                fingerprint=artifact.fingerprint,
                authority=artifact.authority,
                candidate=artifact,
            )
            return loaded, EvidenceRetrievalReceipt(
                retrieval_ref=existing,
                fingerprint=artifact.fingerprint,
                dedup_hit=True,
                query_plan_ref=loaded.query_plan_ref,
                acquisition_receipt_ref=(
                    loaded.acquisition_receipt.receipt_ref
                    if loaded.acquisition_receipt is not None
                    else ""
                ),
            )
        descriptor = self.repository.put_json(
            artifact.model_dump(mode="json"),
            schema_id="EvidenceRetrievalArtifact",
            schema_version=ARTIFACT_SCHEMA_VERSION,
            producer_stage="evidence",
            run_id=self.workflow_run_id,
            branch_id=self.branch_id,
            parent_digests={
                "evidence_snapshot": artifact.bootstrap_refs.evidence_snapshot_ref.digest,
                "external_observations": artifact.bootstrap_refs.external_observations_ref.digest,
                "gap_ledger": artifact.bootstrap_refs.gap_ledger_ref.digest,
            },
            provenance={
                "artifact_key": key,
                "context_fingerprint": artifact.authority.context_fingerprint,
                "fingerprint": artifact.fingerprint,
                "write_once": True,
            },
        )
        try:
            self.repository.compare_and_set_named_ref(
                self.workflow_run_id,
                self.branch_id,
                key,
                descriptor,
                expected_descriptor_digest=None,
            )
        except NamedRefConflict as exc:
            winner: ArtifactRef | None = None
            for _ in range(5):
                winner = self._load_descriptor(key)
                if winner is not None:
                    break
                time.sleep(0.01)
            if winner is None:
                raise ArtifactReplayError("retrieval CAS race winner could not be reloaded") from exc
            loaded = self._load_and_validate(
                winner,
                fingerprint=artifact.fingerprint,
                authority=artifact.authority,
                candidate=artifact,
            )
            return loaded, EvidenceRetrievalReceipt(
                retrieval_ref=winner,
                fingerprint=artifact.fingerprint,
                dedup_hit=True,
                query_plan_ref=loaded.query_plan_ref,
                acquisition_receipt_ref=(
                    loaded.acquisition_receipt.receipt_ref
                    if loaded.acquisition_receipt is not None
                    else ""
                ),
            )
        return artifact, EvidenceRetrievalReceipt(
            retrieval_ref=descriptor,
            fingerprint=artifact.fingerprint,
            dedup_hit=False,
            query_plan_ref=artifact.query_plan_ref,
            acquisition_receipt_ref=(
                artifact.acquisition_receipt.receipt_ref
                if artifact.acquisition_receipt is not None
                else ""
            ),
        )


__all__ = [
    "EvidenceRetrievalArtifactStore",
    "canonicalize_request",
    "retrieval_fingerprint",
]
