"""Public L1 application facade.

The facade is the only new entry point for L1.  It accepts workflow control
state, delegates one real aggregate implementation, reloads the committed
typed artifact, and returns a typed result to the orchestrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1Snapshot

from .aggregation import l1_aggregate


class L1RunRequest(BaseModel):
    """Typed identity required to start an L1 aggregation."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    branch_id: str = Field(default="main", min_length=1)
    context_version: str = Field(min_length=1)
    context_ref: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "L1RunRequest":
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            branch_id=str(state.get("branch_id") or "main"),
            context_version=str(state.get("context_version") or ""),
            context_ref=dict(state.get("context_ref") or {}),
        )


class L1RunResult(BaseModel):
    """Typed result returned by the L1 facade after CAS commit and reload."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: L1RunRequest
    snapshot: L1Snapshot
    snapshot_ref: ArtifactRef
    gate_ref: ArtifactRef
    review_id: str = ""
    projection_digest: str = ""
    input_snapshot_ref: ArtifactRef | None = None
    iteration: int = 0
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        """Convert the typed result to the workflow's control-plane patch."""

        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "l1_snapshot": self.snapshot_ref.model_dump(mode="json"),
            "l1_gate": self.gate_ref.model_dump(mode="json"),
        }
        patch["l1_review_id"] = self.review_id
        return patch


