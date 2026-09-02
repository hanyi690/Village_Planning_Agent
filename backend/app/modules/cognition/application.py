"""Public World Model/KG bootstrap facade.

The facade projects a frozen DATA catalog into the cognition store and
publishes only a bounded ``SessionWorldModelSnapshot``.  RDF triples, source
geometry and raw attributes remain behind the WorldModel ports; downstream
stages use the snapshot/ref for lineage and resolve geometry back through
DATA.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.cognition.decision import (
    SCHEMA_MAPPING_CODE_CONTRACT_VERSION,
    SourceSemanticMappingSnapshot,
)
from app.contracts.cognition.snapshot import SessionWorldModelSnapshot
from app.contracts.cognition.stage_contracts import (
    CognitionGapRecord,
    CognitionStageSnapshot,
)
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    load_artifact,
    store_artifact,
)
from app.infrastructure.cognition_runtime.world_model_store import get_world_model_store
from app.infrastructure.paths import run_tmp_root
from app.workflow.stage_adapter import persist_gate_decision


_GAP_SOURCE_SAMPLE_LIMIT = 16


class CognitionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    branch_id: str = Field(default="main", min_length=1)
    source_snapshot_ref: str = ""
    previous_world_model_ref: str = ""
    context_version: str = ""
    context_ref: dict[str, Any] = Field(default_factory=dict)


class CognitionRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: CognitionRunRequest
    schema_mapping_snapshot: SourceSemanticMappingSnapshot
    snapshot: SessionWorldModelSnapshot
    stage_snapshot: CognitionStageSnapshot
    snapshot_ref: ArtifactRef
    schema_mapping_ref: ArtifactRef
    stage_ref: ArtifactRef
    gate_ref: ArtifactRef
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "schema_mapping_snapshot": self.schema_mapping_ref.model_dump(mode="json"),
            "world_model_snapshot": self.snapshot_ref.model_dump(mode="json"),
            "kg_stage": self.stage_ref.model_dump(mode="json"),
            "kg_gate": self.gate_ref.model_dump(mode="json"),
        }
        patch.update({
            "world_model_snapshot_ref": self.snapshot.snapshot_ref,
            "world_model_snapshot_digest": self.snapshot.graph_digest,
        })
        return patch


def _descriptor_digest(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("descriptor_digest") or value.get("digest") or "")
    return str(getattr(value, "descriptor_digest", "") or getattr(value, "digest", "") or "")


def _summarize_world_model(
    store: Any,
    snapshot: SessionWorldModelSnapshot,
    schema_mapping_snapshot: Any,
) -> dict[str, Any]:
    """Summarize existence, semantic resolution and geometry lineage separately.

    A missing authoritative name/ID is not a missing entity. Schema gaps are
    collection-scoped and point to the complete mapping artifact rather than
    being repeated for every feature. No gap list is silently truncated.
    """

    from rdflib import RDF

    from app.infrastructure.kg.ontology import PLN

    graph = getattr(store, "g", None)
    if graph is None:
        return {
            "entity_part_count": 0,
            "observed_entity_count": 0,
            "source_local_entity_count": 0,
            "accepted_semantic_entity_count": 0,
            "unresolved_entity_count": 0,
            "ambiguous_entity_count": 0,
            "available_representation_count": 0,
            "unresolved_representation_count": 0,
            "capability_count": 0,
            "gaps": (),
            "diagnostics": ("world_model_graph_unavailable",),
        }

    entities = tuple(graph.subjects(RDF.type, PLN.WorldEntity))
    parts = tuple(graph.subjects(RDF.type, PLN.EntityPart))
    representations = tuple(graph.subjects(RDF.type, PLN.SpatialRepresentation))
    catalog_snapshot = getattr(getattr(store, "catalog", None), "snapshot", None)
    capabilities = tuple(
        catalog_snapshot.capabilities if catalog_snapshot is not None else ()
    )
    catalog_features = tuple(
        catalog_snapshot.features if catalog_snapshot is not None else ()
    )
    feature_by_key = {
        (
            str(getattr(item, "dataset_ref", "") or ""),
            str(getattr(item, "source_feature_ref", "") or ""),
        ): item
        for item in catalog_features
    }
    feature_by_resource = {
        (
            f"resource:{getattr(item, 'dataset_ref', '')}:"
            f"{getattr(item, 'source_feature_ref', '')}"
        ): item
        for item in catalog_features
    }
    features_by_bare_ref: dict[str, list[Any]] = {}
    for item in catalog_features:
        features_by_bare_ref.setdefault(
            str(getattr(item, "source_feature_ref", "") or ""),
            [],
        ).append(item)

    def feature_for_lineage(
        dataset_ref: str,
        source_feature_ref: str,
    ) -> Any:
        if dataset_ref:
            return feature_by_key.get((dataset_ref, source_feature_ref))
        matches = features_by_bare_ref.get(source_feature_ref, ())
        return matches[0] if len(matches) == 1 else None

    def feature_for_component(component_ref: str) -> Any:
        direct = feature_by_resource.get(component_ref)
        if direct is not None:
            return direct
        matches = features_by_bare_ref.get(component_ref, ())
        return matches[0] if len(matches) == 1 else None

    observed = unresolved = ambiguous = 0
    source_local = accepted_semantic = 0
    gaps: list[CognitionGapRecord] = []

    def add_gap(
        *,
        subject_refs: tuple[str, ...],
        reason: str,
        missing_fields: tuple[str, ...],
        earliest: str = "evidence",
        subject_count: int = 0,
        subject_digest: str = "",
        mapping_decision_ref: str = "",
        recovery_pointer: str = "",
    ) -> None:
        payload = {
            "source_catalog_digest": snapshot.source_catalog_digest,
            "subject_refs": subject_refs,
            "reason": reason,
            "missing_fields": missing_fields,
        }
        gap_ref = "kg.gap." + semantic_checksum(payload)[:24]
        gaps.append(
            CognitionGapRecord(
                artifact_id=gap_ref,
                gap_ref=gap_ref,
                subject_refs=subject_refs,
                subject_count=subject_count,
                subject_digest=subject_digest,
                mapping_decision_ref=mapping_decision_ref,
                source_catalog_digest=snapshot.source_catalog_digest,
                missing_fields=missing_fields,
                reason=reason,
                earliest_resolution_stage=earliest,
                recovery_pointer=(
                    recovery_pointer
                    or (f"kg-entity:{subject_refs[0]}" if subject_refs else "kg-snapshot")
                ),
            )
        )

    for entity in entities:
        status = str(graph.value(entity, PLN.entityStatus) or "unresolved").casefold()
        if status == "ambiguous":
            ambiguous += 1
        elif status == "observed":
            observed += 1
        else:
            unresolved += 1
        identity_status = str(
            graph.value(entity, PLN.identityResolutionStatus) or "source_local"
        ).casefold()
        if identity_status == "source_local":
            source_local += 1
        semantic_status = str(
            graph.value(entity, PLN.semanticStatus) or "unresolved"
        ).casefold()
        if semantic_status == "accepted":
            accepted_semantic += 1
        if identity_status == "ambiguous":
            source_refs = tuple(sorted({
                (
                    f"resource:{graph.value(part, PLN.sourceDatasetRef)}:"
                    f"{value}"
                )
                for part in graph.objects(entity, PLN.hasEntityPart)
                for value in graph.objects(part, PLN.sourceFeatureRef)
                if str(value).strip()
                and str(graph.value(part, PLN.sourceDatasetRef) or "").strip()
            }))
            add_gap(
                subject_refs=(str(entity),),
                subject_count=len(source_refs),
                subject_digest="sha256:" + semantic_checksum(source_refs),
                reason="entity_identity_ambiguous",
                missing_fields=("accepted_semantic_identity",),
                earliest="evidence",
                recovery_pointer=f"kg-entity:{entity}",
            )

    profiles = {
        str(getattr(item, "collection_ref", "") or ""): item
        for item in tuple(
            getattr(schema_mapping_snapshot, "collection_profiles", ()) or ()
        )
    }
    schema_decisions = tuple(
        getattr(schema_mapping_snapshot, "decisions", ()) or ()
    )
    spatial_kinds = {"point", "line", "polygon", "multipatch"}
    for decision in schema_decisions:
        field_name = str(getattr(decision, "field_name", "") or "")
        if field_name != "__concept__" and not field_name.startswith(
            "__representation__:"
        ):
            continue
        if str(getattr(decision, "status", "") or "") == "accepted":
            continue
        collection_ref = str(
            getattr(decision, "collection_ref", "") or ""
        )
        profile = profiles.get(collection_ref)
        if profile is None or not spatial_kinds.intersection({
            str(value).casefold()
            for value in getattr(profile, "geometry_kinds", ()) or ()
        }):
            continue
        decision_ref = str(
            getattr(decision, "decision_ref", "") or collection_ref
        )
        source_refs = tuple(
            str(value)
            for value in (
                getattr(profile, "source_record_refs", ())
                or getattr(profile, "source_feature_refs", ())
                or ()
            )
            if str(value).strip()
        )
        is_concept = field_name == "__concept__"
        add_gap(
            # Keep the scheduler row flat and bounded.  The complete
            # collection is represented by subject_count + subject_digest;
            # this exact DATA sample lets EVIDENCE attach local rows now and
            # lets L1 reason without receiving thousands of nested features.
            subject_refs=(
                decision_ref,
                collection_ref,
                *source_refs[:_GAP_SOURCE_SAMPLE_LIMIT],
            ),
            subject_count=len(source_refs),
            subject_digest="sha256:" + semantic_checksum(source_refs),
            mapping_decision_ref=decision_ref,
            reason=(
                "collection_semantics_unresolved"
                if is_concept
                else "representation_role_unresolved"
            ),
            missing_fields=(
                "accepted_collection_concept"
                if is_concept
                else "accepted_representation_role",
            ),
            earliest="evidence",
            recovery_pointer=f"schema-mapping:{decision_ref}",
        )

    available_representations = 0
    unresolved_representations = 0
    for representation in representations:
        source_dataset_ref = str(
            graph.value(representation, PLN.sourceDatasetRef) or ""
        )
        source_ref = str(graph.value(representation, PLN.sourceFeatureRef) or "")
        # Source refs are attached to the EntityPart rather than the
        # representation node in the projection; recover them from the
        # inverse relation when necessary.
        if not source_ref:
            owner_part = next(
                iter(graph.subjects(PLN.hasSpatialRepresentation, representation)),
                None,
            )
            if owner_part is not None:
                source_ref = str(
                    graph.value(owner_part, PLN.sourceFeatureRef) or ""
                )
                source_dataset_ref = source_dataset_ref or str(
                    graph.value(owner_part, PLN.sourceDatasetRef) or ""
                )
        resource_ref = str(graph.value(representation, PLN.resourceRef) or "")
        geometry_ref = str(graph.value(representation, PLN.geometryRef) or "")
        source_snapshot_ref = str(graph.value(representation, PLN.sourceSnapshotRef) or "")
        component_refs = tuple(
            str(value)
            for value in graph.objects(representation, PLN.componentRef)
            if str(value).strip()
        )
        feature = feature_for_lineage(source_dataset_ref, source_ref)
        component_features = tuple(
            feature_for_component(component_ref)
            for component_ref in component_refs
        )
        components_available = bool(component_refs) and all(
            item is not None
            and getattr(item, "normalized_geometry", None) is not None
            for item in component_features
        )
        source_geometry_available = bool(
            feature is not None
            and (
                getattr(feature, "normalized_geometry", None) is not None
                or str(getattr(feature, "geometry_kind", "") or "") == "raster"
            )
        )
        # Derived representations are semantically available but intentionally
        # not directly executable; their component refs are the only valid
        # route back to DATA geometry.
        is_available = bool(
            components_available
            or (
                resource_ref
                and geometry_ref
                and source_snapshot_ref
                and (feature is None or source_geometry_available)
            )
        )
        if is_available:
            available_representations += 1
        else:
            unresolved_representations += 1
            rep_ref = str(graph.value(representation, PLN.representationRef) or representation)
            add_gap(
                subject_refs=(
                    (
                        rep_ref,
                        f"resource:{source_dataset_ref}:{source_ref}",
                    )
                    if source_ref and source_dataset_ref
                    else (rep_ref, *component_refs)
                ),
                reason="spatial_representation_lineage_unresolved",
                missing_fields=tuple(
                    field
                    for field, value in (
                        ("resource_ref", resource_ref),
                        ("geometry_ref", geometry_ref),
                        ("source_snapshot_ref", source_snapshot_ref),
                    )
                    if not value
                ) or ("normalized_geometry",),
            )

    unique_gaps = {item.gap_ref: item for item in gaps}
    ordered_gaps = tuple(unique_gaps[key] for key in sorted(unique_gaps))
    accepted_schema = sum(
        str(getattr(item, "status", "") or "") == "accepted"
        for item in schema_decisions
    )
    unresolved_schema = len(schema_decisions) - accepted_schema
    diagnostics = (
        f"entities={len(entities)}",
        f"parts={len(parts)}",
        f"representations={len(representations)}",
        f"capabilities={len(capabilities)}",
        f"semantic_gaps={len(unique_gaps)}",
        f"collection_profiles={len(profiles)}",
        f"schema_decisions={len(schema_decisions)}",
        f"schema_unresolved={unresolved_schema}",
    )
    return {
        "entity_part_count": len(parts),
        "observed_entity_count": observed,
        "source_local_entity_count": source_local,
        "accepted_semantic_entity_count": accepted_semantic,
        "unresolved_entity_count": unresolved,
        "ambiguous_entity_count": ambiguous,
        "available_representation_count": available_representations,
        "unresolved_representation_count": unresolved_representations,
        "capability_count": len(capabilities),
        "collection_profile_count": len(profiles),
        "schema_decision_count": len(schema_decisions),
        "accepted_schema_decision_count": accepted_schema,
        "unresolved_schema_decision_count": unresolved_schema,
        "gaps": ordered_gaps,
        "diagnostics": diagnostics,
    }


class CognitionApplication:
    """Bootstrap and reload the KG-backed World Model."""

    @staticmethod
    def _artifact_state(
        state: Mapping[str, Any] | None,
        *,
        session_id: str,
        refs: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(state or {})
        result.setdefault("session_id", session_id)
        result.setdefault("run_id", session_id)
        result.setdefault("artifact_root", str(run_tmp_root()))
        result.setdefault("artifact_schema_version", "3")
        result.setdefault("branch_id", "main")
        result["artifact_refs"] = dict(refs)
        return result

    @staticmethod
    def _request(
        session_id: str,
        source_snapshot_ref: str,
        *,
        previous_world_model_ref: str,
        state: Mapping[str, Any] | None,
    ) -> CognitionRunRequest:
        values = dict(state or {})
        return CognitionRunRequest(
            run_id=str(values.get("run_id") or session_id),
            session_id=str(values.get("session_id") or session_id),
            branch_id=str(values.get("branch_id") or "main"),
            source_snapshot_ref=str(source_snapshot_ref or ""),
            previous_world_model_ref=str(previous_world_model_ref or ""),
            context_version=str(values.get("context_version") or ""),
            context_ref=dict(values.get("context_ref") or {}),
        )

    @staticmethod
    def _load_reusable_schema_mapping(
        state: Mapping[str, Any],
        catalog: Any,
        *,
        source_snapshot_ref: str,
        data_snapshot_id: str,
        data_digest: str,
        enabled: bool | None,
    ) -> SourceSemanticMappingSnapshot | None:
        """Load a mapping only when every builder input is proven identical.

        A named ref is merely a lookup pointer.  Reuse is deliberately
        fail-closed: old artifacts, incomplete metadata, changed DATA,
        changed candidate sets, and changed implementation contracts all
        return ``None`` and force the normal builder path.
        """

        refs = dict(state.get("artifact_refs") or {})
        if not refs.get("schema_mapping_snapshot"):
            return None
        try:
            mapping = load_artifact(
                dict(state),
                "schema_mapping_snapshot",
                SourceSemanticMappingSnapshot,
            )
            if mapping is None:
                return None
            mapping_ref = ArtifactRef.model_validate(
                refs["schema_mapping_snapshot"]
            )
            for parent_key in (
                "data_catalog",
                "data_snapshot",
                "data_stage",
                "data_gate",
            ):
                raw_parent_ref = refs.get(parent_key)
                if not raw_parent_ref:
                    return None
                parent_ref = ArtifactRef.model_validate(raw_parent_ref)
                if (
                    mapping_ref.parent_digests.get(parent_key)
                    != parent_ref.digest
                ):
                    return None
            expected_source_ref = str(data_snapshot_id or source_snapshot_ref or "")
            expected_source_digest = str(data_digest or "")
            if not expected_source_ref or not expected_source_digest:
                return None
            if (
                mapping.source_snapshot_ref != expected_source_ref
                or mapping.source_snapshot_digest != expected_source_digest
            ):
                return None

            # These are the exact deterministic inputs used by the builder;
            # constructing them does not invoke the LLM.
            from app.modules.cognition.schema_understanding import (
                _digest,
                _mapping_rows,
                build_collection_profiles,
            )
            from app.infrastructure.cognition_runtime.schema_matcher import (
                candidate_digest,
            )

            profiles = build_collection_profiles(catalog)
            rows, membership = _mapping_rows(profiles)
            expected_profile_digest = _digest([
                item.model_dump(mode="json") for item in profiles
            ])
            expected_input_digest = _digest(rows)
            expected_candidate_digest = candidate_digest({
                f"{collection}:{field}": refs
                for (collection, field), refs in membership.items()
            })
            if (
                mapping.profile_digest != expected_profile_digest
                or mapping.input_digest != expected_input_digest
                or mapping.candidate_digest != expected_candidate_digest
            ):
                return None

            from app.core.settings import LLM_MODEL, SOURCE_SEMANTIC_LLM_ENABLED

            effective_enabled = (
                bool(enabled)
                if enabled is not None
                else bool(SOURCE_SEMANTIC_LLM_ENABLED)
            )
            expected_model_id = (
                str(LLM_MODEL or "configured-default")
                if effective_enabled
                else "disabled"
            )
            if (
                mapping.prompt_version != "schema-mapping-v2"
                or mapping.code_contract_version
                != SCHEMA_MAPPING_CODE_CONTRACT_VERSION
                or mapping.model_id != expected_model_id
                or not mapping.mapping_fingerprint
                or not mapping.decision_fingerprint
            ):
                return None

            # Verify the durable snapshot's internal fingerprints too.  This
            # prevents a structurally valid artifact with copied metadata
            # from qualifying as an exact hit.
            decision_payload = [
                item.model_dump(mode="json") for item in mapping.decisions
            ]
            expected_decision_fingerprint = _digest(decision_payload)
            expected_mapping_fingerprint = _digest({
                "source_snapshot_ref": mapping.source_snapshot_ref,
                "source_snapshot_digest": mapping.source_snapshot_digest,
                "profile_digest": mapping.profile_digest,
                "input_digest": mapping.input_digest,
                "candidate_digest": mapping.candidate_digest,
                "prompt_version": mapping.prompt_version,
                "code_contract_version": mapping.code_contract_version,
                "model_id": mapping.model_id,
                "raw_output_digest": mapping.raw_output_digest,
                "decision_fingerprint": expected_decision_fingerprint,
                "verifier_findings": mapping.verifier_findings,
            })
            if (
                mapping.decision_fingerprint != expected_decision_fingerprint
                or mapping.mapping_fingerprint != expected_mapping_fingerprint
            ):
                return None
            return mapping
        except Exception as exc:
            # A malformed, cross-run or cross-branch CAS ref is checkpoint
            # corruption, not a cache miss.  Do not hide it behind an LLM
            # rebuild that would consume quota before the write fails.
            raise ArtifactReplayError(
                "schema mapping CAS reuse validation failed"
            ) from exc

    async def bootstrap(
        self,
        session_id: str,
        source_snapshot_ref: str,
        *,
        previous_world_model_ref: str = "",
        catalog: Any = None,
        state: Mapping[str, Any] | None = None,
        village_name: str = "",
        external_observation_snapshot: Any = None,
    ) -> CognitionRunResult:
        """Project ``catalog`` and persist a World Model snapshot.

        ``source_snapshot_ref`` is checked against the DATA snapshot id or
        digest when either is available.  It is a lineage assertion, not an
        instruction to load geometry from the KG.
        """

        session_id = str(session_id or "").strip()
        if not session_id:
            raise ValueError("CognitionApplication.bootstrap requires session_id")
        if state is None:
            raise RuntimeError(
                "KG bootstrap requires DATA artifact/gate state for lineage validation"
            )
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(dict(state), ("data",))
        request = self._request(
            session_id,
            source_snapshot_ref,
            previous_world_model_ref=previous_world_model_ref,
            state=state,
        )
        if catalog is None and state is not None:
            catalog = state.get("data_catalog")
        if catalog is None or getattr(catalog, "snapshot", None) is None:
            raise RuntimeError("KG bootstrap requires a normalized DATA catalog")
        snapshot_input = getattr(catalog, "snapshot", catalog)
        catalog_snapshot_id = str(getattr(snapshot_input, "snapshot_id", "") or "")
        catalog_digest = str(getattr(snapshot_input, "digest", "") or "")
        from app.data.model.snapshot import SessionDataSnapshot

        data_manifest = load_artifact(
            dict(state),
            "data_snapshot",
            SessionDataSnapshot,
        )
        data_snapshot_id = str(
            getattr(data_manifest, "snapshot_id", "")
            or catalog_snapshot_id
            or ""
        )
        data_snapshot_digest = str(getattr(data_manifest, "digest", "") or "")
        if source_snapshot_ref and source_snapshot_ref not in {
            catalog_snapshot_id,
            data_snapshot_id,
            catalog_digest,
        }:
            raise RuntimeError(
                "World Model source snapshot does not match DATA: "
                f"expected={source_snapshot_ref} actual={catalog_snapshot_id or data_snapshot_id}"
            )
        from app.data.admission import assert_cognition_ready_catalog

        assert_cognition_ready_catalog(snapshot_input)
        from app.modules.cognition.schema_understanding import (
            build_schema_mapping_snapshot_async,
        )

        configured_semantics = (state.get("config") or {}).get(
            "source_semantic_llm_enabled"
        )
        effective_enabled = (
            bool(configured_semantics) if configured_semantics is not None else None
        )
        schema_mapping = self._load_reusable_schema_mapping(
            state,
            catalog,
            source_snapshot_ref=source_snapshot_ref,
            data_snapshot_id=data_snapshot_id,
            data_digest=catalog_digest,
            enabled=effective_enabled,
        )
        if schema_mapping is None:
            schema_mapping = await build_schema_mapping_snapshot_async(
                catalog,
                source_snapshot_ref=data_snapshot_id or source_snapshot_ref,
                enabled=effective_enabled,
            )
        refs = dict((state or {}).get("artifact_refs") or {})
        artifact_state = self._artifact_state(
            state,
            session_id=session_id,
            refs=refs,
        )
        schema_mapping_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "schema_mapping_snapshot",
                "kg",
                "SourceSemanticMappingSnapshot",
                schema_mapping,
                parent_keys=(
                    "data_catalog",
                    "data_snapshot",
                    "data_stage",
                    "data_gate",
                ),
            )
        )
        refs["schema_mapping_snapshot"] = schema_mapping_ref.model_dump(mode="json")
        store = get_world_model_store(
            session_id,
            village_name or str((state or {}).get("village_name") or ""),
            catalog,
            schema_mapping_snapshot=schema_mapping,
            schema_mapping_artifact_ref=_descriptor_digest(schema_mapping_ref),
            artifact_root=str(artifact_state.get("artifact_root") or ""),
        )
        # External observations remain DATA/Evidence products here.  They may
        # be used for spatial blocking and closed-set entity support, but a raw
        # provider snapshot is not a validated Cognition change set.  Only an
        # accepted EntitySupportProposal may advance the World Model through
        # its commit port; bootstrap therefore never writes provider geometry
        # or aliases into the graph directly.
        snapshot = store.snapshot_contract()
        quality = _summarize_world_model(store, snapshot, schema_mapping)
        if previous_world_model_ref and previous_world_model_ref == snapshot.snapshot_ref:
            # The store is content-addressed; retaining the pointer is safe
            # and avoids a spurious cognition revision.
            pass
        artifact_state = self._artifact_state(
            state,
            session_id=session_id,
            refs=refs,
        )
        snapshot_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "world_model_snapshot",
                "kg",
                "SessionWorldModelSnapshot",
                snapshot,
                parent_keys=(
                    "data_catalog",
                    "data_snapshot",
                    "data_stage",
                    "data_gate",
                    "schema_mapping_snapshot",
                ),
            )
        )
        refs["world_model_snapshot"] = snapshot_ref.model_dump(mode="json")

        # Cognition changes the authority carried by PlanningContext.  Publish
        # a new frozen Context immediately after the World Model snapshot is
        # durable; mutating the DATA-stage Context in one workflow node leaves
        # resumed workers and other callers with a stale, port-less cache.
        from app.infrastructure.context_runtime.manager import (
            build_planning_context,
            get_cached_context,
        )

        cached_context = get_cached_context(session_id)
        context_ref = dict((state or {}).get("context_ref") or {})
        expected_data_digest = str(
            data_snapshot_digest
            or context_ref.get("snapshot_digest")
            or context_ref.get("data_snapshot_digest")
            or getattr(
                getattr(cached_context, "data_snapshot", None),
                "digest",
                "",
            )
            or ""
        ).strip()
        context_version_text = str(
            request.context_version
            or context_ref.get("version")
            or getattr(cached_context, "version", "")
            or ""
        )
        refreshed_context = await build_planning_context(
            session_id,
            village_name=(
                village_name
                or str(((state or {}).get("config") or {}).get("village_name") or "")
                or str((state or {}).get("village_name") or "")
            ),
            refresh=True,
            include_reports=False,
            version=(
                int(context_version_text)
                if context_version_text.isdigit()
                else None
            ),
            expected_snapshot_digest=expected_data_digest or None,
            expected_world_model_digest=snapshot.graph_digest,
            data_catalog=catalog,
            schema_mapping_snapshot=schema_mapping,
            schema_mapping_artifact_ref=_descriptor_digest(schema_mapping_ref),
            artifact_root=str(artifact_state.get("artifact_root") or ""),
            defer_cognition_bootstrap=False,
        )
        context_world_model = getattr(refreshed_context, "world_model", None)
        context_ports = getattr(refreshed_context, "ports", None)
        if (
            context_world_model is None
            or getattr(context_ports, "world_model", None) is None
            or getattr(context_ports, "world_model_commit", None) is None
        ):
            raise RuntimeError(
                "KG_CONTEXT_PUBLICATION_FAILED: WorldModel read/commit ports are unavailable"
            )
        if str(getattr(context_world_model, "snapshot_digest", "") or "") != str(
            snapshot.graph_digest
        ):
            raise RuntimeError(
                "KG_CONTEXT_PUBLICATION_FAILED: WorldModel digest mismatch"
            )
        published_context_version = str(
            request.context_version
            or (state.get("context_ref") or {}).get("version")
            or "1"
        )
        published_context_fingerprint = str(
            state.get("context_fingerprint")
            or (
                "sha256:" + str(getattr(refreshed_context, "content_hash", ""))[:16]
                if str(getattr(refreshed_context, "content_hash", "") or "")
                else ""
            )
        )
        published_context_ref = {
            **dict(state.get("context_ref") or {}),
            "session_id": session_id,
            "version": published_context_version,
            "snapshot_id": data_snapshot_id,
            "snapshot_digest": data_snapshot_digest,
            "data_snapshot_digest": data_snapshot_digest,
            "data_resource_catalog_digest": str(
                catalog_digest
                or getattr(getattr(catalog, "snapshot", None), "digest", "")
                or ""
            ),
            "world_model_mode": str(
                getattr(refreshed_context, "world_model_mode", "") or ""
            ),
            "world_model_snapshot_ref": snapshot.snapshot_ref,
            "world_model_snapshot_digest": snapshot.graph_digest,
        }
        request = request.model_copy(update={
            "context_version": published_context_version,
            "context_ref": published_context_ref,
        })
        published_state = {
            **state,
            "context_version": published_context_version,
            "context_fingerprint": published_context_fingerprint,
            "context_ref": published_context_ref,
        }
        artifact_state = self._artifact_state(
            published_state,
            session_id=session_id,
            refs=refs,
        )
        hard_gaps = tuple(
            item
            for item in quality["gaps"]
            if item.reason == "spatial_representation_lineage_unresolved"
        )
        stage_snapshot = CognitionStageSnapshot(
            context_version=published_context_version,
            context_fingerprint=published_context_fingerprint,
            artifact_id="kg-" + semantic_checksum({
                "snapshot": snapshot_ref.digest,
                "world_model": snapshot.graph_digest,
            })[:16],
            status="blocked" if hard_gaps else "ready",
            world_model_ref=snapshot.snapshot_ref,
            world_model_snapshot_ref=snapshot.snapshot_ref,
            world_model_snapshot_digest=snapshot.graph_digest,
            source_catalog_ref=snapshot.source_catalog_ref,
            source_catalog_digest=snapshot.source_catalog_digest,
            schema_mapping_ref=_descriptor_digest(schema_mapping_ref),
            schema_mapping_digest=(
                schema_mapping.mapping_fingerprint
                or schema_mapping.decision_fingerprint
            ),
            version=snapshot.version,
            entity_count=len(snapshot.entity_refs),
            entity_part_count=int(quality["entity_part_count"]),
            observed_entity_count=int(quality["observed_entity_count"]),
            source_local_entity_count=int(quality["source_local_entity_count"]),
            accepted_semantic_entity_count=int(
                quality["accepted_semantic_entity_count"]
            ),
            unresolved_entity_count=int(quality["unresolved_entity_count"]),
            ambiguous_entity_count=int(quality["ambiguous_entity_count"]),
            representation_count=len(snapshot.representation_refs),
            available_representation_count=int(quality["available_representation_count"]),
            unresolved_representation_count=int(quality["unresolved_representation_count"]),
            assertion_count=len(snapshot.assertion_refs),
            capability_count=int(quality["capability_count"]),
            collection_profile_count=int(quality["collection_profile_count"]),
            schema_decision_count=int(quality["schema_decision_count"]),
            accepted_schema_decision_count=int(
                quality["accepted_schema_decision_count"]
            ),
            unresolved_schema_decision_count=int(
                quality["unresolved_schema_decision_count"]
            ),
            gap_count=len(quality["gaps"]),
            diagnostics=tuple(quality["diagnostics"]),
            gap_refs=tuple(item.gap_ref for item in quality["gaps"]),
            gaps=tuple(quality["gaps"]),
            data_dependency_graph_digest=str(state.get("data_dependency_graph_digest") or ""),
        )
        stage_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "kg_stage",
                "kg",
                "CognitionStageSnapshot",
                stage_snapshot,
                parent_keys=(
                    "data_catalog",
                    "data_snapshot",
                    "data_stage",
                    "data_gate",
                    "schema_mapping_snapshot",
                    "world_model_snapshot",
                ),
            )
        )
        refs["kg_stage"] = stage_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(
            published_state,
            session_id=session_id,
            refs=refs,
        )
        evidence_gap_refs = [
            item.gap_ref
            for item in quality["gaps"]
            if item.reason != "spatial_representation_lineage_unresolved"
        ]
        pending_requests = []
        if hard_gaps:
            pending_requests.append(PendingRequest(
                request_id="pr-kg-data-lineage",
                stage="kg",
                request_type="data_representation_recovery",
                context={
                    "gap_refs": [item.gap_ref for item in hard_gaps],
                    "source_catalog_digest": snapshot.source_catalog_digest,
                },
            ))
        gate = GateDecision(
            stage="kg",
            passed=not hard_gaps,
            feedback_route="DATA" if hard_gaps else None,
            pending_requests=pending_requests,
            # Semantic/identity gaps are part of the typed Cognition stage
            # product.  EVIDENCE consumes them from ``kg_stage.gaps`` and
            # publishes its own bounded schedule for L1.  Keeping the same
            # refs on a passed KG gate makes every later strict gate consumer
            # treat an otherwise usable World Model as permanently pending.
            evidence_requests=[],
            context_version=published_context_version,
            artifact_id="gate-kg-" + semantic_checksum({
                "stage": stage_ref.digest,
                "world_model": snapshot.graph_digest,
            })[:16],
            route_reason=(
                "data_representation_lineage_blocked"
                if hard_gaps
                else (
                    "world_model_ready_with_evidence_gaps"
                    if evidence_gap_refs
                    else "world_model_ready"
                )
            ),
        )
        gate_ref = persist_gate_decision(
            artifact_state,
            "kg",
            gate,
            output_refs={
                "schema_mapping_snapshot": schema_mapping_ref,
                "world_model_snapshot": snapshot_ref,
                "kg_stage": stage_ref,
            },
        )
        return CognitionRunResult(
            request=request,
            schema_mapping_snapshot=schema_mapping,
            snapshot=SessionWorldModelSnapshot.model_validate(snapshot),
            stage_snapshot=stage_snapshot,
            snapshot_ref=snapshot_ref,
            schema_mapping_ref=schema_mapping_ref,
            stage_ref=stage_ref,
            gate_ref=gate_ref,
            state_patch={
                "artifact_refs": refs,
                "context_version": published_context_version,
                "context_fingerprint": published_context_fingerprint,
                "context_ref": published_context_ref,
                "world_model_snapshot_ref": snapshot.snapshot_ref,
                "world_model_snapshot_digest": snapshot.graph_digest,
                "schema_mapping_digest": (
                    schema_mapping.mapping_fingerprint
                    or schema_mapping.decision_fingerprint
                ),
                "kg_stage_status": stage_snapshot.status,
                "kg_gap_refs": list(stage_snapshot.gap_refs),
            },
        )

    @staticmethod
    def load_snapshot(state: Mapping[str, Any]) -> SessionWorldModelSnapshot | None:
        return load_artifact(dict(state), "world_model_snapshot", SessionWorldModelSnapshot)

    @staticmethod
    def load_current_snapshot(
        state: Mapping[str, Any],
    ) -> SessionWorldModelSnapshot | None:
        """Reload the latest committed World Model child when one exists."""

        return load_artifact(
            dict(state),
            "world_model_current_snapshot",
            SessionWorldModelSnapshot,
        ) or CognitionApplication.load_snapshot(state)

    def commit_proposal_batch(
        self,
        state: Mapping[str, Any],
        batch: Any,
    ) -> Any:
        """Route one immutable proposal batch through Cognition's write port."""

        from app.contracts.cognition.proposals import (
            WorldModelCommitResult,
            WorldModelProposalBatch,
        )

        typed_batch = WorldModelProposalBatch.model_validate(batch)
        current = dict(state)
        refs = dict(current.get("artifact_refs") or {})
        parent_key = "world_model_current_snapshot" if refs.get(
            "world_model_current_snapshot"
        ) else "world_model_snapshot"
        parent_snapshot = load_artifact(
            current,
            parent_key,
            SessionWorldModelSnapshot,
        )
        if parent_snapshot is None:
            raise ArtifactReplayError(
                "World Model proposal commit requires a reloadable parent snapshot"
            )
        commit_port = None
        session_id = str(current.get("session_id") or "")
        if session_id:
            try:
                from app.infrastructure.context_runtime.manager import get_cached_context

                cached = get_cached_context(session_id)
                commit_port = getattr(
                    getattr(cached, "ports", None),
                    "world_model_commit",
                    None,
                )
            except Exception:
                commit_port = None
        if not callable(getattr(commit_port, "commit_proposal_batch", None)):
            from app.contracts.cognition.decision import SourceSemanticMappingSnapshot
            from app.data.resource_catalog import DataResourceCatalog
            from app.modules.data.application import DataApplication
            from app.infrastructure.cognition_runtime.world_model_store import get_world_model_store

            catalog_snapshot = DataApplication.load_catalog(current)
            if catalog_snapshot is None:
                raise ArtifactReplayError(
                    "World Model proposal commit requires a DATA catalog"
                )
            mapping = load_artifact(
                current,
                "schema_mapping_snapshot",
                SourceSemanticMappingSnapshot,
            )
            mapping_ref = refs.get("schema_mapping_snapshot") or {}
            mapping_descriptor_digest = (
                str(mapping_ref.get("descriptor_digest") or "")
                if isinstance(mapping_ref, Mapping)
                else str(getattr(mapping_ref, "descriptor_digest", "") or "")
            )
            store = get_world_model_store(
                session_id,
                str((current.get("config") or {}).get("village_name") or ""),
                DataResourceCatalog(catalog_snapshot),
                schema_mapping_snapshot=mapping,
                schema_mapping_artifact_ref=mapping_descriptor_digest,
                artifact_root=str(current.get("artifact_root") or ""),
                expected_snapshot_digest=parent_snapshot.graph_digest,
            )
            commit_port = store
        outcome = WorldModelCommitResult.model_validate(
            commit_port.commit_proposal_batch(typed_batch)
        )
        if outcome.status == "noop":
            current_ref = refs.get("world_model_current_snapshot") or refs.get(
                "world_model_snapshot"
            )
            if current_ref:
                return outcome.model_copy(update={
                    "world_model_artifact_ref": ArtifactRef.model_validate(current_ref),
                })
            return outcome
        if not outcome.committed or outcome.world_model_snapshot is None:
            return outcome

        commit_state = {
            **current,
            "artifact_refs": refs,
        }
        committed_ref = ArtifactRef.model_validate(
            store_artifact(
                commit_state,
                "world_model_commit_snapshot",
                "cognition",
                "SessionWorldModelSnapshot",
                outcome.world_model_snapshot,
                parent_keys=(parent_key,),
            )
        )
        refs["world_model_commit_snapshot"] = committed_ref.model_dump(mode="json")
        commit_state["artifact_refs"] = refs
        current_ref = ArtifactRef.model_validate(
            store_artifact(
                commit_state,
                "world_model_current_snapshot",
                "cognition",
                "SessionWorldModelSnapshot",
                outcome.world_model_snapshot,
                parent_keys=("world_model_commit_snapshot",),
            )
        )
        return outcome.model_copy(update={"world_model_artifact_ref": current_ref})

    @staticmethod
    def load_schema_mapping(
        state: Mapping[str, Any],
    ) -> SourceSemanticMappingSnapshot | None:
        return load_artifact(
            dict(state),
            "schema_mapping_snapshot",
            SourceSemanticMappingSnapshot,
        )

    @staticmethod
    def load_stage(state: Mapping[str, Any]) -> CognitionStageSnapshot | None:
        return load_artifact(dict(state), "kg_stage", CognitionStageSnapshot)


__all__ = ["CognitionApplication", "CognitionRunRequest", "CognitionRunResult"]
