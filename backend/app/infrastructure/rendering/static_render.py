"""Session-scoped static planning preview renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _coordinates(geometry: Dict[str, Any]) -> Iterable[Tuple[float, float]]:
    geometry_type = geometry.get("type", "")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Point":
        if len(coordinates) >= 2:
            yield float(coordinates[0]), float(coordinates[1])
    elif geometry_type in ("MultiPoint", "LineString"):
        for coordinate in coordinates:
            if len(coordinate) >= 2:
                yield float(coordinate[0]), float(coordinate[1])
    elif geometry_type in ("MultiLineString", "Polygon"):
        for part in coordinates:
            for coordinate in part:
                if len(coordinate) >= 2:
                    yield float(coordinate[0]), float(coordinate[1])
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                for coordinate in ring:
                    if len(coordinate) >= 2:
                        yield float(coordinate[0]), float(coordinate[1])


def _layer_color(layer: Dict[str, Any], index: int) -> str:
    color = layer.get("color")
    if isinstance(color, str) and color:
        return color
    palette = (
        "#4C78A8",
        "#F58518",
        "#54A24B",
        "#E45756",
        "#72B7B2",
        "#B279A2",
        "#FF9DA6",
        "#9D755D",
    )
    return palette[index % len(palette)]


def _feature_color(properties: Dict[str, Any], fallback: str) -> str:
    from app.spatial.delivery import classification_color

    return classification_color(properties, fallback=fallback)
def _load_font(size: int):
    from PIL import ImageFont

    for path in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size), True
    return ImageFont.load_default(), False


def render_map_preview(
    layers: List[Dict[str, Any]],
    output_dir: str,
    village_name: str,
    *,
    force_layer_colors: bool = False,
    extent: Tuple[float, float, float, float] | None = None,
) -> Dict[str, Any]:
    """Render validated MapLibre layers to a session-scoped PNG preview."""
    from PIL import Image, ImageColor, ImageDraw

    output_path = Path(output_dir) / "planning_preview.png"

    all_points: List[Tuple[float, float]] = []
    boundary_points: List[Tuple[float, float]] = []
    current_landuse_points: List[Tuple[float, float]] = []
    for layer in layers:
        geojson = layer.get("geojson") or {}
        layer_points: List[Tuple[float, float]] = []
        for feature in geojson.get("features", []):
            layer_points.extend(_coordinates(feature.get("geometry") or {}))
        all_points.extend(layer_points)
        layer_type = layer.get("layerType") or layer.get("layer_type") or ""
        layer_name = layer.get("layerName") or layer.get("layer_name") or ""
        if layer_type == "boundary":
            boundary_points.extend(layer_points)
        if layer_name == "current_landuse":
            current_landuse_points.extend(layer_points)
    all_points = boundary_points or current_landuse_points or all_points
    if not all_points:
        return {
            "status": "failed",
            "reason": "no_renderable_geometry",
            "path": "",
            "layer_count": 0,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width_px = 1800
    height_px = 1300
    margin = 90
    image = Image.new("RGBA", (width_px, height_px), "#f8fafc")
    draw = ImageDraw.Draw(image, "RGBA")
    title_font, has_cjk_font = _load_font(34)
    label_font, _ = _load_font(20)
    small_font, _ = _load_font(16)

    if extent is None:
        xs = [point[0] for point in all_points]
        ys = [point[1] for point in all_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
    else:
        min_x, min_y, max_x, max_y = extent
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    extent_padding_x = span_x * 0.05
    extent_padding_y = span_y * 0.05

    def is_visible(point: Tuple[float, float]) -> bool:
        return (
            min_x - extent_padding_x <= point[0] <= max_x + extent_padding_x
            and min_y - extent_padding_y <= point[1] <= max_y + extent_padding_y
        )

    available_width = width_px - margin * 2
    available_height = height_px - margin * 2
    scale = min(available_width / span_x, available_height / span_y)
    drawn_width = span_x * scale
    drawn_height = span_y * scale
    offset_x = margin + (available_width - drawn_width) / 2
    offset_y = margin + (available_height - drawn_height) / 2

    def project(point: Tuple[float, float]) -> Tuple[float, float]:
        x = offset_x + (point[0] - min_x) * scale
        y = height_px - offset_y - (point[1] - min_y) * scale
        return x, y

    for grid_index in range(6):
        gx = margin + grid_index * available_width / 5
        gy = margin + grid_index * available_height / 5
        draw.line([(gx, margin), (gx, height_px - margin)], fill="#cbd5e1", width=1)
        draw.line([(margin, gy), (width_px - margin, gy)], fill="#cbd5e1", width=1)

    legend_items: List[Tuple[str, str]] = []
    legend_names = set()
    rendered_layers = 0
    for index, layer in enumerate(layers):
        geojson = layer.get("geojson") or {}
        layer_type = (
            layer.get("layerType")
            or layer.get("layer_type")
            or f"layer_{index + 1}"
        )
        layer_name = (
            layer.get("layerName")
            or layer.get("layer_name")
            or layer_type
        )
        color = _layer_color(layer, index)
        layer_drawn = False
        feature_legend: Dict[str, str] = {}

        for feature in geojson.get("features", []):
            properties = feature.get("properties") or {}
            feature_color = (
                color
                if force_layer_colors or layer.get("force_layer_colors")
                else _feature_color(properties, color)
            )
            try:
                rgb = ImageColor.getrgb(feature_color)
            except (TypeError, ValueError):
                feature_color = color
                rgb = ImageColor.getrgb(color)
            feature_label = (
                properties.get("zone_type")
                or properties.get("assigned_zone")
                or properties.get("zone_name")
                or properties.get("category_name_zh")
                or properties.get("DLMC")
                or properties.get("planning_name")
                or properties.get("planning_land_use")
                or properties.get("name")
                or properties.get("SDDLMC")
                or properties.get("landuse_name")
            )
            if feature_label:
                feature_legend.setdefault(str(feature_label), feature_color)
            geometry = feature.get("geometry") or {}
            geometry_type = geometry.get("type", "")
            coordinates = geometry.get("coordinates") or []
            style = layer.get("style") or {}
            try:
                fill_alpha = int(float(style.get("fill-opacity", 0.41)) * 255)
            except (TypeError, ValueError):
                fill_alpha = 105
            polygon_fill = None if layer_type == "boundary" else (*rgb, fill_alpha)
            polygon_width = 5 if layer_type == "boundary" else 2
            try:
                polygon_width = int(style.get("line-width", polygon_width))
            except (TypeError, ValueError):
                pass
            line_color = style.get("line-color") or feature_color
            try:
                line_rgb = ImageColor.getrgb(line_color)
            except (TypeError, ValueError):
                line_rgb = rgb
            if geometry_type == "Polygon":
                for ring in coordinates[:1]:
                    if not any(is_visible((point[0], point[1])) for point in ring):
                        continue
                    points = [project((point[0], point[1])) for point in ring]
                    if len(points) >= 3:
                        draw.polygon(
                            points,
                            fill=polygon_fill,
                            outline=(*line_rgb, 230),
                            width=polygon_width,
                        )
                        layer_drawn = True
            elif geometry_type == "MultiPolygon":
                for polygon in coordinates:
                    for ring in polygon[:1]:
                        if not any(is_visible((point[0], point[1])) for point in ring):
                            continue
                        points = [project((point[0], point[1])) for point in ring]
                        if len(points) >= 3:
                            draw.polygon(
                                points,
                                fill=polygon_fill,
                                outline=(*line_rgb, 230),
                                width=polygon_width,
                            )
                            layer_drawn = True
            elif geometry_type == "LineString":
                if not any(is_visible((point[0], point[1])) for point in coordinates):
                    continue
                points = [project((point[0], point[1])) for point in coordinates]
                if len(points) >= 2:
                    draw.line(points, fill=(*rgb, 255), width=5, joint="curve")
                    layer_drawn = True
            elif geometry_type == "MultiLineString":
                for line in coordinates:
                    if not any(is_visible((point[0], point[1])) for point in line):
                        continue
                    points = [project((point[0], point[1])) for point in line]
                    if len(points) >= 2:
                        draw.line(points, fill=(*rgb, 255), width=5, joint="curve")
                        layer_drawn = True
            elif geometry_type == "Point" and len(coordinates) >= 2:
                if not is_visible((coordinates[0], coordinates[1])):
                    continue
                x, y = project((coordinates[0], coordinates[1]))
                layer_is_point_overlay = layer_type in {
                    "planned_project_point", "facility_point", "planned_facility",
                }
                radius = 3 if properties.get("marker_size") == "small" or layer_is_point_overlay else 5
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*rgb, 255), outline="white", width=1)
                layer_drawn = True
            elif geometry_type == "MultiPoint":
                for point in coordinates:
                    if len(point) >= 2 and is_visible((point[0], point[1])):
                        x, y = project((point[0], point[1]))
                        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(*rgb, 255), outline="white", width=1)
                        layer_drawn = True

        if layer_drawn:
            rendered_layers += 1
            for feature_name, feature_color in feature_legend.items():
                if len(legend_items) >= 12:
                    break
                if feature_name not in legend_names:
                    legend_items.append((feature_name, feature_color))
                    legend_names.add(feature_name)
            if not feature_legend and len(legend_items) < 12 and layer_name not in legend_names:
                legend_items.append((str(layer_name), color))
                legend_names.add(str(layer_name))

    title = village_name if has_cjk_font else f"{village_name} Planning Preview"
    draw.text((margin, 24), title, fill="#111827", font=title_font)
    draw.text(
        (margin, height_px - 55),
        f"Extent: {min_x:.6f}, {min_y:.6f} - {max_x:.6f}, {max_y:.6f}",
        fill="#475569",
        font=small_font,
    )

    north_x = width_px - 125
    north_y = 100
    draw.text((north_x - 8, north_y - 42), "N", fill="#111827", font=label_font)
    draw.line(
        [(north_x, north_y + 45), (north_x, north_y)],
        fill="#111827",
        width=4,
    )
    draw.polygon(
        [(north_x, north_y - 8), (north_x - 10, north_y + 12), (north_x + 10, north_y + 12)],
        fill="#111827",
    )

    if legend_items:
        legend_x = width_px - 390
        legend_y = height_px - margin - len(legend_items) * 32 - 30
        draw.rounded_rectangle(
            (
                legend_x - 18,
                legend_y - 18,
                width_px - margin,
                height_px - margin,
            ),
            radius=10,
            fill=(255, 255, 255, 225),
            outline="#94a3b8",
            width=1,
        )
        for item_index, (name, color) in enumerate(legend_items):
            y = legend_y + item_index * 32
            draw.rectangle(
                (legend_x, y + 3, legend_x + 24, y + 23),
                fill=ImageColor.getrgb(color),
            )
            draw.text((legend_x + 34, y), name, fill="#111827", font=small_font)

    image.convert("RGB").save(output_path, format="PNG")
    artifact = {
        "status": "completed",
        "path": str(output_path),
        "layer_count": rendered_layers,
        "width_px": width_px,
        "height_px": height_px,
        "cjk_font_available": has_cjk_font,
        "extent": [min_x, min_y, max_x, max_y],
    }

    manifest_path = output_path.parent / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = [
                item
                for item in manifest.get("artifacts", [])
                if item.get("kind") != "planning_preview"
            ]
            manifest["artifacts"].append({
                "kind": "planning_preview",
                **artifact,
            })
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
    return artifact


def render_comparison_preview(
    layers: List[Dict[str, Any]],
    output_dir: str,
    village_name: str,
) -> Dict[str, Any]:
    """Render one PNG containing side-by-side current and planned maps."""
    from PIL import Image, ImageColor, ImageDraw
    import tempfile

    current_types = {
        "current_landuse", "current_road", "current_annotation", "boundary",
        "input_constraint",
    }
    planned_types = {
        "complete_planned_landuse", "planned_changes", "function_zone",
        "planned_project", "planned_project_point", "facility_point", "planned_road", "development_axis", "boundary",
    }
    current_layers = [
        layer for layer in layers
        if (layer.get("layerType") or layer.get("layer_type")) in current_types
    ]
    planned_layers = [
        layer for layer in layers
        if (layer.get("layerType") or layer.get("layer_type")) in planned_types
    ]
    with tempfile.TemporaryDirectory(prefix="planning-preview-") as temp_dir:
        current_dir = Path(temp_dir) / "current"
        planned_dir = Path(temp_dir) / "planned"
        # The current land-use/boundary layers define the authoritative map
        # extent.  Planned overlays may contain unresolved placeholder
        # geometries (for example POINT (0 0)); allowing those values to
        # define the shared extent makes both panels appear empty.
        comparison_points: List[Tuple[float, float]] = []
        for layer in current_layers:
            for feature in (layer.get("geojson") or {}).get("features", []):
                comparison_points.extend(_coordinates(feature.get("geometry") or {}))
        if not comparison_points:
            for layer in planned_layers:
                for feature in (layer.get("geojson") or {}).get("features", []):
                    comparison_points.extend(_coordinates(feature.get("geometry") or {}))
        xs = [point[0] for point in comparison_points]
        ys = [point[1] for point in comparison_points]
        shared_extent = (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None
        current_result = render_map_preview(
            current_layers,
            str(current_dir),
            f"{village_name} 现状",
            extent=shared_extent,
        )
        planned_result = render_map_preview(
            planned_layers,
            str(planned_dir),
            f"{village_name} 规划",
            extent=shared_extent,
        )
        if current_result.get("status") != "completed" or planned_result.get("status") != "completed":
            return {"status": "failed", "reason": "current_or_planned_panel_failed", "current": current_result, "planned": planned_result}
        current_image = Image.open(current_result["path"]).convert("RGBA")
        planned_image = Image.open(planned_result["path"]).convert("RGBA")
        panel_width = max(current_image.width, planned_image.width)
        panel_height = max(current_image.height, planned_image.height)
        canvas = Image.new("RGBA", (panel_width * 2, panel_height), "#f8fafc")
        canvas.alpha_composite(current_image, (0, 0))
        canvas.alpha_composite(planned_image, (panel_width, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        margin = 90
        draw.line(
            (panel_width, 0, panel_width, panel_height), fill="#0f172a", width=4
        )
        planned_landuse = next(
            (
                layer
                for layer in planned_layers
                if (layer.get("layerType") or layer.get("layer_type"))
                == "complete_planned_landuse"
            ),
            {},
        )
        changed_count = sum(
            1
            for feature in (planned_landuse.get("geojson") or {}).get("features", [])
            if (feature.get("properties") or {}).get("change_status")
            not in {None, "preserved", "unchanged"}
        )
        point_count = sum(
            len((layer.get("geojson") or {}).get("features", []))
            for layer in planned_layers
            if (layer.get("layerType") or layer.get("layer_type"))
            in {"planned_project_point", "facility_point", "planned_facility"}
        )
        status_font, _ = _load_font(17)
        status_text = (
            f"地类变更 {changed_count} 个"
            if changed_count
            else "地类变更 0 个（全部保留现状）"
        ) + f" · 定位点 {point_count} 个"
        status_color = "#166534" if changed_count else "#92400e"
        status_box_x = panel_width + margin
        status_box_y = 52
        draw.rounded_rectangle(
            (status_box_x - 12, status_box_y - 8, status_box_x + 390, status_box_y + 28),
            radius=8,
            fill=(255, 251, 235, 235) if not changed_count else (240, 253, 244, 235),
            outline=status_color,
            width=1,
        )
        draw.text((status_box_x, status_box_y), status_text, fill=status_color, font=status_font)
        overlay_items: list[tuple[str, str, str, int]] = []
        overlay_labels = {
            "planned_project": ("规划项目面", "#b91c1c", "polygon"),
            "planned_project_point": ("规划项目点", "#b91c1c", "point"),
            "facility_point": ("公共服务设施", "#2563eb", "point"),
            "planned_facility": ("公共服务设施", "#2563eb", "point"),
            "planned_road": ("规划道路", "#d97706", "line"),
            "development_axis": ("发展轴线", "#7c3aed", "line"),
        }
        seen_overlay_labels: set[str] = set()
        for layer in planned_layers:
            layer_type = layer.get("layerType") or layer.get("layer_type") or ""
            descriptor = overlay_labels.get(layer_type)
            count = len((layer.get("geojson") or {}).get("features", []))
            if descriptor is None or count <= 0 or descriptor[0] in seen_overlay_labels:
                continue
            seen_overlay_labels.add(descriptor[0])
            overlay_items.append((*descriptor, count))
        if overlay_items:
            overlay_font, _ = _load_font(18)
            box_x = panel_width + margin
            box_y = 112
            box_height = 22 + len(overlay_items) * 28
            draw.rounded_rectangle(
                (box_x - 12, box_y - 10, box_x + 285, box_y + box_height),
                radius=8,
                fill=(255, 255, 255, 225),
                outline="#94a3b8",
                width=1,
            )
            for item_index, (label, color, geometry_kind, count) in enumerate(overlay_items):
                y = box_y + item_index * 28
                rgb = ImageColor.getrgb(color)
                if geometry_kind == "point":
                    draw.ellipse((box_x, y + 5, box_x + 10, y + 15), fill=(*rgb, 255), outline="white", width=1)
                elif geometry_kind == "line":
                    draw.line((box_x, y + 10, box_x + 18, y + 10), fill=(*rgb, 255), width=3)
                else:
                    draw.rectangle((box_x, y + 4, box_x + 15, y + 16), fill=(*rgb, 150), outline=(*rgb, 255), width=1)
                draw.text((box_x + 28, y), f"{label} ({count})", fill="#111827", font=overlay_font)
        output_path = Path(output_dir) / "planning_preview.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path)
    return {
        "status": "completed",
        "path": str(output_path),
        "layer_count": len(current_layers) + len(planned_layers),
        "panel_count": 2,
        "planned_change_count": changed_count,
        "planned_point_count": point_count,
        "panels": {"current": current_result, "planned": planned_result},
    }


__all__ = ["render_map_preview", "render_comparison_preview"]
