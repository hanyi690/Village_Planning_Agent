"""三路对比渲染 — Python/matplotlib 生成 PNG 对比图。

输出 output/jintian_comparison/:
  - comparison.png   : 三路并排 planning_zone 对比图
  - comparison.json  : 三路对比数据
  - gen/ plan/ planned/ : 各路径 GeoJSON 图层
  - summary.json     : 输入输出摘要
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 中文字体 ──
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
# 强制重建字体缓存
import matplotlib.font_manager
matplotlib.font_manager._load_fontmanager(try_read_cache=False)

# 所有颜色从 zone_schema 导入——不在此处定义
from app.services.modules.gis.zone_schema import PLANNING_ZONE_COLORS, DEFAULT_ZONE_COLOR

outdir = Path("F:/project/Village_Planning_Agent/output/jintian_comparison")
outdir.mkdir(parents=True, exist_ok=True)

# ============================================================
# Step 1: 双路径生成
# ============================================================
print("Generating layers...")
from app.services.modules.gis.layout.data_loader import load_all, load_planned
from app.services.modules.gis.layout.intent_cache import resolve_gen_intent_cached, resolve_plan_intent_cached
from app.tools.gis.generate import (
    _generate_function_zones, _make_planning_zone_layer,
    _generate_facilities, _generate_axes,
)
from app.services.modules.gis.zone_schema import dlbm_to_planning_zone, PLANNING_ZONE_COLORS

gis_data = load_all()
planned_data = load_planned()

def _run_layers(intent):
    layers = []
    for fn, args in [
        (_generate_function_zones, (intent, gis_data)),
        (_make_planning_zone_layer, (None, gis_data)),
        (_generate_facilities, (intent, gis_data)),
        (_generate_axes, (intent, gis_data)),
    ]:
        try:
            lyr = fn(*args)
            if lyr:
                layers.append(lyr)
        except Exception as e:
            print(f"  Layer failed: {e}")
    return layers

# ── gen 路径: 人工规划 markdown → LLM → layers ──
gen_intent = resolve_gen_intent_cached("金田村委会", gis_data)
gen_layers = _run_layers(gen_intent)

# ── plan 路径: L3 reports → LLM → layers ──
plan_intent = resolve_plan_intent_cached("金田村委会", gis_data)
plan_layers = _run_layers(plan_intent)

# ============================================================
# Step 2: 保存 GeoJSON
# ============================================================
print("Saving GeoJSON...")
for tag, layers in [("gen", gen_layers), ("plan", plan_layers)]:
    tag_dir = outdir / tag
    tag_dir.mkdir(exist_ok=True)
    for lyr in layers:
        lt = lyr["layerType"]
        data = lyr.get("data", {})
        with open(tag_dir / f"{lt}.geojson", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)

# 保存 planned/ ground truth
planned_dir = outdir / "planned"
planned_dir.mkdir(exist_ok=True)
for key, geojson in planned_data.items():
    if geojson.get("features"):
        name = key.replace("_geojson", "")
        with open(planned_dir / f"{name}.geojson", "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, default=str)

for tag, intent in [("gen", gen_intent), ("plan", plan_intent)]:
    with open(outdir / f"{tag}_intent.json", "w", encoding="utf-8") as f:
        json.dump(intent, f, ensure_ascii=False, indent=2, default=str)

# ============================================================
# Step 3: 三路对比数据
# ============================================================
print("Computing three-way comparison...")
from app.services.modules.gis.layout.compare_layouts import compare

protection = {}
for key, name in [
    ("farmland_protection_geojson", "farmland"),
    ("ecological_protection_geojson", "ecological"),
    ("historical_protection_geojson", "historical"),
]:
    val = gis_data.get(key)
    if val and val.get("features"):
        protection[name] = val

comparison_data = {}
if gen_layers:
    comparison_data["gen_vs_planned"] = compare(gen_layers, planned_data, protection if protection else None).to_dict()
if plan_layers:
    comparison_data["plan_vs_planned"] = compare(plan_layers, planned_data, protection if protection else None).to_dict()
if gen_layers and plan_layers:
    pz = next((l.get("data") for l in plan_layers if l["layerType"] == "planning_zone"), None)
    if pz:
        comparison_data["gen_vs_plan"] = compare(gen_layers, {"landuse_planned_geojson": pz}, protection if protection else None).to_dict()

with open(outdir / "comparison.json", "w", encoding="utf-8") as f:
    json.dump(comparison_data, f, ensure_ascii=False, indent=2, default=str)

summary = {
    "gen": {
        "intent_zones": len(gen_intent.get("zones", [])),
        "layers": [(l["layerType"], len(l.get("data", {}).get("features", []))) for l in gen_layers],
        "source": gen_intent.get("metadata", {}).get("source", "unknown"),
    },
    "plan": {
        "intent_zones": len(plan_intent.get("zones", [])),
        "layers": [(l["layerType"], len(l.get("data", {}).get("features", []))) for l in plan_layers],
        "source": plan_intent.get("metadata", {}).get("source", "unknown"),
    },
}
with open(outdir / "summary.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

# ============================================================
# Step 4: matplotlib 三路并排 PNG 渲染
# ============================================================
print("Rendering comparison PNG...")

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

def _geojson_to_gdf(geojson):
    """Convert GeoJSON FeatureCollection to colored GeoDataFrame.

    Color priority: feature.properties.color → PLANNING_ZONE_COLORS[zone_type] → #CCCCCC.
    Each feature already has its color set by engine/generate layer (zone_schema).
    """
    feats = geojson.get("features", [])
    rows = []
    for f in feats:
        geom = shape(f["geometry"])
        props = f.get("properties", {})
        zone_type = props.get("zone_type") or props.get("assigned_zone") or ""
        # 优先用 feature 自带颜色（engine 已经用 zone_schema 设好）
        color = props.get("color") or PLANNING_ZONE_COLORS.get(
            zone_type, DEFAULT_ZONE_COLOR.get("fill", "#CCCCCC"))
        rows.append({"geometry": geom, "color": color, "zone_type": zone_type})
    if not rows:
        return None, None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf, rows

def _get_planning_zone_layer(layers):
    """Extract planning_zone data from layers list."""
    for l in layers or []:
        if l.get("layerType") == "planning_zone":
            return l.get("data", {})
    return {}

def _build_planned_planning_zone(planned_data):
    """Convert landuse_planned to planning_zone via DLBM mapping."""
    landuse = planned_data.get("landuse_planned_geojson", {})
    if not landuse.get("features"):
        return {}
    feats = []
    for f in landuse["features"]:
        props = dict(f.get("properties", {}))
        dlbm = str(props.get("DLBM", ""))
        zone = dlbm_to_planning_zone(dlbm)
        color = PLANNING_ZONE_COLORS.get(zone, DEFAULT_ZONE_COLOR.get("fill", "#CCCCCC"))
        feats.append({"type": "Feature", "geometry": f.get("geometry", {}),
                       "properties": {**props, "zone_type": zone, "color": color}})
    return {"type": "FeatureCollection", "features": feats}

# 构建 GeoDataFrame
gen_pz = _get_planning_zone_layer(gen_layers)
plan_pz = _get_planning_zone_layer(plan_layers)
planned_pz = _build_planned_planning_zone(planned_data)

gen_gdf, gen_rows = _geojson_to_gdf(gen_pz)
plan_gdf, plan_rows = _geojson_to_gdf(plan_pz)
planned_gdf, planned_rows = _geojson_to_gdf(planned_pz)

# ── 公共边界 ──
all_gdfs = [g for g in [gen_gdf, plan_gdf, planned_gdf] if g is not None]
if all_gdfs:
    all_union = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True), crs="EPSG:4326")
    bounds = all_union.total_bounds  # [minx, miny, maxx, maxy]
else:
    bounds = [0, 0, 1, 1]

# ── 绘图 ──
fig, axes = plt.subplots(1, 3, figsize=(24, 9))
fig.suptitle("Jin Tian Village — 三路规划对比", fontsize=18, fontweight="bold", y=0.98)

panel_info = [
    ("gen", "Gen: 人工规划文本 → AI 生成", gen_gdf, gen_rows,
     f"Intent zones: {len(gen_intent.get('zones', []))}"),
    ("plan", "Plan: L3 系统报告 → AI 生成", plan_gdf, plan_rows,
     f"Intent zones: {len(plan_intent.get('zones', []))}"),
    ("planned", "Planned: 人工绘制 GIS (Ground Truth)", planned_gdf, planned_rows, ""),
]

for i, (tag, title, gdf, rows, extra) in enumerate(panel_info):
    ax = axes[i]
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.set_aspect("equal")
    ax.axis("off")

    if gdf is not None and rows:
        # 按颜色分组绘制
        color_groups = {}
        for j, row in enumerate(rows):
            c = row["color"]
            if c not in color_groups:
                color_groups[c] = []
            color_groups[c].append(j)

        for color, indices in color_groups.items():
            subset = gdf.iloc[indices]
            subset.plot(ax=ax, color=color, edgecolor="#999999", linewidth=0.15)

        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])
    else:
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", fontsize=14, color="#999")

    # 额外的信息文本
    if extra:
        ax.text(0.02, 0.02, extra, transform=ax.transAxes, fontsize=10, color="#333",
                verticalalignment="bottom", bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

# ── 图例（从实际数据中收集所有出现的分区类型 + 规范色卡）──
all_zone_types = set()
for rows in [gen_rows, plan_rows, planned_rows]:
    if rows:
        for r in rows:
            zt = r.get("zone_type", "")
            if zt:
                all_zone_types.add(zt)
# 用规范色卡渲染图例
legend_patches = []
for zt in sorted(all_zone_types):
    c = PLANNING_ZONE_COLORS.get(zt, "#CCCCCC")
    legend_patches.append(mpatches.Patch(color=c, label=f"{zt} ({c})"))
fig.legend(handles=legend_patches, loc="lower center", ncol=4,
           fontsize=11, frameon=True, bbox_to_anchor=(0.5, -0.02))

# ── 差距分析 ──
# 收集各面板的实际分区分布
gen_zone_dist = Counter(r["zone_type"] for r in (gen_rows or []))
plan_zone_dist = Counter(r["zone_type"] for r in (plan_rows or []))
planned_zone_dist = Counter(r["zone_type"] for r in (planned_rows or []))

gap_lines = []
gap_lines.append("=== 差距分析: AI 生成 vs 人工绘制 ===")
gap_lines.append("")
gap_lines.append("Gen intent (人工规划文本→LLM) 产出:")
for z in gen_intent.get("zones", []):
    gap_lines.append(f"  {z.get('zone_id')}: {z.get('land_use')} ratio={z.get('area_ratio')} dlbm={z.get('dlbm')}")
gap_lines.append("")
gap_lines.append("Plan intent (L3报告→LLM) 产出:")
for z in plan_intent.get("zones", []):
    gap_lines.append(f"  {z.get('zone_id')}: {z.get('land_use')} ratio={z.get('area_ratio')} dlbm={z.get('dlbm')}")
gap_lines.append("")
gap_lines.append("Gen 分区分布 (660 parcels):")
for zt, cnt in gen_zone_dist.most_common():
    gap_lines.append(f"  {zt}: {cnt} parcels ({cnt/6.6:.1f}%)")
gap_lines.append("")
gap_lines.append("Plan 分区分布 (660 parcels):")
for zt, cnt in plan_zone_dist.most_common():
    gap_lines.append(f"  {zt}: {cnt} parcels ({cnt/6.6:.1f}%)")
gap_lines.append("")
gap_lines.append("Planned 分区分布 (ground truth):")
for zt, cnt in planned_zone_dist.most_common():
    gap_lines.append(f"  {zt}: {cnt} parcels ({cnt/6.6:.1f}%)")
gap_lines.append("")
gap_lines.append("--- 低分原因分析 ---")
gap_lines.append("1. 分类体系差异: AI 基于 DLBM 编码→6类规划分区; 人工 planned/ 的分区逻辑不一定遵循 DLBM 编码规则")
gap_lines.append(f"2. 面积比例: Gen intent 最大的 zone={gen_intent.get('zones',[{}])[0].get('land_use','?')}, Planned/ 的生态保护区面积最大")
gap_lines.append("3. 空间分布: AI 的 ZoneGenerator 按 DLBM 归类合并 parcel; 人工绘制可能按功能/地理边界划分")
gap_lines.append("4. compare 函数: tolerance_pct 默认 20%，zone_area_matches 负值=AI area < planned area")
gap_lines.append("")

with open(outdir / "gap_analysis.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(gap_lines))

# ── 底部对比指标 ──
metrics_text = ""
for key in ["gen_vs_planned", "plan_vs_planned", "gen_vs_plan"]:
    c = comparison_data.get(key, {})
    if "overall_score" in c:
        score = c.get("overall_score", 0)
        metrics_text += f"  {key}: score={score:.1f}%"
        if "zone_area_matches" in c:
            details = "; ".join(
                f"{m.get('zone_type', '?')}:{m.get('match_pct', 0):.0f}%"
                for m in c["zone_area_matches"][:4]
            )
            metrics_text += f"  [{details}]"
        metrics_text += "\n"

if metrics_text:
    fig.text(0.5, -0.08, f"对比指标:\n{metrics_text}", ha="center", fontsize=9,
             family="monospace", bbox=dict(boxstyle="round", facecolor="#f5f5f5", alpha=0.9))

plt.tight_layout()
png_path = outdir / "comparison.png"
fig.savefig(png_path, dpi=200, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved {png_path}")

# ── 单独的 comparison.json 摘要 ──
print(f"\n=== 对比摘要 ===")
for key in ["gen_vs_planned", "plan_vs_planned", "gen_vs_plan"]:
    c = comparison_data.get(key, {})
    score = c.get("overall_score", "N/A")
    zones = c.get("planning_zone_match", {})
    print(f"  {key}: score={score}")
    if zones:
        for zt, v in list(zones.items())[:4]:
            print(f"    {zt}: match={v}")

print(f"\nDone. Output: {outdir}")
print(f"  PNG: {outdir}/comparison.png")
print(f"  JSON: {outdir}/comparison.json")
