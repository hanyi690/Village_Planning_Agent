"""Generate static PNG map from Jin Tian GIS pipeline output using matplotlib."""

import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Use Chinese font available on Windows
_chinese_fonts = [f for f in fm.fontManager.ttflist if "Microsoft YaHei" in f.name]
if _chinese_fonts:
    _CN_FONT = "Microsoft YaHei"
elif [f for f in fm.fontManager.ttflist if "SimHei" in f.name]:
    _CN_FONT = "SimHei"
elif [f for f in fm.fontManager.ttflist if "STXihei" in f.name]:
    _CN_FONT = "STXihei"
else:
    _CN_FONT = "sans-serif"

plt.rcParams["font.family"] = _CN_FONT
plt.rcParams["font.sans-serif"] = [_CN_FONT, "DejaVu Sans"]
plt.rcParams["font.monospace"] = [_CN_FONT, "DejaVu Sans Mono"]
plt.rcParams["axes.unicode_minus"] = False
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

os.makedirs("F:/project/Village_Planning_Agent/output/jintian_render", exist_ok=True)
outdir = "F:/project/Village_Planning_Agent/output/jintian_render"

# Load generated layers
layers = {}
for name in ["boundary", "function_zone", "planning_zone", "facility_point", "infrastructure"]:
    path = f"{outdir}/{name}.geojson"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            layers[name] = json.load(f)

def extract_coords(geojson, geom_filter=None):
    """Extract all coordinates from a FeatureCollection."""
    coords = []
    props_list = []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        gt = geom.get("type", "")
        if geom_filter and gt not in geom_filter:
            continue
        gc = geom.get("coordinates", [])
        if gt == "Point":
            coords.append(gc)
            props_list.append(feat.get("properties", {}))
        elif gt == "MultiPoint":
            coords.extend(gc)
        elif gt in ("Polygon", "MultiLineString"):
            for ring in gc:
                coords.extend(ring)
        elif gt == "MultiPolygon":
            for poly in gc:
                for ring in poly:
                    coords.extend(ring)
        elif gt == "LineString":
            coords.extend(gc)
    return coords, props_list


def plot_polygon_layer(ax, geojson, facecolor, edgecolor, alpha=0.6, linewidth=0.8):
    """Plot all polygon features with matplotlib."""
    from shapely.geometry import shape
    for feat in geojson.get("features", []):
        try:
            geom = shape(feat["geometry"])
            if geom.is_empty:
                continue
            if geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    x, y = poly.exterior.xy
                    ax.fill(x, y, facecolor=facecolor, edgecolor=edgecolor,
                           alpha=alpha, linewidth=linewidth)
                    for interior in poly.interiors:
                        xi, yi = interior.xy
                        ax.fill(xi, yi, facecolor="white", edgecolor="none", alpha=1.0)
            elif geom.geom_type == "Polygon":
                x, y = geom.exterior.xy
                ax.fill(x, y, facecolor=facecolor, edgecolor=edgecolor,
                       alpha=alpha, linewidth=linewidth)
                for interior in geom.interiors:
                    xi, yi = interior.xy
                    ax.fill(xi, yi, facecolor="white", edgecolor="none", alpha=1.0)
        except Exception:
            pass


def plot_line_layer(ax, geojson, color, linewidth=1.5, linestyle="-", alpha=0.8):
    """Plot all LineString features."""
    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") not in ("LineString", "MultiLineString"):
            continue
        coords = geom.get("coordinates", [])
        if geom["type"] == "LineString":
            coords = [coords]
        for line in coords:
            xs = [c[0] for c in line]
            ys = [c[1] for c in line]
            ax.plot(xs, ys, color=color, linewidth=linewidth, linestyle=linestyle,
                   alpha=alpha, solid_capstyle="round")


def plot_points(ax, geojson, default_color="#DC143C", size=40, marker="o"):
    """Plot all Point features."""
    xs, ys, colors = [], [], []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry", {})
        if geom.get("type") != "Point":
            continue
        c = geom["coordinates"]
        props = feat.get("properties", {})
        color = props.get("color", default_color)
        xs.append(c[0])
        ys.append(c[1])
        colors.append(color)
    if xs:
        ax.scatter(xs, ys, c=colors, s=size, marker=marker, edgecolors="white",
                  linewidths=0.6, zorder=10)


# === Build Figure ===
fig, (ax_map, ax_legend) = plt.subplots(1, 2, figsize=(20, 12),
    gridspec_kw={"width_ratios": [3, 1]})
fig.patch.set_facecolor("#1a1a2e")

# Map area
ax_map.set_facecolor("#16213e")
ax_map.set_aspect("equal")

# 1. Planning zone underlay (lighter)
if "planning_zone" in layers:
    plot_polygon_layer(ax_map, layers["planning_zone"],
                      facecolor="#ffffff", edgecolor="none", alpha=0.06)

