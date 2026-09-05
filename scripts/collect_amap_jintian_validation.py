"""Collect auditable AMap evidence for the Jintian validation experiment.

This script deliberately does not modify the production data, KG, bundle, or
GROUND layers.  It creates two independent evidence stores:

1. ``01_admin_scope`` uses only the known administrative scope and the
   geocoded administrative anchor.
2. ``02_l1_place_names`` uses place-like names from the latest L1 snapshot.

Every request is cached by endpoint and sanitized parameters.  The cache is
purpose-specific, so a later production integration cannot accidentally treat
an L1-name probe as an administrative-scope observation.  Raw JSON responses
are retained in full; normalized records are only a convenience index.

Usage::

    python scripts/collect_amap_jintian_validation.py
    python scripts/collect_amap_jintian_validation.py --stage admin
    python scripts/collect_amap_jintian_validation.py --stage l1
    python scripts/collect_amap_jintian_validation.py --stage all --refresh

The default is ``all`` with the expanded administrative plan and cache reuse
enabled.  ``--refresh`` is explicit authorization to repeat successful calls
whose sanitized request is already cached; retryable failures are retried by
the collector without requiring a full refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests
from dotenv import load_dotenv
from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform as shapely_transform


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "data" / "cache" / "map_observations" / "amap"
AMAP_V3 = "https://restapi.amap.com/v3"
AMAP_V5 = "https://restapi.amap.com/v5"
CITY_ADCODE = "441400"
COUNTY_ADCODE = "441426"
PAGE_SIZE = 25
MAX_PAGES = 8
MAX_RECORDS_PER_QUERY = PAGE_SIZE * MAX_PAGES
MAX_RETRIES = 4
DEFAULT_MIN_INTERVAL = 0.35
TRANSIENT_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
TRANSIENT_INFO_CODES = {"10001", "10002", "10003", "10004"}

sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from app.spatial.model.coord_transform import gcj02_to_wgs84, wgs84_to_gcj02
from app.data.boundary_scope import load_boundary_scope_artifact
from app.data.ingestion.providers.amap.constants import POI_TYPES_PUBLIC_SERVICE
from app.data.catalog.provider_run_lease import ProviderObservationWriter, ProviderRunLeaseStore

ADMIN_SCOPE = {
    "province": "广东省",
    "city": "梅州市",
    "county": "平远县",
    "township": "泗水镇",
    "village": "金田村",
    "village_committee_code": "441426108004",
    "city_adcode": CITY_ADCODE,
    "county_adcode": COUNTY_ADCODE,
}

PLACE_TYPES = {
    "all_top_level": "010000|020000|030000|040000|050000|060000|070000|080000|090000|100000|110000|120000|130000|140000|150000|160000|170000|180000|190000|200000",
    "public_and_transport": "130000|140000|150000|160000",
    "natural_and_water": "070000|120000|190000|200000",
    "services_and_recreation": "050000|060000|080000|090000|110000",
}

PLACE_TYPE_SHARDS = {
    "type_010000": "010000",
    "type_020000": "020000",
    "type_030000": "030000",
    "type_040000": "040000",
    "type_050000": "050000",
    "type_060000": "060000",
    "type_070000": "070000",
    "type_080000": "080000",
    "type_090000": "090000",
    "type_100000": "100000",
    "type_110000": "110000",
    "type_120000": "120000",
    "type_130000": "130000",
    "type_140000": "140000",
    "type_150000": "150000",
    "type_160000": "160000",
    "type_170000": "170000",
    "type_180000": "180000",
    "type_190000": "190000",
    "type_200000": "200000",
}
for _typecode in sorted(set(POI_TYPES_PUBLIC_SERVICE.values())):
    PLACE_TYPE_SHARDS[f"fine_type_{_typecode}"] = _typecode

NON_PLACE_NAMES = {
    "农业": "产业概念，不是地点名称",
    "林地": "土地覆盖类别，不是地点名称",
    "杉木家具制造业": "产业概念，不是地点名称",
    "阁楼": "建筑部位，不是地点名称",
    "12个自然村": "数量短语；其关联的 12 个自然村会单独检索",
}

PLACE_ROLES = {
    "natural_village",
    "parent_area",
    "service_area",
    "road",
    "primary_road",
    "east_west_road",
    "internal_road",
    "water_body",
    "facility",
    "facility_location",
    "facility_cluster",
    "infrastructure",
    "building_concentration_area",
    "new_building_location",
    "cluster_location",
    "unknown",
}

SCOPE_BUCKETS = (
    "project_local",
    "township_local",
    "county_local",
    "meizhou_other",
    "outside_meizhou",
    "unknown_scope",
)

DETAIL_FIELDS = "children,business,indoor,navi,photos"
MEIZHOU_CITY_CODES = {"0753", CITY_ADCODE}
LOCAL_TOWN_CODE_PREFIXES = {"441426108"}

_WGS84_TO_METERS = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
_METERS_TO_WGS84 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)


def compact(value: Any, limit: int = 1200) -> Any:
    """Keep manifests readable without shortening the raw response store."""

    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, list):
        return [compact(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: compact(item, limit) for key, item in value.items()}
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def path_ref(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def resolve_path_ref(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _polygon_parts(geometry: Any) -> list[Any]:
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return [geometry]


def _polygon_string_gcj02(geometry: Any) -> str:
    rings: list[str] = []
    for part in _polygon_parts(geometry):
        coords = list(part.exterior.coords)
        gcj_coords = [wgs84_to_gcj02(float(lon), float(lat)) for lon, lat in coords]
        rings.append("|".join(f"{lon:.6f},{lat:.6f}" for lon, lat in gcj_coords))
    return ";".join(rings)


def _boundary_samples(geometry: Any, spacing_degrees: float = 0.005) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    samples: list[tuple[float, float]] = []
    lon = min_lon
    while lon <= max_lon + 1e-9:
        lat = min_lat
        while lat <= max_lat + 1e-9:
            point = Point(lon, lat)
            if geometry.covers(point):
                samples.append((lon, lat))
            lat += spacing_degrees
        lon += spacing_degrees
    return samples


def split_saturated_scope(geometry: Any, cell_size_m: float = 2500.0) -> list[Any]:
    """Create deterministic WGS84 cells for queries that hit the 200-row cap."""

    metric = shapely_transform(_WGS84_TO_METERS.transform, geometry)
    min_x, min_y, max_x, max_y = metric.bounds
    cells: list[Any] = []
    x = min_x
    while x < max_x or not cells:
        y = min_y
        while y < max_y or not cells:
            cell = box(x, y, min(x + cell_size_m, max_x), min(y + cell_size_m, max_y))
            if cell.intersects(metric):
                cells.append(shapely_transform(_METERS_TO_WGS84.transform, cell.intersection(metric)))
            y += cell_size_m
            if y >= max_y:
                break
        x += cell_size_m
        if x >= max_x:
            break
    return cells


def simplify_wgs84_meters(geometry: Any, tolerance_m: float) -> Any:
    metric = shapely_transform(_WGS84_TO_METERS.transform, geometry)
    simplified = metric.simplify(tolerance_m, preserve_topology=True)
    return shapely_transform(_METERS_TO_WGS84.transform, simplified)


def polygon_request_geometries(geometry: Any) -> list[Any]:
    """Use short spatial request polygons; exact scope stays local WGS84."""

    return [simplify_wgs84_meters(cell, 10.0) for cell in split_saturated_scope(geometry)]


def around_params(location: str, radius: int, types: str) -> dict[str, str | int]:
    return {
        "location": location,
        "radius": radius,
        "types": types,
        "sortrule": "distance",
        "region": CITY_ADCODE,
        "city_limit": "true",
    }


def spatial_probe_centers(geometry: Any, cell_size_m: float = 2500.0) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for cell in split_saturated_scope(geometry, cell_size_m):
        point = cell.representative_point()
        centers.append((float(point.x), float(point.y)))
    return list(dict.fromkeys(centers))


def load_admin_boundary_context(
    expansion_m: float = 500.0,
    *,
    boundary_scope: Any | None = None,
) -> dict[str, Any]:
    """Load a normalized boundary scope and derive provider request views.

    Production collection must pass a ``BoundaryScopeArtifact`` compiled from
    an admitted DATA boundary. Provider code never reads a fixed local file.
    """

    if boundary_scope is not None:
        geometry_payload = getattr(boundary_scope, "geometry", None)
        if not isinstance(geometry_payload, dict):
            geometry_payload = dict(boundary_scope.get("geometry") or {})
        geometry = shape(geometry_payload)
        source_path = f"artifact://{getattr(boundary_scope, 'scope_ref', '')}"
        boundary_ref = str(getattr(boundary_scope, "scope_ref", "") or "")
        boundary_digest = str(getattr(boundary_scope, "boundary_digest", "") or "")
        query_geometry_digest = str(
            getattr(boundary_scope, "query_geometry_digest", "") or ""
        )
        source_crs = str(getattr(boundary_scope, "normalized_crs", "EPSG:4326"))
    else:
        raise ValueError("a BoundaryScopeArtifact is required for provider collection")
    simplified = geometry.simplify(0.0002, preserve_topology=True)
    metric_geometry = shapely_transform(_WGS84_TO_METERS.transform, simplified)
    expanded_metric = metric_geometry.buffer(expansion_m)
    expanded_wgs84 = shapely_transform(_METERS_TO_WGS84.transform, expanded_metric)
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    boundary_vertices_wgs84: list[tuple[float, float]] = []
    for part in _polygon_parts(simplified):
        boundary_vertices_wgs84.extend((float(lon), float(lat)) for lon, lat in list(part.exterior.coords)[:-1])
    sample_wgs84 = boundary_vertices_wgs84 + _boundary_samples(simplified)
    sample_wgs84 = list(dict.fromkeys(sample_wgs84))
    context = {
        "source_path": source_path,
        "boundary_ref": boundary_ref,
        "boundary_digest": boundary_digest,
        "query_geometry_digest": query_geometry_digest,
        "geometry_type": geometry.geom_type,
        "source_crs": source_crs,
        "request_crs": "GCJ-02",
        "check_crs": "WGS84",
        "bbox_wgs84": [min_lon, min_lat, max_lon, max_lat],
        "simplification_tolerance_degrees": 0.0002,
        "expansion_m": expansion_m,
        "polygon_strings_gcj02": [_polygon_string_gcj02(part) for part in _polygon_parts(simplified)],
        "expanded_polygon_strings_gcj02": [_polygon_string_gcj02(expanded_wgs84)],
        "sample_points_wgs84": [[lon, lat] for lon, lat in sample_wgs84],
        "sample_points_gcj02": [[wgs84_to_gcj02(lon, lat)[0], wgs84_to_gcj02(lon, lat)[1]] for lon, lat in sample_wgs84],
        "boundary_geometry_wgs84": simplified,
        "expanded_geometry_wgs84": expanded_wgs84,
    }
    if boundary_scope is not None:
        from app.contracts.data.provider_acquisition_contracts import build_provider_acquisition_plan

        context["provider_acquisition_plans"] = {
            provider: build_provider_acquisition_plan(
                boundary_scope,
                provider=provider,
                stage="01_admin_scope",
            ).model_dump(mode="json")
            for provider in ("amap", "tencent", "tianditu")
        }
    else:
        context["provider_acquisition_plans"] = {}
    return context


def response_ok(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    status = str(data.get("status", ""))
    infocode = str(data.get("infocode", "10000"))
    return status == "1" and infocode in {"", "10000"}


def classify_status(
    *,
    attempted: bool,
    capability_available: bool,
    payload: Any,
    http_status: int | None = None,
    error: str | None = None,
) -> str:
    """Return an auditable state without conflating empty, missing, or failed."""

    if not attempted:
        return "missing_capability" if not capability_available else "not_attempted"
    if not response_ok(payload) or error or http_status not in {None, 200}:
        return "failed"
    return "success_nonempty" if response_records(payload) else "success_empty"


def max_pages_for_page_size(page_size: int = PAGE_SIZE) -> int:
    """AMap documents a 200-record ceiling for one unchanged query."""

    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return max(1, MAX_RECORDS_PER_QUERY // page_size)


def _is_retryable(http_status: int | None, payload: Any) -> bool:
    if http_status is None or http_status in TRANSIENT_HTTP_STATUS:
        return True
    if isinstance(payload, dict) and str(payload.get("infocode", "")) in TRANSIENT_INFO_CODES:
        return True
    return False


def _is_capability_unavailable(payload: Any) -> bool:
    """Detect a provider capability rejection that will not change per query."""

    return (
        isinstance(payload, dict)
        and str(payload.get("infocode", "")) in {"10012"}
    )


def records_in(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    for key in ("pois", "tips", "geocodes", "districts", "roads", "roadinters"):
        value = data.get(key)
        if isinstance(value, list):
            return len(value)
    route = data.get("route")
    if isinstance(route, dict):
        paths = route.get("paths")
        if isinstance(paths, list):
            return len(paths)
    return 0


def point_from_location(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str) or "," not in value:
        return None
    try:
        lon, lat = (float(part) for part in value.split(",", 1))
    except ValueError:
        return None
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return lon, lat
    return None


def locations_from(data: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not isinstance(data, dict):
        return points
    for key in ("pois", "tips", "geocodes"):
        for item in data.get(key) or []:
            if isinstance(item, dict):
                point = point_from_location(item.get("location"))
                if point:
                    points.append(point)
    return list(dict.fromkeys(points))


def nearest_distinct_points(points: Iterable[tuple[float, float]], limit: int = 3) -> list[tuple[float, float]]:
    selected: list[tuple[float, float]] = []
    for point in points:
        if all(abs(point[0] - other[0]) > 0.00001 or abs(point[1] - other[1]) > 0.00001 for other in selected):
            selected.append(point)
        if len(selected) >= limit:
            break
    return selected


def chunk_ids(values: Iterable[str], size: int = 10) -> Iterator[list[str]]:
    batch: list[str] = []
    for value in values:
        if value and value not in batch:
            batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def normalize_amap_location(record: dict[str, Any]) -> dict[str, Any]:
    """Preserve AMap GCJ-02 and derive the WGS84 coordinate once."""

    point = point_from_location(record.get("location"))
    normalized = dict(record)
    if point is None:
        normalized["location_gcj02"] = None
        normalized["location_wgs84"] = None
        return normalized
    wgs_point = gcj02_to_wgs84(*point)
    normalized["location_gcj02"] = [point[0], point[1]]
    normalized["location_wgs84"] = [wgs_point[0], wgs_point[1]]
    normalized["coordinate_contract"] = "AMap response GCJ-02; local check WGS84"
    return normalized


def _record_text(record: dict[str, Any]) -> str:
    fields = (
        "province",
        "pname",
        "city",
        "cityname",
        "district",
        "adname",
        "township",
        "townname",
        "address",
        "formatted_address",
        "name",
    )
    return "".join(normalize_name(record.get(field)) for field in fields)


class ScopeClassifier:
    """Classify external records without allowing LLMs to override scope."""

    def __init__(self, boundary_wgs84: Any | None = None) -> None:
        self.boundary_wgs84 = boundary_wgs84

    def classify(self, record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_amap_location(record)
        text = _record_text(normalized)
        city_code = normalize_name(normalized.get("citycode"))
        adcode = normalize_name(normalized.get("adcode"))
        towncode = normalize_name(normalized.get("towncode"))
        city_match = city_code in MEIZHOU_CITY_CODES or "梅州市" in text
        county_match = adcode.startswith(COUNTY_ADCODE) or "平远县" in text
        town_match = (
            towncode.startswith(tuple(LOCAL_TOWN_CODE_PREFIXES))
            or "泗水镇" in text
        )
        project_match = False
        point = normalized.get("location_wgs84")
        if self.boundary_wgs84 is not None and point:
            project_match = bool(self.boundary_wgs84.covers(Point(point[0], point[1])))

        if not city_match and (county_match or town_match or project_match):
            city_match = True
        if not city_match:
            bucket = "outside_meizhou"
        elif project_match:
            bucket = "project_local"
        elif town_match:
            bucket = "township_local"
        elif county_match:
            bucket = "county_local"
        elif city_match:
            bucket = "meizhou_other"
        else:
            bucket = "unknown_scope"

        normalized.update(
            {
                "scope_bucket": bucket,
                "admin_match": {
                    "city": city_match,
                    "county": county_match,
                    "township": town_match,
                    "project_boundary": project_match,
                },
            }
        )
        return normalized


def candidate_quality(record: dict[str, Any], query_name: str | None = None, role: str | None = None) -> tuple[int, list[str]]:
    name = normalize_name(record.get("name"))
    query = normalize_name(query_name)
    bucket = record.get("scope_bucket")
    score = {
        "project_local": 8,
        "township_local": 6,
        "county_local": 4,
        "meizhou_other": 0,
        "unknown_scope": -4,
        "outside_meizhou": -100,
    }.get(str(bucket), -4)
    flags: list[str] = []
    if query and name == query:
        score += 4
    elif query and (query in name or name in query):
        score += 2
        flags.append("normalized_name_match")
    elif query:
        score -= 2
        flags.append("name_mismatch")
    type_text = normalize_name(record.get("type")) + normalize_name(record.get("typecode"))
    if role == "road" and ("道路" in type_text or str(record.get("typecode", "")).startswith("190")):
        score += 3
    if role == "water_body" and ("水" in type_text or str(record.get("typecode", "")).startswith("1902")):
        score += 3
    level = normalize_name(record.get("level"))
    if level in {"村庄", "乡镇", "区县"} and query and name != query:
        score -= 5
        flags.append("parent_fallback")
    if bucket == "outside_meizhou":
        flags.append("outside_meizhou")
    if not record.get("location_wgs84"):
        flags.append("missing_coordinate")
        score -= 2
    return score, flags


def jsonable_boundary_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if not key.endswith("_geometry_wgs84")}


def load_latest_l1() -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """Resolve the latest L1 ref -> descriptor -> blob chain."""

    refs = sorted(
        (path for path in (PROJECT_ROOT / ".run-tmp").rglob("l1_snapshot.json")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for ref in refs:
        try:
            ref_data = load_json(ref)
            descriptor_digest = str(ref_data["descriptor_digest"]).split(":", 1)[1]
            descriptor_path = PROJECT_ROOT / ".run-tmp" / "descriptors" / f"{descriptor_digest}.json"
            descriptor = load_json(descriptor_path)
            blob_digest = str(descriptor["digest"]).split(":", 1)[1]
            blob_path = PROJECT_ROOT / ".run-tmp" / "blobs" / "sha256" / blob_digest
            payload = load_json(blob_path)
            if isinstance(payload.get("location_mentions"), list):
                return ref, blob_path, descriptor, payload
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            continue
    raise FileNotFoundError("没有找到包含 location_mentions 的有效 L1Snapshot")


def collect_l1_place_names(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect main and related location names with auditable L1 provenance."""

    by_name: dict[str, dict[str, Any]] = {}
    excluded: dict[str, dict[str, Any]] = {}

    def add(name: Any, source: dict[str, Any], related: bool) -> None:
        normalized = normalize_name(name)
        if not normalized:
            return
        role = str(source.get("role") or "unknown")
        entry = by_name.get(normalized)
        if normalized in NON_PLACE_NAMES:
            item = excluded.setdefault(
                normalized,
                {"name": normalized, "reason": NON_PLACE_NAMES[normalized], "l1_sources": []},
            )
            item["l1_sources"].append({"role": role, "related": related, "source": compact(source)})
            return
        if role not in PLACE_ROLES and not related:
            return
        if entry is None:
            entry = {
                "name": normalized,
                "roles": [],
                "dimensions": [],
                "source_quotes": [],
                "source_refs": [],
                "main_mention_count": 0,
                "related_mention_count": 0,
            }
            by_name[normalized] = entry
        if role not in entry["roles"]:
            entry["roles"].append(role)
        dimension = source.get("dimension_key")
        if dimension and dimension not in entry["dimensions"]:
            entry["dimensions"].append(dimension)
        provenance = source.get("provenance") or {}
        quote = provenance.get("source_quote") or source.get("source_span")
        if quote and quote not in entry["source_quotes"]:
            entry["source_quotes"].append(quote)
        for ref in provenance.get("source_refs") or source.get("evidence_refs") or []:
            if ref not in entry["source_refs"]:
                entry["source_refs"].append(ref)
        entry["related_mention_count" if related else "main_mention_count"] += 1

    for mention in payload.get("location_mentions") or []:
        if not isinstance(mention, dict):
            continue
        add(mention.get("normalized_name") or mention.get("mention"), mention, False)
        for related_name in mention.get("related_mentions") or []:
            add(related_name, mention, True)
        for scope in mention.get("scopes") or []:
            if isinstance(scope, dict):
                add(scope.get("normalized_name") or scope.get("name"), {**mention, **scope}, True)

    return sorted(by_name.values(), key=lambda item: item["name"]), sorted(excluded.values(), key=lambda item: item["name"])


