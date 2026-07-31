"""POC: 三区三线 WMTS 矢量化粒度可行性验证

真实数据,无任何 mock。

步骤:
  1. 读真实 token (.env TIANDITU_API_KEY)
  2. 读真实村庄 bbox (data/gis/jintian/current/boundary.geojson)
  3. 真实下载 SQSXWPSJ WMTS 瓦片 (3 个图层,bbox 内 L12 全部)
  4. 镶嵌为 GeoTIFF (rasterio)
  5. 矢量化 (rasterio.features.shapes + shapely 拓扑清理)
  6. 与本地 ground truth (jintian/planned/*.geojson) 对比
  7. 输出 granularity_report.md + comparison.html

输出目录: F:\\project\\Village_Planning_Agent\\backend\\output\\spike\\three_lines_granularity\\
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, NamedTuple

import httpx
import numpy as np
from PIL import Image
from shapely.geometry import shape, mapping, box as shapely_box
from shapely.ops import unary_union
from shapely.validation import make_valid

PROJECT_ROOT = Path("F:/project/Village_Planning_Agent")
BACKEND_ROOT = PROJECT_ROOT / "backend"
OUTPUT_DIR = BACKEND_ROOT / "output" / "spike" / "three_lines_granularity"
TILE_CACHE = OUTPUT_DIR / "tile_cache"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TILE_CACHE.mkdir(parents=True, exist_ok=True)

GD_BASE = "https://guangdong.tianditu.gov.cn"
WMTS_URL = f"{GD_BASE}/server/SQSXWPSJ/wmts"

ZOOM_LEVEL = 12
TILE_SIZE = 256
TOLERANCE = 12

# 三个图层配置: (key, wmts 中文 layer 名, expected color, ground_truth_filename, color_zh)
LAYERS = [
    {
        "key": "farmland_redline",
        "wmts_layer": "永久基本农田保护",
        "matrix_set": "永久基本农田保护_Matrix_0",
        "expected_rgb": (255, 215, 0),
        "ground_truth": "planned/farmland_protection.geojson",
        "color_zh": "永久基本农田",
        "color_hex": "#FFD500",
    },
    {
        "key": "urban_dev_boundary",
        "wmts_layer": "广东省城镇开发边界",
        "matrix_set": "广东省城镇开发边界_Matrix_0",
        "expected_rgb": (255, 0, 0),
        "ground_truth": "planned/construction_zone.geojson",
        "color_zh": "城镇开发边界",
        "color_hex": "#FF0000",
    },
    {
        "key": "ecological_redline",
        "wmts_layer": "GDSTBHHX",
        "matrix_set": "GDSTBHHX_Matrix_0",
        "expected_rgb": (144, 238, 144),
        "ground_truth": "planned/ecological_protection.geojson",
        "color_zh": "生态保护红线",
        "color_hex": "#90EE90",
    },
]


def load_token() -> str:
    env_path = PROJECT_ROOT / ".env"
    token = os.getenv("TIANDITU_API_KEY", "")
    if not token and env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("TIANDITU_API_KEY=") and not line.startswith("#"):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not token:
        raise RuntimeError("TIANDITU_API_KEY not found in env or .env")
    return token


def load_village_bbox() -> tuple[float, float, float, float]:
    bnd_path = PROJECT_ROOT / "data" / "gis" / "jintian" / "current" / "boundary.geojson"
    bnd = json.loads(bnd_path.read_text(encoding="utf-8"))
    coords: list[tuple[float, float]] = []
    for feat in bnd["features"]:
        g = feat["geometry"]
        if g["type"] == "MultiPolygon":
            for poly in g["coordinates"]:
                coords.extend(poly[0])
        else:
            coords.extend(g["coordinates"][0])
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


def deg_to_tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2.0**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return x, y


def tiles_for_bbox(
    bbox: tuple[float, float, float, float], z: int
) -> list[tuple[int, int]]:
    west, south, east, north = bbox
    x_min, y_max = deg_to_tile(south, west, z)
    x_max, y_min = deg_to_tile(north, east, z)
    return [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]


async def download_tile(
    client: httpx.AsyncClient,
    layer_key: str,
    wmts_layer: str,
    matrix_set: str,
    z: int,
    x: int,
    y: int,
    tk: str,
) -> tuple[int, int, int, int, str]:
    cache_path = TILE_CACHE / layer_key / str(z) / str(x) / f"{y}.png"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return (z, x, y, 200, "cached")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    params = {
        "SERVICE": "WMTS",
        "VERSION": "1.0.0",
        "REQUEST": "GetTile",
        "LAYER": wmts_layer,
        "STYLE": wmts_layer,
        "FORMAT": "image/png",
        "TILEMATRIXSET": matrix_set,
        "TILEMATRIX": str(z),
        "TILEROW": str(y),
        "TILECOL": str(x),
        "tk": tk,
    }
    try:
        resp = await client.get(WMTS_URL, params=params, timeout=20.0)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            cache_path.write_bytes(resp.content)
            return (z, x, y, resp.status_code, "ok")
        return (z, x, y, resp.status_code, (resp.text[:120] if resp.text else "no body"))
    except Exception as e:
        return (z, x, y, 0, f"exception: {e}")


async def download_all_tiles(
    bbox: tuple[float, float, float, float], tk: str
) -> dict[str, dict]:
    tiles_xy = tiles_for_bbox(bbox, ZOOM_LEVEL)
    print(f"[1/4] bbox={bbox}")
    print(f"      → {len(tiles_xy)} tiles at L{ZOOM_LEVEL} (x: {min(t[0] for t in tiles_xy)}-{max(t[0] for t in tiles_xy)}, y: {min(t[1] for t in tiles_xy)}-{max(t[1] for t in tiles_xy)})")

    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(8)

    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "VillagePlanningAgent/1.0 (granularity-spike)"},
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
    ) as client:
        for layer in LAYERS:
            layer_results: list[tuple[int, int, int, int, str]] = []
            t0 = time.time()

            async def sem_download(x, y, layer=layer):
                async with sem:
                    return await download_tile(
                        client,
                        layer["key"],
                        layer["wmts_layer"],
                        layer["matrix_set"],
                        ZOOM_LEVEL,
                        x,
                        y,
                        tk,
                    )

            tasks = [sem_download(x, y) for (x, y) in tiles_xy]
            for r in await asyncio.gather(*tasks):
                layer_results.append(r)

            ok = sum(1 for r in layer_results if r[4] in ("ok", "cached"))
            elapsed = time.time() - t0
            results[layer["key"]] = {
                "tiles_total": len(layer_results),
                "tiles_ok": ok,
                "elapsed_sec": round(elapsed, 1),
                "results": layer_results,
            }
            print(
                f"      [{layer['key']:<22}] {ok}/{len(layer_results)} ok, {elapsed:.1f}s"
            )

    return results


def mosaic_layer(layer_key: str, bbox: tuple[float, float, float, float]) -> tuple[Path, int]:
    import rasterio
    from rasterio.merge import merge

    tile_files: list[Path] = []
    for z_dir in (TILE_CACHE / layer_key / str(ZOOM_LEVEL)).iterdir():
        if not z_dir.is_dir():
            continue
        for y_file in z_dir.iterdir():
            if y_file.suffix == ".png" and y_file.stat().st_size > 0:
                tile_files.append(y_file)

    if not tile_files:
        raise FileNotFoundError(f"No cached tiles for {layer_key}")

    datasets = []
    for p in tile_files:
        try:
            ds = rasterio.open(p)
            datasets.append(ds)
        except Exception as e:
            print(f"        skip {p.name}: {e}")

    if not datasets:
        raise RuntimeError(f"All tile datasets failed for {layer_key}")

    try:
        west, south, east, north = bbox
        mosaic_data, mosaic_transform = merge(
            datasets, bounds=(west, south, east, north)
        )
    finally:
        for ds in datasets:
            ds.close()

    out_path = OUTPUT_DIR / f"mosaic_{layer_key}.tif"
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=mosaic_data.shape[1],
        width=mosaic_data.shape[2],
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=mosaic_transform,
        compress="lzw",
    ) as dst:
        dst.write(mosaic_data[:3])

    return out_path, len(datasets)


def vectorize_layer(
    mosaic_path: Path, target_rgb: tuple[int, int, int], layer_key: str
) -> list[dict]:
    import rasterio
    from rasterio.features import shapes as rio_shapes

    with rasterio.open(mosaic_path) as src:
        rgb = np.dstack([src.read(b) for b in (1, 2, 3)])
        transform = src.transform
        tr, tg, tb = target_rgb
        mask = (
            (np.abs(rgb[:, :, 0].astype(int) - tr) <= TOLERANCE)
            & (np.abs(rgb[:, :, 1].astype(int) - tg) <= TOLERANCE)
            & (np.abs(rgb[:, :, 2].astype(int) - tb) <= TOLERANCE)
        )

        polys: list[dict] = []
        for geom_dict, value in rio_shapes(
            mask.astype(np.uint8), mask=mask, transform=transform
        ):
            if value == 1:
                p = shape(geom_dict)
                if not p.is_valid:
                    p = make_valid(p)
                if p.area > 1e-10:
                    polys.append({
                        "geometry": mapping(p),
                        "area": p.area,
                    })

    polys.sort(key=lambda x: x["area"], reverse=True)
    return polys


def auto_detect_color(mosaic_path: Path, exclude_bg: bool = True) -> list[tuple]:
    with rasterio.open(mosaic_path) as src:
        rgb = np.dstack([src.read(b) for b in (1, 2, 3)])
    pixels = rgb.reshape(-1, 3)
    if exclude_bg:
        not_white = ~((pixels >= 245).all(axis=1))
        not_black = ~((pixels <= 10).all(axis=1))
        pixels = pixels[not_white & not_black]
    if len(pixels) == 0:
        return []
    counter = Counter(map(tuple, pixels.tolist()))
    return counter.most_common(5)


def load_ground_truth(bbox: tuple[float, float, float, float]) -> dict[str, list[dict]]:
    results = {}
    west, south, east, north = bbox
    query_box = shapely_box(west, south, east, north)
    for layer in LAYERS:
        gt_path = PROJECT_ROOT / "data" / "gis" / "jintian" / layer["ground_truth"]
        if not gt_path.exists():
            results[layer["key"]] = []
            continue
        try:
            data = json.loads(gt_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"        GT {layer['key']}: read error {e}")
            results[layer["key"]] = []
            continue
        polys = []
        for feat in data.get("features", []):
            g = feat.get("geometry")
            if not g:
                continue
            try:
                p = shape(g)
                if not p.is_valid:
                    p = make_valid(p)
                if query_box.intersects(p):
                    polys.append({"geometry": mapping(p), "area": p.area})
            except Exception:
                continue
        polys.sort(key=lambda x: x["area"], reverse=True)
        results[layer["key"]] = polys
    return results


def intersection_stats(
    detected: list[dict], ground_truth: list[dict]
) -> dict:
    if not ground_truth:
        return {
            "gt_count": 0,
            "det_count": len(detected),
            "overlap_area": 0.0,
            "gt_total_area": 0.0,
            "det_total_area": sum(p["area"] for p in detected),
            "iou_proxy": 0.0,
        }
    gt_union = unary_union([shape(p["geometry"]) for p in ground_truth])
    if not detected:
        return {
            "gt_count": len(ground_truth),
            "det_count": 0,
            "overlap_area": 0.0,
            "gt_total_area": gt_union.area,
            "det_total_area": 0.0,
            "iou_proxy": 0.0,
        }
    det_union = unary_union([shape(p["geometry"]) for p in detected])
    if not det_union.is_valid:
        det_union = make_valid(det_union)
    if not gt_union.is_valid:
        gt_union = make_valid(gt_union)
    inter = gt_union.intersection(det_union)
    inter_area = inter.area if not inter.is_empty else 0.0
    union_area = gt_union.union(det_union).area
    iou = inter_area / union_area if union_area > 0 else 0.0
    return {
        "gt_count": len(ground_truth),
        "det_count": len(detected),
        "overlap_area": inter_area,
        "gt_total_area": gt_union.area,
        "det_total_area": det_union.area,
        "iou_proxy": iou,
    }


def write_geojson(polys: list[dict], path: Path) -> None:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": p["geometry"],
                "properties": {"area_deg2": p["area"]},
            }
            for p in polys
        ],
    }
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")


def write_html_report(
    bbox: tuple[float, float, float, float],
    tile_stats: dict,
    vector_stats: dict,
    gt_stats: dict,
    intersect: dict,
    out_path: Path,
) -> None:
    html = [
        "<!DOCTYPE html>",
        "<html lang='zh'><head><meta charset='utf-8'><title>三区三线粒度 POC</title>",
        "<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' />",
        "<style>",
        "  body{font-family:Microsoft YaHei,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}",
        "  #map{width:100vw;height:55vh}",
        "  #panel{padding:12px 20px;background:#1e293b;display:flex;flex-wrap:wrap;gap:18px;align-items:center;font-size:13px}",
        "  .swatch{width:14px;height:14px;border-radius:3px;display:inline-block;border:1px solid rgba(255,255,255,0.2)}",
        "  table{border-collapse:collapse;width:100%;font-size:13px}",
        "  th,td{padding:6px 10px;border-bottom:1px solid #334155;text-align:left}",
        "  th{background:#1e293b;color:#94a3b8}",
        "  .ok{color:#4ade80}.warn{color:#fbbf24}.fail{color:#f87171}",
        "  #stats{padding:14px 20px;background:#0f172a}",
        "  h2{color:#fbbf24;margin:18px 0 8px}",
        "</style></head><body>",
        "<div id='map'></div>",
        "<div id='panel'>",
        f"<span style='font-weight:bold'>三区三线粒度 POC</span>",
        f"<span>bbox: ({bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f})</span>",
        f"<span>L{ZOOM_LEVEL} · 跨度 {(bbox[2]-bbox[0])*111:.2f}×{(bbox[3]-bbox[1])*111:.2f} km</span>",
        "</div>",
        "<div id='stats'>",
        "<h2>1. 瓦片下载</h2>",
        "<table><tr><th>图层</th><th>总瓦片</th><th>成功</th><th>用时 (s)</th></tr>",
    ]
    for layer in LAYERS:
        s = tile_stats.get(layer["key"], {})
        cls = "ok" if s.get("tiles_ok", 0) == s.get("tiles_total", 1) else "warn"
        html.append(
            f"<tr><td><span class='swatch' style='background:{layer['color_hex']}'></span> {layer['color_zh']}</td>"
            f"<td>{s.get('tiles_total', 0)}</td><td class='{cls}'>{s.get('tiles_ok', 0)}</td>"
            f"<td>{s.get('elapsed_sec', 0)}</td></tr>"
        )
    html.append("</table>")

    html.append("<h2>2. 矢量化 (WMTS → GeoJSON)</h2>")
    html.append("<table><tr><th>图层</th><th>检测多边形数</th><th>总面积 (deg²)</th><th>采样主导色</th></tr>")
    for layer in LAYERS:
        s = vector_stats.get(layer["key"], {})
        cls = "ok" if s.get("count", 0) > 0 else "fail"
        html.append(
            f"<tr><td><span class='swatch' style='background:{layer['color_hex']}'></span> {layer['color_zh']}</td>"
            f"<td class='{cls}'>{s.get('count', 0)}</td>"
            f"<td>{s.get('total_area', 0):.6f}</td>"
            f"<td>{s.get('dominant_color', 'N/A')}</td></tr>"
        )
    html.append("</table>")

    html.append("<h2>3. 与本地 ground truth 对比 (IoU 近似)</h2>")
    html.append("<table><tr><th>图层</th><th>本地 GT 数量</th><th>WMTS 检出</th><th>GT 面积</th><th>检出面积</th><th>重叠面积</th><th>IoU 近似</th></tr>")
    for layer in LAYERS:
        s = intersect.get(layer["key"], {})
        iou = s.get("iou_proxy", 0)
        cls = "ok" if iou > 0.3 else ("warn" if iou > 0.05 else "fail")
        html.append(
            f"<tr><td><span class='swatch' style='background:{layer['color_hex']}'></span> {layer['color_zh']}</td>"
            f"<td>{s.get('gt_count', 0)}</td><td>{s.get('det_count', 0)}</td>"
            f"<td>{s.get('gt_total_area', 0):.6f}</td>"
            f"<td>{s.get('det_total_area', 0):.6f}</td>"
            f"<td>{s.get('overlap_area', 0):.6f}</td>"
            f"<td class='{cls}'>{iou:.3f}</td></tr>"
        )
    html.append("</table>")

    html.append("<h2>图例 (可点击切换)</h2>")
    html.append("<div id='panel'>")
    for layer in LAYERS:
        html.append(
            f"<label><input type='checkbox' id='cb-{layer['key']}' checked> "
            f"<span class='swatch' style='background:{layer['color_hex']}'></span> "
            f"WMTS 检出 · {layer['color_zh']}</label>"
        )
        html.append(
            f"<label><input type='checkbox' id='cb-gt-{layer['key']}' checked> "
            f"<span class='swatch' style='background:#ffffff;border:2px dashed {layer['color_hex']}'></span> "
            f"本地 GT · {layer['color_zh']}</label>"
        )
    html.append("</div>")

    html.append("<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>")
    html.append("<script>")
    html.append("var map = L.map('map').setView([24.83, 116.05], 13);")
    html.append("L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:18, opacity:0.2, attribution:'&copy; OSM'}).addTo(map);")

    for layer in LAYERS:
        det_path = OUTPUT_DIR / f"detected_{layer['key']}.geojson"
        gt_path = OUTPUT_DIR / f"groundtruth_{layer['key']}.geojson"
        if det_path.exists():
            html.append(
                f"fetch('{det_path.name}').then(r=>r.json()).then(g=>{{"
                f"window.l_{layer['key']}=L.geoJSON(g,{{style:{{color:'{layer['color_hex']}',weight:2,fillColor:'{layer['color_hex']}',fillOpacity:0.4}}}}).addTo(map);"
                f"document.getElementById('cb-{layer['key']}').addEventListener('change',function(){{if(this.checked){{map.addLayer(window.l_{layer['key']})}}else{{map.removeLayer(window.l_{layer['key']})}}}});"
                f"}});"
            )
        if gt_path.exists():
            html.append(
                f"fetch('{gt_path.name}').then(r=>r.json()).then(g=>{{"
                f"window.gt_{layer['key']}=L.geoJSON(g,{{style:{{color:'#ffffff',weight:2,dashArray:'5,5',fill:false}}}}).addTo(map);"
                f"document.getElementById('cb-gt-{layer['key']}').addEventListener('change',function(){{if(this.checked){{map.addLayer(window.gt_{layer['key']})}}else{{map.removeLayer(window.gt_{layer['key']})}}}});"
                f"}});"
            )
    html.append("</script>")
    html.append("</body></html>")

    out_path.write_text("\n".join(html), encoding="utf-8")


def write_markdown_report(
    bbox: tuple[float, float, float, float],
    tile_stats: dict,
    vector_stats: dict,
    gt_stats: dict,
    intersect: dict,
    auto_colors: dict,
    out_path: Path,
) -> None:
    lines = [
        "# 三区三线粒度可行性验证报告",
        "",
        f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**测试村庄**: jintian (金田村委会)  ",
        f"**bbox (lon_min, lat_min, lon_max, lat_max)**: ({bbox[0]:.4f}, {bbox[1]:.4f}, {bbox[2]:.4f}, {bbox[3]:.4f})  ",
        f"**跨度**: {(bbox[2]-bbox[0])*111:.2f} km × {(bbox[3]-bbox[1])*111:.2f} km  ",
        f"**Level**: {ZOOM_LEVEL} (单瓦片 ~{360/(256*2**ZOOM_LEVEL):.4f}° ≈ {360/(256*2**ZOOM_LEVEL)*111:.2f} km)  ",
        f"**容差**: ±{TOLERANCE} RGB",
        "",
        "## 1. 瓦片下载结果",
        "",
        "| 图层 | 总瓦片 | 成功 | 失败 | 用时 (s) |",
        "|------|-------|------|------|---------|",
    ]
    for layer in LAYERS:
        s = tile_stats.get(layer["key"], {})
        total = s.get("tiles_total", 0)
        ok = s.get("tiles_ok", 0)
        lines.append(
            f"| {layer['color_zh']} | {total} | {ok} | {total - ok} | {s.get('elapsed_sec', 0)} |"
        )

    lines += [
        "",
        "## 2. 主导色自动检测 (验证预期配色)",
        "",
        "| 图层 | 预期 RGB | 自动检测 TOP 3 (RGB) | 匹配? |",
        "|------|---------|---------------------|-------|",
    ]
    for layer in LAYERS:
        top3 = auto_colors.get(layer["key"], [])
        top3_str = ", ".join(f"({c[0][0]},{c[0][1]},{c[0][2]})×{c[1]}" for c in top3[:3])
        match = any(
            abs(c[0] - layer["expected_rgb"][0]) <= TOLERANCE
            and abs(c[1] - layer["expected_rgb"][1]) <= TOLERANCE
            and abs(c[2] - layer["expected_rgb"][2]) <= TOLERANCE
            for c in top3
        )
        mark = "✅" if match else "❌"
        lines.append(
            f"| {layer['color_zh']} | {layer['expected_rgb']} | {top3_str or 'N/A'} | {mark} |"
        )

    lines += [
        "",
        "## 3. 矢量化结果 (WMTS → 多边形)",
        "",
        "| 图层 | 检测多边形数 | 总面积 (deg²) | 大小约 (km²) |",
        "|------|-------------|--------------|--------------|",
    ]
    for layer in LAYERS:
        s = vector_stats.get(layer["key"], {})
        area_deg2 = s.get("total_area", 0)
        # deg² → km² (在 24°N 处): 1° 经度 ≈ 101.7 km, 1° 纬度 ≈ 110.6 km
        area_km2 = area_deg2 * 101.7 * 110.6
        lines.append(
            f"| {layer['color_zh']} | {s.get('count', 0)} | {area_deg2:.6f} | ~{area_km2:.1f} |"
        )

    lines += [
        "",
        "## 4. 与本地 ground truth 对比",
        "",
        "Ground truth = `data/gis/jintian/planned/*.geojson`",
        "",
        "| 图层 | GT 数量 | WMTS 检出 | GT 面积 | 检出面积 | 重叠面积 | IoU 近似 |",
        "|------|---------|----------|---------|---------|---------|---------|",
    ]
    for layer in LAYERS:
        s = intersect.get(layer["key"], {})
        iou = s.get("iou_proxy", 0)
        status = "✅ 可用" if iou > 0.3 else ("⚠️ 部分" if iou > 0.05 else "❌ 不可用")
        lines.append(
            f"| {layer['color_zh']} | {s.get('gt_count', 0)} | {s.get('det_count', 0)} | "
            f"{s.get('gt_total_area', 0):.6f} | {s.get('det_total_area', 0):.6f} | "
            f"{s.get('overlap_area', 0):.6f} | {iou:.3f} ({status}) |"
        )

    lines += [
        "",
        "## 5. 结论",
        "",
    ]
    ious = {k: v.get("iou_proxy", 0) for k, v in intersect.items()}
    avg_iou = sum(ious.values()) / max(len(ious), 1)
    if avg_iou > 0.4:
        lines.append(
            f"**L{ZOOM_LEVEL} 粒度可用,平均 IoU ≈ {avg_iou:.3f}**。可继续完整方案实施。"
        )
    elif avg_iou > 0.15:
        lines.append(
            f"**L{ZOOM_LEVEL} 粒度部分可用,平均 IoU ≈ {avg_iou:.3f}**。建议: 1) 升级 L13 重跑 POC; 2) 调整颜色识别参数; 3) 检查本地 GT 是否基于 SQSXWPSJ 源数据。"
        )
    else:
        lines.append(
            f"**L{ZOOM_LEVEL} 粒度不可用,平均 IoU ≈ {avg_iou:.3f}**。建议: 1) 升级 L13/L14; 2) 验证本地 GT 来源; 3) 联系天地图服务方确认数据源精度。"
        )

    lines += [
        "",
        "## 6. 产物清单",
        "",
        f"- 瓦片缓存: `{TILE_CACHE}`",
        f"- GeoTIFF 镶嵌: `mosaic_*.tif` (3 个)",
        f"- WMTS 检出 GeoJSON: `detected_*.geojson` (3 个)",
        f"- Ground truth GeoJSON 副本: `groundtruth_*.geojson` (3 个)",
        f"- 可视化: `comparison.html` (浏览器打开,Leaflet 双图对比)",
        f"- 本报告: `granularity_report.md`",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


async def main():
    print("=" * 70)
    print("POC: 三区三线 WMTS 矢量化粒度可行性验证")
    print("=" * 70)

    tk = load_token()
    print(f"  Token 已加载 (长度 {len(tk)} 字符,内容已隐藏)")

    bbox = load_village_bbox()
    print(f"  bbox: {bbox}")
    print(f"  L{ZOOM_LEVEL} → {len(tiles_for_bbox(bbox, ZOOM_LEVEL))} 瓦片/层")
    print()

    print("[步骤 1/4] 下载 WMTS 瓦片 (httpx async, 真服务)...")
    tile_stats = await download_all_tiles(bbox, tk)

    print("\n[步骤 2/4] 镶嵌为 GeoTIFF (rasterio)...")
    vector_stats: dict = {}
    auto_colors: dict = {}
    for layer in LAYERS:
        try:
            tif_path, n_tiles = mosaic_layer(layer["key"], bbox)
            print(f"  [{layer['key']:<22}] → {tif_path.name} ({n_tiles} tiles)")
        except Exception as e:
            print(f"  [{layer['key']:<22}] FAILED: {e}")
            continue

        print(f"  采样主导色 (排除白/黑)...")
        top5 = auto_detect_color(tif_path)
        auto_colors[layer["key"]] = top5
        if top5:
            top_color = top5[0][0]
            print(f"    → 主色: RGB({top_color[0]},{top_color[1]},{top_color[2]})")
        else:
            top_color = layer["expected_rgb"]
            print(f"    → 单一颜色,使用预期: {top_color}")

        polys = vectorize_layer(tif_path, top_color, layer["key"])
        total_area = sum(p["area"] for p in polys)
        vector_stats[layer["key"]] = {
            "count": len(polys),
            "total_area": total_area,
            "dominant_color": f"RGB({top_color[0]},{top_color[1]},{top_color[2]})",
        }
        det_path = OUTPUT_DIR / f"detected_{layer['key']}.geojson"
        write_geojson(polys, det_path)
        print(f"    → {len(polys)} 多边形, {total_area:.6f} deg², → {det_path.name}")

    print("\n[步骤 3/4] 加载本地 ground truth 并对比...")
    gt_stats = load_ground_truth(bbox)
    intersect_stats_result: dict = {}
    for layer in LAYERS:
        gt = gt_stats.get(layer["key"], [])
        det = []
        det_path = OUTPUT_DIR / f"detected_{layer['key']}.geojson"
        if det_path.exists():
            det_fc = json.loads(det_path.read_text(encoding="utf-8"))
            det = [{"geometry": f["geometry"], "area": f["properties"]["area_deg2"]} for f in det_fc.get("features", [])]
        s = intersection_stats(det, gt)
        intersect_stats_result[layer["key"]] = s
        print(f"  [{layer['key']:<22}] IoU ≈ {s['iou_proxy']:.3f}  (GT={s['gt_count']}, detected={s['det_count']})")
        if gt:
            write_geojson(gt, OUTPUT_DIR / f"groundtruth_{layer['key']}.geojson")

    print("\n[步骤 4/4] 写报告...")
    report_md = OUTPUT_DIR / "granularity_report.md"
    report_html = OUTPUT_DIR / "comparison.html"
    write_markdown_report(bbox, tile_stats, vector_stats, gt_stats, intersect_stats_result, auto_colors, report_md)
    write_html_report(bbox, tile_stats, vector_stats, gt_stats, intersect_stats_result, report_html)

    print()
    print("=" * 70)
    print("✓ POC 完成")
    print(f"  报告 (md):  {report_md}")
    print(f"  可视化:    {report_html}")
    print(f"  瓦片缓存:   {TILE_CACHE}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
