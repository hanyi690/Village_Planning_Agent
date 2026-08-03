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
) -> Dict[str, Any]:
    """Render validated MapLibre layers to a session-scoped PNG preview."""
    from PIL import Image, ImageColor, ImageDraw

    output_path = Path(output_dir) / "planning_preview.png"

    all_points: List[Tuple[float, float]] = []
    for layer in layers:
        geojson = layer.get("geojson") or {}
        for feature in geojson.get("features", []):
            all_points.extend(_coordinates(feature.get("geometry") or {}))
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

    xs = [point[0] for point in all_points]
    ys = [point[1] for point in all_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)

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
            feature_color = properties.get("color") or color
            try:
                rgb = ImageColor.getrgb(feature_color)
            except (TypeError, ValueError):
                feature_color = color
                rgb = ImageColor.getrgb(color)
            feature_label = (
                properties.get("zone_type")
                or properties.get("assigned_zone")
                or properties.get("category_name_zh")
                or properties.get("DLMC")
            )
            if feature_label and properties.get("color"):
                feature_legend.setdefault(str(feature_label), feature_color)
            geometry = feature.get("geometry") or {}
            geometry_type = geometry.get("type", "")
            coordinates = geometry.get("coordinates") or []
            if geometry_type == "Polygon":
                for ring in coordinates[:1]:
                    points = [project((point[0], point[1])) for point in ring]
                    if len(points) >= 3:
                        draw.polygon(points, fill=(*rgb, 105), outline=(*rgb, 230), width=2)
                        layer_drawn = True
            elif geometry_type == "MultiPolygon":
                for polygon in coordinates:
                    for ring in polygon[:1]:
                        points = [project((point[0], point[1])) for point in ring]
                        if len(points) >= 3:
                            draw.polygon(points, fill=(*rgb, 105), outline=(*rgb, 230), width=2)
                            layer_drawn = True
            elif geometry_type == "LineString":
                points = [project((point[0], point[1])) for point in coordinates]
                if len(points) >= 2:
                    draw.line(points, fill=(*rgb, 255), width=5, joint="curve")
                    layer_drawn = True
            elif geometry_type == "MultiLineString":
                for line in coordinates:
                    points = [project((point[0], point[1])) for point in line]
                    if len(points) >= 2:
                        draw.line(points, fill=(*rgb, 255), width=5, joint="curve")
                        layer_drawn = True
            elif geometry_type == "Point" and len(coordinates) >= 2:
                x, y = project((coordinates[0], coordinates[1]))
                draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(*rgb, 255), outline="white", width=2)
                layer_drawn = True
            elif geometry_type == "MultiPoint":
                for point in coordinates:
                    if len(point) >= 2:
                        x, y = project((point[0], point[1]))
                        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(*rgb, 255), outline="white", width=2)
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

    title = f"{village_name} 规划成果预览" if has_cjk_font else f"{village_name} Planning Preview"
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
    }

    manifest_path = output_path.parent / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.setdefault("artifacts", []).append({
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


__all__ = ["render_map_preview"]
