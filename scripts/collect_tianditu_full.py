"""Collect the documented Tianditu data surface for the Jintian project.

This collector is deliberately independent from production KG/Evidence/GROUND.
It creates a durable provider-data snapshot with three separate products:

* every request, response and retry attempt;
* normalized provider records with scope and coverage decisions;
* a small candidate package that later stages may consume by reference.

Tianditu search APIs return structured place data, not an unrestricted dump of
every visual basemap label.  The planner therefore uses documented search
types, administrative/category/spatial sharding, local WGS84 filtering, and
WFS capability discovery without reading private tile endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests
from shapely.geometry import MultiPolygon, Point, Polygon, box, shape
from shapely.ops import triangulate

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_amap_jintian_validation import (  # noqa: E402
    collect_l1_place_names,
    load_admin_boundary_context,
    load_latest_l1,
    write_json,
    write_jsonl,
)
from app.data.boundary_scope import load_boundary_scope_artifact  # noqa: E402
from app.data.catalog.provider_run_lease import ProviderObservationWriter, ProviderRunLeaseStore  # noqa: E402


TD_BASE = "https://api.tianditu.gov.cn"
TD_SEARCH_URL = f"{TD_BASE}/v2/search"
TD_GEOCODER_URL = f"{TD_BASE}/geocoder"
TD_ADMIN_URL = f"{TD_BASE}/v2/administrative"
TD_WFS_URL = "http://gisserver.tianditu.gov.cn/TDTService/wfs"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "cache" / "map_observations" / "tianditu"
COORDINATE_CONTRACT = "Tianditu documented lon/lat; WGS84-compatible"
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
DETERMINISTIC_HTTP = {400, 401, 403, 404, 413, 414, 422}
MAX_PROVIDER_TOTAL = 500
MAX_SEARCH_COUNT = 300
MAX_POLYGON_VERTICES = 20

# These are intentional category shards rather than a fake wildcard.  The
# official data classification table may be added through configuration when a
# deployment has a more exhaustive licensed catalogue.
DEFAULT_CATEGORIES = (
    "村",
    "居民地",
    "道路",
    "桥",
    "河流",
    "水库",
    "水电站",
    "学校",
    "幼儿园",
    "医院",
    "卫生站",
    "村委会",
    "公交站",
    "停车场",
    "公园",
    "文化设施",
    "体育设施",
    "旅游景点",
    "历史文化",
    "宗教设施",
    "公共设施",
)


def compact(value: Any, limit: int = 4000) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, list):
        return [compact(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: compact(item, limit) for key, item in value.items()}
    return value


def sanitized_params(params: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in {"tk", "key", "sig"}}


def request_key(url: str, params: Mapping[str, Any]) -> str:
    material = json.dumps(
        {"url": url, "params": sanitized_params(params)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def td_poststr(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def bbox_string(bounds: Iterable[float]) -> str:
    return ",".join(str(float(value)) for value in bounds)


def path_reference(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def polygon_string(geometry: Polygon) -> str:
    coordinates = list(geometry.exterior.coords)
    return ",".join(f"{float(lon):.8f},{float(lat):.8f}" for lon, lat in coordinates)


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return [part for part in getattr(geometry, "geoms", []) if isinstance(part, Polygon)]


def polygon_chunks(geometry: Any, max_vertices: int = MAX_POLYGON_VERTICES) -> list[str]:
    """Return valid WGS84 polygon strings accepted by Tianditu's 20-point limit.

    A large boundary is triangulated and clipped instead of being truncated.
    Truncation could silently move the query outside the village boundary.
    """

    if max_vertices < 4:
        raise ValueError("max_vertices must allow a closed triangle")
    cleaned = geometry.buffer(0) if not geometry.is_valid else geometry
    # The source boundary may contain hundreds of vertices (especially after
    # the 500 m expansion).  First create a topology-preserving query shape;
    # the precise local boundary remains the authoritative post-filter.
    bounds = cleaned.bounds
    tolerance = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 1e-7
    for _ in range(24):
        simplified = cleaned.simplify(tolerance, preserve_topology=True)
        if all(len(list(part.exterior.coords)) <= max_vertices for part in _polygon_parts(simplified)):
            cleaned = simplified
            break
        tolerance *= 1.8
    chunks: list[str] = []
    for part in _polygon_parts(cleaned):
        exterior = list(part.exterior.coords)
        if len(exterior) <= max_vertices:
            chunks.append(polygon_string(part))
            continue
        for triangle in triangulate(part):
            clipped = triangle.intersection(part)
            for clipped_part in _polygon_parts(clipped):
                if len(list(clipped_part.exterior.coords)) <= max_vertices:
                    chunks.append(polygon_string(clipped_part))
    if not chunks:
        raise ValueError("unable to split polygon into Tianditu-compatible chunks")
    return list(dict.fromkeys(chunks))


def paginate_offsets(total: int, page_size: int = MAX_SEARCH_COUNT, shard_size: int = 250) -> list[int]:
    """Return safe starts; totals above 500 are expected to be spatially sharded."""

    if total <= 0:
        return [0]
    step = page_size if total <= MAX_PROVIDER_TOTAL else shard_size
    return list(range(0, total, step))


def _status_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if isinstance(status, dict):
        return str(status.get("infocode")) if status.get("infocode") is not None else None
    if payload.get("infocode") is not None:
        return str(payload["infocode"])
    if isinstance(status, (int, str)):
        return str(status)
    return None


def _record_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return [item for item in payload["features"] if isinstance(item, dict)]
    for key in ("pois", "poi", "tips", "geocodes", "roads", "roadinters", "districts", "features"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("pois", "poi", "geocodes", "districts", "features"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if data:
            return [data]
    if payload.get("formatted_address") or payload.get("addressComponent"):
        return [payload]
    return []


def _wfs_xml_success(payload: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("_raw_text"), str):
        return False
    text = payload["_raw_text"].lower()
    return "serviceexception" not in text and any(
        token in text for token in ("wfs_capabilities", "featuretypelist", "schemadescription", "featurecollection")
    )


def classify_tianditu_response(
    http_status: int | None,
    payload: Any,
    error: str | None = None,
) -> dict[str, Any]:
    """Separate successful emptiness from failed retrieval."""

    code = _status_code(payload)
    if http_status == 200 and isinstance(payload, dict):
        if "_raw_text" in payload:
            if _wfs_xml_success(payload):
                return {
                    "status": "success_nonempty",
                    "retryable": False,
                    "failure_class": None,
                    "api_status": None,
                }
            return {
                "status": "failed",
                "retryable": False,
                "failure_class": "malformed_or_service_exception",
                "api_status": None,
            }
        # WFS responses generally have no Tianditu status field.
        provider_ok = code in {None, "0", "1000", "200", "OK"}
        if provider_ok:
            return {
                "status": "success_nonempty" if _record_items(payload) else "success_empty",
                "retryable": False,
                "failure_class": None,
                "api_status": code,
            }
        retryable = code in {"3000", "429", "500", "503"}
        return {
            "status": "failed",
            "retryable": retryable,
            "failure_class": "provider_error" if code != "2007" else "provider_limit",
            "api_status": code,
        }
    retryable = http_status in TRANSIENT_HTTP or http_status is None
    return {
        "status": "failed",
        "retryable": retryable,
        "failure_class": "transport" if http_status is None else "http_error",
        "api_status": code,
        "error": error or f"HTTP {http_status}",
    }


def normalize_tianditu_record(record: Mapping[str, Any], raw_response: str, operation: str) -> dict[str, Any]:
    row = dict(record)
    if record.get("type") == "Feature" and isinstance(record.get("properties"), dict):
        row.update(record["properties"])
        row["source_geometry"] = record.get("geometry")
        try:
            geometry = shape(record["geometry"])
            if not geometry.is_empty:
                centroid = geometry.centroid
                row["lon"] = centroid.x
                row["lat"] = centroid.y
        except (TypeError, ValueError, KeyError):
            pass
    point: tuple[float, float] | None = None
    for key in ("lonlat", "location", "pointLonlat"):
        value = row.get(key)
        if isinstance(value, str) and "," in value:
            try:
                point = tuple(float(part) for part in value.split(",", 1))  # type: ignore[assignment]
            except ValueError:
                point = None
            if point:
                break
    if point is None and row.get("lon") is not None and row.get("lat") is not None:
        try:
            point = (float(row["lon"]), float(row["lat"]))
        except (TypeError, ValueError):
            point = None
    row["location_wgs84"] = list(point) if point else None
    row["coordinate_contract"] = COORDINATE_CONTRACT
    row["raw_response"] = raw_response
    row["operation"] = operation
    return row


def _text(record: Mapping[str, Any]) -> str:
    fields = (
        "name",
        "address",
        "formatted_address",
        "province",
        "city",
        "county",
        "district",
        "town",
        "townname",
        "adminName",
    )
    return "".join(str(record.get(field) or "") for field in fields)


def scope_bucket(record: Mapping[str, Any], boundary: Any, expanded: Any) -> tuple[str, dict[str, bool]]:
    point = record.get("location_wgs84")
    point_obj = Point(point[0], point[1]) if isinstance(point, list) and len(point) == 2 else None
    text = _text(record)
    city = "梅州市" in text or str(record.get("cityCode") or "") in {"0753", "441400"}
    county = "平远县" in text or str(record.get("countyCode") or "").startswith("441426")
    township = "泗水镇" in text or str(record.get("towncode") or "").startswith("441426108")
    project = bool(point_obj and boundary.covers(point_obj))
    expanded_match = bool(point_obj and expanded.covers(point_obj))
    if project:
        bucket = "project_local"
    elif expanded_match and (city or county or township or not text):
        bucket = "expanded_local"
    elif township:
        bucket = "township_local"
    elif county:
        bucket = "county_local"
    elif city:
        bucket = "meizhou_other"
    else:
        bucket = "outside_meizhou"
    return bucket, {
        "city": city,
        "county": county,
        "township": township,
        "project_boundary": project,
        "expanded_boundary": expanded_match,
    }


@dataclass(frozen=True)
class TiandituCollectorConfig:
    output_root: Path = OUTPUT_ROOT
    boundary_scope: Any | None = None
    scope_codes: Mapping[str, str] = field(
        default_factory=lambda: {
            "project": "金田村",
            "township": "泗水镇",
            "county": "平远县",
            "city": "梅州市",
        }
    )
    categories: tuple[str, ...] = DEFAULT_CATEGORIES
    max_retries: int = 4
    min_interval: float = 0.35
    timeout: float = 30.0
    page_size: int = MAX_SEARCH_COUNT
    max_polygon_vertices: int = MAX_POLYGON_VERTICES
    wfs_url: str = TD_WFS_URL


@dataclass(frozen=True)
class TiandituRequestJob:
    operation: str
    url: str
    params: Mapping[str, Any]
    scope: str = ""
    category: str = ""
    partition: str = ""
    coordinate_contract: str = COORDINATE_CONTRACT
    query_name: str = ""

    @property
    def key(self) -> str:
        return request_key(self.url, self.params)


def _job(
    operation: str,
    params: Mapping[str, Any],
    *,
    scope: str = "",
    category: str = "",
    partition: str = "",
    query_name: str = "",
    url: str = TD_SEARCH_URL,
) -> TiandituRequestJob:
    return TiandituRequestJob(operation, url, dict(params), scope, category, partition, query_name=query_name)


def _scope_bbox(context: Mapping[str, Any], scope: str) -> str:
    if scope == "expanded":
        return bbox_string(context["expanded_geometry_wgs84"].bounds)
    return bbox_string(context["bbox_wgs84"])


def build_admin_jobs(context: Mapping[str, Any], config: TiandituCollectorConfig) -> list[TiandituRequestJob]:
    jobs: list[TiandituRequestJob] = []
    for address in ("广东省梅州市平远县泗水镇金田村", "广东省梅州市平远县泗水镇"):
        jobs.append(
            _job(
                "td_geocode_admin",
                {"ds": td_poststr({"keyWord": address})},
                query_name=address,
                url=TD_GEOCODER_URL,
            )
        )
    jobs.append(
        _job(
            "td_administrative_boundary",
            {"keyword": "广东省梅州市平远县泗水镇金田村", "extensions": "true"},
            scope="project",
            query_name="金田村行政边界",
            url=TD_ADMIN_URL,
        )
    )
    for scope, specify in config.scope_codes.items():
        for category in config.categories:
            jobs.append(
                _job(
                    "td_search_admin",
                    {
                        "keyWord": category,
                        "specify": specify,
                        "queryType": 12,
                        "start": 0,
                        "count": config.page_size,
                        "dataTypes": category,
                        "show": 2,
                    },
                    scope=scope,
                    category=category,
                    query_name=f"行政区划-{scope}-{category}",
                )
            )
            jobs.append(
                _job(
                    "td_search_stats",
                    {
                        "keyWord": category,
                        "specify": specify,
                        "queryType": 14,
                        "dataTypes": category,
                        "show": 2,
                    },
                    scope=scope,
                    category=category,
                    query_name=f"统计-{scope}-{category}",
                )
            )
    for scope, specify in (("project", config.scope_codes["project"]),):
        for partition_name, bounds in (("project_bbox_all", context["bbox_wgs84"]), ("expanded_bbox_all", context["expanded_geometry_wgs84"].bounds)):
            jobs.append(
                _job(
                    "td_search_category_all",
                    {
                        "specify": specify,
                        "mapBound": bbox_string(bounds),
                        "queryType": 13,
                        "start": 0,
                        "count": config.page_size,
                        "show": 2,
                    },
                    scope=scope,
                    category="__all__",
                    partition=partition_name,
                    query_name=f"无分类全要素-{partition_name}",
                )
            )
        for category in config.categories:
            for partition_name, bounds in (("project_bbox", context["bbox_wgs84"]), ("expanded_bbox", context["expanded_geometry_wgs84"].bounds)):
                common = {
                    "specify": specify,
                    "mapBound": bbox_string(bounds),
                    "start": 0,
                    "count": config.page_size,
                    "dataTypes": category,
                    "show": 2,
                }
                jobs.append(
                    _job(
                        "td_search_category",
                        {**common, "queryType": 13},
                        scope=scope,
                        category=category,
                        partition=partition_name,
                        query_name=f"分类-{partition_name}-{category}",
                    )
                )
            for index, polygon in enumerate(polygon_chunks(context["boundary_geometry_wgs84"], config.max_polygon_vertices), 1):
                jobs.append(
                    _job(
                        "td_search_polygon",
                        {
                            "keyWord": category,
                            "polygon": polygon,
                            "queryType": 10,
                            "start": 0,
                            "count": config.page_size,
                            "dataTypes": category,
                            "show": 2,
                        },
                        scope=scope,
                        category=category,
                        partition=f"project_polygon_{index}",
                        query_name=f"多边形-{index}-{category}",
                    )
                )
            for query_type, label in ((1, "普通"), (2, "视野"), (7, "地名")):
                params: dict[str, Any] = {
                    "keyWord": category,
                    "queryType": query_type,
                    "mapBound": _scope_bbox(context, "project"),
                    "level": 12,
                    "start": 0,
                    "count": config.page_size,
                    "specify": specify,
                    "dataTypes": category,
                    "show": 2,
                }
                jobs.append(
                    _job(
                        f"td_search_{label}",
                        params,
                        scope=scope,
                        category=category,
                        partition="project_bbox",
                        query_name=f"{label}-金田村-{category}",
                    )
                )
    jobs.append(
        _job(
            "td_wfs_capabilities",
            {"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetCapabilities"},
            query_name="WFS能力发现",
            url=config.wfs_url,
        )
    )
    for index, point in enumerate(context.get("sample_points_wgs84", [])[:240], 1):
        jobs.append(
            _job(
                "td_reverse_geocode_probe",
                {"postStr": td_poststr({"lon": point[0], "lat": point[1], "ver": 1}), "type": "geocode"},
                scope="project",
                partition=f"sample_{index}",
                query_name=f"边界网格逆地理-{index}",
                url=TD_GEOCODER_URL,
            )
        )
    origin = "116.044146,24.818629"
    destination = "116.029180,24.749940"
    for style in range(4):
        jobs.append(
            _job(
                "td_route_probe",
                {"postStr": td_poststr({"orig": origin, "dest": destination, "style": style}), "type": "search"},
                scope="project",
                partition=f"style_{style}",
                query_name=f"路线连通验证-{style}",
                url=f"{TD_BASE}/drive",
            )
        )
    return jobs


def build_l1_jobs(
    context: Mapping[str, Any],
    names: Iterable[Mapping[str, Any]],
    config: TiandituCollectorConfig,
) -> list[TiandituRequestJob]:
    jobs: list[TiandituRequestJob] = []
    local_scopes = ("project", "township", "county", "city")
    for item in names:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        full_address = f"广东省梅州市平远县泗水镇金田村{name}"
        for scope in local_scopes:
            specify = config.scope_codes[scope]
            if scope == "project":
                for area_name, area_geometry in (("project", context["boundary_geometry_wgs84"]), ("expanded", context["expanded_geometry_wgs84"])):
                    jobs.extend(
                        _job(
                            "td_l1_polygon",
                            {
                                "keyWord": name,
                                "polygon": polygon,
                                "queryType": 10,
                                "start": 0,
                                "count": config.page_size,
                                "show": 2,
                            },
                            scope=scope,
                            category=name,
                            partition=f"{area_name}_polygon_{index}",
                            query_name=f"L1多边形-{area_name}-{name}",
                        )
                        for index, polygon in enumerate(polygon_chunks(area_geometry, config.max_polygon_vertices), 1)
                    )
                bounds = (context["bbox_wgs84"], context["expanded_geometry_wgs84"].bounds)
            else:
                bounds = None
            if bounds is not None:
                for area_index, area_bounds in enumerate(bounds, 1):
                    for query_type, label in ((7, "place"), (1, "normal"), (2, "view")):
                        jobs.append(
                            _job(
                                f"td_l1_{label}",
                                {
                                    "keyWord": name,
                                    "queryType": query_type,
                                    "level": 12,
                                    "mapBound": bbox_string(area_bounds),
                                    "specify": specify,
                                    "start": 0,
                                    "count": config.page_size,
                                    "show": 2,
                                },
                                scope=scope,
                                category=name,
                                partition=f"{scope}_bbox_{area_index}",
                                query_name=f"L1-{label}-{scope}-{area_index}-{name}",
                            )
                        )
            else:
                jobs.append(
                    _job(
                        "td_l1_admin",
                        {
                            "keyWord": name,
                            "specify": specify,
                            "queryType": 12,
                            "start": 0,
                            "count": config.page_size,
                            "show": 2,
                        },
                        scope=scope,
                        category=name,
                        partition=f"{scope}_admin",
                        query_name=f"L1行政-{scope}-{name}",
                    )
                )
        jobs.append(
            _job(
                "td_l1_geocode",
                {"ds": td_poststr({"keyWord": full_address})},
                scope="project",
                category=name,
                query_name=f"L1地理编码-{name}",
                url=TD_GEOCODER_URL,
            )
        )
    return jobs


@dataclass
class RequestResult:
    job: TiandituRequestJob
    status: str
    payload: Any
    raw_response: str | None
    cache_hit: bool
    attempts: int
    retryable: bool
    failure_class: str | None
    http_status: int | None
    api_status: str | None
    error: str | None


class CacheStore:
    def __init__(self, stage_dir: Path) -> None:
        self.stage_dir = stage_dir
        self.cache_dir = stage_dir / "cache"
        self.raw_dir = stage_dir / "raw_responses"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _pointer_paths(self, key: str) -> list[Path]:
        return [self.cache_dir / f"{key}.json"]

    def load(self, key: str) -> dict[str, Any] | None:
        for pointer_path in self._pointer_paths(key):
            if not pointer_path.exists():
                continue
            try:
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                raw_ref = pointer.get("raw_response")
                raw_path = Path(raw_ref) if raw_ref and Path(raw_ref).is_absolute() else PROJECT_ROOT / str(raw_ref)
                if raw_path.exists():
                    return json.loads(raw_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
        return None

    def write(self, key: str, envelope: Mapping[str, Any]) -> str:
        raw_path = self.raw_dir / f"{key}.json"
        raw_ref = path_reference(raw_path)
        stored = dict(envelope)
        stored["raw_response"] = raw_ref
        write_json(raw_path, stored)
        pointer = {"request_key": key, "raw_response": raw_ref, "status": envelope["status"]}
        write_json(self.cache_dir / f"{key}.json", pointer)
        return pointer["raw_response"]


class TiandituTransport:
    def __init__(
        self,
        config: TiandituCollectorConfig,
        stage_dir: Path,
        *,
        refresh: bool = False,
        session: requests.Session | None = None,
        api_key: str | None = None,
    ) -> None:
        self.config = config
        self.refresh = refresh
        self.session = session or requests.Session()
        self.api_key = api_key if api_key is not None else os.getenv("TIANDITU_API_KEY", "")
        self.last_request = 0.0
        self.store = CacheStore(stage_dir)
        self.attempt_rows: list[dict[str, Any]] = []

    def request(self, job: TiandituRequestJob, run_dir: Path) -> RequestResult:
        key = job.key
        cached = None if self.refresh else self.store.load(key)
        if cached:
            return RequestResult(
                job,
                cached.get("status", "failed"),
                cached.get("response_json", {}),
                cached.get("raw_response"),
                True,
                int(cached.get("attempts", 0)),
                bool(cached.get("retryable", False)),
                cached.get("failure_class"),
                cached.get("http_status"),
                cached.get("api_status"),
                cached.get("error"),
            )
        if not self.api_key:
            envelope = {
                "status": "failed",
                "retryable": False,
                "failure_class": "missing_credential",
                "error": "TIANDITU_API_KEY 未配置",
                "response_json": {},
                "http_status": None,
                "api_status": None,
                "attempts": 0,
                "url": job.url,
                "params": sanitized_params(job.params),
                "coordinate_contract": job.coordinate_contract,
            }
            raw_ref = self.store.write(key, envelope)
            return RequestResult(job, "failed", {}, raw_ref, False, 0, False, "missing_credential", None, None, envelope["error"])

        payload: Any = {}
        http_status: int | None = None
        error: str | None = None
        result_meta: dict[str, Any] = {}
        attempts = 0
        for attempt in range(1, self.config.max_retries + 1):
            attempts = attempt
            wait = self.config.min_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            request_params = dict(job.params)
            request_params["tk"] = self.api_key
            try:
                response = self.session.get(
                    job.url,
                    params=request_params,
                    timeout=self.config.timeout,
                    headers={"User-Agent": "VillagePlanningAgent/TiandituFullCollector", "Accept": "application/json, application/xml"},
                )
                self.last_request = time.monotonic()
                http_status = response.status_code
                try:
                    payload = response.json()
                except ValueError:
                    payload = {"_raw_text": response.text}
                classified = classify_tianditu_response(http_status, payload)
                result_meta = classified
                attempt_row = {
                    "request_key": key,
                    "operation": job.operation,
                    "attempt": attempt,
                    "http_status": http_status,
                    "api_status": classified.get("api_status"),
                    "status": classified["status"],
                    "retryable": classified["retryable"],
                    "failure_class": classified.get("failure_class"),
                }
                self.attempt_rows.append(attempt_row)
                append_jsonl(run_dir / "attempts.jsonl", attempt_row)
                if classified["status"] != "failed":
                    error = None
                    break
                error = classified.get("error") or classified.get("failure_class")
                if not classified["retryable"]:
                    break
            except requests.RequestException as exc:
                self.last_request = time.monotonic()
                error = f"{type(exc).__name__}: {exc}"
                result_meta = {"status": "failed", "retryable": True, "failure_class": "transport", "api_status": None}
                attempt_row = {
                    "request_key": key,
                    "operation": job.operation,
                    "attempt": attempt,
                    "http_status": None,
                    "api_status": None,
                    "status": "failed",
                    "retryable": True,
                    "failure_class": "transport",
                    "error": error,
                }
                self.attempt_rows.append(attempt_row)
                append_jsonl(run_dir / "attempts.jsonl", attempt_row)
            if attempt < self.config.max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))
        result_meta = result_meta or classify_tianditu_response(http_status, payload, error)
        envelope = {
            "provider": "tianditu",
            "operation": job.operation,
            "url": job.url,
            "params": sanitized_params(job.params),
            "coordinate_contract": job.coordinate_contract,
            "status": result_meta["status"],
            "retryable": result_meta.get("retryable", False),
            "failure_class": result_meta.get("failure_class"),
            "error": error,
            "http_status": http_status,
            "api_status": result_meta.get("api_status"),
            "attempts": attempts,
            "response_json": compact(payload),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        raw_ref = self.store.write(key, envelope)
        return RequestResult(
            job,
            envelope["status"],
            payload,
            raw_ref,
            False,
            attempts,
            bool(envelope["retryable"]),
            envelope["failure_class"],
            http_status,
            envelope["api_status"],
            error,
        )


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _local_wfs_layers(payload: Any) -> list[str]:
    text = payload.get("_raw_text", "") if isinstance(payload, dict) else ""
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    names: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag == "name" and element.text and element.text.strip() not in names:
            names.append(element.text.strip())
    return [name for name in names if ":" in name or name.startswith("TDT")]


class TiandituFullCollector:
    def __init__(self, config: TiandituCollectorConfig, *, refresh: bool = False, dry_run: bool = False) -> None:
        self.config = config
        self.refresh = refresh
        self.dry_run = dry_run
        self.context = load_admin_boundary_context(
            boundary_scope=self.config.boundary_scope
        )
        self.boundary = self.context["boundary_geometry_wgs84"]
        self.expanded = self.context["expanded_geometry_wgs84"]
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.records: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.coverage: list[dict[str, Any]] = []
        self.lease_store = ProviderRunLeaseStore(self.config.output_root.parent)
        self.lease = self.lease_store.acquire(
            self.run_id,
            "tianditu",
            f"pid-{os.getpid()}",
            ttl_seconds=3600,
        )

    def _stage_paths(self, stage: str) -> tuple[Path, Path]:
        stage_dir = self.config.output_root / stage
        run_dir = stage_dir / "runs" / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return stage_dir, run_dir

    def _add_result(self, result: RequestResult, run_dir: Path) -> None:
        self.lease_store.assert_writer(self.lease)
        event = {
            "provider": "tianditu",
            "operation": result.job.operation,
            "query_name": result.job.query_name,
            "scope": result.job.scope,
            "category": result.job.category,
            "partition": result.job.partition,
            "url": result.job.url,
            "params": sanitized_params(result.job.params),
            "request_key": result.job.key,
            "status": result.status,
            "cache_hit": result.cache_hit,
            "attempted": not result.cache_hit or result.attempts > 0,
            "attempts": result.attempts,
            "retryable": result.retryable,
            "failure_class": result.failure_class,
            "http_status": result.http_status,
            "api_status": result.api_status,
            "error": result.error,
            "raw_response": result.raw_response,
            "coordinate_contract": result.job.coordinate_contract,
        }
        self.events.append(event)
        append_jsonl(run_dir / "requests.jsonl", event)
        for index, item in enumerate(_record_items(result.payload)):
            row = normalize_tianditu_record(item, result.raw_response or "", result.job.operation)
            bucket, match = scope_bucket(row, self.boundary, self.expanded)
            row.update(
                {
                    "provider": "tianditu",
                    "scope": result.job.scope,
                    "category": result.job.category,
                    "partition": result.job.partition,
                    "query_name": result.job.query_name,
                    "request_key": result.job.key,
                    "record_index": index,
                    "scope_bucket": bucket,
                    "admin_match": match,
                }
            )
            self.records.append(row)

        if result.job.operation in {"td_search_admin", "td_search_stats", "td_search_category", "td_search_category_all", "td_search_polygon", "td_l1_admin", "td_l1_place", "td_l1_normal", "td_l1_view", "td_l1_polygon"}:
            self.coverage.append(
                {
                    "request_key": result.job.key,
                    "scope": result.job.scope,
                    "category": result.job.category,
                    "partition": result.job.partition,
                    "status": result.status,
                    "provider_total": self._provider_total(result.payload),
                    "retrieved_records": len(_record_items(result.payload)),
                    "complete_within_documented_limit": result.status != "failed" and self._provider_total(result.payload) <= MAX_PROVIDER_TOTAL,
                }
            )

    @staticmethod
    def _provider_total(payload: Any) -> int:
        if not isinstance(payload, dict):
            return 0
        for source in (payload, payload.get("data") if isinstance(payload.get("data"), dict) else {}):
            value = source.get("count")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return len(_record_items(payload))

    def _expand_dynamic_jobs(self, result: RequestResult) -> list[TiandituRequestJob]:
        if result.job.operation == "td_wfs_feature" and result.status == "success_nonempty" and len(_record_items(result.payload)) >= 5000:
            bbox_value = str(result.job.params.get("BBOX", ""))
            try:
                min_lon, min_lat, max_lon, max_lat = (float(value) for value in bbox_value.split(","))
            except ValueError:
                return []
            mid_lon = (min_lon + max_lon) / 2
            mid_lat = (min_lat + max_lat) / 2
            tiles = (
                (min_lon, min_lat, mid_lon, mid_lat),
                (mid_lon, min_lat, max_lon, mid_lat),
                (min_lon, mid_lat, mid_lon, max_lat),
                (mid_lon, mid_lat, max_lon, max_lat),
            )
            return [
                replace(
                    result.job,
                    params={**result.job.params, "BBOX": bbox_string(tile)},
                    partition=f"{result.job.partition}_tile_{index}",
                )
                for index, tile in enumerate(tiles, 1)
            ]
        total = self._provider_total(result.payload)
        if result.status != "success_nonempty" or total <= self.config.page_size:
            return []
        if total > MAX_PROVIDER_TOTAL:
            # The official service reports overflow above 500.  Spatially
            # sharding is the only safe way to continue; the planner records
            # this as a derived coverage requirement in the manifest.
            if "mapBound" in result.job.params:
                min_lon, min_lat, max_lon, max_lat = (float(v) for v in str(result.job.params["mapBound"]).split(","))
                mid_lon = (min_lon + max_lon) / 2
                mid_lat = (min_lat + max_lat) / 2
                tiles = (
                    (min_lon, min_lat, mid_lon, mid_lat),
                    (mid_lon, min_lat, max_lon, mid_lat),
                    (min_lon, mid_lat, mid_lon, max_lat),
                    (mid_lon, mid_lat, max_lon, max_lat),
                )
                jobs: list[TiandituRequestJob] = []
                for index, tile in enumerate(tiles, 1):
                    params = dict(result.job.params)
                    params["mapBound"] = bbox_string(tile)
                    params["start"] = 0
                    jobs.append(replace(result.job, params=params, partition=f"{result.job.partition}_tile_{index}"))
                return jobs
            return []
        return [replace(result.job, params={**result.job.params, "start": offset}, partition=f"{result.job.partition}_page_{offset}") for offset in paginate_offsets(total, self.config.page_size) if offset > 0]

    def _run_jobs(self, jobs: list[TiandituRequestJob], stage_dir: Path, run_dir: Path) -> None:
        if self.dry_run:
            write_json(run_dir / "planned_jobs.json", [{"operation": job.operation, "scope": job.scope, "category": job.category, "partition": job.partition, "url": job.url, "params": sanitized_params(job.params)} for job in jobs])
            return
        transport = TiandituTransport(self.config, stage_dir, refresh=self.refresh)
        queue = list(jobs)
        seen = {job.key for job in queue}
        while queue:
            job = queue.pop(0)
            result = transport.request(job, run_dir)
            self._add_result(result, run_dir)
            for extra in self._expand_dynamic_jobs(result):
                if extra.key not in seen:
                    seen.add(extra.key)
                    queue.append(extra)
            if job.operation == "td_wfs_capabilities" and result.status == "success_nonempty":
                for layer in _local_wfs_layers(result.payload):
                    describe = replace(
                        job,
                        operation="td_wfs_describe",
                        params={"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "DescribeFeatureType", "TYPENAME": layer},
                        category=layer,
                        query_name=f"WFS字段-{layer}",
                    )
                    feature = replace(
                        job,
                        operation="td_wfs_feature",
                        params={"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature", "TYPENAME": layer, "BBOX": bbox_string(self.context["bbox_wgs84"]), "MAXFEATURES": 5000, "OUTPUTFORMAT": "application/json"},
                        category=layer,
                        query_name=f"WFS要素-{layer}",
                    )
                    for extra in (describe, feature):
                        if extra.key not in seen:
                            seen.add(extra.key)
                            queue.append(extra)
        write_jsonl(run_dir / "attempts_all.jsonl", transport.attempt_rows)

    def _finish(self, stage: str, run_dir: Path, manifest: dict[str, Any]) -> Path:
        self.lease_store.assert_writer(self.lease)
        deduped: dict[str, dict[str, Any]] = {}
        for row in self.records:
            point = row.get("location_wgs84") or []
            identity = "|".join(
                str(row.get(key) or "")
                for key in ("hotPointID", "id", "name", "address", "lonlat")
            )
            if not identity.strip("|"):
                identity = f"{row.get('request_key')}|{row.get('record_index')}"
            deduped.setdefault(identity, row)
        normalized = list(deduped.values())
        retained = [row for row in normalized if row["scope_bucket"] in {"project_local", "expanded_local", "township_local", "county_local", "meizhou_other"}]
        rejected = [row for row in normalized if row not in retained]
        for row in rejected:
            row["rejection_reasons"] = [row.get("scope_bucket", "unknown_scope")]
        published_dir = ProviderObservationWriter(
            self.config.output_root.parent,
            "tianditu",
            self.run_id,
            stage=stage,
        ).publish(
            self.lease,
            normalized,
            boundary_digest=str(self.context.get("boundary_digest") or ""),
            query_geometry_digest=str(self.context.get("query_geometry_digest") or ""),
            crs_contract=COORDINATE_CONTRACT,
            coverage={
                "coverage_status": "COMPLETE" if not any(event.get("status") == "failed" for event in self.events) else "PARTIAL",
                "request_count": len(self.events),
            },
        )
        published_manifest = json.loads((published_dir / "manifest.json").read_text(encoding="utf-8"))
        write_jsonl(run_dir / "retained_candidates.jsonl", retained)
        write_jsonl(run_dir / "rejected_candidates.jsonl", rejected)
        write_jsonl(run_dir / "coverage.jsonl", self.coverage)
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event["status"]] = counts.get(event["status"], 0) + 1
        buckets: dict[str, int] = {}
        for row in normalized:
            buckets[row["scope_bucket"]] = buckets.get(row["scope_bucket"], 0) + 1
        manifest.update(
            {
                "provider": "tianditu",
                "stage": stage,
                "run_id": self.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "refresh": self.refresh,
                "dry_run": self.dry_run,
                "request_count": len(self.events) if not self.dry_run else manifest.get("planned_job_count", 0),
                "status_counts": counts,
                "raw_response_directory": path_reference(self.config.output_root / stage / "raw_responses"),
                "cache_directory": path_reference(self.config.output_root / stage / "cache"),
                "normalized_record_count": len(normalized),
                "retained_candidate_count": len(retained),
                "rejected_record_count": len(rejected),
                "scope_bucket_counts": buckets,
                "coordinate_contract": COORDINATE_CONTRACT,
                "boundary_ref": self.context.get("boundary_ref", ""),
                "boundary_digest": self.context.get("boundary_digest", ""),
                "query_geometry_digest": self.context.get("query_geometry_digest", ""),
                "boundary_source_path": self.context.get("source_path", ""),
                "provider_coordinate_contract": COORDINATE_CONTRACT,
                "provider_acquisition_plan": self.context.get("provider_acquisition_plans", {}).get("tianditu", {}),
                "provider_limits": {"search_count_max": MAX_SEARCH_COUNT, "search_total_overflow": MAX_PROVIDER_TOTAL, "polygon_vertices_max": self.config.max_polygon_vertices},
                "coverage_summary": {"partial_or_overflow": sum(item["status"] == "failed" or not item["complete_within_documented_limit"] for item in self.coverage)},
            }
        )
        manifest = {**published_manifest, **manifest}
        write_json(run_dir / "manifest.json", manifest)
        write_json(
            run_dir / "query_plan.json",
            self.context.get("provider_acquisition_plans", {}).get("tianditu", {}),
        )
        self.lease_store.release(self.lease)
        return run_dir

    def collect(self, stage: str) -> Path:
        stage_dir, run_dir = self._stage_paths(stage)
        if stage == "01_admin_scope":
            jobs = build_admin_jobs(self.context, self.config)
            manifest = {"purpose": "Tianditu documented administrative and spatial baseline", "scope": dict(self.config.scope_codes), "planned_job_count": len(jobs)}
        else:
            _, blob_path, _, payload = load_latest_l1()
            names, excluded = collect_l1_place_names(payload)
            write_json(run_dir / "l1_place_names.json", names)
            write_json(run_dir / "l1_excluded_names.json", excluded)
            jobs = build_l1_jobs(self.context, names, self.config)
            manifest = {"purpose": "Tianditu L1 place-name retrieval with tiered Meizhou-only scope", "scope": dict(self.config.scope_codes), "l1_source": path_reference(blob_path), "place_like_name_count": len(names), "excluded_non_place_count": len(excluded), "planned_job_count": len(jobs)}
        self._run_jobs(jobs, stage_dir, run_dir)
        return self._finish(stage, run_dir, manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("admin", "l1", "all"), default="all")
    parser.add_argument("--refresh", action="store_true", help="重试并重新请求已有成功缓存")
    parser.add_argument("--dry-run", action="store_true", help="只生成请求计划，不调用网络")
    parser.add_argument("--min-interval", type=float, default=0.35)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--boundary-artifact-root", type=Path, help="CAS root containing an admitted BoundaryScopeArtifact")
    parser.add_argument("--boundary-run-id", help="DATA admission run id whose named boundary scope is used")
    parser.add_argument("--boundary-branch-id", default="main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
    config = TiandituCollectorConfig(output_root=args.output_root, min_interval=args.min_interval, max_retries=args.max_retries, boundary_scope=boundary_scope)
    stages = ("01_admin_scope", "02_l1_place_names") if args.stage == "all" else (("01_admin_scope",) if args.stage == "admin" else ("02_l1_place_names",))
    for stage in stages:
        collector = TiandituFullCollector(config, refresh=args.refresh, dry_run=args.dry_run)
        print(collector.collect(stage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