# 2. Function zones — colored by type
zone_colors = {
    "生态绿地": "#68B167",
    "农业用地": "#F5F8DC",
    "居住用地": "#FF9F43",
    "水域": "#87CEEB",
    "交通用地": "#AAAAAA",
}
site_colors = {
    "耕地": "#EBF5C8",
    "园地": "#C8E6C9",
    "林地": "#68B167",
    "草地": "#A5D6A7",
    "住宅用地": "#FF9F43",
    "商业服务业用地": "#FFAB91",
    "工矿仓储用地": "#BCAAA4",
    "公共服务用地": "#CE93D8",
    "交通运输用地": "#AAAAAA",
    "水域及水利设施": "#87CEEB",
    "其他土地": "#EEEEEE",
}

# First collect feature geometries by land_use type
if "function_zone" in layers:
    for feat in layers["function_zone"].get("features", []):
        props = feat.get("properties", {})
        land_use = props.get("land_use", "")
        color = props.get("color", zone_colors.get(land_use, "#cccccc"))
        try:
            from shapely.geometry import shape
            geom = shape(feat["geometry"])
            if geom.is_empty:
                continue
            if geom.geom_type == "MultiPolygon":
                for poly in geom.geoms:
                    x, y = poly.exterior.xy
                    ax_map.fill(x, y, facecolor=color, edgecolor=props.get("stroke", "#666"),
                               alpha=0.65, linewidth=1.2)
            elif geom.geom_type == "Polygon":
                x, y = geom.exterior.xy
                ax_map.fill(x, y, facecolor=color, edgecolor=props.get("stroke", "#666"),
                           alpha=0.65, linewidth=1.2)
        except Exception:
            pass

# 3. Roads / infrastructure lines
if "infrastructure" in layers:
    plot_line_layer(ax_map, layers["infrastructure"], color="#FF4444", linewidth=2.5, linestyle="--")

# 4. Facility points
if "facility_point" in layers:
    # Separate hazard points from facilities
    fac_feats = []
    haz_feats = []
    for feat in layers["facility_point"].get("features", []):
        if feat.get("properties", {}).get("facility_type") == "地质灾害点":
            haz_feats.append(feat)
        else:
            fac_feats.append(feat)

    fac_gj = {"type": "FeatureCollection", "features": fac_feats}
    haz_gj = {"type": "FeatureCollection", "features": haz_feats}
    plot_points(ax_map, fac_gj, default_color="#DC143C", size=80, marker="o")
    plot_points(ax_map, haz_gj, default_color="#FF4400", size=25, marker="^")

# 5. Boundary outline
if "boundary" in layers:
    plot_line_layer(ax_map, layers["boundary"], color="#FFFFFF", linewidth=2.5, linestyle="--")

# Auto-fit view
all_xs, all_ys = [], []
for key in ["boundary", "function_zone"]:
    if key in layers:
        coords, _ = extract_coords(layers[key])
        for c in coords:
            all_xs.append(c[0])
            all_ys.append(c[1])

if all_xs:
    pad = 0.003
    ax_map.set_xlim(min(all_xs) - pad, max(all_xs) + pad)
    ax_map.set_ylim(min(all_ys) - pad, max(all_ys) + pad)

ax_map.set_xticks([])
ax_map.set_yticks([])
for spine in ax_map.spines.values():
    spine.set_visible(False)

# Title
# Calculate center for title
cx = np.mean(all_xs) if all_xs else 116.04
cy = max(all_ys) + pad * 1.5 if all_ys else 24.825
ax_map.text(cx, cy, "金田村 空间布局规划渲染结果",
           fontsize=18, fontweight="bold", color="white",
           ha="center", va="bottom",
           bbox=dict(boxstyle="round,pad=0.4", facecolor="#0f3460", edgecolor="#ffd380", linewidth=1.5))

# North arrow (右上角, TD/T 1022-2009)
from matplotlib.patches import FancyArrowPatch
xlim = ax_map.get_xlim()
ylim = ax_map.get_ylim()
n_x = xlim[1] - pad * 0.3
n_y = ylim[1] - pad * 0.5
ax_map.annotate("N", xy=(n_x, n_y + pad * 0.15), fontsize=14, fontweight="bold",
               color="white", ha="center", va="bottom")
ax_map.annotate("", xy=(n_x, n_y + pad * 0.12), xytext=(n_x, n_y - pad * 0.05),
               arrowprops=dict(arrowstyle="->", color="white", lw=2.0))

# Scale bar (图廓外正下方, TD/T 1022-2009)
# WGS-84: at 24°N, 1°lat ≈ 110.6km, 1°lon ≈ 101.1km
import math
_lat_center = np.mean(all_ys) if all_ys else 24.82
_m_per_deg_lat = 110600.0
_m_per_deg_lon = 110600.0 * math.cos(math.radians(_lat_center))
_map_width_m = (xlim[1] - xlim[0]) * _m_per_deg_lon
# Choose scale: 1km, 2km, or 5km
for _scale_m in [500, 1000, 2000, 5000]:
    _scale_deg = _scale_m / _m_per_deg_lon
    _bar_frac = _scale_deg / (xlim[1] - xlim[0])
    if 0.15 <= _bar_frac <= 0.35:
        break
