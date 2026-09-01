"""Public DATA application facade.

The facade owns the DATA-to-CAS boundary.  It accepts a normalized
``DataResourceCatalog`` (or lossless records), creates the session manifest,
and returns only typed products and immutable references.  Planning stages do
not need to know how a file was decoded or which source fields were present.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.data.source_contracts import DataResourceCatalogSnapshot
from app.contracts.data.admission_contracts import (
    DataAdmissionGap,
    DataAdmissionReceipt,
    DataAdmissionRequest,
    DataAdmissionResult,
)
from app.contracts.data.source_contracts import SourceAdmissionDecision
from app.contracts.data.stage_contracts import DataGapRecord, DataStageSnapshot
from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest
from app.data.model.snapshot import SessionDataSnapshot
from app.data.resource_catalog import DataResourceCatalog
from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.infrastructure.artifacts.runtime import load_artifact
from app.infrastructure.artifacts.runtime import store_artifact
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.paths import run_tmp_root
from app.workflow.stage_adapter import persist_gate_decision


class DataRunRequest(BaseModel):
    """Minimal identity for one DATA normalization transaction."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    branch_id: str = Field(default="main", min_length=1)
    context_version: str = ""
    context_ref: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "DataRunRequest":
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            branch_id=str(state.get("branch_id") or "main"),
            context_version=str(state.get("context_version") or ""),
            context_ref=dict(state.get("context_ref") or {}),
        )


