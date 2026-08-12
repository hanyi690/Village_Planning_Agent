"""DELIVER export adapter for a validated spatial snapshot."""

from __future__ import annotations

from typing import Any


def export_delivery_products(
    render_layers: list[dict[str, Any]],
    *,
    snapshot: Any,
    village_name: str,
    session_id: str,
    validation_result: dict[str, Any],
) -> dict[str, Any]:
    """Write the delivery package from the same snapshot used by rendering."""

    from app.modules.spatial_ops.output.export_package import export_delivery_package

    return export_delivery_package(
        layout_configs=render_layers,
        snapshot=snapshot,
        village_name=village_name,
        session_id=session_id,
        validation_result=validation_result,
    )


__all__ = ["export_delivery_products"]