class StageCollector:
    def __init__(
        self,
        stage_name: str,
        refresh: bool,
        min_interval: float,
        root: Path | None = None,
        max_retries: int = MAX_RETRIES,
        boundary_context: dict[str, Any] | None = None,
    ) -> None:
        self.stage_name = stage_name
        output_root = root if root is not None else OUTPUT_ROOT
        self.stage_dir = output_root / stage_name
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_dir = self.stage_dir / "runs" / self.run_id
        self.cache_dir = self.stage_dir / "cache"
        self.response_dir = self.stage_dir / "responses"
        self.boundary_context = dict(boundary_context or {})
        self.refresh = refresh
        self.min_interval = min_interval
        self.max_retries = max(1, max_retries)
        self.last_request_at = 0.0
        self.session = requests.Session()
        self.api_key = os.getenv("AMAP_API_KEY", "")
        self.events: list[dict[str, Any]] = []
        self.normalized: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []
        self.response_payloads: dict[str, dict[str, Any]] = {}
        self.query_meta: dict[str, dict[str, Any]] = {}
        self._unavailable_operations: set[str] = set()
        self.lease_store = ProviderRunLeaseStore(output_root.parent)
        self.lease = self.lease_store.acquire(
            self.run_id,
            "amap",
            f"pid-{os.getpid()}",
            ttl_seconds=3600,
        )

    def request_key(self, url: str, params: dict[str, Any]) -> str:
        sanitized = {key: value for key, value in params.items() if key not in {"key", "sig"}}
        material = json.dumps({"url": url, "params": sanitized}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    _request_key = request_key

    def request(self, operation: str, url: str, params: dict[str, Any], kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.lease_store.assert_writer(self.lease)
        sanitized = {key: value for key, value in params.items() if key not in {"key", "sig"}}
        key = self._request_key(url, sanitized)

        if operation in self._unavailable_operations:
            event = {
                "operation": operation,
                "url": url,
                "params": sanitized,
                "request_key": key,
                "cache_hit": False,
                "raw_response": None,
                "http_status": 200,
                "api_status": "0",
                "api_infocode": "10012",
                "api_info": "INSUFFICIENT_PRIVILEGES",
                "status": "missing_capability",
                "success": False,
                "record_count": 0,
                "retry_count": 0,
                "retryable": False,
                "attempts": [],
                "error": "provider capability unavailable for this operation; skipped after first rejection",
                "attempted": False,
                "capability_available": False,
            }
            self.events.append(event)
            append_jsonl(self.run_dir / "requests.jsonl", event)
            return {}, event

        cache_path = self.cache_dir / f"{key}.json"
        raw_path: Path | None = None
        envelope: dict[str, Any] | None = None
        cache_hit = False

        cached_path = cache_path if cache_path.exists() else None
        if cached_path is not None and not self.refresh:
            pointer = load_json(cached_path)
            raw_path = resolve_path_ref(pointer["raw_response"])
            cached = load_json(raw_path)
            cached_payload = cached.get("response_json") or {}
            cached_status = cached.get("status") or pointer.get("status")
            if not cached_status:
                cached_status = classify_status(
                    attempted=True,
                    capability_available=True,
                    payload=cached_payload,
                    http_status=cached.get("http_status"),
                    error=cached.get("error"),
                )
            elif cached_status == "missing":
                cached_status = classify_status(
                    attempted=bool(cached.get("attempted", True)),
                    capability_available=True,
                    payload=cached_payload,
                    http_status=cached.get("http_status"),
                    error=cached.get("error"),
                )
            cached["status"] = cached_status
            cached_retryable = cached.get("retryable")
            if cached_retryable is None:
                cached_retryable = cached_status == "failed" and _is_retryable(
                    cached.get("http_status"), cached_payload
                )
            if cached_status != "failed" or not cached_retryable:
                envelope = cached
                cache_hit = True

        attempts: list[dict[str, Any]] = []
        if envelope is None and not self.api_key:
            envelope = {
                "status": "not_attempted",
                "attempted": False,
                "http_status": None,
                "response_json": {},
                "response_text": "",
                "error": "AMAP_API_KEY 未配置",
                "retryable": False,
                "retry_count": 0,
                "attempts": attempts,
            }
        elif envelope is None:
            final_payload: Any = {}
            final_http: int | None = None
            final_error: str | None = None
            for attempt in range(1, self.max_retries + 1):
                wait = self.min_interval - (time.monotonic() - self.last_request_at)
                if wait > 0:
                    time.sleep(wait)
                request_params = {**sanitized, "key": self.api_key, "output": "JSON"}
                try:
                    response = self.session.get(
                        url,
                        params=request_params,
                        timeout=30,
                        headers={"User-Agent": "VillagePlanningAgent/validation"},
                    )
                    self.last_request_at = time.monotonic()
                    final_http = response.status_code
                    try:
                        final_payload = response.json()
                    except ValueError:
                        final_payload = {}
                    api_ok = response_ok(final_payload) and final_http == 200
                    final_error = (
                        None
                        if api_ok
                        else f"HTTP {final_http}"
                        if final_http != 200
                        else str(final_payload.get("info", "provider_error"))
                        if isinstance(final_payload, dict)
                        else "provider_error"
                    )
                    retryable = not api_ok and _is_retryable(final_http, final_payload)
                except requests.RequestException as exc:
                    self.last_request_at = time.monotonic()
                    final_payload = {}
                    final_http = None
                    final_error = f"{type(exc).__name__}: {exc}"
                    retryable = True
                attempt_row = {
                    "attempt": attempt,
                    "http_status": final_http,
                    "success": final_http == 200 and response_ok(final_payload),
                    "retryable": retryable,
                    "error": final_error,
                }
                attempts.append(attempt_row)
                if attempt_row["success"] or not retryable:
                    break
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
            status = classify_status(
                attempted=True,
                capability_available=True,
                payload=final_payload,
                http_status=final_http,
                error=final_error,
            )
            envelope = {
                "status": status,
                "attempted": True,
                "http_status": final_http,
                "response_json": final_payload,
                "response_text": "",
                "error": final_error,
                "retryable": status == "failed" and bool(attempts) and bool(attempts[-1].get("retryable")),
                "retry_count": max(0, len(attempts) - 1),
                "attempts": attempts,
            }
            raw_path = self.response_dir / f"{key}.json"
            write_json(raw_path, {"request": {"operation": operation, "url": url, "params": sanitized}, **envelope})
            write_json(
                cache_path,
                {
                    "raw_response": path_ref(raw_path),
                    "request_key": key,
                    "status": status,
                    "retryable": envelope["retryable"],
                },
            )

        data = envelope.get("response_json") or {}
        status = envelope.get("status") or classify_status(
            attempted=bool(envelope.get("attempted", True)),
            capability_available=True,
            payload=data,
            http_status=envelope.get("http_status"),
            error=envelope.get("error"),
        )
        self.response_payloads[key] = data
        event = {
            "operation": operation,
            "url": url,
            "params": sanitized,
            "request_key": key,
            "cache_hit": cache_hit,
            "raw_response": path_ref(raw_path) if raw_path else None,
            "http_status": envelope.get("http_status"),
            "api_status": data.get("status") if isinstance(data, dict) else None,
            "api_infocode": data.get("infocode") if isinstance(data, dict) else None,
            "api_info": data.get("info") if isinstance(data, dict) else None,
            "status": status,
            "success": status in {"success_nonempty", "success_empty"},
            "record_count": len(response_records(data)),
            "retry_count": envelope.get("retry_count", 0),
            "retryable": envelope.get("retryable", False),
            "attempts": envelope.get("attempts", []),
            "error": envelope.get("error"),
        }
        self.events.append(event)
        append_jsonl(self.run_dir / "requests.jsonl", event)
        if status == "failed" and _is_capability_unavailable(data):
            self._unavailable_operations.add(operation)
        return data, event

    def add_normalized(self, event: dict[str, Any], kind: str, data: dict[str, Any], query_name: str | None = None) -> None:
        event["query_name"] = query_name
        item = {
            "operation": event["operation"],
            "kind": kind,
            "query_name": query_name,
            "request_key": event["request_key"],
            "raw_response": event["raw_response"],
            "status": event.get("status"),
            "success": event["success"],
            "retry_count": event.get("retry_count", 0),
            "records": compact(data),
        }
        self.normalized.append(item)
        append_jsonl(self.run_dir / "normalized.jsonl", item)

    def finish(self, manifest: dict[str, Any]) -> Path:
        self.lease_store.assert_writer(self.lease)
        status_counts: dict[str, int] = {}
        for event in self.events:
            status = str(event.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        manifest.update(
            {
                "stage_name": self.stage_name,
                "run_id": self.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "refresh": self.refresh,
                "request_count": len(self.events),
                "cache_hits": sum(1 for event in self.events if event["cache_hit"]),
                "cache_misses": sum(1 for event in self.events if not event["cache_hit"]),
                "successful_requests": sum(
                    1 for event in self.events
                    if event.get("status") in {"success_nonempty", "success_empty"}
                ),
                "failed_requests": sum(1 for event in self.events if event.get("status") == "failed"),
                "status_counts": status_counts,
                "query_meta": self.query_meta,
                "truncated_queries": [
                    name for name, meta in self.query_meta.items() if meta.get("truncated")
                ],
                "partial_queries": [
                    name for name, meta in self.query_meta.items()
                    if meta.get("coverage_status") == "partial_requires_spatial_sharding"
                ],
                "raw_response_directory": path_ref(self.response_dir),
                "cache_directory": path_ref(self.cache_dir),
                "boundary_ref": self.boundary_context.get("boundary_ref", ""),
                "boundary_digest": self.boundary_context.get("boundary_digest", ""),
                "query_geometry_digest": self.boundary_context.get("query_geometry_digest", ""),
                "boundary_source_path": self.boundary_context.get("source_path", ""),
                "provider_coordinate_contract": "AMap request GCJ-02; local checks WGS84",
                "provider_acquisition_plan": self.boundary_context.get("provider_acquisition_plans", {}).get("amap", {}),
            }
        )
        ProviderObservationWriter(
            self.lease_store.root,
            "amap",
            self.run_id,
            stage=self.stage_name,
        ).publish(
            self.lease,
            self.normalized,
            boundary_digest=str(self.boundary_context.get("boundary_digest") or ""),
            query_geometry_digest=str(self.boundary_context.get("query_geometry_digest") or ""),
            crs_contract="source=AMap GCJ-02; target=EPSG:4326; transform=declared",
            coverage={
                "coverage_status": "COMPLETE"
                if not manifest["failed_requests"] and not manifest["partial_queries"]
                else "PARTIAL",
                "request_count": len(self.events),
            },
            manifest_extra=manifest,
        )
        write_json(
            self.run_dir / "query_plan.json",
            self.boundary_context.get("provider_acquisition_plans", {}).get("amap", {}),
        )
        write_json(self.run_dir / "skipped_or_excluded.json", self.skipped)
        self.lease_store.release(self.lease)
        return self.run_dir

    def paged_place_search(self, query_name: str, region_params: dict[str, Any], around: bool = False) -> list[dict[str, Any]]:
        """Query the declared AMap place API with bounded pagination."""

        results: list[dict[str, Any]] = []
        if around:
            v5_url = f"{AMAP_V5}/place/around"
            v5_base = {
                **region_params,
                "region": region_params.get("region", CITY_ADCODE),
                "city_limit": region_params.get("city_limit", "true"),
                "page_size": PAGE_SIZE,
                "show_fields": "children,business,indoor,navi,photos",
            }
        else:
            v5_url = f"{AMAP_V5}/place/text"
            v5_base = {**region_params, "page_size": PAGE_SIZE, "show_fields": "children,business,indoor,navi,photos"}
        for page in range(1, MAX_PAGES + 1):
            params = {**v5_base, "page_num": page}
            data, event = self.request("poi_v5_around" if around else "poi_v5_text", v5_url, params, "poi")
            self.add_normalized(event, "poi_v5", data, query_name)
            if not event["success"]:
                break
            batch = data.get("pois") or []
            results.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        self.query_meta[query_name] = {
            "pages": min(MAX_PAGES, max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)),
            "record_count": len(results),
            "truncated": bool(results) and len(results) >= MAX_RECORDS_PER_QUERY,
            "provider_limit": MAX_RECORDS_PER_QUERY,
        }
        return results

    def paged_place_polygon(self, query_name: str, polygon: str, types: str) -> list[dict[str, Any]]:
        """Search one administrative polygon with bounded v5 pagination."""

        results: list[dict[str, Any]] = []
        v5_params = {
            "polygon": polygon,
            "types": types,
            "region": CITY_ADCODE,
            "city_limit": "true",
            "page_size": PAGE_SIZE,
            "show_fields": "children,business,indoor,navi,photos",
            "langCode": "zh",
        }
        for page in range(1, MAX_PAGES + 1):
            data, event = self.request(
                "poi_v5_polygon",
                f"{AMAP_V5}/place/polygon",
                {**v5_params, "page_num": page},
                "poi",
            )
            self.add_normalized(event, "poi_v5_polygon", data, query_name)
            if not event["success"]:
                break
            batch = data.get("pois") or []
            results.extend(batch)
            if len(batch) < PAGE_SIZE:
                break

        self.query_meta[query_name] = {
            "pages": min(MAX_PAGES, max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)),
            "record_count": len(results),
            "truncated": bool(results) and len(results) >= MAX_RECORDS_PER_QUERY,
            "provider_limit": MAX_RECORDS_PER_QUERY,
        }

        return results

    def place_details(self, poi_ids: Iterable[str], query_name: str = "") -> int:
        """Fetch v5 POI details for already scope-filtered POI IDs."""

        requested = 0
        for batch in chunk_ids(poi_ids, 10):
            data, event = self.request(
                "poi_v5_detail",
                f"{AMAP_V5}/place/detail",
                {"id": "|".join(batch), "show_fields": DETAIL_FIELDS, "langCode": "zh"},
                "poi_detail",
            )
            self.add_normalized(event, "poi_v5_detail", data, query_name)
            requested += len(batch)
        return requested

    def inputtips(self, query_name: str, location: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"keywords": query_name, "city": CITY_ADCODE, "citylimit": "true", "datatype": "all"}
        if location:
            params["location"] = location
        data, event = self.request("inputtips", f"{AMAP_V3}/assistant/inputtips", params, "inputtips")
        self.add_normalized(event, "inputtips", data, query_name)
        return data

    def geocode(self, address: str) -> dict[str, Any]:
        data, event = self.request("geocode", f"{AMAP_V3}/geocode/geo", {"address": address, "city": CITY_ADCODE}, "geocode")
        self.add_normalized(event, "geocode", data, address)
        return data

    def regeo(self, location: str, query_name: str | None = None, radius: int = 3000) -> dict[str, Any]:
        params = {"location": location, "extensions": "all", "roadlevel": "0", "radius": str(radius)}
        data, event = self.request("reverse_geocode_full", f"{AMAP_V3}/geocode/regeo", params, "regeo")
        self.add_normalized(event, "regeo_full", data, query_name)
        return data


def response_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("pois", "tips", "geocodes", "roads", "roadinters", "districts"):
        if key in data and isinstance(data.get(key), list):
            values = data.get(key)
            return [item for item in values if isinstance(item, dict)]
    route = data.get("route")
    if isinstance(route, dict) and isinstance(route.get("paths"), list):
        return [item for item in route["paths"] if isinstance(item, dict)]
    regeocode = data.get("regeocode")
    if isinstance(regeocode, dict):
        component = regeocode.get("addressComponent") or {}
        if isinstance(component, dict) and (
            component or regeocode.get("formatted_address")
        ):
            return [{**component, "formatted_address": regeocode.get("formatted_address", "")}]
    return []


def build_external_records(collector: StageCollector, classifier: ScopeClassifier) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for event in collector.events:
        key = event["request_key"]
        query_name = event.get("query_name")
        if (key, query_name) in seen:
            continue
        seen.add((key, query_name))
        data = collector.response_payloads.get(key) or {}
        for index, raw_record in enumerate(response_records(data)):
            if not isinstance(raw_record, dict):
                continue
            record = classifier.classify(raw_record)
            score, flags = candidate_quality(record, event.get("query_name"))
            record.update(
                {
                    "source": "amap",
                    "operation": event["operation"],
                    "query_name": query_name,
                    "request_key": key,
                    "raw_response": event.get("raw_response"),
                    "record_index": index,
                    "poi_id": raw_record.get("id"),
                    "quality_score": score,
                    "quality_flags": flags,
                }
            )
            records.append(record)
    return records


def write_candidate_outputs(
    collector: StageCollector,
    classifier: ScopeClassifier,
    query_roles: dict[str, str] | None = None,
    top_k_project: int = 20,
    top_k_extended: int = 10,
) -> dict[str, Any]:
    """Write audit-all and downstream-retained candidate projections."""

    query_roles = query_roles or {}
    all_records: list[dict[str, Any]] = []
    for record in build_external_records(collector, classifier):
        role = query_roles.get(str(record.get("query_name")))
        score, flags = candidate_quality(record, record.get("query_name"), role)
        record["quality_score"] = score
        record["quality_flags"] = sorted(set(record.get("quality_flags", []) + flags))
        record["retained"] = (
            record.get("scope_bucket") in {"project_local", "township_local", "county_local"}
            and "parent_fallback" not in record["quality_flags"]
            and "outside_meizhou" not in record["quality_flags"]
        )
        all_records.append(record)

    retained: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in all_records:
        if record["retained"]:
            grouped.setdefault(str(record.get("query_name") or "__unscoped__"), []).append(record)
        else:
            reasons = record.get("quality_flags") or [str(record.get("scope_bucket", "unknown_scope"))]
            record["rejection_reasons"] = sorted(set(reasons))
            rejected.append(record)

    for query_name, candidates in grouped.items():
        candidates.sort(key=lambda item: (-int(item.get("quality_score", -100)), str(item.get("poi_id") or item.get("name") or "")))
        project = [item for item in candidates if item.get("scope_bucket") == "project_local"][:top_k_project]
        extended = [item for item in candidates if item.get("scope_bucket") != "project_local"][:top_k_extended]
        retained.extend(project + extended)
        retained_keys = {id(item) for item in project + extended}
        for item in candidates:
            if id(item) not in retained_keys:
                item["retained"] = False
                item["rejection_reasons"] = ["top_k_overflow"]
                rejected.append(item)

    bucket_counts = {bucket: 0 for bucket in SCOPE_BUCKETS}
    for record in all_records:
        bucket = record.get("scope_bucket", "unknown_scope")
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    # The formal provider writer publishes canonical observation rows.  The
    # request-level wrappers collected by add_normalized() remain in
    # normalized.jsonl as an audit index, but must never become the DATA
    # normalized_all.jsonl product.
    collector.normalized = all_records
    write_jsonl(collector.run_dir / "normalized_all.jsonl", all_records)
    write_jsonl(collector.run_dir / "retained_candidates.jsonl", retained)
    write_jsonl(collector.run_dir / "rejected_candidates.jsonl", rejected)
    summary = {
        "normalized_record_count": len(all_records),
        "retained_candidate_count": len(retained),
        "rejected_record_count": len(rejected),
        "scope_bucket_counts": bucket_counts,
        "top_k": {"project_local": top_k_project, "extended": top_k_extended},
    }
    write_json(collector.run_dir / "scope_summary.json", summary)
    return summary


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_admin(
    refresh: bool,
    min_interval: float,
    expand: bool = True,
    root: Path | None = None,
    boundary_scope: Any | None = None,
) -> Path:
    boundary_context = load_admin_boundary_context(boundary_scope=boundary_scope)
    collector = StageCollector(
        "01_admin_scope",
        refresh,
        min_interval,
        root=root,
        boundary_context=boundary_context,
    )
    admin_address = "广东省梅州市平远县泗水镇金田村"
    town_address = "广东省梅州市平远县泗水镇"
    village_geo = collector.geocode(admin_address)
    town_geo = collector.geocode(town_address)
    anchor_points = locations_from(village_geo) + locations_from(town_geo)
    anchor_points = nearest_distinct_points(anchor_points, 2)
    anchor = f"{anchor_points[0][0]},{anchor_points[0][1]}" if anchor_points else None

    for query in ["金田村", "泗水镇", "平远县"]:
        collector.inputtips(query, anchor)
        collector.paged_place_search(
            query,
            {"keywords": query, "region": CITY_ADCODE, "city_limit": "true"},
        )

    if anchor:
        for label, types in PLACE_TYPES.items():
            collector.paged_place_search(
                label,
                {
                    "location": anchor,
                    "radius": "3000",
                    "types": types,
                    "sortrule": "distance",
                },
                around=True,
            )
        collector.regeo(anchor, "行政村地理编码中心")
        traffic_params = {"location": anchor, "radius": "3000", "extensions": "all"}
        traffic, event = collector.request("traffic_circle", f"{AMAP_V3}/traffic/status/circle", traffic_params, "traffic")
        collector.add_normalized(event, "traffic_circle", traffic, "行政村地理编码中心")

    if expand and boundary_context:
        polygon_requests = [
            ("project", polygon_request_geometries(boundary_context["boundary_geometry_wgs84"])),
            ("expanded", polygon_request_geometries(boundary_context["expanded_geometry_wgs84"])),
        ]
        for scope_label, geometries in polygon_requests:
            for polygon_index, geometry in enumerate(geometries, start=1):
                for shard_name, types in PLACE_TYPE_SHARDS.items():
                    query_name = f"金田村行政边界-{scope_label}-cell-{polygon_index}-{shard_name}"
                    collector.paged_place_polygon(
                        query_name,
                        _polygon_string_gcj02(geometry),
                        types,
                    )
                    if collector.query_meta.get(query_name, {}).get("truncated"):
                        collector.query_meta[query_name]["coverage_status"] = "partial_requires_spatial_sharding"
                        for cell_index, cell in enumerate(split_saturated_scope(geometry, 1200.0), start=1):
                            cell_query = f"{query_name}-subcell-{cell_index}"
                            collector.paged_place_polygon(
                                cell_query,
                                _polygon_string_gcj02(simplify_wgs84_meters(cell, 5.0)),
                                types,
                            )
                            collector.query_meta[cell_query]["parent_query"] = query_name
        for radius in ("3000", "10000"):
            for shard_name, types in PLACE_TYPE_SHARDS.items():
                query_name = f"金田村中心{radius}米-{shard_name}"
                collector.paged_place_search(
                    query_name,
                    around_params(anchor, int(radius), types),
                    around=True,
                )
                if collector.query_meta.get(query_name, {}).get("truncated"):
                    collector.query_meta[query_name]["coverage_status"] = "partial_requires_spatial_sharding"
                    for cell_index, (lon, lat) in enumerate(
                        spatial_probe_centers(boundary_context["expanded_geometry_wgs84"]), start=1
                    ):
                        cell_query = f"{query_name}-cell-{cell_index}"
                        collector.paged_place_search(
                            cell_query,
                            around_params(f"{wgs84_to_gcj02(lon, lat)[0]:.6f},{wgs84_to_gcj02(lon, lat)[1]:.6f}", min(int(radius), 3000), types),
                            around=True,
                        )
                        collector.query_meta[cell_query]["parent_query"] = query_name
        for index, point in enumerate(boundary_context["sample_points_gcj02"], start=1):
            collector.regeo(f"{point[0]:.6f},{point[1]:.6f}", f"行政边界采样-{index}", radius=300)
    geocoded_points = nearest_distinct_points(locations_from(village_geo) + locations_from(town_geo), 2)
    if len(geocoded_points) >= 2:
        origin = f"{geocoded_points[0][0]},{geocoded_points[0][1]}"
        destination = f"{geocoded_points[1][0]},{geocoded_points[1][1]}"
        route, event = collector.request(
            "driving_route_v5_admin_anchor",
            f"{AMAP_V5}/direction/driving",
            {"origin": origin, "destination": destination, "alternative_route": "3", "show_fields": "cost,polyline,tmcs,navi"},
            "route",
        )
        collector.add_normalized(event, "driving_route", route, "金田村—泗水镇行政锚点")
        route_v3, event_v3 = collector.request(
            "driving_route_v3_admin_anchor",
            f"{AMAP_V3}/direction/driving",
            {"origin": origin, "destination": destination, "extensions": "all", "strategy": "0"},
            "route",
        )
        collector.add_normalized(event_v3, "driving_route_v3", route_v3, "金田村—泗水镇行政锚点")
        if expand:
            for mode in ("walking", "bicycling", "electrobike"):
                route_data, route_event = collector.request(
                    f"{mode}_route_v5_admin_anchor",
                    f"{AMAP_V5}/direction/{mode}",
                    {"origin": origin, "destination": destination, "alternative_route": "3", "show_fields": "cost,polyline,navi,tmcs"},
                    "route",
                )
                collector.add_normalized(route_event, f"{mode}_route", route_data, "金田村—泗水镇行政锚点")
    else:
        collector.skipped.append({"operation": "driving_route_v5_admin_anchor", "reason": "行政地址编码未返回两个可区分坐标"})

    district_params = {"keywords": CITY_ADCODE, "subdistrict": "3", "extensions": "all"}
    district, event = collector.request("district_tree_meizhou", f"{AMAP_V3}/config/district", district_params, "district")
    collector.add_normalized(event, "district_tree", district, "梅州市行政层级")
    district_probes = ((COUNTY_ADCODE, "2"), ("平远县", "2"), ("泗水镇", "0"))
    if expand:
        district_probes += (("金田村", "0"), ("441426108004", "0"))
    for keyword, subdistrict in district_probes:
        district, event = collector.request(
            "district_scope_probe",
            f"{AMAP_V3}/config/district",
            {"keywords": keyword, "subdistrict": subdistrict, "extensions": "all"},
            "district",
        )
        collector.add_normalized(event, "district_scope_probe", district, keyword)

    classifier = ScopeClassifier(boundary_context["boundary_geometry_wgs84"])
    preliminary = build_external_records(collector, classifier)
    detail_ids = []
    for record in preliminary:
        if record.get("operation") not in {
            "poi_v5_text",
            "poi_v5_around",
            "poi_v5_polygon",
        }:
            continue
        if record.get("scope_bucket") in {"project_local", "township_local", "county_local"}:
            poi_id = normalize_name(record.get("id"))
            if poi_id and poi_id not in detail_ids:
                detail_ids.append(poi_id)
    detail_count = collector.place_details(detail_ids, "行政阶段范围内POI详情") if expand else 0
    candidate_summary = write_candidate_outputs(collector, classifier)

    return collector.finish(
        {
            "purpose": "仅基于已知行政区划和行政地址锚点，验证高德公开接口能返回的附近 POI、地址、道路/区域、交通和行政树数据",
            "scope": ADMIN_SCOPE,
            "input_policy": {
                "l1_names_used": False,
                "queries": ["广东省梅州市平远县泗水镇金田村", "广东省梅州市平远县泗水镇", "金田村", "泗水镇", "平远县"],
                "city_constraint": CITY_ADCODE,
                "expanded": expand,
                "boundary_context": jsonable_boundary_context(boundary_context),
                "candidate_summary": candidate_summary,
                "detail_poi_count": detail_count,
                "detail_coverage": "all_scoped_ids" if expand else "not_attempted",
            },
            "capability_boundary": {
                "basemap_label_enumeration": "not_available_via_public_general_api",
                "unpublished_vector_tile_scraping": "not_attempted",
                "raw_response_policy": "full_response_saved_under_responses; normalized.jsonl is only an index",
            },
        }
    )


def run_l1(
    refresh: bool,
    min_interval: float,
    root: Path | None = None,
    boundary_scope: Any | None = None,
) -> Path:
    ref_path, blob_path, descriptor, payload = load_latest_l1()
    names, excluded = collect_l1_place_names(payload)
    boundary_context = load_admin_boundary_context(boundary_scope=boundary_scope)
    collector = StageCollector(
        "02_l1_place_names",
        refresh,
        min_interval,
        root=root,
        boundary_context=boundary_context,
    )
    classifier = ScopeClassifier(boundary_context["boundary_geometry_wgs84"])
    admin_address = "广东省梅州市平远县泗水镇金田村"
    admin_geo = collector.geocode(admin_address)
    anchor_points = nearest_distinct_points(locations_from(admin_geo), 1)
    anchor = f"{anchor_points[0][0]},{anchor_points[0][1]}" if anchor_points else None
    all_name_points: dict[str, list[tuple[float, float]]] = {}

    for item in names:
        name = item["name"]
        points: list[tuple[float, float]] = []
        tips = collector.inputtips(name, anchor)
        points.extend(locations_from(tips))
        poi_results = collector.paged_place_search(
            name,
            {"keywords": name, "region": CITY_ADCODE, "city_limit": "true"},
        )
        if not (tips.get("tips") or poi_results) and name != "金田村" and "金田村" not in name:
            scoped_name = f"金田村{name}"
            scoped_tips = collector.inputtips(scoped_name, anchor)
            points.extend(locations_from(scoped_tips))
            poi_results = collector.paged_place_search(
                scoped_name,
                {"keywords": scoped_name, "region": CITY_ADCODE, "city_limit": "true"},
            )
        structured = f"广东省梅州市平远县泗水镇金田村{name}"
        geocode_data = collector.geocode(structured)
        points.extend(locations_from(geocode_data))
        if not locations_from(geocode_data):
            raw_geocode_data = collector.geocode(name)
            points.extend(locations_from(raw_geocode_data))
        points = nearest_distinct_points(points, 2)
        all_name_points[name] = points
        for point in points:
            collector.regeo(f"{point[0]},{point[1]}", name)

    preliminary = build_external_records(collector, classifier)
    detail_ids: list[str] = []
    for record in preliminary:
        if record.get("operation") != "poi_v5_text":
            continue
        if record.get("scope_bucket") not in {"project_local", "township_local", "county_local"}:
            continue
        poi_id = normalize_name(record.get("poi_id"))
        if poi_id and poi_id not in detail_ids:
            detail_ids.append(poi_id)
    detail_count = collector.place_details(detail_ids, "L1范围内POI详情")

    # Route probing is restricted to road-like L1 names and only occurs when
    # the API itself returned two distinct local anchors.
    for item in names:
        name = item["name"]
        if not (set(item["roles"]) & {"road", "primary_road", "east_west_road", "internal_road"}):
            continue
        points = all_name_points.get(name) or []
        if len(points) < 2:
            collector.skipped.append({"operation": "driving_route_v5_l1_name", "name": name, "reason": "该 L1 名称没有返回两个可区分的点状锚点"})
            continue
        origin = f"{points[0][0]},{points[0][1]}"
        destination = f"{points[1][0]},{points[1][1]}"
        route, event = collector.request(
            "driving_route_v5_l1_name",
            f"{AMAP_V5}/direction/driving",
            {"origin": origin, "destination": destination, "alternative_route": "3", "show_fields": "cost,polyline,tmcs,navi"},
            "route",
        )
        collector.add_normalized(event, "driving_route", route, name)
        route_v3, event_v3 = collector.request(
            "driving_route_v3_l1_name",
            f"{AMAP_V3}/direction/driving",
            {"origin": origin, "destination": destination, "extensions": "all", "strategy": "0"},
            "route",
        )
        collector.add_normalized(event_v3, "driving_route_v3", route_v3, name)

    write_json(collector.run_dir / "l1_place_names.json", names)
    write_json(collector.run_dir / "l1_excluded_names.json", excluded)
    query_roles = {
        item["name"]: next(iter(item.get("roles") or []), None)
        for item in names
    }
    candidate_summary = write_candidate_outputs(collector, classifier, query_roles)
    manifest = {
        "purpose": "仅使用最新有效 L1Snapshot 提取的地点/道路/水体/设施名称进行高德结构化检索",
        "l1_source": {
            "ref_path": str(ref_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "blob_path": str(blob_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "descriptor": descriptor,
            "location_mentions_count": len(payload.get("location_mentions") or []),
        },
        "scope": ADMIN_SCOPE,
        "input_policy": {
            "city_constraint": CITY_ADCODE,
            "structured_address_prefix": admin_address,
            "related_mentions_included": True,
            "place_like_name_count": len(names),
            "excluded_non_place_count": len(excluded),
            "candidate_summary": candidate_summary,
            "detail_poi_count": detail_count,
            "detail_coverage": "all_scoped_ids",
        },
        "capability_boundary": {
            "basemap_label_enumeration": "not available via public general API; this stage only probes structured endpoints",
            "unpublished_vector_tile_scraping": "not attempted",
            "raw_response_policy": "full_response_saved_under_responses; normalized.jsonl is only an index",
        },
    }
    return collector.finish(manifest)


class AmapJintianCollector:
    """Canonical AMap planner used by both standalone and unified commands."""

    def __init__(
        self,
        refresh: bool = False,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        root: Path | None = None,
        expand_admin: bool = True,
        boundary_scope: Any | None = None,
    ) -> None:
        self.refresh = refresh
        self.min_interval = min_interval
        self.root = root
        self.expand_admin = expand_admin
        self.boundary_scope = boundary_scope

    def collect(self, stage: str) -> Path:
        if stage == "01_admin_scope":
            return run_admin(
                self.refresh,
                self.min_interval,
                expand=self.expand_admin,
                root=self.root,
                boundary_scope=self.boundary_scope,
            )
        if stage == "02_l1_place_names":
            return run_l1(
                self.refresh,
                self.min_interval,
                root=self.root,
                boundary_scope=self.boundary_scope,
            )
        raise ValueError(f"unsupported AMap stage: {stage}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("admin", "l1", "all"), default="all")
    parser.add_argument("--refresh", action="store_true", help="显式重复已缓存请求；默认不重复消耗额度")
    parser.add_argument(
        "--expand-admin",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="行政阶段执行 Polygon、空间采样和多种路线探测（默认开启）",
    )
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL, help="请求之间的最小秒数")
    parser.add_argument("--boundary-artifact-root", type=Path, help="CAS root containing an admitted BoundaryScopeArtifact")
    parser.add_argument("--boundary-run-id", help="DATA admission run id whose named boundary scope is used")
    parser.add_argument("--boundary-branch-id", default="main")
    return parser.parse_args()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()
    if not os.getenv("AMAP_API_KEY"):
        print("AMAP_API_KEY 未配置；将只生成失败记录，不会发出高德请求。", file=sys.stderr)
    if bool(args.boundary_artifact_root) != bool(args.boundary_run_id):
        raise SystemExit("--boundary-artifact-root and --boundary-run-id must be supplied together")
    boundary_scope = (
        load_boundary_scope_artifact(
            str(args.boundary_artifact_root),
            args.boundary_run_id,
            branch_id=args.boundary_branch_id,
        )
        if args.boundary_artifact_root
        else None
    )
    paths: list[Path] = []
    if args.stage in {"admin", "all"}:
        paths.append(run_admin(args.refresh, args.min_interval, args.expand_admin, boundary_scope=boundary_scope))
    if args.stage in {"l1", "all"}:
        paths.append(run_l1(args.refresh, args.min_interval, boundary_scope=boundary_scope))
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
