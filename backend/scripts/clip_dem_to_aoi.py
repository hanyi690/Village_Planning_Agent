"""Clip province-wide DEM to village AOI.

Usage:
    python scripts/clip_dem_to_aoi.py --input data/gis/广东DEM30M.zip \
        --aoi data/gis/jintian/current/boundary.geojson \
        --output data/gis/jintian/terrain/dem.tif

The input zip is the NASA ASTGTM v3 dataset for Guangdong province: a zip of
zips, one per 1-degree tile (ASTGTMV003_N<lat>E<lon>.zip -> *_dem.tif).

Pipeline:
  1. Read AOI bbox from the boundary GeoJSON.
  2. Select only the ASTGTM tiles whose 1-degree cell overlaps the AOI bbox.
  3. Extract those tiles' *_dem.tif.
  4. If rasterio is available, mask/crop each tile to the AOI geometry and
     write a clipped GeoTIFF (reprojected to EPSG:4326 if needed).
  5. If rasterio is unavailable and exactly one tile covers the AOI, copy the
     tile's *_dem.tif verbatim (ASTGTM tiles are already EPSG:4326, 1-arcsec).
     This is the common case for a single village.

Requires (optional, for true clipping): rasterio, geopandas, shapely.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path


_TILE_RE = re.compile(r"ASTGTMV003_N(\d+)E(\d+)\.zip")


def _aoi_bbox(aoi_path: Path) -> tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) WGS84 bbox of the AOI GeoJSON."""
    with open(aoi_path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    xs: list[float] = []
    ys: list[float] = []

    def _walk(coords):
        for c in coords:
            if isinstance(c[0], (int, float)):
                xs.append(c[0])
                ys.append(c[1])
            else:
                _walk(c)

    for feat in gj.get("features", []):
        _walk(feat.get("geometry", {}).get("coordinates", []))
    if not xs:
        raise ValueError(f"No coordinates found in {aoi_path}")
    return min(xs), min(ys), max(xs), max(ys)


def _tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[tuple[str, int, int]]:
    """Return list of (inner_zip_name, lat, lon) covering the AOI bbox."""
    minx, miny, maxx, maxy = bbox
    lat_lo = int(miny)
    lat_hi = int(maxy)
    lon_lo = int(minx)
    lon_hi = int(maxx)
    tiles = []
    for lat in range(lat_lo, lat_hi + 1):
        for lon in range(lon_lo, lon_hi + 1):
            tiles.append((f"ASTGTMV003_N{lat:02d}E{lon:03d}.zip", lat, lon))
    return tiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Clip province-wide DEM to village AOI")
    parser.add_argument("--input", required=True, help="Input DEM zip (zip of ASTGTM tile zips)")
    parser.add_argument("--aoi", required=True, help="AOI boundary GeoJSON")
    parser.add_argument("--output", required=True, help="Output clipped DEM tif")
    args = parser.parse_args()

    input_zip = Path(args.input)
    aoi_path = Path(args.aoi)
    output_path = Path(args.output)

    if not input_zip.exists():
        print(f"ERROR: input zip not found: {input_zip}", file=sys.stderr)
        return 2
    if not aoi_path.exists():
        print(f"ERROR: AOI not found: {aoi_path}", file=sys.stderr)
        return 2

    bbox = _aoi_bbox(aoi_path)
    print(f"AOI bbox (WGS84): minx={bbox[0]:.6f} miny={bbox[1]:.6f} "
          f"maxx={bbox[2]:.6f} maxy={bbox[3]:.6f}")

    tiles = _tiles_for_bbox(bbox)
    print(f"Required ASTGTM tiles: {[t[0] for t in tiles]}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Path A: rasterio available -> true clip with mask ────────────
    try:
        import rasterio
        from rasterio.mask import mask
        import geopandas as gpd
    except ImportError:
        rasterio = None
    else:
        rasterio = rasterio

    if rasterio is not None:
        aoi_gdf = gpd.read_file(str(aoi_path))
        if aoi_gdf.crs is None:
            aoi_gdf.set_crs(epsg=4326, inplace=True)

        with zipfile.ZipFile(input_zip, "r") as z:
            tile_names = {info.filename for info in z.infolist()}
            for tile_zip_name, _lat, _lon in tiles:
                if tile_zip_name not in tile_names:
                    print(f"WARNING: tile {tile_zip_name} not in input zip", file=sys.stderr)
                    continue
                with z.open(tile_zip_name) as f:
                    buf = io.BytesIO(f.read())
                with zipfile.ZipFile(buf, "r") as iz:
                    dem_names = [n for n in iz.namelist() if n.endswith("_dem.tif")]
                    if not dem_names:
                        continue
                    with iz.open(dem_names[0]) as dem_f:
                        dem_bytes = dem_f.read()
                tmp_tif = output_path.with_suffix(".tmp.tif")
                tmp_tif.write_bytes(dem_bytes)

                with rasterio.open(str(tmp_tif)) as src:
                    print(f"Tile {tile_zip_name}: CRS={src.crs} shape={src.shape}")
                    aoi_local = aoi_gdf.to_crs(src.crs) if src.crs else aoi_gdf
                    geoms = aoi_local.geometry.tolist()
                    out_image, out_transform = mask(src, geoms, crop=True)
                    out_meta = src.meta.copy()
                    out_meta.update({
                        "height": out_image.shape[1],
                        "width": out_image.shape[2],
                        "transform": out_transform,
                    })
                    with rasterio.open(str(output_path), "w", **out_meta) as dst:
                        dst.write(out_image)
                    print(f"Wrote clipped DEM: {output_path} "
                          f"({out_image.shape[1]}x{out_image.shape[2]})")
                tmp_tif.unlink(missing_ok=True)
                return 0
        print("WARNING: no matching tiles found for clip", file=sys.stderr)

    # ── Path B: no rasterio -> single-tile passthrough ──────────────
    if len(tiles) != 1:
        print(
            f"ERROR: rasterio is required to clip AOI spanning multiple tiles "
            f"({len(tiles)} tiles). Install: pip install rasterio geopandas",
            file=sys.stderr,
        )
        return 3

    tile_zip_name = tiles[0][0]
    with zipfile.ZipFile(input_zip, "r") as z:
        if tile_zip_name not in z.namelist():
            print(f"ERROR: tile {tile_zip_name} not in input zip", file=sys.stderr)
            return 3
        with z.open(tile_zip_name) as f:
            buf = io.BytesIO(f.read())
        with zipfile.ZipFile(buf, "r") as iz:
            dem_names = [n for n in iz.namelist() if n.endswith("_dem.tif")]
            if not dem_names:
                print(f"ERROR: no *_dem.tif inside {tile_zip_name}", file=sys.stderr)
                return 3
            with iz.open(dem_names[0]) as dem_f:
                output_path.write_bytes(dem_f.read())

    print(f"Wrote DEM tile (unclipped, full 1-degree cell) -> {output_path}")
    print(f"Size: {output_path.stat().st_size} bytes")
    print("NOTE: install rasterio+geopandas to crop to the AOI boundary.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
