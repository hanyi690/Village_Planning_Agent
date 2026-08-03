"""Self-contained interactive HTML renderer for session GIS results."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.tools.gis.static_render import _coordinates, _feature_color


Point = Tuple[float, float]


def _layer_points(layer: Dict[str, Any]) -> List[Point]:
    points: List[Point] = []
    for feature in (layer.get("geojson") or {}).get("features", []):
        points.extend(_coordinates(feature.get("geometry") or {}))
    return points


def _reference_extent(layers: Sequence[Dict[str, Any]]) -> Tuple[float, float, float, float]:
    boundary: List[Point] = []
    current_landuse: List[Point] = []
    all_points: List[Point] = []
    for layer in layers:
        points = _layer_points(layer)
        all_points.extend(points)
        layer_type = layer.get("layerType") or layer.get("layer_type") or ""
        layer_name = layer.get("layerName") or layer.get("layer_name") or ""
        if layer_type == "boundary":
            boundary.extend(points)
        if layer_name == "current_landuse":
            current_landuse.extend(points)
    points = boundary or current_landuse or all_points
    if not points:
        raise ValueError("no_renderable_geometry")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _projector(
    extent: Tuple[float, float, float, float],
    width: int,
    height: int,
):
    min_x, min_y, max_x, max_y = extent
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    padding = 24
    scale = min((width - padding * 2) / span_x, (height - padding * 2) / span_y)
    offset_x = padding + ((width - padding * 2) - span_x * scale) / 2
    offset_y = padding + ((height - padding * 2) - span_y * scale) / 2

    def project(point: Point) -> Point:
        return (
            offset_x + (point[0] - min_x) * scale,
            height - offset_y - (point[1] - min_y) * scale,
        )

    def visible(point: Point) -> bool:
        pad_x = span_x * 0.05
        pad_y = span_y * 0.05
        return (
            min_x - pad_x <= point[0] <= max_x + pad_x
            and min_y - pad_y <= point[1] <= max_y + pad_y
        )

    return project, visible


def _path(points: Iterable[Point], project, close: bool = False) -> str:
    projected = [project(point) for point in points]
    if not projected:
        return ""
    commands = [f"M {projected[0][0]:.2f} {projected[0][1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in projected[1:])
    if close:
        commands.append("Z")
    return " ".join(commands)


def _geometry_svg(
    geometry: Dict[str, Any],
    project,
    visible,
    color: str,
    layer_type: str,
    attrs: str,
) -> str:
    geometry_type = geometry.get("type", "")
    coordinates = geometry.get("coordinates") or []
    is_boundary = layer_type == "boundary"
    fill = "none" if is_boundary else color
    fill_opacity = "0" if is_boundary else "0.55"
    stroke_width = "2.6" if is_boundary else "0.8"

    if geometry_type == "Point" and len(coordinates) >= 2:
        point = (coordinates[0], coordinates[1])
        if not visible(point):
            return ""
        x, y = project(point)
        return (
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="{color}" '
            f'stroke="#ffffff" stroke-width="1" {attrs}/>'
        )
    if geometry_type == "MultiPoint":
        return "".join(
            _geometry_svg(
                {"type": "Point", "coordinates": point},
                project,
                visible,
                color,
                layer_type,
                attrs,
            )
            for point in coordinates
        )
    if geometry_type == "LineString":
        points = [(point[0], point[1]) for point in coordinates if len(point) >= 2]
        if not points or not any(visible(point) for point in points):
            return ""
        path = _path(points, project)
        width = "2.2" if "road" in layer_type else "1.8"
        return (
            f'<path d="{path}" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" {attrs}/>'
        )
    if geometry_type == "MultiLineString":
        return "".join(
            _geometry_svg(
                {"type": "LineString", "coordinates": line},
                project,
                visible,
                color,
                layer_type,
                attrs,
            )
            for line in coordinates
        )
    if geometry_type == "Polygon":
        paths = []
        for ring in coordinates:
            points = [(point[0], point[1]) for point in ring if len(point) >= 2]
            if points and any(visible(point) for point in points):
                paths.append(_path(points, project, close=True))
        if not paths:
            return ""
        return (
            f'<path d="{" ".join(paths)}" fill="{fill}" fill-opacity="{fill_opacity}" '
            f'stroke="{color}" stroke-width="{stroke_width}" fill-rule="evenodd" {attrs}/>'
        )
    if geometry_type == "MultiPolygon":
        return "".join(
            _geometry_svg(
                {"type": "Polygon", "coordinates": polygon},
                project,
                visible,
                color,
                layer_type,
                attrs,
            )
            for polygon in coordinates
        )
    return ""


def _display_properties(properties: Dict[str, Any]) -> str:
    selected: Dict[str, Any] = {}
    preferred = (
        "name",
        "注记",
        "分类",
        "zone_type",
        "planning_zone",
        "category_name_zh",
        "DLBM",
        "DLMC",
        "BSM",
        "area_ha",
        "area_sqm",
        "operation",
        "requires_human_confirmation",
        "location_status",
    )
    for key in preferred:
        if key in properties and properties[key] not in (None, "", [], {}):
            selected[key] = properties[key]
    if not selected:
        for key, value in list(properties.items())[:8]:
            if value not in (None, "", [], {}):
                selected[key] = value
    return json.dumps(selected, ensure_ascii=False, default=str)


def render_interactive_map(
    layers: List[Dict[str, Any]],
    output_dir: str,
    village_name: str,
    issues: List[Dict[str, Any]] | None = None,
    project_summary: Dict[str, Any] | None = None,
    narrative_sections: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """Write a dependency-free HTML map with toggles, zoom and feature inspection."""
    output_path = Path(output_dir) / "planning_map.html"
    extent = _reference_extent(layers)
    width, height = 1200, 820
    project, visible = _projector(extent, width, height)

    groups: List[str] = []
    controls: List[str] = []
    zone_legend: Dict[str, str] = {}
    rendered_layers = 0
    for index, layer in enumerate(layers):
        layer_type = layer.get("layerType") or layer.get("layer_type") or f"layer_{index + 1}"
        layer_name = layer.get("layerName") or layer.get("layer_name") or layer_type
        features = (layer.get("geojson") or {}).get("features", [])
        fallback = layer.get("color") or "#64748b"
        elements: List[str] = []
        for feature in features:
            properties = feature.get("properties") or {}
            color = _feature_color(properties, fallback)
            zone_name = (
                properties.get("zone_type")
                or properties.get("land_use")
                or properties.get("assigned_zone")
                or properties.get("category_name_zh")
            )
            if zone_name and layer_type in {
                "function_zone",
                "planning_zone",
                "custom_functional_zone",
                "space_control_zone",
            }:
                zone_legend[str(zone_name)] = color
            attrs = (
                'class="map-feature" tabindex="0" '
                f'data-layer="{html.escape(str(layer_name), quote=True)}" '
                f'data-properties="{html.escape(_display_properties(properties), quote=True)}"'
            )
            element = _geometry_svg(
                feature.get("geometry") or {},
                project,
                visible,
                color,
                str(layer_type),
                attrs,
            )
            if element:
                elements.append(element)
                if zone_name and layer_type in {
                    "function_zone",
                    "planning_zone",
                    "custom_functional_zone",
                    "space_control_zone",
                }:
                    points = list(_coordinates(feature.get("geometry") or {}))
                    visible_points = [point for point in points if visible(point)]
                    if visible_points:
                        center = (
                            sum(point[0] for point in visible_points) / len(visible_points),
                            sum(point[1] for point in visible_points) / len(visible_points),
                        )
                        x, y = project(center)
                        elements.append(
                            f'<text x="{x:.2f}" y="{y:.2f}" class="zone-label">'
                            f'{html.escape(str(zone_name))}</text>'
                        )
        group_id = f"layer-{index}"
        empty = not elements
        default_visible = bool(layer.get("default_visible", True))
        semantic_group = layer.get("semantic_group") or "规划分析"
        if not empty:
            rendered_layers += 1
        groups.append(
            f'<g id="{group_id}" data-layer-type="{html.escape(str(layer_type))}" '
            f'style="display:{"" if default_visible else "none"}">' 
            + "".join(elements)
            + "</g>"
        )
        status = "无可绘制要素" if empty else f"{len(elements)} 个图形"
        controls.append(
            f'<div class="layer-group">{html.escape(str(semantic_group))}</div>'
            '<label class="layer-row">'
            f'<input type="checkbox" {"checked" if default_visible else ""} data-target="{group_id}">' 
            f'<span class="swatch" style="background:{html.escape(fallback)}"></span>'
            f'<span class="layer-label">{html.escape(str(layer_name))}</span>'
            f'<span class="layer-count">{html.escape(status)}</span>'
            "</label>"
        )

    issue_items = "".join(
        f"<li><code>{html.escape(str(item.get('code', 'issue')))}</code> "
        f"{html.escape(str(item.get('message', '')))}</li>"
        for item in (issues or [])
    )
    issue_panel = (
        f'<section class="issues"><h3>可行性提示</h3><ul>{issue_items}</ul></section>'
        if issue_items
        else '<section class="issues ok"><h3>可行性提示</h3><p>未记录阻断项。</p></section>'
    )
    project_summary = project_summary or {}
    project_blocks: List[str] = []
    for category, label in (("zones", "规划分区"), ("facilities", "设施项目"), ("roads", "道路项目")):
        items = project_summary.get(category) or []
        rows = []
        for item in items:
            name = html.escape(str(item.get("name") or item.get("title") or "未命名项目"))
            status = html.escape(str(item.get("status") or "已生成"))
            detail = html.escape(str(item.get("detail") or ""))
            rows.append(
                f'<div class="project-row"><span class="project-name">{name}</span>'
                f'<span class="project-status">{status}</span>'
                f'<span class="project-detail">{detail}</span></div>'
            )
        if rows:
            project_blocks.append(f'<h3>{label}（{len(rows)}）</h3>{"".join(rows)}')
    project_panel = (
        '<section class="projects"><h2>规划项目</h2>' + "".join(project_blocks) + '</section>'
        if project_blocks
        else '<section class="projects"><h2>规划项目</h2><p>本次没有可展示的规划项目。</p></section>'
    )
    zone_legend_panel = (
        '<section class="zone-legend"><h2>分区名称</h2>'
        + "".join(
            f'<div class="zone-item"><span class="swatch" style="background:{html.escape(color)}"></span>'
            f'<span>{html.escape(name)}</span></div>'
            for name, color in sorted(zone_legend.items())
        )
        + '</section>'
        if zone_legend
        else ''
    )
    narrative_blocks = []
    for section in narrative_sections or []:
        title = html.escape(str(section.get("title") or "规划说明"))
        text = html.escape(str(section.get("text") or ""))
        if text:
            narrative_blocks.append(f'<div class="narrative"><h3>{title}</h3><p>{text}</p></div>')
    explanation_panel = (
        '<section class="explanation"><h2>规划说明</h2>'
        '<p>本图由现状报告的 L1/L2/L3 分析、同一 session 的 GIS 上传数据和规划知识图谱共同生成。</p>'
        + "".join(narrative_blocks)
        + '</section>'
    )
    extent_text = ", ".join(f"{value:.6f}" for value in extent)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(village_name)} 规划交互地图</title>
<style>
:root {{ color-scheme: light; font-family: "Microsoft YaHei", system-ui, sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #eef2f7; color: #172033; }}
header {{ height: 64px; padding: 14px 20px; background: #152238; color: white; display:flex; align-items:center; justify-content:space-between; }}
header h1 {{ margin:0; font-size:22px; font-weight:650; }}
header .meta {{ color:#cbd5e1; font-size:12px; }}
main {{ display:grid; grid-template-columns: 310px minmax(0,1fr) 320px; height:calc(100vh - 64px); gap:1px; background:#cbd5e1; }}
aside, section.map-shell {{ background:white; min-width:0; }}
aside {{ padding:16px; overflow:auto; }}
aside h2 {{ margin:0 0 12px; font-size:16px; }}
.layer-row {{ display:grid; grid-template-columns:18px 12px 1fr; gap:8px; align-items:center; padding:8px 0; border-bottom:1px solid #edf1f5; cursor:pointer; }}
.layer-group {{ margin-top:12px; color:#64748b; font-size:11px; font-weight:650; letter-spacing:.03em; }}
.swatch {{ width:10px; height:10px; border-radius:2px; }}
.layer-label {{ font-size:13px; overflow-wrap:anywhere; }}
.layer-count {{ grid-column:3; color:#7b8798; font-size:11px; }}
.map-shell {{ position:relative; overflow:hidden; }}
#map {{ width:100%; height:100%; background:#f8fafc; cursor:grab; touch-action:none; }}
#map.dragging {{ cursor:grabbing; }}
.toolbar {{ position:absolute; top:14px; right:14px; display:flex; gap:6px; }}
button {{ border:1px solid #cbd5e1; background:white; border-radius:6px; padding:7px 10px; cursor:pointer; box-shadow:0 2px 8px #0f172a14; }}
.map-feature {{ cursor:pointer; vector-effect:non-scaling-stroke; }}
.map-feature:hover, .map-feature:focus {{ stroke:#111827; stroke-width:3; outline:none; }}
.map-tooltip {{ position:absolute; z-index:5; pointer-events:none; display:none; max-width:300px; padding:10px 12px; border:1px solid #cbd5e1; border-radius:8px; background:rgba(255,255,255,.97); box-shadow:0 6px 22px #0f172a26; }}
.map-tooltip strong {{ display:block; margin-bottom:5px; font-size:12px; color:#1e293b; }}
.map-tooltip pre {{ margin:0; max-height:180px; overflow:hidden; white-space:pre-wrap; overflow-wrap:anywhere; font:11px/1.45 Consolas, monospace; color:#475569; }}
.issues {{ border:1px solid #f59e0b; background:#fffbeb; border-radius:8px; padding:12px; margin-bottom:14px; }}
.issues.ok {{ border-color:#22c55e; background:#f0fdf4; }}
.issues h3 {{ margin:0 0 8px; font-size:14px; }}
.issues ul {{ margin:0; padding-left:18px; font-size:12px; line-height:1.6; }}
.issues code {{ color:#9a3412; }}
.projects {{ margin-bottom:14px; }}
.projects h3 {{ margin:12px 0 4px; font-size:13px; color:#334155; }}
.project-row {{ display:grid; grid-template-columns:1fr auto; gap:4px 8px; padding:7px 0; border-bottom:1px solid #edf1f5; }}
.project-name {{ font-size:12px; overflow-wrap:anywhere; }}
.project-status {{ color:#b45309; font-size:11px; white-space:nowrap; }}
.project-detail {{ grid-column:1 / -1; color:#64748b; font-size:11px; line-height:1.45; }}
.zone-legend {{ margin-bottom:14px; }}
.zone-item {{ display:flex; gap:8px; align-items:center; padding:4px 0; font-size:12px; }}
.zone-label {{ font-size:13px; font-weight:650; fill:#1f2937; paint-order:stroke; stroke:#ffffff; stroke-width:4px; stroke-linejoin:round; text-anchor:middle; pointer-events:none; }}
.explanation {{ margin-bottom:14px; padding:12px; border-radius:8px; background:#f8fafc; border:1px solid #e2e8f0; }}
.explanation h2 {{ margin:0 0 8px; }}
.explanation h3 {{ margin:10px 0 3px; font-size:13px; }}
.explanation p {{ margin:0; color:#475569; font-size:12px; line-height:1.55; }}
#details {{ white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.55 Consolas, monospace; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; min-height:180px; }}
.hint {{ color:#64748b; font-size:12px; line-height:1.6; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(village_name)} 规划交互地图</h1>
  <div class="meta">范围 {extent_text} · 自包含 HTML · 图层 {len(layers)}</div>
</header>
<main>
  <aside><h2>图层</h2>{"".join(controls)}</aside>
  <section class="map-shell">
    <svg id="map" viewBox="0 0 {width} {height}" role="img" aria-label="规划交互地图">
      <rect width="{width}" height="{height}" fill="#f8fafc"/>
      <g id="viewport">{"".join(groups)}</g>
    </svg>
    <div id="map-tooltip" class="map-tooltip"><strong id="tooltip-layer"></strong><pre id="tooltip-content"></pre></div>
    <div class="toolbar"><button id="zoom-in">＋</button><button id="zoom-out">－</button><button id="reset">重置</button></div>
  </section>
  <aside>
    {explanation_panel}
    {zone_legend_panel}
    {project_panel}
    {issue_panel}
    <h2>要素属性</h2>
    <div id="details">点击地图要素查看属性。</div>
    <p class="hint">滚轮缩放；拖拽平移；左侧可切换图层。空道路或空设施图层会明确标注，不会伪造成果。</p>
  </aside>
</main>
<script>
const svg = document.getElementById("map");
const original = [0, 0, {width}, {height}];
let view = [...original], drag = null;
function applyView() {{ svg.setAttribute("viewBox", view.join(" ")); }}
function zoom(factor, cx=view[0]+view[2]/2, cy=view[1]+view[3]/2) {{
  const nw=view[2]*factor, nh=view[3]*factor;
  view=[cx-(cx-view[0])*factor, cy-(cy-view[1])*factor, nw, nh]; applyView();
}}
svg.addEventListener("wheel", event => {{
  event.preventDefault();
  const rect=svg.getBoundingClientRect();
  const cx=view[0]+(event.clientX-rect.left)/rect.width*view[2];
  const cy=view[1]+(event.clientY-rect.top)/rect.height*view[3];
  zoom(event.deltaY>0 ? 1.15 : 0.87, cx, cy);
}}, {{passive:false}});
svg.addEventListener("pointerdown", event => {{ drag=[event.clientX,event.clientY,...view]; svg.classList.add("dragging"); svg.setPointerCapture(event.pointerId); }});
svg.addEventListener("pointermove", event => {{
  if(!drag) return;
  const rect=svg.getBoundingClientRect();
  view[0]=drag[2]-(event.clientX-drag[0])/rect.width*drag[4];
  view[1]=drag[3]-(event.clientY-drag[1])/rect.height*drag[5];
  applyView();
}});
svg.addEventListener("pointerup", () => {{ drag=null; svg.classList.remove("dragging"); }});
document.getElementById("zoom-in").onclick=()=>zoom(0.8);
document.getElementById("zoom-out").onclick=()=>zoom(1.25);
document.getElementById("reset").onclick=()=>{{ view=[...original]; applyView(); }};
const tooltip = document.getElementById("map-tooltip");
const tooltipLayer = document.getElementById("tooltip-layer");
const tooltipContent = document.getElementById("tooltip-content");
function moveTooltip(event) {{
  const shell = document.querySelector(".map-shell").getBoundingClientRect();
  tooltip.style.left = Math.min(event.clientX - shell.left + 14, shell.width - 315) + "px";
  tooltip.style.top = Math.min(event.clientY - shell.top + 14, shell.height - 210) + "px";
}}
function showTooltip(event) {{
  tooltipLayer.textContent = event.currentTarget.dataset.layer || "地图要素";
  try {{ tooltipContent.textContent = JSON.stringify(JSON.parse(event.currentTarget.dataset.properties || "{{}}"), null, 2); }}
  catch {{ tooltipContent.textContent = event.currentTarget.dataset.properties || ""; }}
  tooltip.style.display = "block";
  moveTooltip(event);
}}
function hideTooltip() {{ tooltip.style.display = "none"; }}
document.querySelectorAll("[data-target]").forEach(input => {{
  input.addEventListener("change", () => {{
    document.getElementById(input.dataset.target).style.display=input.checked ? "" : "none";
  }});
}});
document.querySelectorAll(".map-feature").forEach(feature => {{
  const show = () => {{
    const props=JSON.parse(feature.dataset.properties || "{{}}");
    document.getElementById("details").textContent=feature.dataset.layer+"\\n\\n"+JSON.stringify(props,null,2);
  }};
  feature.addEventListener("click", show);
  feature.addEventListener("mouseenter", showTooltip);
  feature.addEventListener("mousemove", moveTooltip);
  feature.addEventListener("mouseleave", hideTooltip);
  feature.addEventListener("keydown", event => {{ if(event.key==="Enter") show(); }});
}});
</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    artifact = {
        "status": "completed",
        "path": str(output_path),
        "layer_count": rendered_layers,
        "extent": list(extent),
        "self_contained": True,
    }

    manifest_path = output_path.parent / "run_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"] = [
                item
                for item in manifest.get("artifacts", [])
                if item.get("kind") != "interactive_map"
            ]
            manifest["artifacts"].append({"kind": "interactive_map", **artifact})
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, ValueError):
            pass
    return artifact


__all__ = ["render_interactive_map"]