_sb_y = ylim[0] + pad * 0.3
_sb_x_start = xlim[0] + pad * 0.5
_sb_x_end = _sb_x_start + _scale_deg
ax_map.plot([_sb_x_start, _sb_x_end], [_sb_y, _sb_y], color="white", linewidth=2.5)
ax_map.plot([_sb_x_start, _sb_x_start], [_sb_y - pad * 0.02, _sb_y + pad * 0.02],
           color="white", linewidth=1.5)
ax_map.plot([_sb_x_end, _sb_x_end], [_sb_y - pad * 0.02, _sb_y + pad * 0.02],
           color="white", linewidth=1.5)
_scale_label = f"{_scale_m}m" if _scale_m < 1000 else f"{_scale_m // 1000}km"
ax_map.text((_sb_x_start + _sb_x_end) / 2, _sb_y - pad * 0.06, _scale_label,
           fontsize=10, color="white", ha="center", va="top")

# Date stamp (右下角)
from datetime import date
ax_map.text(xlim[1] - pad * 0.1, ylim[0] + pad * 0.1,
           f"制图日期: {date.today().strftime('%Y-%m-%d')}",
           fontsize=9, color="#aaa", ha="right", va="bottom")

# Legend panel
ax_legend.set_facecolor("#16213e")
ax_legend.set_xlim(0, 10)
ax_legend.set_ylim(0, 10)
ax_legend.set_xticks([])
ax_legend.set_yticks([])
for spine in ax_legend.spines.values():
    spine.set_visible(False)

y = 9.5

# Title
ax_legend.text(5, y, "图层图例", fontsize=16, fontweight="bold", color="#ffd380",
              ha="center", va="top")
y -= 0.8

legend_items = [
    ("功能分区", [
        ("■  生态绿地 (2,230 ha)", "#68B167"),
        ("■  农业用地 (100 ha)", "#F5F8DC"),
        ("■  居住用地 (14 ha)", "#FF9F43"),
        ("■  水域 (36 ha)", "#87CEEB"),
    ]),
    ("一级三区", [
        ("■  生态空间", "#2E8B57"),
        ("■  农业空间", "#FFE4B5"),
        ("■  建设空间", "#FF6347"),
    ]),
    ("二级6类规划分区", [
        ("■  生态保护区", "#2E8B57"),
        ("■  生态控制区", "#90EE90"),
        ("■  农田保护区", "#FFE4B5"),
        ("■  一般农业区", "#98FB98"),
        ("■  村庄建设区", "#FF6347"),
        ("■  林业发展区", "#3CB371"),
    ]),
    ("设施 (46)", [
        ("●  规划设施 (6)", "#DC143C"),
        ("▲  地质灾害点 (40)", "#FF4400"),
    ]),
    ("发展结构", [
        ("---  发展轴", "#FF4444"),
        ("- -  村界", "#FFFFFF"),
    ]),
]

for section_title, items in legend_items:
    ax_legend.text(0.5, y, section_title, fontsize=13, fontweight="bold",
                  color="#aaa", va="top")
    y -= 0.5
    for label, color in items:
        ax_legend.text(1.5, y, label, fontsize=11, color="#ddd", va="top")
        if label.startswith("●"):
            ax_legend.scatter([0.7], [y - 0.1], c=color, s=60, marker="o",
                            edgecolors="white", linewidths=0.5, zorder=5)
        elif label.startswith("▲"):
            ax_legend.scatter([0.7], [y - 0.1], c=color, s=50, marker="^",
                            edgecolors="white", linewidths=0.5, zorder=5)
        elif label.startswith("---"):
            ax_legend.plot([0.2, 1.2], [y - 0.1, y - 0.1], color=color,
                          linewidth=2.5, linestyle="--", solid_capstyle="round")
        elif label.startswith("- -"):
            ax_legend.plot([0.2, 1.2], [y - 0.1, y - 0.1], color=color,
                          linewidth=2.5, linestyle="--", dashes=(8, 4), solid_capstyle="round")
        y -= 0.4
    y -= 0.3

# Stats
y -= 0.2
ax_legend.text(5, y, "统计", fontsize=13, fontweight="bold", color="#aaa", ha="center")
y -= 0.5
stats = [
    "现状地块: 660",
    "功能分区: 5",
    "设施点: 46 (含40地质灾害点)",
    "总面积: 2,353 ha",
    "坐标系: WGS-84 (EPSG:4326)",
    "生成引擎: ZoneGenerator",
    "          + FacilityPlacer",
    "          + AxisBuilder",
]
for s in stats:
    ax_legend.text(0.5, y, s, fontsize=10, color="#888", va="top")
    y -= 0.35

# Save
png_path = f"{outdir}/jintian_layout.png"
fig.savefig(png_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
plt.close(fig)
print(f"Saved: {png_path}")
print(f"Size: {os.path.getsize(png_path):,} bytes")
