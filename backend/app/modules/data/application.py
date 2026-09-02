"""Public DATA application facade.

The facade owns the DATA-to-CAS boundary.  It accepts a normalized
``DataResourceCatalog`` (or lossless records), creates the session manifest,
and returns only typed products and immutable references.  Planning stages do
not need to know how a file was decoded or which source fields were present.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.data.source_contracts import (
    DataResourceCatalogIndexSnapshot,
    DataResourceCatalogSnapshot,
)
from app.contracts.data.admission_contracts import (
    DataAdmissionGap,
    DataAdmissionReceipt,
    DataAdmissionRequest,
    DataAdmissionResult,
)
from app.contracts.data.remote_admission_contracts import (
    RemoteSourceAdmissionReceipt,
    RemoteSourceAdmissionRequest,
)
from app.contracts.data.source_contracts import SourceAdmissionDecision
from app.contracts.data.product_contracts import (
    CapabilityIndexArtifact,
    NormalizedResourceArtifact,
    RepresentationSnapshotArtifact,
    SourceSnapshotArtifact,
    compose_catalog,
    normalized_product,
    source_product,
)
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
    source_snapshot_ref: ArtifactRef
    normalized_resource_ref: ArtifactRef
    representation_snapshot_ref: ArtifactRef
    capability_index_ref: ArtifactRef
    data_snapshot_ref: ArtifactRef
    stage_ref: ArtifactRef
    gate_ref: ArtifactRef
    receipt_ref: str = ""
    gap_ref: str = ""
    lifecycle_state: str = ""
    lifecycle: tuple[str, ...] = ()
    boundary_scope_ref: ArtifactRef | None = None
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
        patch["artifact_refs"].update({
            "source_snapshot": self.source_snapshot_ref.model_dump(mode="json"),
            "normalized_resource": self.normalized_resource_ref.model_dump(mode="json"),
            "representation_snapshot": self.representation_snapshot_ref.model_dump(mode="json"),
            "capability_index": self.capability_index_ref.model_dump(mode="json"),
        })
        if self.boundary_scope_ref is not None:
            patch["artifact_refs"]["boundary_scope"] = self.boundary_scope_ref.model_dump(mode="json")
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
            "content_digest": request.content_digest,
            "parent_catalog_ref": request.parent_catalog_ref,
            "recovery_gap_ref": request.recovery_gap_ref,
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
    def admit_declared_remote(
        request: RemoteSourceAdmissionRequest,
        *,
        state: Mapping[str, Any] | None = None,
    ) -> RemoteSourceAdmissionReceipt:
        """Admit a remote source declaration without executing a provider.

        This is intentionally synchronous and side-effect-free with respect
        to the network.  The only durable side effect, when ``state`` is
        supplied, is the immutable receipt in the DATA CAS.  A provider run
        must later prove complete coverage before its observation product can
        be consumed by Evidence or World Model.
        """

        receipt_id = "data.remote.receipt." + semantic_checksum({
            "request_digest": request.request_digest,
            "source_id": request.source_id,
        })[:24]
        receipt = RemoteSourceAdmissionReceipt(
            receipt_id=receipt_id,
            request_digest=request.request_digest,
            source_id=request.source_id,
            kind=request.kind,
            provider=request.provider,
            status="ADMITTED",
            boundary_ref=request.boundary_ref,
            boundary_digest=request.boundary_digest,
            query_geometry_digest=request.query_geometry_digest,
            crs_contract=request.crs_contract,
            capability_contract=request.capabilities,
            provenance={
                "admission_mode": "declaration_only",
                "network_contacted": False,
                "auth_ref": request.auth_ref,
                "limits": request.limits.model_dump(mode="json"),
                "endpoint": str(request.endpoint),
            },
        )
        if state is not None:
            artifact_state = dict(state)
            artifact_state.setdefault("artifact_schema_version", "3")
            artifact_state.setdefault("branch_id", "main")
            refs = dict(artifact_state.get("artifact_refs") or {})
            artifact_state["artifact_refs"] = refs
            stored_ref = store_artifact(
                artifact_state,
                "data_remote_admission_receipt",
                "data",
                "RemoteSourceAdmissionReceipt",
                receipt,
            )
            refs["data_remote_admission_receipt"] = stored_ref
            if isinstance(state, dict):
                state.setdefault("artifact_refs", {})["data_remote_admission_receipt"] = stored_ref
        return receipt

    @staticmethod
    def _prepare_input(request: DataAdmissionRequest, value: Any) -> Any:
        """Materialize one declared file input into generic DATA records."""

        media = str(request.declared_media_type or "").strip().casefold()
        if media in {
            "geojson", "application/geo+json", "application/x-esri-shapefile",
            "application/x-shapefile", "application/geopackage+sqlite3",
            "application/vnd.google-earth.kml+xml", "application/gml+xml",
        }:
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
                    "source_content_digest": request.content_digest,
                    "input_role": request.expected_role,
                    "source_feature_ordinal": index,
                })
                feature["properties"] = properties
                features.append(feature)
            result = {"type": "FeatureCollection", "features": features}
            if payload.get("crs") is not None:
                result["crs"] = payload["crs"]
            return result
        if media in {
            "text/csv", "text/tab-separated-values", "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }:
            if not isinstance(value, Mapping) or str(value.get("type") or "").casefold() != "tableresource":
                raise ValueError("table input must be a materialized TableResource")
            records: list[dict[str, Any]] = []
            for table in value.get("tables") or ():
                if not isinstance(table, Mapping):
                    raise ValueError("table resource contains an invalid sheet")
                sheet_name = str(table.get("name") or "default")
                for row_ordinal, row in enumerate(table.get("rows") or ()):
                    if not isinstance(row, Mapping):
                        raise ValueError(f"table row {row_ordinal} is not an object")
                    records.append({
                        "geometry": None,
                        "properties": {
                            "resource_kind": "table",
                            "sheet_name": sheet_name,
                            "row_ordinal": row_ordinal,
                            "columns": dict(row),
                            "source_uri": request.source_ref,
                            "source_content_ref": request.source_ref,
                            "source_content_digest": request.content_digest,
                            "input_role": request.expected_role,
                        },
                    })
            return records
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
                    "parser": "mineru",
                    "text": text,
                    "source_uri": source_uri,
                    "source_content_ref": request.source_ref,
                    "source_content_digest": request.content_digest,
                    "input_role": request.expected_role,
                    "source_span_strategy": "markdown_line",
                },
            }]
        if media in {"image/tiff", "image/geotiff", "application/geotiff", "geotiff"}:
            from app.data.ingestion.sources.local_raster import LocalRasterDriver

            if isinstance(value, Mapping) and str(value.get("type") or "").casefold() == "rasterresource":
                metadata = dict(value)
                metadata.setdefault("source_crs", metadata.get("crs") or request.declared_crs)
                metadata.update({
                    "source_uri": request.source_ref,
                    "source_content_ref": request.source_ref,
                    "source_content_digest": request.content_digest,
                    "input_role": request.expected_role,
                })
                return [{"geometry": None, "properties": metadata}]
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
                    "source_content_digest": request.content_digest,
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
            "source_snapshot",
            "normalized_resource",
            "representation_snapshot",
            "capability_index",
            "data_snapshot",
            "data_stage",
        ):
            ref = repository.get_named_ref(run_id, branch_id, key)
            if ref is None:
                return None
            refs[key] = ref.model_dump(mode="json")
        if str(policy.get("boundary_scope_mode") or "").strip():
            boundary_ref = repository.get_named_ref(run_id, branch_id, "boundary_scope")
            if boundary_ref is None:
                return None
            refs["boundary_scope"] = boundary_ref.model_dump(mode="json")
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
            source_snapshot_ref=ArtifactRef.model_validate(refs["source_snapshot"]),
            normalized_resource_ref=ArtifactRef.model_validate(refs["normalized_resource"]),
            representation_snapshot_ref=ArtifactRef.model_validate(refs["representation_snapshot"]),
            capability_index_ref=ArtifactRef.model_validate(refs["capability_index"]),
            data_snapshot_ref=ArtifactRef.model_validate(refs["data_snapshot"]),
            stage_ref=ArtifactRef.model_validate(refs["data_stage"]),
            gate_ref=ArtifactRef.model_validate(refs["data_gate"]),
            boundary_scope_ref=(
                ArtifactRef.model_validate(refs["boundary_scope"])
                if "boundary_scope" in refs
                else None
            ),
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
            boundary_scope_artifact_ref=data_run.boundary_scope_ref,
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
        lifecycle_prefix: tuple[str, ...] = ("DISCOVERED", "CLASSIFIED"),
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
                "recovery_gap_ref": request.recovery_gap_ref,
            },
            input_refs=tuple(dict.fromkeys([
                request.source_ref,
                *([_artifact_digest(request.recovery_gap_ref)] if request.recovery_gap_ref is not None else []),
            ])),
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
            input_role=request.expected_role,
            admission_status="quarantined",
            state=state,
            state_at_failure=state,
            reason_code=reason_code,
            recovery_action=gap.recovery_action,
            retryability=gap.retryability,
            owner=gap.owner,
            budget_state=gap.budget_state,
            lifecycle=tuple(dict.fromkeys([*lifecycle_prefix, state])),
            gap_ref=gap_ref,
            observed_metadata=gap.observed_metadata,
            input_refs=gap.input_refs,
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

    def record_ingress_admission(
        self,
        request: DataAdmissionRequest,
        assessment: Any,
    ) -> DataAdmissionResult:
        """Persist a non-current ingress decision without publishing DATA.

        Control text, reference plans, planned outputs, and unresolved uploads
        are still first-class ingress products.  They receive the same
        receipt/gap boundary as current evidence, but never create a current
        world catalog.  This keeps the upload table and CAS on one admission
        contract without pretending that every upload is spatial DATA.
        """

        input_role = str(getattr(assessment, "input_role", "unclassified") or "unclassified")
        admission_status = str(getattr(assessment, "status", "quarantined") or "quarantined")
        reason = str(getattr(assessment, "reason", "source_admission_unresolved") or "source_admission_unresolved")
        budget_error = str((request.policy_context or {}).get("budget_error") or "").strip()
        signals = tuple(str(item) for item in getattr(assessment, "signals", ()) if str(item).strip())
        attempt_ref = self._attempt_ref(request, request.normalized_input if request.normalized_input is not None else request.content)
        gap_ref = "data.gap." + semantic_checksum({
            "attempt_ref": attempt_ref,
            "reason": reason,
            "status": admission_status,
        })[:24]
        observed = {
            "media_type": request.declared_media_type,
            "encoding": request.declared_encoding,
            "crs": request.declared_crs,
            "adapter_hint": request.adapter_hint,
            "expected_role": request.expected_role,
            "input_role": input_role,
            "admission_status": admission_status,
            "reason": reason,
            "signals": list(signals),
            "classifier_ref": str(getattr(assessment, "classifier_ref", "") or ""),
            "classifier_input_digest": str(getattr(assessment, "classifier_input_digest", "") or ""),
            "classifier_output_digest": str(getattr(assessment, "classifier_output_digest", "") or ""),
            "classifier_model": str(getattr(assessment, "classifier_model", "") or ""),
            "classifier_confidence": float(getattr(assessment, "classifier_confidence", 0.0) or 0.0),
        }
        gap = DataAdmissionGap(
            gap_ref=gap_ref,
            source_ref=request.source_ref,
            attempt_ref=attempt_ref,
            state_at_failure="POLICY_REJECTED",
            reason_code=(
                budget_error
                if budget_error
                else "source_admission_quarantined"
                if admission_status == "quarantined"
                else "non_current_source_isolated"
            ),
            required_capability=self._required_capability(request),
            observed_metadata=observed,
            input_refs=(request.source_ref,),
            recovery_action=(
                "reduce the upload to the configured DATA byte budget and retry"
                if budget_error
                else
                "provide an explicit current_evidence declaration and pass the temporal-role gate"
                if admission_status == "quarantined"
                else "consume this source only through its declared control or reference channel"
            ),
            retryability="retryable" if admission_status == "quarantined" else "non_retryable",
            owner="data",
            budget_state=dict(request.policy_context.get("budget_state") or {}),
        )
        receipt_ref = "data.receipt." + semantic_checksum({
            "attempt_ref": attempt_ref,
            "gap_ref": gap_ref,
        })[:24]
        receipt = DataAdmissionReceipt(
            receipt_ref=receipt_ref,
            source_ref=request.source_ref,
            attempt_ref=attempt_ref,
            input_role=input_role,
            admission_status=admission_status,
            state="POLICY_REJECTED",
            state_at_failure="POLICY_REJECTED",
            reason_code=gap.reason_code,
            required_capability=gap.required_capability,
            lifecycle=("DISCOVERED", "CLASSIFIED", "POLICY_REJECTED"),
            gap_ref=gap_ref,
            observed_metadata=observed,
            input_refs=(request.source_ref,),
            recovery_action=gap.recovery_action,
            retryability=gap.retryability,
            owner="data",
            budget_state=gap.budget_state,
        )
        receipt_artifact_ref, gap_artifact_ref = self._persist_rejection(
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
        from app.data.admission import check_local_admission_boundary

        raw_value = request.normalized_input if request.normalized_input is not None else request.content
        if raw_value is None:
            attempt_ref = self._attempt_ref(request, raw_value)
            return self._rejection(
                request, attempt_ref=attempt_ref, state="INVALID",
                reason_code="input_missing", reason="content or normalized_input is required",
            )
        policy = dict(request.policy_context or {})
        budget_error = str(policy.get("budget_error") or "").strip()
        if budget_error:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="POLICY_REJECTED",
                reason_code=budget_error,
                reason="input exceeds a configured DATA admission budget",
                lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
            )
        try:
            from app.core.settings import (
                DATA_MAX_FEATURES,
                DATA_MAX_TABLE_ROWS,
                DATA_MAX_TEXT_CHARS,
            )
        except Exception:
            DATA_MAX_FEATURES, DATA_MAX_TABLE_ROWS, DATA_MAX_TEXT_CHARS = 500000, 1000000, 2000000
        media = str(request.declared_media_type or "").casefold()
        if media in {"text/markdown", "text/x-markdown", "markdown"} and isinstance(raw_value, str):
            if len(raw_value) > DATA_MAX_TEXT_CHARS:
                return self._rejection(
                    request,
                    attempt_ref=self._attempt_ref(request, raw_value),
                    state="POLICY_REJECTED",
                    reason_code="text_length_exceeded",
                    reason="Markdown exceeds DATA_MAX_TEXT_CHARS",
                    lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
                )
        if isinstance(raw_value, Mapping):
            if str(raw_value.get("type") or "").casefold() == "featurecollection":
                count = len(raw_value.get("features") or ())
                if count > DATA_MAX_FEATURES:
                    return self._rejection(
                        request,
                        attempt_ref=self._attempt_ref(request, raw_value),
                        state="POLICY_REJECTED",
                        reason_code="feature_count_exceeded",
                        reason="FeatureCollection exceeds DATA_MAX_FEATURES",
                        lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
                    )
            if str(raw_value.get("type") or "").casefold() == "tableresource":
                row_count = sum(
                    len(table.get("rows") or ())
                    for table in raw_value.get("tables") or ()
                    if isinstance(table, Mapping)
                )
                if row_count > DATA_MAX_TABLE_ROWS:
                    return self._rejection(
                        request,
                        attempt_ref=self._attempt_ref(request, raw_value),
                        state="POLICY_REJECTED",
                        reason_code="table_row_count_exceeded",
                        reason="TableResource exceeds DATA_MAX_TABLE_ROWS",
                        lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
                    )
        attempt_ref = self._attempt_ref(request, raw_value)
        normalized_source_ref = (
            "/"
            + str(request.source_ref).replace("\\", "/").strip("/").casefold()
            + "/"
        )
        if "/planned/" in normalized_source_ref:
            return self._rejection(
                request,
                attempt_ref=attempt_ref,
                state="POLICY_REJECTED",
                reason_code="planned_input_excluded",
                reason="planned inputs are outside the DATA current_evidence boundary",
            )
        boundary = check_local_admission_boundary(
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
                lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
            )
        except FileNotFoundError as exc:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="INVALID",
                reason_code="input_file_missing",
                reason=str(exc),
                lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
            )
        except Exception as exc:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, raw_value),
                state="INVALID",
                reason_code="input_parse_failed",
                reason=f"{type(exc).__name__}: {exc}",
                lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
            )
        if isinstance(value, Mapping) and str(value.get("type") or "").casefold() == "featurecollection":
            if len(value.get("features") or ()) > DATA_MAX_FEATURES:
                return self._rejection(
                    request,
                    attempt_ref=self._attempt_ref(request, value),
                    state="POLICY_REJECTED",
                    reason_code="feature_count_exceeded",
                    reason="materialized FeatureCollection exceeds DATA_MAX_FEATURES",
                    lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
                )
        if str(request.adapter_hint or "").casefold() == "table" and isinstance(value, list):
            if len(value) > DATA_MAX_TABLE_ROWS:
                return self._rejection(
                    request,
                    attempt_ref=self._attempt_ref(request, value),
                    state="POLICY_REJECTED",
                    reason_code="table_row_count_exceeded",
                    reason="materialized table exceeds DATA_MAX_TABLE_ROWS",
                    lifecycle_prefix=("DISCOVERED", "CLASSIFIED", "PARSING"),
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
            if parent_ref.schema_id not in {
                "DataResourceCatalogIndexSnapshot",
            }:
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

        try:
            catalog = DataApplication.normalize(
                value,
                dataset_ref=request.source_ref,
                session_id=request.session_id,
                source_snapshot_ref="data-input:" + attempt_ref,
                layer_ref=str(request.policy_context.get("layer_ref") or ""),
            )
        except (ValueError, TypeError, KeyError) as exc:
            message = str(exc)
            terminal_state = (
                "CRS_UNRESOLVED"
                if "crs" in message.casefold()
                else "GEOMETRY_INVALID"
                if "geometr" in message.casefold()
                else "INVALID"
            )
            return self._rejection(
                request,
                attempt_ref=attempt_ref,
                state=terminal_state,
                reason_code=terminal_state.casefold(),
                reason=f"{type(exc).__name__}: {message}",
                lifecycle_prefix=(
                    "DISCOVERED", "CLASSIFIED", "PARSING", "NORMALIZED",
                ),
            )
        features = catalog.snapshot.features
        if not features:
            return self._rejection(
                request, attempt_ref=attempt_ref, state="INVALID",
                reason_code="empty_geojson", reason="GeoJSON contains no features",
                lifecycle_prefix=(
                    "DISCOVERED", "CLASSIFIED", "PARSING", "NORMALIZED",
                ),
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
                lifecycle_prefix=(
                    "DISCOVERED", "CLASSIFIED", "PARSING", "NORMALIZED",
                    "REPRESENTATION_BUILT",
                ),
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
                reason="explicit_local_capability_admission",
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
        boundary_scope_ref: ArtifactRef | None = None
        boundary_scope_artifact = None
        boundary_scope_mode = str(
            request.policy_context.get("boundary_scope_mode") or ""
        ).strip()
        if boundary_scope_mode:
            from app.data.boundary_scope import build_boundary_scope_artifact

            if boundary_scope_mode not in {
                "admitted_boundary",
                "polygonized_admin_boundary",
            }:
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="POLICY_REJECTED",
                    reason_code="boundary_scope_mode_invalid",
                    reason="boundary scope mode must be explicit",
                )
            boundary_scope = build_boundary_scope_artifact(
                run.catalog,
                mode=boundary_scope_mode,
                source_dataset_ref=str(
                    request.policy_context.get("boundary_dataset_ref") or ""
                ),
                source_layer_ref=str(
                    request.policy_context.get("boundary_layer_ref") or "boundary"
                ),
            )
            if boundary_scope is None:
                return self._rejection(
                    request,
                    attempt_ref=attempt_ref,
                    state="GEOMETRY_INVALID",
                    reason_code="boundary_scope_unavailable",
                    reason="an admitted normalized polygon boundary is required",
                )
            boundary_state = {
                **run_state,
                **run.to_state_patch(),
                "artifact_refs": dict(run.to_state_patch().get("artifact_refs") or {}),
            }
            boundary_scope_ref = ArtifactRef.model_validate(
                store_artifact(
                    boundary_state,
                    "boundary_scope",
                    "data",
                    "BoundaryScopeArtifact",
                    boundary_scope,
                    parent_keys=(
                        "data_catalog", "source_snapshot", "normalized_resource",
                        "representation_snapshot", "capability_index",
                    ),
                )
            )
            boundary_scope_artifact = boundary_scope
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
            input_role="current_evidence",
            admission_status="admitted",
            state="ADMITTED",
            state_at_failure="ADMITTED",
            lifecycle=lifecycle,
            catalog_ref=run.catalog_ref.digest,
            stage_ref=run.stage_ref.digest,
            gate_ref=run.gate_ref.digest,
            boundary_scope_ref=(
                boundary_scope_ref.digest if boundary_scope_ref is not None else ""
            ),
            required_capability=DataAdmissionFacade._required_capability(request),
            observed_metadata={
                "feature_count": len(run.catalog.features),
                "dataset_count": len(run.catalog.datasets or ()),
                "dataset_refs": [item.dataset_ref for item in run.catalog.datasets or ()],
                "resource_kinds": sorted({
                    str(item.geometry_kind or "")
                    for item in run.catalog.features
                }),
                "content_digest": request.content_digest,
                "classifier_ref": str(request.policy_context.get("classifier_ref") or ""),
                "classifier_input_digest": str(request.policy_context.get("classifier_input_digest") or ""),
                "classifier_output_digest": str(request.policy_context.get("classifier_output_digest") or ""),
                "classifier_model": str(request.policy_context.get("classifier_model") or ""),
                "classifier_confidence": float(request.policy_context.get("classifier_confidence") or 0.0),
                "boundary_scope_ref": (
                    boundary_scope_ref.digest if boundary_scope_ref is not None else ""
                ),
                "boundary_digest": str(
                    getattr(boundary_scope_artifact, "boundary_digest", "") or ""
                ),
                "query_geometry_digest": str(
                    getattr(boundary_scope_artifact, "query_geometry_digest", "") or ""
                ),
                "recovery_gap_ref": (
                    _artifact_digest(request.recovery_gap_ref)
                    if request.recovery_gap_ref is not None
                    else ""
                ),
            },
            input_refs=tuple(dict.fromkeys([
                request.source_ref,
                *( [parent_ref.digest] if parent_ref is not None else [] ),
                *( [boundary_scope_ref.digest] if boundary_scope_ref is not None else [] ),
                *(
                    [_artifact_digest(request.recovery_gap_ref)]
                    if request.recovery_gap_ref is not None
                    else []
                ),
            ])),
        )
        stage = run.stage_snapshot.model_copy(update={
            "receipt_ref": receipt_ref,
            "lifecycle_state": "ADMITTED",
            "lifecycle": lifecycle,
        })
        run_refs = dict(run.to_state_patch().get("artifact_refs") or {})
        if boundary_scope_ref is not None:
            run_refs["boundary_scope"] = boundary_scope_ref.model_dump(mode="json")
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
                "source_snapshot": run.source_snapshot_ref,
                "normalized_resource": run.normalized_resource_ref,
                "representation_snapshot": run.representation_snapshot_ref,
                "capability_index": run.capability_index_ref,
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
            "source_snapshot",
            "normalized_resource",
            "representation_snapshot",
            "capability_index",
            "data_snapshot",
            "data_stage",
            "data_gate",
        ]
        if boundary_scope_ref is not None:
            receipt_parent_keys.append("boundary_scope")
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
            "boundary_scope_ref": boundary_scope_ref,
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
            boundary_scope_artifact_ref=boundary_scope_ref,
            data_run=run,
        )

    async def resume(self, request: DataAdmissionRequest) -> DataAdmissionResult:
        if request.recovery_gap_ref is None:
            raise ValueError("resume requires recovery_gap_ref")
        try:
            recovery_ref = ArtifactRef.model_validate(request.recovery_gap_ref)
        except Exception:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, request.normalized_input or request.content),
                state="POLICY_REJECTED",
                reason_code="recovery_gap_ref_invalid",
                reason="recovery_gap_ref must be an immutable DataAdmissionGap artifact ref",
            )
        if recovery_ref.schema_id != "DataAdmissionGap":
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, request.normalized_input or request.content),
                state="POLICY_REJECTED",
                reason_code="recovery_gap_ref_wrong_schema",
                reason="recovery_gap_ref must identify a DataAdmissionGap artifact",
            )
        recovery_state = self._admission_state(
            request,
            run_id=recovery_ref.run_id,
            refs={"data_admission_gap": recovery_ref.model_dump(mode="json")},
        )
        recovery_state["branch_id"] = recovery_ref.branch_id
        gap = load_artifact(recovery_state, "data_admission_gap", DataAdmissionGap)
        if gap is None or gap.source_ref != request.source_ref:
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, request.normalized_input or request.content),
                state="POLICY_REJECTED",
                reason_code="recovery_gap_source_mismatch",
                reason="recovery gap does not belong to this source",
            )
        if gap.retryability != "retryable":
            return self._rejection(
                request,
                attempt_ref=self._attempt_ref(request, request.normalized_input or request.content),
                state="POLICY_REJECTED",
                reason_code="recovery_gap_not_retryable",
                reason="the recorded admission gap is terminal and cannot be resumed",
            )
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


def _artifact_digest(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("digest") or value.get("descriptor_digest") or "")
    return str(
        getattr(value, "digest", "")
        or getattr(value, "descriptor_digest", "")
        or ""
    )


def _data_budget(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


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
    def _catalog_index(
        snapshot: DataResourceCatalogSnapshot,
        *,
        source_ref: ArtifactRef,
        normalized_ref: ArtifactRef,
        representation_ref: ArtifactRef,
        capability_ref: ArtifactRef,
    ) -> DataResourceCatalogIndexSnapshot:
        """Build the small catalog pointer kept in workflow-visible DATA state."""

        return DataResourceCatalogIndexSnapshot(
            snapshot_id=snapshot.snapshot_id,
            catalog_digest=snapshot.digest,
            source_snapshot_ref=source_ref.digest,
            source_snapshot_digest=source_ref.digest,
            normalized_resource_ref=normalized_ref.digest,
            normalized_resource_digest=normalized_ref.digest,
            representation_snapshot_ref=representation_ref.digest,
            representation_snapshot_digest=representation_ref.digest,
            capability_index_ref=capability_ref.digest,
            capability_index_digest=capability_ref.digest,
            dataset_refs=tuple(item.dataset_ref for item in snapshot.datasets),
            dataset_digests=tuple(item.digest for item in snapshot.datasets),
            feature_refs=tuple(
                f"{item.dataset_ref}:{item.source_feature_ref}"
                for item in snapshot.features
            ),
            feature_digests=tuple(item.source_feature_digest for item in snapshot.features),
            representation_refs=tuple(item.representation_ref for item in snapshot.representations),
            representation_digests=tuple(item.content_digest for item in snapshot.representations),
            capability_refs=tuple(item.capability_ref for item in snapshot.capabilities),
            capability_digests=tuple(item.content_digest for item in snapshot.capabilities),
            admission_decision_refs=tuple(item.decision_ref for item in snapshot.admission_decisions),
            admission_policy_version=snapshot.admission_policy_version,
        )

    @staticmethod
    def normalize(
        source: Any,
        *,
        dataset_ref: str,
        session_id: str = "",
        village_name: str = "",
        source_snapshot_ref: str = "",
        layer_ref: str = "",
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
            layer_ref=layer_ref,
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
        from app.modules.data.invalidation import build_data_dependency_graph

        dependency_graph = build_data_dependency_graph(
            normalized,
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
        source_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "source_snapshot",
                "data",
                "SourceSnapshotArtifact",
                source_product(
                    normalized.snapshot,
                    source_ref=str(state.get("source_ref") or request.session_id),
                    content_digest=str(state.get("content_digest") or ""),
                ),
                parent_keys=(),
            )
        )
        refs["source_snapshot"] = source_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        normalized_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "normalized_resource",
                "data",
                "NormalizedResourceArtifact",
                normalized_product(normalized.snapshot),
                parent_keys=("source_snapshot",),
            )
        )
        refs["normalized_resource"] = normalized_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        representation_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "representation_snapshot",
                "data",
                "RepresentationSnapshotArtifact",
                RepresentationSnapshotArtifact(
                    snapshot_id=normalized.snapshot.snapshot_id,
                    representations=normalized.snapshot.representations,
                ),
                parent_keys=("normalized_resource",),
            )
        )
        refs["representation_snapshot"] = representation_ref.model_dump(mode="json")
        artifact_state = self._artifact_state(state, refs)
        capability_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "capability_index",
                "data",
                "CapabilityIndexArtifact",
                CapabilityIndexArtifact(
                    snapshot_id=normalized.snapshot.snapshot_id,
                    capabilities=normalized.snapshot.capabilities,
                ),
                parent_keys=("representation_snapshot",),
            )
        )
        refs["capability_index"] = capability_ref.model_dump(mode="json")
        catalog_index = self._catalog_index(
            normalized.snapshot,
            source_ref=source_ref,
            normalized_ref=normalized_ref,
            representation_ref=representation_ref,
            capability_ref=capability_ref,
        )
        artifact_state = self._artifact_state(state, refs)
        catalog_ref = ArtifactRef.model_validate(
            store_artifact(
                artifact_state,
                "data_catalog",
                "data",
                "DataResourceCatalogIndexSnapshot",
                catalog_index,
                parent_keys=(
                    "source_snapshot", "normalized_resource",
                    "representation_snapshot", "capability_index",
                ),
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
            data_dependency_graph_digest=dependency_graph.graph_digest,
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
                "source_snapshot": source_ref,
                "normalized_resource": normalized_ref,
                "representation_snapshot": representation_ref,
                "capability_index": capability_ref,
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
            source_snapshot_ref=source_ref,
            normalized_resource_ref=normalized_ref,
            representation_snapshot_ref=representation_ref,
            capability_index_ref=capability_ref,
            data_snapshot_ref=data_snapshot_ref,
            stage_ref=stage_ref,
            gate_ref=gate_ref,
            state_patch={
                "artifact_refs": refs,
                "data_snapshot_id": snapshot.snapshot_id,
                "data_snapshot_digest": snapshot.digest,
                "data_stage_status": stage_snapshot.status,
                "data_gap_refs": list(stage_snapshot.gap_refs),
                "data_dependency_graph_digest": dependency_graph.graph_digest,
            },
        )

    @staticmethod
    def load_catalog(state: Mapping[str, Any]) -> DataResourceCatalogSnapshot | None:
        index = load_artifact(dict(state), "data_catalog", DataResourceCatalogIndexSnapshot)
        if index is None:
            return None
        source = load_artifact(dict(state), "source_snapshot", SourceSnapshotArtifact)
        normalized = load_artifact(dict(state), "normalized_resource", NormalizedResourceArtifact)
        representations = load_artifact(dict(state), "representation_snapshot", RepresentationSnapshotArtifact)
        capabilities = load_artifact(dict(state), "capability_index", CapabilityIndexArtifact)
        if any(item is None for item in (source, normalized, representations, capabilities)):
            raise RuntimeError("DATA catalog component artifact is missing")
        refs = dict(state).get("artifact_refs") or {}
        expected = {
            "source_snapshot": index.source_snapshot_ref,
            "normalized_resource": index.normalized_resource_ref,
            "representation_snapshot": index.representation_snapshot_ref,
            "capability_index": index.capability_index_ref,
        }
        for key, digest in expected.items():
            actual = str((refs.get(key) or {}).get("digest") or "")
            if actual != digest:
                raise RuntimeError(f"DATA catalog component ref mismatch: {key}")
        return compose_catalog(
            source,
            normalized,
            representations,
            capabilities,
            expected_digest=index.catalog_digest,
        )

    @staticmethod
    def load_snapshot(state: Mapping[str, Any]) -> SessionDataSnapshot | None:
        return load_artifact(dict(state), "data_snapshot", SessionDataSnapshot)

    @staticmethod
    def load_stage(state: Mapping[str, Any]) -> DataStageSnapshot | None:
        return load_artifact(dict(state), "data_stage", DataStageSnapshot)

    @staticmethod
    def load_boundary_scope(state: Mapping[str, Any]) -> Any | None:
        from app.contracts.data.boundary_contracts import BoundaryScopeArtifact

        return load_artifact(dict(state), "boundary_scope", BoundaryScopeArtifact)


async def run_data(
    state: Mapping[str, Any], *, catalog: Any = None
) -> DataRunResult:
    """Convenience entry point for composition roots and one-off probes."""

    return await DataApplication().run(state, catalog=catalog)


__all__ = ["DataApplication", "DataRunRequest", "DataRunResult", "run_data"]
