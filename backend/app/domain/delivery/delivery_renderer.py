"""DELIVER-side rendering orchestration.

This module owns filesystem render side effects. It consumes already-built
render layers and never reads EXECUTE or raw GIS state.
"""

from __future__ import annotations

from typing import Any


def render_delivery_artifacts(
    render_layers: list[dict[str, Any]],
    *,
    session_id: str,
    village_name: str,
    snapshot: Any = None,
    snapshot_error: str = "",
) -> dict[str, Any]:
    """Render PNG/HTML from the exact layers used by delivery export."""
    from app.domain.delivery.delivery_validator import assess_render_quality

    artifacts: dict[str, Any] = {
        "layer_count": len(render_layers),
        "feature_counts": {
            str(layer.get("layerType") or layer.get("layer_type") or "layer"): len(
                (layer.get("geojson") or layer.get("data") or {}).get("features") or []
            )
            for layer in render_layers
            if isinstance(layer, dict)
        },
        "quality": assess_render_quality(render_layers),
    }
    if snapshot is not None:
        artifacts["delivery_snapshot_checksum"] = snapshot.checksum
    if snapshot_error:
        artifacts["delivery_snapshot_error"] = snapshot_error

    try:
        from app.infrastructure.paths import session_run_dir
        from app.infrastructure.rendering.html_render import render_interactive_map
        from app.infrastructure.rendering.static_render import render_comparison_preview

        output_dir = session_run_dir(session_id) / "render"
        if render_layers:
            change_summary = dict(getattr(snapshot, "change_summary", None) or {})
            changed_count = sum(
                int(change_summary.get(key) or 0)
                for key in ("modified", "split", "merged", "created", "removed")
            )
            delivery_status = str(getattr(snapshot, "delivery_status", "") or "partial")
            delivery_issues = []
            if changed_count == 0:
                delivery_issues.append({
                    "code": "NO_PARCEL_CHANGES",
                    "message": (
                        "本次没有 ParcelChange；期末地类仅保留现状，不能视为法定规划成果。"
                    ),
                })
            if delivery_status != "complete":
                delivery_issues.append({
                    "code": "DELIVERY_STATUS",
                    "message": f"交付状态：{delivery_status}",
                })
            layer_types = {
                str(layer.get("layerType") or layer.get("layer_type") or "")
                for layer in render_layers
                if (layer.get("geojson") or layer.get("data") or {}).get("features")
            }
            if "planned_road" not in layer_types:
                delivery_issues.append({
                    "code": "PLANNED_ROAD_NOT_GENERATED",
                    "message": "规划道路未生成；地图不会使用示意线替代权威道路几何。",
                })
            zone_types = {
                "function_zone", "planning_zone", "custom_planning_zone",
                "custom_functional_zone", "restoration_zone", "protection_zone",
            }
            if not layer_types.intersection(zone_types):
                delivery_issues.append({
                    "code": "PLANNED_ZONE_NOT_GENERATED",
                    "message": "规划分区未生成；地图不会使用底图地类冒充规划分区。",
                })
            artifacts["static_preview"] = render_comparison_preview(
                render_layers, str(output_dir), village_name
            )
            artifacts["interactive_map"] = render_interactive_map(
                render_layers,
                str(output_dir),
                village_name,
                issues=delivery_issues,
                narrative_sections=[{
                    "title": "交付事实",
                    "text": (
                        f"期末地类变更 {changed_count} 个；"
                        f"保留地块 {int(change_summary.get('preserved') or 0)} 个；"
                        f"交付状态为 {delivery_status}。"
                    ),
                }],
            )
        else:
            artifacts["mapless"] = True
    except Exception as exc:
        artifacts["error"] = {
            "code": "RENDER_FILE_FAILED",
            "type": type(exc).__name__,
            "message": str(exc),
        }
    return artifacts


__all__ = ["render_delivery_artifacts"]
