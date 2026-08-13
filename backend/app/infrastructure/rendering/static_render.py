"""Session-scoped static planning preview renderer.

The renderer is deliberately presentation-only.  It never invents geometry:
missing planned roads/zones are reported as missing instead of being replaced
with decorative lines or polygons.
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

_POINT_TYPES = {
    "planned_project_point",
    "facility_point",
    "planned_facility",
}
_ZONE_TYPES = {
    "function_zone",
    "planning_zone",
    "custom_planning_zone",
    "custom_functional_zone",
    "restoration_zone",
    "protection_zone",
}


def _coordinates(geometry: Dict[str, Any]) -> Iterable[Point]:
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


def _layer_type(layer: Dict[str, Any]) -> str:
    return str(layer.get("layerType") or layer.get("layer_type") or "layer")


def _layer_name(layer: Dict[str, Any]) -> str:
    return str(layer.get("layerName") or layer.get("layer_name") or _layer_type(layer))


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


def _classification_label(properties: Dict[str, Any]) -> str:
    for key in (
        "zone_type",
        "assigned_zone",
        "zone_name",
        "category_name_zh",
        "DLMC",
        "dlmc",
        "planning_name",
        "planning_land_use",
        "SDDLMC",
        "sddlmc",
        "landuse_name",
    ):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _point_name(properties: Dict[str, Any]) -> str:
    for key in (
        "project_name",
        "name",
        "facility_type",
    ):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return "名称未提供"


def _road_action(properties: Dict[str, Any]) -> str:
    value = str(
        properties.get("action")
        or properties.get("intervention_action")
        or properties.get("operation")
        or properties.get("task_type")
        or ""
    ).strip().lower()
    if any(token in value for token in ("upgrade", "repair", "improve", "reconstruct", "改", "提升", "修复")):
        return "改造"
    if any(token in value for token in ("new", "build", "新增", "新建")):
        return "新建"
    if any(token in value for token in ("retain", "preserve", "保留")):
        return "保留"
    return "动作未提供"


def _road_style(properties: Dict[str, Any]) -> Dict[str, Any]:
    level = str(properties.get("road_level") or properties.get("level") or "未分级")
    if any(token in level for token in ("高速", "国道", "省道")):
        color, width = "#b91c1c", 9
    elif any(token in level for token in ("县道", "三级")):
        color, width = "#ea580c", 8
    elif "乡道" in level:
        color, width = "#f59e0b", 7
    elif "村道" in level:
        color, width = "#2563eb", 6
    elif any(token in level for token in ("机耕", "步道", "巷")):
        color, width = "#16a34a", 4
    else:
        color, width = "#d97706", 6
    action = _road_action(properties)
    dash = (14, 8) if action == "改造" else ((4, 6) if action == "保留" else None)
    return {
        "color": color,
        "width": width,
        "dash": dash,
        "level": level or "未分级",
        "action": action,
    }


def _boxes_overlap(left: Box, right: Box, padding: int = 4) -> bool:
    return not (
        left[2] + padding < right[0]
        or right[2] + padding < left[0]
        or left[3] + padding < right[1]
        or right[3] + padding < left[1]
    )


def _draw_dashed_line(draw, points: List[Point], *, fill: Any, width: int, dash: Tuple[int, int]) -> None:
    on, off = dash
    cycle = float(on + off)
    phase = 0.0
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        cursor = 0.0
        while cursor < length:
            position = (phase + cursor) % cycle
            step = min((on if position < on else cycle) - position, length - cursor)
            if position < on and step > 0:
                a = cursor / length
                b = (cursor + step) / length
                draw.line(
                    (
                        (start[0] + dx * a, start[1] + dy * a),
                        (start[0] + dx * b, start[1] + dy * b),
                    ),
                    fill=fill,
                    width=width,
                )
            cursor += max(step, 0.1)
        phase = (phase + length) % cycle


def _nice_distance(value: float) -> float:
    if value <= 0:
        return 0.0
    exponent = 10 ** math.floor(math.log10(value))
    fraction = value / exponent
    nice = 1 if fraction < 2 else (2 if fraction < 5 else 5)
    return nice * exponent


def _horizontal_distance_m(x0: float, x1: float, latitude: float) -> float:
    if all((-180 <= value <= 180) for value in (x0, x1)) and -90 <= latitude <= 90:
        return abs(math.radians(x1 - x0) * 6_371_008.8 * math.cos(math.radians(latitude)))
    return abs(x1 - x0)


def _draw_scale_bar(draw, bounds: Box, extent: Box, font) -> Dict[str, Any]:
    left, _top, right, bottom = bounds
    min_x, min_y, max_x, max_y = extent
    total_m = _horizontal_distance_m(min_x, max_x, (min_y + max_y) / 2)
    map_width = right - left
    meters_per_pixel = total_m / max(map_width, 1)
    distance_m = _nice_distance(total_m / 5)
    pixel_width = distance_m / max(meters_per_pixel, 1e-9)
    x0 = left + 24
    y = bottom - 28
    draw.rounded_rectangle(
        (x0 - 12, y - 26, x0 + pixel_width + 12, y + 18),
        radius=5,
        fill=(255, 255, 255, 225),
        outline="#94a3b8",
        width=1,
    )
    draw.line((x0, y, x0 + pixel_width, y), fill="#0f172a", width=5)
    draw.line((x0, y - 6, x0, y + 6), fill="#0f172a", width=2)
    draw.line((x0 + pixel_width, y - 6, x0 + pixel_width, y + 6), fill="#0f172a", width=2)
    if distance_m >= 1000:
        label = f"{distance_m / 1000:g} km"
    else:
        label = f"{distance_m:g} m"
    draw.text((x0, y - 24), label, fill="#0f172a", font=font)
    return {"distance_m": distance_m, "pixel_width": round(pixel_width, 2), "label": label}


def _layer_priority(layer: Dict[str, Any]) -> int:
    layer_type = _layer_type(layer)
    return {
        "current_landuse": 10,
        "complete_planned_landuse": 10,
        "input_constraint": 20,
        "function_zone": 25,
        "planning_zone": 25,
        "restoration_zone": 25,
        "protection_zone": 25,
        "current_road": 35,
        "planned_project": 40,
        "planned_changes": 50,
        "development_axis": 60,
        "planned_road": 70,
        "current_annotation": 75,
        "planned_project_point": 80,
        "facility_point": 80,
        "planned_facility": 80,
        "boundary": 90,
    }.get(layer_type, 30)


def _legend_key(
    layer_type: str,
    layer_name: str,
    properties: Dict[str, Any],
    color: str,
) -> Tuple[str, Dict[str, Any]]:
    if layer_type == "planned_road":
        style = _road_style(properties)
        label = f"{style['level']} · {style['action']}"
        return label, {"label": label, "color": style["color"], "symbol": "line", **style}
    if layer_type == "current_road":
        return "现状道路", {"label": "现状道路", "color": "#64748b", "symbol": "line", "width": 2}
    if layer_type in _POINT_TYPES:
        label = "规划项目点" if layer_type == "planned_project_point" else "公共服务设施"
        return label, {"label": label, "color": color, "symbol": "point"}
    if layer_type == "planned_changes":
        return "规划变更地块", {"label": "规划变更地块", "color": "#dc2626", "symbol": "change"}
    if layer_type == "planned_project":
        return "规划项目用地", {"label": "规划项目用地", "color": color, "symbol": "polygon"}
    if layer_type == "development_axis":
        return "发展轴线", {"label": "发展轴线", "color": "#7c3aed", "symbol": "line", "width": 5, "dash": (10, 7)}
    if layer_type == "boundary":
        return "村域边界", {"label": "村域边界", "color": color, "symbol": "line", "width": 4}
    label = _classification_label(properties) or layer_name
    return label, {"label": label, "color": color, "symbol": "polygon"}


def render_map_preview(
    layers: List[Dict[str, Any]],
    output_dir: str,
    village_name: str,
    *,
    force_layer_colors: bool = False,
    extent: Box | None = None,
    planning_panel: bool = False,
) -> Dict[str, Any]:
    """Render a map panel with a non-overlapping legend and audit status rail."""
    from PIL import Image, ImageColor, ImageDraw

    output_path = Path(output_dir) / "planning_preview.png"
    all_points: List[Point] = []
    boundary_points: List[Point] = []
    current_landuse_points: List[Point] = []
    for layer in layers:
        layer_points = [
            point
            for feature in (layer.get("geojson") or {}).get("features", [])
            for point in _coordinates(feature.get("geometry") or {})
        ]
        all_points.extend(layer_points)
        if _layer_type(layer) == "boundary":
            boundary_points.extend(layer_points)
        if _layer_type(layer) == "current_landuse":
            current_landuse_points.extend(layer_points)
    reference_points = boundary_points or current_landuse_points or all_points
    if not reference_points:
        return {"status": "failed", "reason": "no_renderable_geometry", "path": "", "layer_count": 0}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    width_px, height_px = 1800, 1300
    map_bounds: Box = (70, 104, 1395, 1178)
    rail_bounds: Box = (1422, 82, 1768, 1222)
    map_left, map_top, map_right, map_bottom = map_bounds
    image = Image.new("RGBA", (width_px, height_px), "#eef2f7")
    draw = ImageDraw.Draw(image, "RGBA")
    title_font, has_cjk_font = _load_font(34)
    section_font, _ = _load_font(21)
    label_font, _ = _load_font(17)
    small_font, _ = _load_font(14)
    marker_font, _ = _load_font(13)

    if extent is None:
        xs = [point[0] for point in reference_points]
        ys = [point[1] for point in reference_points]
        min_x, min_y, max_x, max_y = min(xs), min(ys), max(xs), max(ys)
    else:
        min_x, min_y, max_x, max_y = extent
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    extent_padding_x = span_x * 0.05
    extent_padding_y = span_y * 0.05

    def is_visible(point: Point) -> bool:
        return (
            min_x - extent_padding_x <= point[0] <= max_x + extent_padding_x
            and min_y - extent_padding_y <= point[1] <= max_y + extent_padding_y
        )

    available_width = map_right - map_left
    available_height = map_bottom - map_top
    scale = min(available_width / span_x, available_height / span_y)
    drawn_width = span_x * scale
    drawn_height = span_y * scale
    offset_x = map_left + (available_width - drawn_width) / 2
    offset_y = map_top + (available_height - drawn_height) / 2

    def project(point: Point) -> Point:
        return (
            offset_x + (point[0] - min_x) * scale,
            map_bottom - (available_height - drawn_height) / 2 - (point[1] - min_y) * scale,
        )

    draw.rounded_rectangle(map_bounds, radius=8, fill="#f8fafc", outline="#94a3b8", width=2)
    for grid_index in range(6):
        gx = map_left + grid_index * available_width / 5
        gy = map_top + grid_index * available_height / 5
        draw.line((gx, map_top, gx, map_bottom), fill="#cbd5e1", width=1)
        draw.line((map_left, gy, map_right, gy), fill="#cbd5e1", width=1)

    legend: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    rendered_layers = 0
    point_counts = {"planned_project_point": 0, "facility": 0}
    total_facility_points = sum(
        len((layer.get("geojson") or layer.get("data") or {}).get("features", []))
        for layer in layers
        if _layer_type(layer) in {"facility_point", "planned_facility"}
    )
    facility_label_stride = max(1, math.ceil(total_facility_points / 6))
    labelled_points = 0
    change_badge_count = 0
    change_anchors: List[Point] = []
    occupied_labels: List[Box] = []
    road_style_labels: set[str] = set()

    sorted_layers = sorted(enumerate(layers), key=lambda item: (_layer_priority(item[1]), item[0]))
    for index, layer in sorted_layers:
        geojson = layer.get("geojson") or layer.get("data") or {}
        layer_type = _layer_type(layer)
        layer_name = _layer_name(layer)
        fallback = _layer_color(layer, index)
        layer_drawn = False
        style = layer.get("style") or {}
        try:
            fill_alpha = int(float(style.get("fill-opacity", 0.38)) * 255)
        except (TypeError, ValueError):
            fill_alpha = 97

        for feature in geojson.get("features", []):
            properties = feature.get("properties") or {}
            feature_color = fallback if force_layer_colors or layer.get("force_layer_colors") else _feature_color(properties, fallback)
            if layer_type == "planned_changes":
                feature_color = "#dc2626"
            try:
                rgb = ImageColor.getrgb(feature_color)
            except (TypeError, ValueError):
                feature_color = fallback
                rgb = ImageColor.getrgb(fallback)
            legend_key, legend_item = _legend_key(layer_type, layer_name, properties, feature_color)
            item = legend.setdefault(legend_key, {**legend_item, "count": 0})
            item["count"] += 1

            geometry = feature.get("geometry") or {}
            geometry_type = geometry.get("type", "")
            coordinates = geometry.get("coordinates") or []
            line_color = style.get("line-color") or feature_color
            try:
                line_rgb = ImageColor.getrgb(line_color)
            except (TypeError, ValueError):
                line_rgb = rgb
            polygon_fill = (
                None
                if layer_type in {"boundary", "planned_changes"}
                else (*rgb, fill_alpha)
            )
            polygon_width = 5 if layer_type == "boundary" else (4 if layer_type == "planned_changes" else 1)
            try:
                polygon_width = int(style.get("line-width", polygon_width))
            except (TypeError, ValueError):
                pass

            polygons = []
            feature_change_badged = False
            if geometry_type == "Polygon":
                polygons = [coordinates]
            elif geometry_type == "MultiPolygon":
                polygons = coordinates
            for polygon in polygons:
                for ring in polygon[:1]:
                    if not any(is_visible((point[0], point[1])) for point in ring):
                        continue
                    points = [project((point[0], point[1])) for point in ring]
                    if len(points) >= 3:
                        draw.polygon(points, fill=polygon_fill, outline=(*line_rgb, 245), width=polygon_width)
                        if layer_type == "planned_changes":
                            draw.line(points, fill=(255, 255, 255, 235), width=1, joint="curve")
                            draw.line(points, fill=(*line_rgb, 255), width=4, joint="curve")
                            if not feature_change_badged:
                                change_badge_count += 1
                                center_x = sum(point[0] for point in points) / len(points)
                                center_y = sum(point[1] for point in points) / len(points)
                                change_anchors.append((center_x, center_y))
                                feature_change_badged = True
                        layer_drawn = True

            lines = []
            if geometry_type == "LineString":
                lines = [coordinates]
            elif geometry_type == "MultiLineString":
                lines = coordinates
            for line in lines:
                if not any(is_visible((point[0], point[1])) for point in line):
                    continue
                points = [project((point[0], point[1])) for point in line]
                if len(points) < 2:
                    continue
                if layer_type == "planned_road":
                    road_style = _road_style(properties)
                    road_rgb = ImageColor.getrgb(road_style["color"])
                    draw.line(points, fill=(255, 255, 255, 245), width=road_style["width"] + 5, joint="curve")
                    draw.line(points, fill=(71, 85, 105, 210), width=road_style["width"] + 2, joint="curve")
                    if road_style["dash"]:
                        _draw_dashed_line(draw, points, fill=(*road_rgb, 255), width=road_style["width"], dash=road_style["dash"])
                    else:
                        draw.line(points, fill=(*road_rgb, 255), width=road_style["width"], joint="curve")
                    road_style_labels.add(f"{road_style['level']} · {road_style['action']}")
                elif layer_type == "current_road":
                    draw.line(points, fill=(100, 116, 139, 165), width=2, joint="curve")
                elif layer_type == "development_axis":
                    _draw_dashed_line(draw, points, fill=(124, 58, 237, 255), width=5, dash=(12, 8))
                else:
                    try:
                        width = int(style.get("line-width", 4))
                    except (TypeError, ValueError):
                        width = 4
                    draw.line(points, fill=(*rgb, 255), width=width, joint="curve")
                layer_drawn = True

            points_to_draw = []
            if geometry_type == "Point" and len(coordinates) >= 2:
                points_to_draw = [coordinates]
            elif geometry_type == "MultiPoint":
                points_to_draw = coordinates
            for coordinate in points_to_draw:
                if len(coordinate) < 2 or not is_visible((coordinate[0], coordinate[1])):
                    continue
                x, y = project((coordinate[0], coordinate[1]))
                if layer_type in _POINT_TYPES:
                    counter_key = "planned_project_point" if layer_type == "planned_project_point" else "facility"
                    point_counts[counter_key] += 1
                    prefix = "P" if counter_key == "planned_project_point" else "F"
                    marker = f"{prefix}{point_counts[counter_key]:02d}"
                    marker_color = "#b91c1c" if prefix == "P" else "#1d4ed8"
                    marker_rgb = ImageColor.getrgb(marker_color)
                    radius = 12
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*marker_rgb, 255), outline="white", width=2)
                    marker_box = draw.textbbox((0, 0), marker, font=marker_font)
                    draw.text(
                        (x - (marker_box[2] - marker_box[0]) / 2, y - (marker_box[3] - marker_box[1]) / 2 - 1),
                        marker,
                        fill="white",
                        font=marker_font,
                    )
                    label = f"{marker}  {_point_name(properties)[:18]}"
                    should_label = prefix == "P" or point_counts[counter_key] % facility_label_stride == 1
                    if total_facility_points <= 12:
                        should_label = True
                    if not should_label:
                        layer_drawn = True
                        continue
                    text_box = draw.textbbox((0, 0), label, font=small_font)
                    text_width = text_box[2] - text_box[0]
                    text_height = text_box[3] - text_box[1]
                    for dx, dy in ((18, -28), (18, 8), (-text_width - 26, -28), (-text_width - 26, 8), (18, -52), (-text_width - 26, -52)):
                        candidate: Box = (x + dx, y + dy, x + dx + text_width + 12, y + dy + text_height + 8)
                        if candidate[0] < map_left or candidate[2] > map_right or candidate[1] < map_top or candidate[3] > map_bottom:
                            continue
                        if any(_boxes_overlap(candidate, existing) for existing in occupied_labels):
                            continue
                        draw.line((x, y, candidate[0] if dx > 0 else candidate[2], (candidate[1] + candidate[3]) / 2), fill=(*marker_rgb, 180), width=1)
                        draw.rounded_rectangle(candidate, radius=4, fill=(255, 255, 255, 232), outline=(*marker_rgb, 210), width=1)
                        draw.text((candidate[0] + 6, candidate[1] + 3), label, fill="#111827", font=small_font)
                        occupied_labels.append(candidate)
                        labelled_points += 1
                        break
                else:
                    radius = 5
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*rgb, 255), outline="white", width=1)
                layer_drawn = True

        if layer_drawn:
            rendered_layers += 1

    for badge_index, (x, y) in enumerate(change_anchors, start=1):
        badge = f"Δ{badge_index:02d} 地类变更"
        draw.polygon(
            ((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)),
            fill=(185, 28, 28, 255),
            outline="white",
        )
        text_box = draw.textbbox((0, 0), badge, font=small_font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        candidates = (
            (x + 16, y - 38),
            (x + 16, y + 14),
            (x - text_width - 30, y - 38),
            (x - text_width - 30, y + 14),
        )
        for label_x, label_y in candidates:
            candidate: Box = (
                label_x,
                label_y,
                label_x + text_width + 12,
                label_y + text_height + 8,
            )
            if candidate[0] < map_left or candidate[2] > map_right or candidate[1] < map_top or candidate[3] > map_bottom:
                continue
            if any(_boxes_overlap(candidate, existing) for existing in occupied_labels):
                continue
            draw.line(
                (x, y, candidate[0] if label_x > x else candidate[2], (candidate[1] + candidate[3]) / 2),
                fill=(185, 28, 28, 220),
                width=2,
            )
            draw.rounded_rectangle(
                candidate,
                radius=4,
                fill=(255, 255, 255, 242),
                outline=(185, 28, 28, 255),
                width=2,
            )
            draw.text((candidate[0] + 6, candidate[1] + 3), badge, fill="#991b1b", font=small_font)
            occupied_labels.append(candidate)
            break

    title = village_name if has_cjk_font else f"{village_name} Planning Preview"
    draw.text((map_left, 24), title, fill="#0f172a", font=title_font)
    subtitle = "权威规划几何叠加" if planning_panel else "现状基准"
    draw.text((map_left, 70), subtitle, fill="#64748b", font=small_font)

    draw.rounded_rectangle(rail_bounds, radius=10, fill=(255, 255, 255, 245), outline="#94a3b8", width=1)
    rail_left, rail_top, rail_right, rail_bottom = rail_bounds
    status_y = rail_top + 20
    missing_outputs: List[str] = []
    road_count = sum(len((layer.get("geojson") or {}).get("features", [])) for layer in layers if _layer_type(layer) == "planned_road")
    zone_count = sum(len((layer.get("geojson") or {}).get("features", [])) for layer in layers if _layer_type(layer) in _ZONE_TYPES)
    if planning_panel:
        draw.text((rail_left + 18, status_y), "成果完整性", fill="#0f172a", font=section_font)
        status_y += 38
        for label, count in (("规划道路", road_count), ("规划分区", zone_count)):
            if count:
                color, text_value = "#166534", f"{label}：已生成 {count} 个"
            else:
                color, text_value = "#b45309", f"{label}：未生成"
                missing_outputs.append(label)
            draw.rounded_rectangle((rail_left + 16, status_y - 4, rail_right - 16, status_y + 27), radius=5, fill="#fffbeb" if not count else "#f0fdf4", outline=color, width=1)
            draw.text((rail_left + 26, status_y + 1), text_value, fill=color, font=label_font)
            status_y += 39
        status_y += 8

    draw.text((rail_left + 18, status_y), "本图实际显示", fill="#0f172a", font=section_font)
    status_y += 38
    legend_items = list(legend.values())
    max_items = max(1, int((rail_bottom - status_y - 122) / 28))
    visible_legend_items = legend_items[:max_items]
    for item in visible_legend_items:
        y = status_y
        color = item["color"]
        try:
            rgb = ImageColor.getrgb(color)
        except (TypeError, ValueError):
            rgb = ImageColor.getrgb("#64748b")
        symbol = item.get("symbol")
        if symbol == "point":
            draw.ellipse((rail_left + 20, y + 4, rail_left + 34, y + 18), fill=(*rgb, 255), outline="white", width=1)
        elif symbol == "line":
            sample = [(rail_left + 18, y + 11), (rail_left + 46, y + 11)]
            if item.get("dash"):
                _draw_dashed_line(draw, sample, fill=(*rgb, 255), width=min(int(item.get("width", 4)), 6), dash=item["dash"])
            else:
                draw.line(sample, fill=(*rgb, 255), width=min(int(item.get("width", 4)), 6))
        elif symbol == "change":
            draw.rectangle((rail_left + 20, y + 2, rail_left + 40, y + 20), fill=(*rgb, 90), outline=(*rgb, 255), width=3)
        else:
            draw.rectangle((rail_left + 20, y + 2, rail_left + 40, y + 20), fill=(*rgb, 150), outline=(*rgb, 255), width=1)
        label = f"{item['label']} ({item['count']})"
        draw.text((rail_left + 54, y), label[:24], fill="#1e293b", font=small_font)
        status_y += 28
    if len(legend_items) > len(visible_legend_items):
        draw.text((rail_left + 20, status_y), f"另有 {len(legend_items) - len(visible_legend_items)} 类（见交互图）", fill="#64748b", font=small_font)

    north_x = rail_right - 54
    north_y = rail_bottom - 74
    draw.text((north_x - 7, north_y - 50), "N", fill="#0f172a", font=section_font)
    draw.line((north_x, north_y + 30, north_x, north_y - 12), fill="#0f172a", width=4)
    draw.polygon(((north_x, north_y - 27), (north_x - 11, north_y - 5), (north_x + 11, north_y - 5)), fill="#0f172a")

    scale_bar = _draw_scale_bar(draw, map_bounds, (min_x, min_y, max_x, max_y), small_font)
    extent_text = f"范围 {min_x:.5f}, {min_y:.5f} — {max_x:.5f}, {max_y:.5f}"
    draw.text((map_left, height_px - 82), extent_text, fill="#475569", font=small_font)
    draw.text((map_left, height_px - 48), "注：未生成成果仅作缺失提示，不以示意几何替代。", fill="#64748b", font=small_font)

    image.convert("RGB").save(output_path, format="PNG")
    artifact = {
        "status": "completed",
        "path": str(output_path),
        "layer_count": rendered_layers,
        "width_px": width_px,
        "height_px": height_px,
        "cjk_font_available": has_cjk_font,
        "extent": [min_x, min_y, max_x, max_y],
        "legend_items": [item["label"] for item in visible_legend_items],
        "missing_outputs": missing_outputs,
        "planned_road_count": road_count,
        "planned_zone_count": zone_count,
        "planned_point_count": sum(point_counts.values()),
        "labelled_point_count": labelled_points,
        "change_badge_count": change_badge_count,
        "road_styles": sorted(road_style_labels),
        "scale_bar": scale_bar,
        "north_arrow": True,
        "layout": {
            "map_bounds": list(map_bounds),
            "legend_bounds": list(rail_bounds),
            "legend_overlaps_map": False,
            "title_reserved_above_map": True,
        },
    }

    manifest_path = output_path.parent / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = [item for item in manifest.get("artifacts", []) if item.get("kind") != "planning_preview"]
            manifest["artifacts"].append({"kind": "planning_preview", **artifact})
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return artifact


def render_comparison_preview(
    layers: List[Dict[str, Any]],
    output_dir: str,
    village_name: str,
) -> Dict[str, Any]:
    """Render side-by-side current/planned panels with one shared extent."""
    from PIL import Image, ImageDraw
    import tempfile

    current_types = {"current_landuse", "current_road", "current_annotation", "boundary", "input_constraint"}
    planned_types = {
        "complete_planned_landuse",
        "planned_changes",
        "function_zone",
        "planning_zone",
        "custom_planning_zone",
        "custom_functional_zone",
        "restoration_zone",
        "protection_zone",
        "planned_project",
        "planned_project_point",
        "facility_point",
        "planned_facility",
        "planned_road",
        "development_axis",
        "boundary",
    }
    current_layers = [layer for layer in layers if _layer_type(layer) in current_types]
    planned_layers = [layer for layer in layers if _layer_type(layer) in planned_types]
    with tempfile.TemporaryDirectory(prefix="planning-preview-") as temp_dir:
        current_dir = Path(temp_dir) / "current"
        planned_dir = Path(temp_dir) / "planned"
        comparison_points = [
            point
            for layer in current_layers
            for feature in (layer.get("geojson") or {}).get("features", [])
            for point in _coordinates(feature.get("geometry") or {})
        ]
        if not comparison_points:
            comparison_points = [
                point
                for layer in planned_layers
                for feature in (layer.get("geojson") or {}).get("features", [])
                for point in _coordinates(feature.get("geometry") or {})
            ]
        xs = [point[0] for point in comparison_points]
        ys = [point[1] for point in comparison_points]
        shared_extent = (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None
        current_result = render_map_preview(current_layers, str(current_dir), f"{village_name}｜现状", extent=shared_extent)
        planned_result = render_map_preview(planned_layers, str(planned_dir), f"{village_name}｜规划", extent=shared_extent, planning_panel=True)
        if current_result.get("status") != "completed" or planned_result.get("status") != "completed":
            return {"status": "failed", "reason": "current_or_planned_panel_failed", "current": current_result, "planned": planned_result}
        current_image = Image.open(current_result["path"]).convert("RGBA")
        planned_image = Image.open(planned_result["path"]).convert("RGBA")
        panel_width = max(current_image.width, planned_image.width)
        panel_height = max(current_image.height, planned_image.height)
        canvas = Image.new("RGBA", (panel_width * 2, panel_height), "#eef2f7")
        canvas.alpha_composite(current_image, (0, 0))
        canvas.alpha_composite(planned_image, (panel_width, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.line((panel_width, 0, panel_width, panel_height), fill="#0f172a", width=5)
        output_path = Path(output_dir) / "planning_preview.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, format="PNG")

    planned_landuse = next((layer for layer in planned_layers if _layer_type(layer) == "complete_planned_landuse"), {})
    changed_count = sum(
        1
        for feature in (planned_landuse.get("geojson") or {}).get("features", [])
        if (feature.get("properties") or {}).get("change_status") not in {None, "preserved", "unchanged"}
    )
    return {
        "status": "completed",
        "path": str(output_path),
        "layer_count": len(current_layers) + len(planned_layers),
        "panel_count": 2,
        "planned_change_count": changed_count,
        "planned_point_count": planned_result["planned_point_count"],
        "planned_road_count": planned_result["planned_road_count"],
        "planned_zone_count": planned_result["planned_zone_count"],
        "missing_outputs": planned_result["missing_outputs"],
        "labelled_point_count": planned_result["labelled_point_count"],
        "change_badge_count": planned_result["change_badge_count"],
        "road_styles": planned_result["road_styles"],
        "scale_bar": planned_result["scale_bar"],
        "panels": {"current": current_result, "planned": planned_result},
    }


__all__ = ["render_map_preview", "render_comparison_preview"]
