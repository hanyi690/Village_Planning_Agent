"""Delivery and map-layer projections from explicit immutable artifacts."""

from __future__ import annotations

import hashlib
import json

from app.application.projections.models import (
    DeliveryView,
    MapLayerCollectionView,
    MapLayerView,
)
from app.application.projections.session import ProjectionNotFoundError
from app.application.queries.artifacts import artifact_queries
from app.application.queries.workflow_state import load_workflow_state
from app.domain.delivery.gate import summarize_planning_output


def _layer_view(layer: dict[str, object]) -> MapLayerView:
    layer_name = str(layer.get("layerType") or layer.get("layer_type") or "")
    data = layer.get("data") or layer.get("geojson") or {
        "type": "FeatureCollection",
        "features": [],
    }
    if not isinstance(data, dict):
        data = {"type": "FeatureCollection", "features": []}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if layer_name in {"current_landuse", "current_road", "boundary"}:
        kind = "current"
    elif layer_name == "input_constraint":
        kind = "constraint"
    elif layer_name == "complete_planned_landuse":
        kind = "planned"
    else:
        kind = "overlay"
    features = data.get("features")
    return MapLayerView(
        layer_type=kind,
        layer_name=layer_name,
        checksum=hashlib.sha256(raw).hexdigest(),
        feature_count=len(features) if isinstance(features, list) else 0,
        geojson=data,
    )


def _effective_delivery_status(
    payload: dict[str, object] | None,
    *,
    render_layers: list[object] | None = None,
    snapshot_payload: dict[str, object] | None = None,
) -> str | None:
    """Expose an explicit status when delivery refs are absent or baseline-only."""
    payload = payload or {}
    planning = payload.get("planning_output")
    if not isinstance(planning, dict):
        diagnostic_summary = payload.get("diagnostic_summary")
        if isinstance(diagnostic_summary, dict):
            planning = diagnostic_summary.get("planning_output")
    if isinstance(planning, dict) and planning.get("status") == "no_planning_output":
        return "no_planning_output"
    if render_layers is not None:
        summary = summarize_planning_output(render_layers, snapshot_payload or {})
        if summary["status"] == "no_planning_output":
            return "no_planning_output"
    status = payload.get("delivery_status")
    return str(status) if status else None


class DeliveryProjectionService:
    async def get(self, session_id: str) -> DeliveryView:
        if not await load_workflow_state(session_id):
            raise ProjectionNotFoundError("session not found")
        manifest = await artifact_queries.read(session_id, "delivery_manifest")
        if not manifest or not isinstance(manifest.payload, dict):
            return DeliveryView(session_id=session_id, available=False)
        payload = manifest.payload
        deliverables = [
            item for item in payload.get("deliverables") or [] if isinstance(item, dict)
        ]
        return DeliveryView(
            session_id=session_id,
            available=True,
            delivery_status=(
                _effective_delivery_status(payload)
            ),
            statutory_complete=bool(payload.get("statutory_complete")),
            snapshot_checksum=str(manifest.artifact_ref.get("digest") or ""),
            deferral_summary=dict(payload.get("deferral_summary") or {}),
            diagnostic_summary=dict(payload.get("diagnostic_summary") or {}),
            deliverables=deliverables,
            downloads=[str(item.get("path")) for item in deliverables if item.get("path")],
        )

    async def map_layers(self, session_id: str) -> MapLayerCollectionView:
        manifest = await artifact_queries.read(session_id, "delivery_manifest")
        snapshot = await artifact_queries.read(session_id, "delivery_spatial_snapshot")
        # Render layers and a spatial snapshot are not independently
        # authoritative.  Without the DeliveryManifest there is no proof that
        # they belong to the same completed/partial delivery transaction, so
        # the read path must fail closed instead of exposing stale layers with
        # a null delivery status.
        if not manifest or not isinstance(manifest.payload, dict):
            if not await load_workflow_state(session_id):
                raise ProjectionNotFoundError("session not found")
            return MapLayerCollectionView(
                session_id=session_id,
                delivery_status="no_planning_output",
                layers=[],
            )
        if not snapshot or not isinstance(snapshot.payload, dict):
            return MapLayerCollectionView(
                session_id=session_id,
                snapshot_checksum=str(manifest.artifact_ref.get("digest") or ""),
                delivery_status="no_planning_output",
                layers=[],
            )
        render_layers = await artifact_queries.read(session_id, "render_layers")
        if not render_layers or not isinstance(render_layers.payload, list):
            return MapLayerCollectionView(
                session_id=session_id,
                snapshot_checksum=str(snapshot.artifact_ref.get("digest") or ""),
                delivery_status="no_planning_output",
                layers=[],
            )
        layers = [
            _layer_view(layer)
            for layer in render_layers.payload
            if isinstance(layer, dict)
        ]
        return MapLayerCollectionView(
            session_id=session_id,
            snapshot_checksum=str(snapshot.artifact_ref.get("digest") or ""),
            delivery_status=(
                _effective_delivery_status(
                    manifest.payload if manifest and isinstance(manifest.payload, dict) else {},
                    render_layers=render_layers.payload,
                    snapshot_payload=snapshot.payload,
                )
            ),
            layers=layers,
        )


delivery_projections = DeliveryProjectionService()


__all__ = ["DeliveryProjectionService", "delivery_projections"]