class L1Application:
    """Application boundary for L1 OBSERVE."""

    @staticmethod
    def _validate_snapshot(
        snapshot: L1Snapshot,
        request: L1RunRequest,
    ) -> L1Snapshot:
        if snapshot.context_version != request.context_version:
            raise RuntimeError("L1Snapshot context version does not match the run")
        if not snapshot.context_fingerprint:
            raise RuntimeError("L1Snapshot has no frozen context fingerprint")
        if not snapshot.sources and snapshot.fact_records:
            raise RuntimeError("L1Snapshot facts have no source catalog")
        source_refs = {
            source.reference
            for source in snapshot.sources
            if source.reference
        }
        for fact in snapshot.fact_records:
            if not fact.source_refs:
                raise RuntimeError(f"L1 fact has no provenance: {fact.fact_id}")
            if not any(
                ref in source_refs
                or any(ref.startswith(f"{source_ref}#") for source_ref in source_refs)
                for ref in fact.source_refs
            ):
                raise RuntimeError(
                    "L1 fact provenance is not represented by sources: "
                    f"fact={fact.fact_id} refs={fact.source_refs}"
                )
            expected_level = {
                "derived_metric": "derived",
                "kg_canonical_fact": "inferred",
            }.get(fact.fact_kind)
            allowed_levels = (
                {expected_level}
                if expected_level is not None
                else {
                    "observed",
                    "inferred",
                    "pending",
                    "conflicted",
                }
            )
            if fact.inference_level not in allowed_levels:
                raise RuntimeError(
                    f"L1 fact inference level mismatch: {fact.fact_id}"
                )
            if fact.status != fact.inference_level:
                raise RuntimeError(f"L1 fact status mismatch: {fact.fact_id}")
        return snapshot

    @staticmethod
    def _validate_evidence_artifacts(
        snapshot: L1Snapshot,
        state: Mapping[str, Any],
        request: L1RunRequest,
    ) -> None:
        """Reload every dynamic Evidence ref consumed by the L1 snapshot."""

        from app.contracts.evidence.retrieval_artifact_contracts import (
            EvidenceRetrievalArtifact,
        )
        from app.infrastructure.artifacts.fingerprint import semantic_checksum
        from app.infrastructure.artifacts.repository import (
            ContentAddressedArtifactRepository,
        )
        from app.infrastructure.paths import run_tmp_root

        refs_by_descriptor = {
            ref.descriptor_digest: ref
            for ref in snapshot.evidence_artifact_refs
        }
        if len(refs_by_descriptor) != len(snapshot.evidence_artifact_refs):
            raise RuntimeError("L1Snapshot has duplicate Evidence artifact refs")

        root_ref = ArtifactRef.model_validate(
            dict(state.get("artifact_refs") or {}).get("l1_snapshot")
        )
        authority_parent_keys = {
            "data_catalog",
            "data_snapshot",
            "data_stage",
            "data_gate",
            "schema_mapping_snapshot",
            "world_model_snapshot",
            "kg_stage",
            "kg_gate",
            "evidence_snapshot",
            "evidence_external_observations",
            "evidence_gap_ledger",
            "evidence_gate",
        }
        dimension_parent_keys = {
            str(key)
            for key in root_ref.parent_digests
            if str(key).startswith("l1_dimension__")
        }
        dynamic_parent_refs: dict[str, ArtifactRef] = {}
        for ref in refs_by_descriptor.values():
            fingerprint = str(
                ref.provenance.get("fingerprint") or ""
            ).strip()
            if len(fingerprint) != 64:
                raise RuntimeError(
                    "L1 Evidence ref has no retrieval fingerprint"
                )
            dynamic_parent_refs[
                f"evidence_retrieval__{fingerprint}"
            ] = ref
        expected_parent_keys = {
            *authority_parent_keys,
            *dimension_parent_keys,
            *dynamic_parent_refs,
        }
        if set(root_ref.parent_digests) != expected_parent_keys:
            raise RuntimeError(
                "L1Snapshot parent closure does not exactly match its inputs"
            )
        active_refs = dict(state.get("artifact_refs") or {})
        for key in sorted(authority_parent_keys | dimension_parent_keys):
            active_ref = ArtifactRef.model_validate(active_refs.get(key))
            if root_ref.parent_digests.get(key) != active_ref.digest:
                raise RuntimeError(
                    f"L1Snapshot parent digest mismatch: {key}"
                )
        for key, evidence_ref in dynamic_parent_refs.items():
            if root_ref.parent_digests.get(key) != evidence_ref.digest:
                raise RuntimeError(
                    f"L1Snapshot Evidence parent digest mismatch: {key}"
                )

        repository = ContentAddressedArtifactRepository(
            str(state.get("artifact_root") or run_tmp_root())
        )
        artifacts: dict[str, EvidenceRetrievalArtifact] = {}
        for descriptor_digest, ref in refs_by_descriptor.items():
            if ref.schema_id != "EvidenceRetrievalArtifact":
                raise RuntimeError(
                    "L1Snapshot references a non-Evidence retrieval artifact"
                )
            if ref.run_id != request.run_id or ref.branch_id != request.branch_id:
                raise RuntimeError(
                    "L1 Evidence artifact is outside the active run/branch"
                )
            descriptor = repository.get_descriptor(descriptor_digest)
            if descriptor.digest != ref.digest:
                raise RuntimeError("L1 Evidence descriptor identity mismatch")
            payload = repository.get_json(descriptor)
            if ref.semantic_digest != f"sha256:{semantic_checksum(payload)}":
                raise RuntimeError("L1 Evidence artifact semantic digest mismatch")
            artifact = EvidenceRetrievalArtifact.model_validate(payload)
            fingerprint = str(
                ref.provenance.get("fingerprint") or ""
            )
            if artifact.fingerprint != fingerprint:
                raise RuntimeError(
                    "L1 Evidence descriptor fingerprint mismatch"
                )
            authority = artifact.authority
            if (
                authority.workflow_run_id != request.run_id
                or authority.branch_id != request.branch_id
                or authority.context_version != request.context_version
                or authority.context_fingerprint != snapshot.context_fingerprint
            ):
                raise RuntimeError(
                    "L1 Evidence artifact authority does not match the snapshot"
                )
            if len(artifact.canonical_request.requirements) != 1:
                raise RuntimeError(
                    "L1 Evidence retrieval must contain exactly one requirement"
                )
            artifacts[descriptor_digest] = artifact

        top_level_descriptors = set(refs_by_descriptor)
        for mention in snapshot.location_mentions:
            from app.modules.evidence.requirements import (
                l1_location_work_item_key,
            )

            for ref in mention.evidence_artifact_refs:
                if ref.descriptor_digest not in top_level_descriptors:
                    raise RuntimeError(
                        "LocationMention Evidence ref is absent from L1Snapshot"
                    )
                artifact = artifacts[ref.descriptor_digest]
                requirement = artifact.canonical_request.requirements[0]
                if requirement.evidence_role != "l1_location_identity":
                    raise RuntimeError(
                        "LocationMention references a non-identity retrieval"
                    )
                expected_name = str(
                    (requirement.metadata or {}).get("mention") or ""
                )
                actual_name = str(
                    mention.normalized_name or mention.mention or ""
                )
                if "".join(expected_name.casefold().split()) != "".join(
                    actual_name.casefold().split()
                ):
                    raise RuntimeError(
                        "LocationMention Evidence ref belongs to another mention"
                    )
                if str(
                    (requirement.metadata or {}).get(
                        "location_work_item_key"
                    )
                    or ""
                ) != l1_location_work_item_key(mention):
                    raise RuntimeError(
                        "LocationMention Evidence work-item identity mismatch"
                    )
                if artifact.outcome.status == "sufficient":
                    packet = artifact.evidence_packet
                    if not (
                        packet.sufficiency == "sufficient"
                        and packet.ambiguity_status == "resolved"
                        and packet.candidate_identity_total == 1
                        and len(packet.candidate_entity_refs) == 1
                        and packet.identity_grouping == "world_entity"
                        and len(packet.candidate_refs) >= 1
                    ):
                        raise RuntimeError(
                            "sufficient L1 identity Evidence is not uniquely bound"
                        )

        resolution_refs = {
            item.evidence_ref for item in snapshot.evidence_resolutions
        }
        if not resolution_refs.issubset(top_level_descriptors):
            raise RuntimeError(
                "L1 Evidence resolution references an unknown retrieval"
            )

        gap_ids = {gap.gap_id for gap in snapshot.evidence_gaps}
        resolution_ids = {
            item.gap_id for item in snapshot.evidence_resolutions
        }
        for descriptor_digest, artifact in artifacts.items():
            requirement = artifact.canonical_request.requirements[0]
            if artifact.outcome.status == "sufficient":
                continue
            source_gap_id = str(
                (requirement.metadata or {}).get("gap_id") or ""
            )
            expected_ids = {
                source_gap_id,
                f"{requirement.requirement_id}:{artifact.outcome.status}",
            }
            expected_ids.discard("")
            if not (
                gap_ids.intersection(expected_ids)
                or resolution_ids.intersection(expected_ids)
            ):
                raise RuntimeError(
                    "non-sufficient L1 Evidence outcome has no typed gap"
                )

    async def run(self, state: Mapping[str, Any]) -> L1RunResult:
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(dict(state), ("data", "kg", "evidence"))
        request = L1RunRequest.from_state(state)
        patch = dict(await l1_aggregate(dict(state)))
        refs = dict(state.get("artifact_refs") or {})
        refs.update(dict(patch.get("artifact_refs") or {}))
        replay_state = {**dict(state), **patch, "artifact_refs": refs}
        snapshot = self.load(replay_state)
        if snapshot is None:
            raise RuntimeError("L1 aggregate did not commit an L1Snapshot artifact")
        from app.infrastructure.artifacts.runtime import validate_artifact_context

        validate_artifact_context(replay_state, "l1_snapshot", refs.get("l1_snapshot"))
        self._validate_snapshot(snapshot, request)
        self._validate_evidence_artifacts(snapshot, replay_state, request)
        snapshot_ref = ArtifactRef.model_validate(refs.get("l1_snapshot"))
        gate_ref = ArtifactRef.model_validate(refs.get("l1_gate"))
        return L1RunResult(
            request=request,
            snapshot=snapshot,
            snapshot_ref=snapshot_ref,
            gate_ref=gate_ref,
            review_id=str(patch.get("l1_review_id") or ""),
            projection_digest=str(patch.get("l1_projection_digest") or ""),
            input_snapshot_ref=(
                ArtifactRef.model_validate(patch["l1_input_snapshot_ref"])
                if patch.get("l1_input_snapshot_ref")
                else None
            ),
            iteration=int(patch.get("l1_iteration") or 0),
            state_patch=patch,
        )

    @staticmethod
    def load(state: Mapping[str, Any]) -> L1Snapshot | None:
        from app.infrastructure.artifacts.runtime import load_artifact

        return load_artifact(dict(state), "l1_snapshot", L1Snapshot)


async def analyze_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    """Run one bounded L1 dimension through the stage-owned facade."""

    from app.workflow.stages.support import require_upstream_gates

    require_upstream_gates(dict(state), ("data", "kg", "evidence"))
    from .reasoning import analyze_dimension as run_dimension

    result = await run_dimension(dict(state))
    from app.infrastructure.artifacts.dimension_runtime import (
        ensure_dimension_product_patch,
    )

    return ensure_dimension_product_patch(state, result, layer=1)


async def run_l1(state: Mapping[str, Any]) -> L1RunResult:
    """Run L1 through the canonical facade."""

    return await L1Application().run(state)


__all__ = [
    "L1Application",
    "L1RunRequest",
    "L1RunResult",
    "analyze_dimension",
    "run_l1",
]