class DataRunResult(BaseModel):
    """Typed DATA products after CAS commit and reload."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: DataRunRequest
    catalog: DataResourceCatalogSnapshot
    data_snapshot: SessionDataSnapshot
    stage_snapshot: DataStageSnapshot
    catalog_ref: ArtifactRef
    data_snapshot_ref: ArtifactRef
    stage_ref: ArtifactRef
    gate_ref: ArtifactRef
    receipt_ref: str = ""
    gap_ref: str = ""
    lifecycle_state: str = ""
    lifecycle: tuple[str, ...] = ()
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "data_catalog": self.catalog_ref.model_dump(mode="json"),
            "data_snapshot": self.data_snapshot_ref.model_dump(mode="json"),
            "data_stage": self.stage_ref.model_dump(mode="json"),
            "data_gate": self.gate_ref.model_dump(mode="json"),
        }
        patch.update({
            "data_snapshot_id": self.data_snapshot.snapshot_id,
            "data_snapshot_digest": self.data_snapshot.digest,
        })
        return patch


class DataAdmissionFacade:
    """Canonical DATA entry point for explicitly declared local files."""

    @staticmethod
    def _attempt_ref(request: DataAdmissionRequest, value: Any) -> str:
        return "data.attempt." + semantic_checksum({
            "session_id": request.session_id,
            "source_ref": request.source_ref,
            "input": value,
            "media": request.declared_media_type,
            "encoding": request.declared_encoding,
            "crs": request.declared_crs,
            "adapter": request.adapter_hint,
            "role": request.expected_role,
            "parent_catalog_ref": request.parent_catalog_ref,
        })[:24]

    @staticmethod
    def _required_capability(request: DataAdmissionRequest) -> str:
        configured = str(
            (request.policy_context or {}).get("required_capability") or ""
        ).strip()
        if configured:
            return configured
        media = str(request.declared_media_type or "").strip()
        crs = str(request.declared_crs or "non-spatial").strip()
        return ":".join((request.adapter_hint, media, crs, request.expected_role))

    @staticmethod
    def _prepare_input(request: DataAdmissionRequest, value: Any) -> Any:
        """Materialize one declared file input into generic DATA records."""

        media = str(request.declared_media_type or "").strip().casefold()
        if media in {"geojson", "application/geo+json"}:
            path = None
            if isinstance(value, (str, Path)):
                candidate = Path(value)
                if candidate.is_file():
                    path = candidate
            if path is not None:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                source_uri = str(path)
            elif isinstance(value, Mapping):
                payload = dict(value)
                source_uri = request.source_ref
            else:
                raise ValueError("GeoJSON input must be a FeatureCollection or file path")
            if payload.get("type") != "FeatureCollection":
                raise ValueError("GeoJSON input must be a FeatureCollection")
            features = []
            for index, raw_feature in enumerate(payload.get("features") or ()):
                if not isinstance(raw_feature, Mapping):
                    raise ValueError(f"GeoJSON feature {index} is not an object")
                feature = dict(raw_feature)
                properties = dict(feature.get("properties") or {})
                properties.update({
                    "source_uri": source_uri,
                    "source_content_ref": request.source_ref,
                    "input_role": request.expected_role,
                    "source_feature_ordinal": index,
                })
                feature["properties"] = properties
                features.append(feature)
            return {"type": "FeatureCollection", "features": features}
        if media in {"text/markdown", "text/x-markdown", "markdown"}:
            if isinstance(value, (str, Path)):
                candidate = Path(value)
                if candidate.is_file():
                    text = candidate.read_text(encoding="utf-8-sig")
                    source_uri = str(candidate)
                else:
                    text = str(value)
                    source_uri = request.source_ref
            elif isinstance(value, Mapping):
                text = str(value.get("markdown") or value.get("text") or value.get("content") or "")
                source_uri = str(value.get("source_uri") or request.source_ref)
            else:
                raise ValueError("Markdown input must be text, a declared payload, or a file path")
            if not text.strip():
                raise ValueError("Markdown input is empty")
            return [{
                "geometry": None,
                "properties": {
                    "resource_kind": "document",
                    "content_format": "markdown",
                    "document_type": "current_evidence_report",
                    "parser": "mineru",
                    "text": text,
                    "source_uri": source_uri,
                    "source_content_ref": request.source_ref,
                    "input_role": request.expected_role,
                    "source_span_strategy": "markdown_line",
                },
            }]
        if media in {"image/tiff", "image/geotiff", "application/geotiff", "geotiff"}:
            from app.data.ingestion.sources.local_raster import LocalRasterDriver

            raw_path = value.get("path") if isinstance(value, Mapping) else value
            path = Path(raw_path) if raw_path else Path("")
            if not path.is_file():
                raise FileNotFoundError(str(path))
            result = LocalRasterDriver({
                "path": str(path),
                "format": "GeoTIFF",
                "crs": request.declared_crs,
                "layer_type": "dem",
            }).fetch()
            if not result.success:
                raise ValueError(result.error or "GeoTIFF could not be read")
            return [{
                "geometry": None,
                "properties": {
                    "resource_kind": "raster",
                    "geometry_kind": "raster",
                    "layer_ref": "dem",
                    "source_uri": str(path),
                    "source_content_ref": request.source_ref,
                    "input_role": request.expected_role,
                    "format": "GeoTIFF",
                    "source_crs": str(result.metadata.get("crs") or request.declared_crs),
                    "raster_metadata": dict(result.metadata),
                },
            }]
        raise ValueError("unsupported DATA media type")

    @staticmethod
    def _admission_state(
        request: DataAdmissionRequest,
        *,
        run_id: str = "",
        refs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = dict(request.policy_context or {})
        context_version = str(policy.get("context_version") or "")
        return {
            "run_id": str(run_id or "data-admission-" + request.session_id),
            "session_id": request.session_id,
            "branch_id": str(policy.get("branch_id") or "main"),
            "artifact_root": str(policy.get("artifact_root") or run_tmp_root()),
            "artifact_schema_version": "3",
            "context_version": context_version,
            "context_fingerprint": str(policy.get("context_fingerprint") or ""),
            "context_ref": dict(
                policy.get("context_ref")
                or {
                    "session_id": request.session_id,
                    "version": context_version,
                }
            ),
            "artifact_refs": dict(refs or {}),
        }

    @staticmethod
    def _persist_rejection(
        request: DataAdmissionRequest,
        *,
        gap: DataAdmissionGap,
        receipt: DataAdmissionReceipt,
    ) -> tuple[ArtifactRef, ArtifactRef]:
        """Persist a failed attempt and its receipt before returning it."""

        state = DataAdmissionFacade._admission_state(
            request,
            run_id=gap.attempt_ref,
        )
        gap_ref = ArtifactRef.model_validate(
            store_artifact(
                state,
                "data_admission_gap",
                "data",
                "DataAdmissionGap",
                gap,
            )
        )
        state["artifact_refs"] = {
            "data_admission_gap": gap_ref.model_dump(mode="json"),
        }
        receipt_ref = ArtifactRef.model_validate(
            store_artifact(
                state,
                "data_admission_receipt",
                "data",
                "DataAdmissionReceipt",
                receipt,
                parent_keys=("data_admission_gap",),
            )
        )
        return receipt_ref, gap_ref

    @staticmethod
    def _reuse_admitted(
        request: DataAdmissionRequest,
        *,
        attempt_ref: str,
        parent_ref: ArtifactRef | None,
    ) -> DataAdmissionResult | None:
        """Replay a completed admission before asking DATA to create a revision."""

        policy = dict(request.policy_context or {})
        run_id = parent_ref.run_id if parent_ref is not None else attempt_ref
        branch_id = parent_ref.branch_id if parent_ref is not None else str(
            policy.get("branch_id") or "main"
        )
        state = DataAdmissionFacade._admission_state(
            request,
            run_id=run_id,
            refs={},
        )
        state["branch_id"] = branch_id
        repository = ContentAddressedArtifactRepository(state["artifact_root"])
        receipt_ref = repository.get_named_ref(run_id, branch_id, "data_admission_receipt")
        if receipt_ref is None:
            return None
        receipt = DataAdmissionReceipt.model_validate(repository.get_json(receipt_ref))
        if receipt.attempt_ref != attempt_ref or receipt.state != "ADMITTED":
            return None
        if not receipt.gate_artifact_ref:
            return None
        gate_descriptor = repository.get_descriptor(receipt.gate_artifact_ref)
        refs: dict[str, Any] = {
            "data_admission_receipt": receipt_ref.model_dump(mode="json"),
            "data_gate": gate_descriptor.model_dump(mode="json"),
        }
        for key in (
            "data_catalog",
            "data_snapshot",
            "data_stage",
        ):
            ref = repository.get_named_ref(run_id, branch_id, key)
            if ref is None:
                return None
            refs[key] = ref.model_dump(mode="json")
        replay_state = {
            **state,
            "artifact_refs": refs,
        }
        if any(
            expected
            and expected != ArtifactRef.model_validate(refs[key]).digest
            for key, expected in (
                ("data_catalog", receipt.catalog_ref),
                ("data_stage", receipt.stage_ref),
                ("data_gate", receipt.gate_ref),
            )
        ):
            return None
        catalog = DataApplication.load_catalog(replay_state)
        data_snapshot = DataApplication.load_snapshot(replay_state)
        stage = DataApplication.load_stage(replay_state)
        if catalog is None or data_snapshot is None or stage is None:
            return None
        data_run = DataRunResult(
            request=DataRunRequest.from_state(replay_state),
            catalog=catalog,
            data_snapshot=data_snapshot,
            stage_snapshot=stage,
            catalog_ref=ArtifactRef.model_validate(refs["data_catalog"]),
            data_snapshot_ref=ArtifactRef.model_validate(refs["data_snapshot"]),
            stage_ref=ArtifactRef.model_validate(refs["data_stage"]),
            gate_ref=ArtifactRef.model_validate(refs["data_gate"]),
            receipt_ref=receipt.receipt_ref,
            lifecycle_state=receipt.state,
            lifecycle=receipt.lifecycle,
            state_patch={
                "artifact_refs": refs,
                "data_snapshot_id": data_snapshot.snapshot_id,
                "data_snapshot_digest": data_snapshot.digest,
                "data_stage_status": stage.status,
                "data_gap_refs": list(stage.gap_refs),
            },
        )
        return DataAdmissionResult(
            receipt=receipt,
            catalog_ref=data_run.catalog_ref,
            stage_ref=data_run.stage_ref,
            gate_ref=data_run.gate_ref,
            receipt_artifact_ref=receipt_ref,
            data_run=data_run,
        )

    @staticmethod
    def _rejection(
        request: DataAdmissionRequest,
        *,
        attempt_ref: str,
        state: str,
        reason_code: str,
        reason: str,
    ) -> DataAdmissionResult:
        gap_ref = "data.gap." + semantic_checksum({
            "attempt_ref": attempt_ref,
            "reason_code": reason_code,
        })[:24]
        gap = DataAdmissionGap(
            gap_ref=gap_ref,
            source_ref=request.source_ref,
            attempt_ref=attempt_ref,
            state_at_failure=state,
            reason_code=reason_code,
            required_capability=DataAdmissionFacade._required_capability(request),
            observed_metadata={
                "media_type": request.declared_media_type,
                "encoding": request.declared_encoding,
                "crs": request.declared_crs,
                "adapter_hint": request.adapter_hint,
                "expected_role": request.expected_role,
                "reason": reason,
            },
            input_refs=(request.source_ref,),
            recovery_action="correct the declaration or provide a supported local input file",
            retryability="retryable" if state != "POLICY_REJECTED" else "non_retryable",
            owner="data",
            budget_state=dict(request.policy_context.get("budget_state") or {}),
        )
        receipt_ref = "data.receipt." + semantic_checksum({
            "attempt_ref": attempt_ref,
            "state": state,
            "gap_ref": gap_ref,
        })[:24]
        receipt = DataAdmissionReceipt(
            receipt_ref=receipt_ref,
            source_ref=request.source_ref,
            attempt_ref=attempt_ref,
            state=state,
            state_at_failure=state,
            reason_code=reason_code,
            recovery_action=gap.recovery_action,
            retryability=gap.retryability,
            owner=gap.owner,
            budget_state=gap.budget_state,
            lifecycle=("DISCOVERED", "CLASSIFIED", state),
            gap_ref=gap_ref,
            observed_metadata=gap.observed_metadata,
            input_refs=(request.source_ref,),
        )
        receipt_artifact_ref, gap_artifact_ref = DataAdmissionFacade._persist_rejection(
            request,
            gap=gap,
            receipt=receipt,
        )
        return DataAdmissionResult(
            receipt=receipt,
            gap=gap,
            receipt_artifact_ref=receipt_artifact_ref,
            gap_artifact_ref=gap_artifact_ref,
        )

    async def admit(self, request: DataAdmissionRequest) -> DataAdmissionResult:
        from app.data.admission import check_p0_local_boundary

        raw_value = request.normalized_input if request.normalized_input is not None else request.content
        if raw_value is None:
            attempt_ref = self._attempt_ref(request, raw_value)
            return self._rejection(
                request, attempt_ref=attempt_ref, state="INVALID",
                reason_code="input_missing", reason="content or normalized_input is required",
            )
        attempt_ref = self._attempt_ref(request, raw_value)
        boundary = check_p0_local_boundary(
            declared_media_type=request.declared_media_type,
            adapter_hint=request.adapter_hint,
            declared_crs=request.declared_crs,
            declared_encoding=request.declared_encoding,
            expected_role=request.expected_role,
        )
        if not boundary.accepted:
            return self._rejection(
                request, attempt_ref=attempt_ref, state=boundary.state,
                reason_code=boundary.reason_code, reason=boundary.reason,
            )

        value = raw_value
        try:
            value = self._prepare_input(request, raw_value)
        except UnicodeDecodeError as exc:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="ENCODING_UNRESOLVED",
                reason_code="encoding_unresolved",
                reason=str(exc),
            )
        except FileNotFoundError as exc:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="INVALID",
                reason_code="input_file_missing",
                reason=str(exc),
            )
        except Exception as exc:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="INVALID",
                reason_code="input_parse_failed",
                reason=f"{type(exc).__name__}: {exc}",
            )
        attempt_ref = self._attempt_ref(request, value)

        parent_ref: ArtifactRef | None = None
        if request.parent_catalog_ref is not None:
            try:
                parent_ref = ArtifactRef.model_validate(request.parent_catalog_ref)
            except Exception:
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="POLICY_REJECTED",
                    reason_code="parent_catalog_ref_invalid",
                    reason="parent_catalog_ref must be an ArtifactRef descriptor",
                )
            if parent_ref.schema_id != "DataResourceCatalogSnapshot":
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="POLICY_REJECTED",
                    reason_code="parent_catalog_ref_wrong_schema",
                    reason="parent catalog ref must identify a DATA catalog snapshot",
                )
            parent_state = self._admission_state(
                request,
                run_id=parent_ref.run_id,
            )
            parent_state["branch_id"] = parent_ref.branch_id
            current_parent = ContentAddressedArtifactRepository(
                parent_state["artifact_root"]
            ).get_named_ref(
                parent_ref.run_id,
                parent_ref.branch_id,
                "data_catalog",
            )
            if current_parent is None:
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="POLICY_REJECTED",
                    reason_code="parent_catalog_unavailable",
                    reason="parent catalog is not the current CAS catalog",
                )
            if current_parent.descriptor_digest != parent_ref.descriptor_digest:
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="POLICY_REJECTED",
                    reason_code="stale_parent_catalog",
                    reason="parent catalog is stale; reload the current catalog and retry",
                )

        replayed = self._reuse_admitted(
            request,
            attempt_ref=attempt_ref,
            parent_ref=parent_ref,
        )
        if replayed is not None:
            return replayed

        catalog = DataApplication.normalize(
            value,
            dataset_ref=request.source_ref,
            session_id=request.session_id,
            source_snapshot_ref="data-input:" + attempt_ref,
        )
        features = catalog.snapshot.features
        if not features:
            return self._rejection(
                request, attempt_ref=attempt_ref, state="INVALID",
                reason_code="empty_geojson", reason="GeoJSON contains no features",
            )
        if any(
            feature.normalized_geometry is None
            and feature.geometry_kind != "raster"
            and str((feature.raw_attributes or {}).get("resource_kind") or "").casefold()
            not in {"table", "document", "text", "markdown", "report", "image"}
            for feature in features
        ):
            return self._rejection(
                request, attempt_ref=attempt_ref, state="GEOMETRY_INVALID",
                reason_code="geometry_invalid", reason="one or more geometries are not normalized WGS84 geometry",
            )
        decisions = tuple(
            SourceAdmissionDecision(
                decision_ref="data.admission." + semantic_checksum({
                    "attempt_ref": attempt_ref,
                    "source_ref": feature.source_feature_ref,
                    "digest": feature.source_feature_digest,
                })[:24],
                source_ref=f"resource:{feature.dataset_ref}:{feature.source_feature_ref}",
                source_digest=feature.source_feature_digest,
                input_role="current_evidence",
                status="admitted",
                resource_kind=feature.geometry_kind,
                reason="explicit_p0_local_boundary_admission",
                recovery_pointer=f"data-receipt:{attempt_ref}",
            )
            for feature in catalog.snapshot.features
        )
        catalog = DataResourceCatalog(catalog.snapshot.model_copy(update={
            "admission_decisions": decisions,
        }))
        from app.data.admission import current_world_snapshot

        catalog = DataResourceCatalog(current_world_snapshot(catalog.snapshot))
        data_snapshot = SessionDataSnapshot.from_data_catalog(
            catalog,
            session_id=request.session_id,
            village_name=str(
                (request.policy_context.get("config") or {}).get("village_name") or ""
            ),
        )
        context_version = str(request.policy_context.get("context_version") or "")
        data_context_ref = {
            **dict(
                request.policy_context.get("context_ref")
                or {
                    "session_id": request.session_id,
                    "version": context_version,
                }
            ),
            "session_id": request.session_id,
            "version": context_version,
            "snapshot_id": data_snapshot.snapshot_id,
            "snapshot_digest": data_snapshot.digest,
            "data_snapshot_digest": data_snapshot.digest,
            "data_resource_catalog_digest": catalog.snapshot.digest,
        }
        run_state = {
            "run_id": parent_ref.run_id if parent_ref is not None else attempt_ref,
            "session_id": request.session_id,
            "branch_id": parent_ref.branch_id if parent_ref is not None else "main",
            "artifact_root": str(
                request.policy_context.get("artifact_root") or run_tmp_root()
            ),
            "artifact_schema_version": "3",
            "context_version": str(request.policy_context.get("context_version") or ""),
            "context_ref": data_context_ref,
            "config": dict(request.policy_context.get("config") or {}),
            "data_catalog": catalog,
        }
        if parent_ref is not None:
            run_state["artifact_refs"] = {
                "data_catalog": parent_ref.model_dump(mode="json"),
            }
        run = await DataApplication().run(
            run_state,
            catalog=catalog,
            data_snapshot=data_snapshot,
        )
        lifecycle = (
            "DISCOVERED", "CLASSIFIED", "PARSING", "NORMALIZED",
            "REPRESENTATION_BUILT", "CAPABILITY_INDEXED", "ADMITTED",
        )
        receipt_ref = "data.receipt." + semantic_checksum({
            "attempt_ref": attempt_ref,
            "catalog": run.catalog.digest,
        })[:24]
        receipt = DataAdmissionReceipt(
            receipt_ref=receipt_ref,
            source_ref=request.source_ref,
            attempt_ref=attempt_ref,
            state="ADMITTED",
            state_at_failure="ADMITTED",
            lifecycle=lifecycle,
            catalog_ref=run.catalog_ref.digest,
            stage_ref=run.stage_ref.digest,
            gate_ref=run.gate_ref.digest,
            required_capability=DataAdmissionFacade._required_capability(request),
            observed_metadata={
                "feature_count": len(run.catalog.features),
                "dataset_count": len(run.catalog.datasets or ()),
                "dataset_refs": [item.dataset_ref for item in run.catalog.datasets or ()],
                "resource_kinds": sorted({
                    str(item.geometry_kind or "")
                    for item in run.catalog.features
                }),
            },
            input_refs=tuple(dict.fromkeys([
                request.source_ref,
                *( [parent_ref.digest] if parent_ref is not None else [] ),
            ])),
        )
        stage = run.stage_snapshot.model_copy(update={
            "receipt_ref": receipt_ref,
            "lifecycle_state": "ADMITTED",
            "lifecycle": lifecycle,
        })
        run_refs = dict(run.to_state_patch().get("artifact_refs") or {})
        revised_state = {
            **run_state,
            **run.to_state_patch(),
            "artifact_refs": run_refs,
        }
        revised_stage_ref = ArtifactRef.model_validate(
            store_artifact(
                revised_state,
                "data_stage",
                "data",
                "DataStageSnapshot",
                stage,
                parent_keys=("data_catalog", "data_snapshot"),
            )
        )
        run_refs["data_stage"] = revised_stage_ref.model_dump(mode="json")
        revised_state["artifact_refs"] = run_refs
        revised_gate = DataApplication._gate(
            revised_state,
            passed=stage.status == "ready",
            context_version=stage.context_version,
            stage_ref=revised_stage_ref,
            reason="" if stage.status == "ready" else "data_normalization_gaps_unresolved",
            gap_refs=tuple(stage.gap_refs),
        )
        revised_gate_ref = persist_gate_decision(
            revised_state,
            "data",
            revised_gate,
            output_refs={
                "data_catalog": run.catalog_ref,
                "data_snapshot": run.data_snapshot_ref,
                "data_stage": revised_stage_ref,
            },
        )
        run_refs["data_gate"] = revised_gate_ref.model_dump(mode="json")
        revised_state["artifact_refs"] = run_refs
        receipt = receipt.model_copy(update={
            "stage_ref": revised_stage_ref.digest,
            "gate_ref": revised_gate_ref.digest,
            "gate_artifact_ref": revised_gate_ref.descriptor_digest,
        })
        receipt_state = dict(revised_state)
        if parent_ref is not None:
            receipt_state["artifact_refs"] = {
                **run_refs,
                "data_catalog_parent": parent_ref.model_dump(mode="json"),
            }
        receipt_parent_keys = [
            "data_catalog",
            "data_snapshot",
            "data_stage",
            "data_gate",
        ]
        if parent_ref is not None:
            receipt_parent_keys.append("data_catalog_parent")
        receipt_artifact_ref = ArtifactRef.model_validate(
            store_artifact(
                receipt_state,
                "data_admission_receipt",
                "data",
                "DataAdmissionReceipt",
                receipt,
                parent_keys=receipt_parent_keys,
            )
        )
        run = run.model_copy(update={
            "stage_snapshot": stage,
            "receipt_ref": receipt_ref,
            "lifecycle_state": "ADMITTED",
            "lifecycle": lifecycle,
            "stage_ref": revised_stage_ref,
            "gate_ref": revised_gate_ref,
            "state_patch": {
                **dict(run.state_patch),
                "artifact_refs": run_refs,
                "data_admission_receipt_ref": receipt_artifact_ref.model_dump(mode="json"),
            },
        })
        return DataAdmissionResult(
            receipt=receipt,
            catalog_ref=run.catalog_ref,
            stage_ref=revised_stage_ref,
            gate_ref=revised_gate_ref,
            receipt_artifact_ref=receipt_artifact_ref,
            data_run=run,
        )

    async def resume(self, request: DataAdmissionRequest) -> DataAdmissionResult:
        return await self.admit(request)

    @staticmethod
    def load_receipt(state: Mapping[str, Any]) -> DataAdmissionReceipt | None:
        return load_artifact(dict(state), "data_admission_receipt", DataAdmissionReceipt)

    @staticmethod
    def load_gap(state: Mapping[str, Any]) -> DataAdmissionGap | None:
        return load_artifact(dict(state), "data_admission_gap", DataAdmissionGap)


def _descriptor_digest(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("descriptor_digest") or value.get("digest") or "")
    return str(
        getattr(value, "descriptor_digest", "")
        or getattr(value, "digest", "")
        or ""
    )


def _catalog_gaps(catalog: DataResourceCatalog) -> tuple[DataGapRecord, ...]:
    """Return deterministic, source-bound gaps for the frozen catalog."""

    from app.data.admission import non_admitted_feature_verdicts

    snapshot = catalog.snapshot
    gaps: list[DataGapRecord] = []

    def add_gap(
        reason: str,
        *,
        source_feature_ref: str = "",
        source_digest: str = "",
        missing_fields: tuple[str, ...] = (),
        blocking: bool = True,
        status: str = "open",
        earliest_resolution_stage: str = "data",
    ) -> None:
        payload = {
            "snapshot": snapshot.snapshot_id,
            "source_feature_ref": source_feature_ref,
            "source_digest": source_digest,
            "missing_fields": missing_fields,
            "reason": reason,
            "blocking": blocking,
            "status": status,
        }
        gap_ref = "data.gap." + semantic_checksum(payload)[:24]
        gaps.append(DataGapRecord(
            artifact_id=gap_ref,
            gap_ref=gap_ref,
            source_feature_ref=source_feature_ref,
            source_digest=source_digest,
            missing_fields=missing_fields,
            reason=reason,
            blocking=blocking,
            status=status,
            earliest_resolution_stage=earliest_resolution_stage,
            recovery_pointer=(
                f"data-resource:{source_feature_ref}"
                if source_feature_ref
                else f"data-catalog:{snapshot.snapshot_id}"
            ),
        ))

    for decision in snapshot.admission_decisions:
        if decision.status == "quarantined":
            add_gap(
                "source_input_role_unclassified",
                source_feature_ref=decision.source_ref,
                source_digest=decision.source_digest,
                missing_fields=("input_role",),
                earliest_resolution_stage="human",
            )
        elif decision.status == "admitted" and decision.input_role != "current_evidence":
            add_gap(
                "source_admission_invariant_broken",
                source_feature_ref=decision.source_ref,
                source_digest=decision.source_digest,
                missing_fields=("current_evidence_admission",),
                earliest_resolution_stage="human",
            )

    admission_collections: dict[tuple[str, str, str], list[Any]] = {}
    for feature, verdict in non_admitted_feature_verdicts(snapshot):
        key = (
            str(feature.dataset_ref or ""),
            str(feature.layer_ref or "<unlayered>"),
            verdict.reason,
        )
        admission_collections.setdefault(key, []).append(feature)
    for (dataset_ref, layer_ref, reason), features in sorted(
        admission_collections.items()
    ):
        add_gap(
            "current_world_admission_unproven:" + reason,
            source_feature_ref=f"collection:{dataset_ref}:{layer_ref}",
            source_digest=semantic_checksum(tuple(sorted(
                str(item.source_feature_digest or "") for item in features
            ))),
            missing_fields=("current_evidence_admission_decision",),
            earliest_resolution_stage="human",
        )

    if not snapshot.features:
        add_gap(
            "source_feature_inventory_empty",
            source_digest=snapshot.digest,
            missing_fields=("source_features",),
        )
    for feature in snapshot.features:
        source_ref = str(feature.source_feature_ref or "")
        source_digest = str(feature.source_feature_digest or "")
        resource_kind = str(
            (feature.raw_attributes or {}).get("resource_kind") or ""
        ).strip().casefold()
        parse_status = str(
            (feature.raw_attributes or {}).get("parse_status") or ""
        ).strip().casefold()
        if parse_status == "failed":
            add_gap(
                "source_readability_failed",
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=("parsed_source",),
            )
            continue
        # Tables/documents are valid non-spatial DATA inputs.  Their lack of
        # geometry is intentional and must not block a session that will use
        # them for L1/EVIDENCE facts.  A spatial record with no geometry still
        # enters the gap path below.
        if resource_kind in {
            "table", "document", "text", "markdown", "report", "image",
        }:
            if resource_kind in {"document", "text", "markdown", "report"}:
                content_format = str(
                    (feature.raw_attributes or {}).get("content_format") or ""
                ).strip().casefold()
                if content_format != "markdown":
                    add_gap(
                        "non_gis_text_not_markdown",
                        source_feature_ref=source_ref,
                        source_digest=source_digest,
                        missing_fields=("content_format=markdown",),
                    )
            media_refs = tuple(
                str(item)
                for item in (feature.raw_attributes or {}).get("media_refs") or ()
                if str(item).strip()
            )
            if media_refs:
                add_gap(
                    "deferred_media_multimodal_not_enabled",
                    source_feature_ref=source_ref,
                    source_digest=source_digest,
                    missing_fields=("multimodal_media_interpretation",),
                    blocking=False,
                    status="deferred",
                    earliest_resolution_stage="human",
                )
            continue
        if feature.geometry_kind == "raster":
            if not str(feature.source_crs or "").strip():
                add_gap(
                    "raster_crs_missing",
                    source_feature_ref=source_ref,
                    source_digest=source_digest,
                    missing_fields=("source_crs",),
                )
            continue
        if feature.geometry is None:
            add_gap(
                "source_geometry_missing",
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=("geometry",),
            )
            continue
        if feature.normalized_geometry is None:
            trace = [
                str(item)
                for item in feature.crs_transform
                if str(item).strip() and str(item) != "identity"
            ]
            missing = ("source_crs",) if not str(feature.source_crs or "").strip() else ("normalized_geometry",)
            add_gap(
                "geometry_normalization_unavailable"
                + (":" + "|".join(trace) if trace else ""),
                source_feature_ref=source_ref,
                source_digest=source_digest,
                missing_fields=missing,
            )
    expected_snapshot_ref = str(snapshot.snapshot_id or "")
    for representation in snapshot.representations:
        if (
            not representation.source_snapshot_ref
            or representation.source_snapshot_ref != expected_snapshot_ref
            or not representation.content_digest
        ):
            add_gap(
                "representation_lineage_incomplete",
                source_feature_ref=str(representation.source_feature_ref or ""),
                source_digest=str(representation.content_digest or ""),
                missing_fields=("source_snapshot_ref", "content_digest"),
            )
    for capability in snapshot.capabilities:
        if (
            not capability.source_snapshot_ref
            or capability.source_snapshot_ref != expected_snapshot_ref
            or not capability.content_digest
        ):
            add_gap(
                "capability_lineage_incomplete",
                source_digest=str(capability.content_digest or ""),
                missing_fields=("source_snapshot_ref", "content_digest"),
            )
    from app.data.admission import cognition_readiness_issues

    additional_reasons = {
        "spatial_feature_inventory_empty",
        "spatial_representation_missing",
        "spatial_representation_unresolved",
        "spatial_capability_missing",
    }
    for issue in cognition_readiness_issues(snapshot):
        if issue.reason.split(":", 1)[0] not in additional_reasons:
            continue
        add_gap(
            issue.reason,
            source_feature_ref=issue.source_feature_ref,
            source_digest=issue.source_digest,
            missing_fields=issue.missing_fields,
            earliest_resolution_stage=issue.earliest_resolution_stage,
        )
    unique = {item.gap_ref: item for item in gaps}
    return tuple(unique[key] for key in sorted(unique))


def _snapshot_inventory_error(
    snapshot: SessionDataSnapshot,
    catalog: DataResourceCatalog,
) -> str:
    expected = {
        str(item.source_feature_ref)
        for item in catalog.snapshot.features
        if str(item.source_feature_ref).strip()
    }
    manifest = {
        str(item)
        for collection in snapshot.collections
        for item in collection.source_feature_ids
        if str(item).strip()
    }
    counted = sum(collection.feature_count for collection in snapshot.collections)
    if counted != len(catalog.snapshot.features):
        return (
            "feature_count_mismatch:"
            f"snapshot={counted}:catalog={len(catalog.snapshot.features)}"
        )
    if manifest != expected:
        return (
            "source_feature_inventory_mismatch:"
            f"snapshot={len(manifest)}:catalog={len(expected)}"
        )
    return ""


class DataApplication:
    """Normalize arbitrary source records and publish a DATA gate."""

    @staticmethod
    def normalize(
        source: Any,
        *,
        dataset_ref: str,
        session_id: str = "",
        village_name: str = "",
        source_snapshot_ref: str = "",
    ) -> DataResourceCatalog:
        """Return a lossless generic catalog without assigning planning types."""

        if isinstance(source, DataResourceCatalog):
            return source
        if isinstance(source, DataResourceCatalogSnapshot):
            return DataResourceCatalog(source)
        return DataResourceCatalog.from_records(
            source,
            dataset_ref=dataset_ref,
            name=village_name,
            snapshot_id=source_snapshot_ref,
        )

    @staticmethod
    def _artifact_state(state: Mapping[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
        """Supply the CAS identity fields for lightweight direct callers."""

        result = dict(state)
        result.setdefault("artifact_root", str(run_tmp_root()))
        result.setdefault("artifact_schema_version", "3")
        result.setdefault("branch_id", "main")
        result["artifact_refs"] = dict(refs)
        return result

    @staticmethod
    def _gate(
        state: Mapping[str, Any],
        *,
        passed: bool,
        context_version: str,
        stage_ref: Any = None,
        reason: str = "",
        gap_refs: tuple[str, ...] = (),
    ) -> GateDecision:
        pending = []
        if not passed:
            pending = [
                PendingRequest(
                    request_id="pr-data-bootstrap",
                    stage="data",
                    request_type="data_preparation",
                    context={
                        "reason": reason or "normalized DATA catalog unavailable",
                        "gap_refs": list(gap_refs),
                        "recovery_stage": "data",
                    },
                )
            ]
        return GateDecision(
            stage="data",
            passed=passed,
            feedback_route=None if passed else "HUMAN",
            pending_requests=pending,
            evidence_requests=[] if passed else list(gap_refs) or [reason or "data_snapshot_unavailable"],
            context_version=context_version,
            artifact_id="gate-data-" + semantic_checksum({
                "passed": passed,
                "stage_ref": _descriptor_digest(stage_ref),
                "reason": reason,
                "gap_refs": gap_refs,
            })[:16],
            route_reason="data_ready" if passed else reason or "data_bootstrap_failed",
        )

    async def run(
        self,
        state: Mapping[str, Any],
        *,
        catalog: Any = None,
        data_snapshot: SessionDataSnapshot | None = None,
    ) -> DataRunResult:
        request = DataRunRequest.from_state(state)
        if catalog is None:
            catalog = state.get("data_catalog")
        if catalog is None:
            raise RuntimeError("DATA requires a normalized DataResourceCatalog")
        normalized = self.normalize(
            catalog,
            dataset_ref=f"session:{request.session_id}:input",
            session_id=request.session_id,
            village_name=str((state.get("config") or {}).get("village_name") or ""),
            source_snapshot_ref=str((state.get("context_ref") or {}).get("snapshot_id") or ""),
        )
        from app.data.admission import current_world_snapshot

        normalized = DataResourceCatalog(
            current_world_snapshot(normalized.snapshot)
        )
        snapshot = data_snapshot or SessionDataSnapshot.from_data_catalog(
            normalized,
            session_id=request.session_id,
            village_name=str((state.get("config") or {}).get("village_name") or ""),
        )
        inventory_error = _snapshot_inventory_error(snapshot, normalized)
        if inventory_error:
            raise RuntimeError(
                "DATA snapshot does not cover the normalized catalog: "
                + inventory_error
            )
        refs = dict(state.get("artifact_refs") or {})
        artifact_state = self._artifact_state(state, refs)
        catalog_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "data_catalog",
                "data",
                "DataResourceCatalogSnapshot",
                normalized.snapshot,
            )
        )
        refs["data_catalog"] = catalog_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        data_snapshot_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "data_snapshot",
                "data",
                "SessionDataSnapshot",
                snapshot,
            )
        )
        refs["data_snapshot"] = data_snapshot_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        gaps = _catalog_gaps(normalized)
        ready = not any(item.blocking and item.status != "resolved" for item in gaps)
        deferred_media_count = sum(
            1 for item in gaps
            if item.reason == "deferred_media_multimodal_not_enabled"
        )
        admission_decisions = tuple(normalized.snapshot.admission_decisions)
        stage_snapshot = DataStageSnapshot(
            context_version=request.context_version,
            context_fingerprint=str(state.get("context_fingerprint") or ""),
            artifact_id="data-" + semantic_checksum({
                "catalog": catalog_ref.digest,
                "snapshot": data_snapshot_ref.digest,
            })[:16],
            status="ready" if ready else "blocked",
            catalog_ref=catalog_ref.digest,
            catalog_digest=normalized.snapshot.digest,
            data_snapshot_ref=data_snapshot_ref.digest,
            source_snapshot_id=snapshot.snapshot_id,
            source_snapshot_digest=snapshot.digest,
            dataset_count=len(normalized.snapshot.datasets or ()),
            feature_count=len(normalized.snapshot.features or ()),
            representation_count=len(normalized.snapshot.representations or ()),
            capability_count=len(normalized.snapshot.capabilities or ()),
            admission_decision_count=len(admission_decisions),
            admitted_source_count=sum(
                1 for item in admission_decisions if item.status == "admitted"
            ),
            excluded_source_count=sum(
                1
                for item in admission_decisions
                if item.status in {"control_only", "reference_only", "excluded"}
            ),
            quarantined_source_count=sum(
                1 for item in admission_decisions if item.status == "quarantined"
            ),
            admission_decision_refs=tuple(
                item.decision_ref for item in admission_decisions
            ),
            deferred_media_count=deferred_media_count,
            diagnostics=tuple(item.reason for item in gaps),
            gap_refs=tuple(item.gap_ref for item in gaps),
            gaps=gaps,
        )
        stage_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "data_stage",
                "data",
                "DataStageSnapshot",
                stage_snapshot,
            )
        )
        refs["data_stage"] = stage_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        gate = self._gate(
            artifact_state,
            passed=ready,
            context_version=request.context_version,
            stage_ref=stage_ref,
            reason="" if ready else "data_normalization_gaps_unresolved",
            gap_refs=tuple(item.gap_ref for item in gaps),
        )
        gate_ref = persist_gate_decision(
            artifact_state,
            "data",
            gate,
            output_refs={
                "data_catalog": catalog_ref,
                "data_snapshot": data_snapshot_ref,
                "data_stage": stage_ref,
            },
        )
        return DataRunResult(
            request=request,
            catalog=DataResourceCatalogSnapshot.model_validate(normalized.snapshot),
            data_snapshot=SessionDataSnapshot.model_validate(snapshot),
            stage_snapshot=stage_snapshot,
            catalog_ref=catalog_ref,
            data_snapshot_ref=data_snapshot_ref,
            stage_ref=stage_ref,
            gate_ref=gate_ref,
            state_patch={
                "artifact_refs": refs,
                "data_snapshot_id": snapshot.snapshot_id,
                "data_snapshot_digest": snapshot.digest,
                "data_stage_status": stage_snapshot.status,
                "data_gap_refs": list(stage_snapshot.gap_refs),
            },
        )

    @staticmethod
    def load_catalog(state: Mapping[str, Any]) -> DataResourceCatalogSnapshot | None:
        return load_artifact(dict(state), "data_catalog", DataResourceCatalogSnapshot)

    @staticmethod
    def load_snapshot(state: Mapping[str, Any]) -> SessionDataSnapshot | None:
        return load_artifact(dict(state), "data_snapshot", SessionDataSnapshot)

    @staticmethod
    def load_stage(state: Mapping[str, Any]) -> DataStageSnapshot | None:
        return load_artifact(dict(state), "data_stage", DataStageSnapshot)


async def run_data(
    state: Mapping[str, Any], *, catalog: Any = None
) -> DataRunResult:
    """Convenience entry point for composition roots and one-off probes."""

    return await DataApplication().run(state, catalog=catalog)


__all__ = ["DataApplication", "DataRunRequest", "DataRunResult", "run_data"]
