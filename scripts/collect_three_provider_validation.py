"""Collect auditable AMap, Tianditu and Tencent evidence for Jintian.

The collector is intentionally independent from production Data/KG/GROUND.
It has two axes of isolation::

    data/cache/map_observations/<provider>/<stage>/

Every attempted request writes an attempt record and a full raw response.
Successful empty responses, unsupported capabilities, skipped requests, and
transport/provider failures use separate auditable states; retryable failures
are retried with bounded backoff.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
from dotenv import load_dotenv
from shapely.geometry import Point, shape


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_amap_jintian_validation import (
    AmapJintianCollector,
    ADMIN_SCOPE,
    PLACE_TYPE_SHARDS,
    ScopeClassifier,
    collect_l1_place_names,
    gcj02_to_wgs84,
    load_admin_boundary_context,
    load_latest_l1,
    wgs84_to_gcj02,
    write_json,
    write_jsonl,
)
from app.data.boundary_scope import load_boundary_scope_artifact
from app.data.catalog.provider_run_lease import ProviderObservationWriter, ProviderRunLeaseStore


OUTPUT_ROOT = PROJECT_ROOT / "data" / "cache" / "map_observations"
AMAP_V3 = "https://restapi.amap.com/v3"
AMAP_V5 = "https://restapi.amap.com/v5"
TD_BASE = "https://api.tianditu.gov.cn"
TD_WFS = "http://gisserver.tianditu.gov.cn/TDTService/wfs"
TX_BASE = "https://apis.map.qq.com/ws"
PAGE_SIZE = 20
MAX_PAGES = 15
MAX_RETRIES = 4
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
DETAIL_FIELDS = "children,business,indoor,navi,photos"


def compact(value: Any, limit: int = 1600) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    if isinstance(value, list):
        return [compact(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: compact(item, limit) for key, item in value.items()}
    return value


def normalized_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in {"key", "tk", "sig"}}


def request_key(url: str, params: dict[str, Any]) -> str:
    material = json.dumps(
        {"url": url, "params": normalized_params(params)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def as_location(record: dict[str, Any], provider: str) -> tuple[float, float] | None:
    value = record.get("location")
    if provider == "tencent" and isinstance(value, dict):
        try:
            return float(value["lng"]), float(value["lat"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, str) and "," in value:
        try:
            lon, lat = (float(part) for part in value.split(",", 1))
            return lon, lat
        except ValueError:
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    if "lon" in record and "lat" in record:
        try:
            return float(record["lon"]), float(record["lat"])
        except (TypeError, ValueError):
            return None
    return None


def normalize_point_record(record: dict[str, Any], provider: str) -> dict[str, Any]:
    row = dict(record)
    point = as_location(record, provider)
    if point is None:
        row["location_wgs84"] = None
        row["location_crs"] = "unknown"
        return row
    if provider == "amap":
        row["location_gcj02"] = [point[0], point[1]]
        wgs = gcj02_to_wgs84(*point)
        row["location_wgs84"] = [wgs[0], wgs[1]]
        row["location_crs"] = "GCJ-02"
    else:
        row["location_wgs84"] = [point[0], point[1]]
        row["location_crs"] = "WGS84-compatible"
    return row


def response_items(payload: Any, provider: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    keys = ("pois", "tips", "geocodes", "districts", "features", "data", "roads", "roadinters")
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if provider == "tianditu" and isinstance(payload.get("data"), dict):
        data = payload["data"]
        for key in ("poi", "pois", "district"):
            if isinstance(data.get(key), list):
                return [item for item in data[key] if isinstance(item, dict)]
    if provider == "tencent" and isinstance(payload.get("result"), dict):
        data = payload["result"].get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return [payload] if payload else []


def provider_success(provider: str, payload: Any, http_status: int | None) -> bool:
    if http_status != 200 or not isinstance(payload, dict):
        return False
    if provider == "amap":
        return str(payload.get("status")) == "1" and str(payload.get("infocode", "10000")) in {"", "10000"}
    if provider == "tencent":
        return payload.get("status") == 0
    status = payload.get("status")
    if isinstance(status, dict):
        return status.get("infocode") == 1000
    return status in {None, 0, "0", 200, "200"}


def is_transient_api_error(provider: str, payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    text = json.dumps(payload, ensure_ascii=False)
    return any(token in text.lower() for token in ("timeout", "tempor", "rate limit", "too many", "gateway", "服务繁忙"))


def classify_response(provider: str, attempted: bool, http_status: int | None, payload: Any, error: str | None = None) -> dict[str, Any]:
    """Classify an attempted operation without conflating empty and failed."""

    if not attempted:
        return {"status": "missing", "failure": None, "retryable": False}
    success = provider_success(provider, payload, http_status)
    if success:
        return {"status": "success_nonempty" if response_items(payload, provider) else "missing", "failure": None, "retryable": False}
    retryable = http_status in TRANSIENT_HTTP or is_transient_api_error(provider, payload) or bool(error and any(token in error.lower() for token in ("timeout", "connection", "ssl", "proxy")))
    return {"status": "failed", "failure": error or "provider_error", "retryable": retryable}


class ValidationCollector:
    def __init__(
        self,
        provider: str,
        stage: str,
        refresh: bool,
        min_interval: float,
        *,
        root: Path | None = None,
        boundary_context: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.stage = stage
        self.refresh = refresh
        self.min_interval = min_interval
        output_root = root or OUTPUT_ROOT
        self.stage_dir = output_root / provider / stage
        self.cache_dir = self.stage_dir / "cache"
        self.raw_dir = self.stage_dir / "raw_responses"
        self.boundary_context = dict(boundary_context or {})
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.run_dir = self.stage_dir / "runs" / self.run_id
        self.events: list[dict[str, Any]] = []
        self.records: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.last_request = 0.0
        self.session = requests.Session()
        self.api_key = self._get_api_key()
        self.lease_store = ProviderRunLeaseStore(output_root)
        self.lease = self.lease_store.acquire(
            self.run_id,
            self.provider,
            f"pid-{os.getpid()}",
            ttl_seconds=3600,
        )

    def _get_api_key(self) -> str:
        if self.provider == "amap":
            return os.getenv("AMAP_API_KEY", "")
        if self.provider == "tianditu":
            return os.getenv("TIANDITU_API_KEY", "")
        return os.getenv("TECENT_MAP_API_KEY", os.getenv("TENCENT_MAP_API_KEY", ""))

    def _credential_name(self) -> str:
        return {"amap": "AMAP_API_KEY", "tianditu": "TIANDITU_API_KEY", "tencent": "TECENT_MAP_API_KEY"}[self.provider]

    def request(
        self,
        operation: str,
        url: str,
        params: dict[str, Any],
        coordinate_contract: str,
        unsupported_reason: str | None = None,
        query_name: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        self.lease_store.assert_writer(self.lease)
        sanitized = normalized_params(params)
        key = request_key(url, sanitized)
        cache_path = self.cache_dir / f"{key}.json"
        raw_path = self.raw_dir / f"{key}.json"
        if unsupported_reason:
            event = self._event(operation, url, sanitized, key, "missing", False, None, None, None, unsupported_reason, coordinate_contract, query_name=query_name)
            self._append_event(event)
            return {}, event
        cached_path = cache_path
        if cached_path is not None and cached_path.exists() and not self.refresh:
            pointer = json.loads(cached_path.read_text(encoding="utf-8"))
            envelope = json.loads((PROJECT_ROOT / pointer["raw_response"]).read_text(encoding="utf-8"))
            reusable_failure = envelope.get("status") == "failed" and envelope.get("retryable") is False
            if envelope.get("status") in {"success_nonempty", "success_empty", "missing"} or reusable_failure:
                event = self._event(operation, url, sanitized, key, envelope["status"], True, envelope.get("http_status"), envelope.get("api_status"), envelope.get("record_count"), envelope.get("error"), coordinate_contract, pointer["raw_response"], query_name=query_name)
                self._append_event(event)
                self._add_records(key, operation, event, envelope.get("response_json") or {})
                return envelope.get("response_json") or {}, event

        if not self.api_key:
            error = f"{self._credential_name()} 未配置"
            event = self._event(operation, url, sanitized, key, "failed", False, None, None, 0, error, coordinate_contract, query_name=query_name)
            self._append_event(event)
            return {}, event

        final_payload: Any = {}
        final_http: int | None = None
        final_error: str | None = None
        retry_count = 0
        for attempt in range(1, MAX_RETRIES + 1):
            wait = self.min_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            request_params = dict(sanitized)
            request_params["key" if self.provider in {"amap", "tencent"} else "tk"] = self.api_key
            try:
                response = self.session.get(url, params=request_params, timeout=30, headers={"User-Agent": "VillagePlanningAgent/validation", "Accept": "application/json"})
                self.last_request = time.monotonic()
                final_http = response.status_code
                try:
                    final_payload = response.json()
                except ValueError:
                    final_payload = {"_raw_text": response.text}
                api_ok = provider_success(self.provider, final_payload, final_http)
                transient = final_http in TRANSIENT_HTTP or is_transient_api_error(self.provider, final_payload)
                attempt_error = None if api_ok else f"HTTP {final_http}" if final_http != 200 else "provider_error"
                attempt_row = {"provider": self.provider, "stage": self.stage, "operation": operation, "request_key": key, "attempt": attempt, "http_status": final_http, "success": api_ok, "retryable": transient, "error": attempt_error}
                self.attempts.append(attempt_row)
                append_jsonl(self.run_dir / "attempts.jsonl", attempt_row)
                if api_ok:
                    final_error = None
                    break
                final_error = attempt_error
                if not transient and attempt >= 2:
                    break
            except requests.RequestException as exc:
                self.last_request = time.monotonic()
                final_error = f"{type(exc).__name__}: {exc}"
                retry_count = attempt
                attempt_row = {"provider": self.provider, "stage": self.stage, "operation": operation, "request_key": key, "attempt": attempt, "http_status": None, "success": False, "retryable": True, "error": final_error}
                self.attempts.append(attempt_row)
                append_jsonl(self.run_dir / "attempts.jsonl", attempt_row)
            if attempt < MAX_RETRIES:
                retry_count = attempt
                time.sleep(min(2 ** (attempt - 1), 8))
        api_ok = provider_success(self.provider, final_payload, final_http)
        items = response_items(final_payload, self.provider) if api_ok else []
        status = "success_nonempty" if items else "success_empty" if api_ok else "failed"
        if status == "success_empty":
            status = "missing"
        retryable_failure = status == "failed" and not (
            final_http in {400, 401, 403, 404, 413, 414, 422}
            or str(final_payload.get("infocode")) == "10012"
        )
        envelope = {
            "provider": self.provider,
            "stage": self.stage,
            "operation": operation,
            "url": url,
            "params": sanitized,
            "coordinate_contract": coordinate_contract,
            "status": status,
            "attempted": True,
            "retry_count": retry_count,
            "http_status": final_http,
            "api_status": final_payload.get("status") if isinstance(final_payload, dict) else None,
            "record_count": len(items),
            "error": final_error,
            "retryable": retryable_failure,
            "response_json": final_payload,
        }
        write_json(raw_path, envelope)
        write_json(cache_path, {"raw_response": str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "request_key": key, "status": status})
        event = self._event(operation, url, sanitized, key, status, False, final_http, envelope["api_status"], len(items), final_error, coordinate_contract, str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), retry_count, query_name=query_name)
        self._append_event(event)
        self._add_records(key, operation, event, final_payload)
        return final_payload, event

    def _add_records(self, key: str, operation: str, event: dict[str, Any], payload: Any) -> None:
        for index, item in enumerate(response_items(payload, self.provider)):
            row = normalize_point_record(item, self.provider)
            row.update({"provider": self.provider, "stage": self.stage, "operation": operation, "query_name": event.get("query_name"), "request_key": key, "raw_response": event.get("raw_response"), "record_index": index})
            self.records.append(row)

    def _event(self, operation: str, url: str, params: dict[str, Any], key: str, status: str, cache_hit: bool, http_status: int | None, api_status: Any, record_count: int | None, error: str | None, coordinate_contract: str, raw_response: str | None = None, retry_count: int = 0, query_name: str | None = None) -> dict[str, Any]:
        return {"provider": self.provider, "stage": self.stage, "operation": operation, "query_name": query_name, "url": url, "params": params, "request_key": key, "status": status, "cache_hit": cache_hit, "attempted": status != "missing" or raw_response is not None, "retry_count": retry_count, "http_status": http_status, "api_status": api_status, "record_count": record_count or 0, "error": error, "coordinate_contract": coordinate_contract, "raw_response": raw_response}

    def _append_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        append_jsonl(self.run_dir / "requests.jsonl", event)

    def finish(self, manifest: dict[str, Any], classifier: ScopeClassifier) -> Path:
        self.lease_store.assert_writer(self.lease)
        normalized: list[dict[str, Any]] = []
        retained: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for row in self.records:
            row = classify_scope_row(row, classifier.boundary_wgs84)
            row["retained"] = row.get("scope_bucket") in {"project_local", "township_local", "county_local"}
            if row["retained"]:
                retained.append(row)
            else:
                row["rejection_reasons"] = [row.get("scope_bucket", "unknown_scope")]
                rejected.append(row)
            normalized.append(row)
        ProviderObservationWriter(
            self.stage_dir.parent.parent,
            self.provider,
            self.run_id,
            stage=self.stage,
        ).publish(
            self.lease,
            normalized,
            boundary_digest=str(self.boundary_context.get("boundary_digest") or ""),
            query_geometry_digest=str(self.boundary_context.get("query_geometry_digest") or ""),
            crs_contract="source=provider; target=EPSG:4326; transform=declared",
            coverage={
                "coverage_status": "COMPLETE" if self._coverage_status() == "complete" else "PARTIAL",
                "request_count": len(self.events),
            },
        )
        write_jsonl(self.run_dir / "retained_candidates.jsonl", retained)
        write_jsonl(self.run_dir / "rejected_candidates.jsonl", rejected)
        bucket_counts: dict[str, int] = {}
        for row in normalized:
            bucket = str(row.get("scope_bucket", "unknown_scope"))
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        manifest.update({
            "provider": self.provider,
            "stage": self.stage,
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "refresh": self.refresh,
            "request_count": len(self.events),
            "successful_nonempty": sum(event["status"] == "success_nonempty" for event in self.events),
            "missing": sum(event["status"] == "missing" for event in self.events),
            "failed": sum(event["status"] == "failed" for event in self.events),
            "cache_hits": sum(event["cache_hit"] for event in self.events),
            "raw_response_directory": str(self.raw_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "cache_directory": str(self.cache_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "normalized_record_count": len(normalized),
            "retained_candidate_count": len(retained),
            "rejected_record_count": len(rejected),
            "scope_bucket_counts": bucket_counts,
            "coordinate_contract": {"amap": "request/response GCJ-02; local checks WGS84", "tencent": "lat,lng request order; coord_type=wgs84; normalized lon,lat", "tianditu": "documented lon,lat / CGCS2000-WGS84-compatible"},
            "boundary_ref": self.boundary_context.get("boundary_ref", ""),
            "boundary_digest": self.boundary_context.get("boundary_digest", ""),
            "query_geometry_digest": self.boundary_context.get("query_geometry_digest", ""),
            "boundary_source_path": self.boundary_context.get("source_path", ""),
            "coverage_status": self._coverage_status(),
            "coverage": {
                "request_count": len(self.events),
                "successful_nonempty": sum(event["status"] == "success_nonempty" for event in self.events),
                "successful_empty": sum(event["status"] == "success_empty" for event in self.events),
                "missing": sum(event["status"] in {"missing", "not_attempted", "missing_capability"} for event in self.events),
                "failed": sum(event["status"] == "failed" for event in self.events),
                "filtered_out_of_scope": len(rejected),
                "complete_within_recorded_plan": self._coverage_status() == "complete",
            },
            "provider_acquisition_plan": self.boundary_context.get("provider_acquisition_plans", {}).get(self.provider, {}),
        })
        write_json(self.run_dir / "manifest.json", manifest)
        write_json(
            self.run_dir / "query_plan.json",
            self.boundary_context.get("provider_acquisition_plans", {}).get(self.provider, {}),
        )
        self.lease_store.release(self.lease)
        return self.run_dir

    def _coverage_status(self) -> str:
        statuses = {str(event.get("status") or "") for event in self.events}
        if "failed" in statuses:
            return "partial_failed" if len(statuses - {"failed"}) else "failed"
        if statuses & {"missing", "not_attempted", "missing_capability"}:
            return "partial_missing"
        return "complete"


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def td_poststr(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def classify_scope_row(row: dict[str, Any], boundary: Any) -> dict[str, Any]:
    text = "".join(str(row.get(key, "")) for key in ("province", "city", "cityname", "district", "adname", "county", "town", "townname", "address", "formatted_address", "name"))
    city_match = "梅州市" in text or str(row.get("citycode", "")) in {"0753", "441400"}
    county_match = "平远县" in text or str(row.get("adcode", "")).startswith("441426") or str(row.get("countyCode", "")).startswith("441426")
    town_match = "泗水镇" in text or str(row.get("towncode", "")).startswith("441426108")
    point = row.get("location_wgs84")
    project_match = bool(point and boundary.covers(Point(point[0], point[1])))
    if project_match or county_match or town_match:
        city_match = True
    if not city_match:
        bucket = "outside_meizhou"
    elif project_match:
        bucket = "project_local"
    elif town_match:
        bucket = "township_local"
    elif county_match:
        bucket = "county_local"
    else:
        bucket = "meizhou_other"
    row["scope_bucket"] = bucket
    row["admin_match"] = {"city": city_match, "county": county_match, "township": town_match, "project_boundary": project_match}
    return row


def polygon_wgs84_string(context: dict[str, Any]) -> str:
    geometry = context["boundary_geometry_wgs84"]
    parts = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
    return ";".join(",".join(f"{lon:.6f},{lat:.6f}" for lon, lat in part.exterior.coords) for part in parts)


def gcj_point(lon: float, lat: float) -> str:
    glon, glat = wgs84_to_gcj02(lon, lat)
    return f"{glon:.6f},{glat:.6f}"


def td_search(collector: ValidationCollector, query_name: str, payload: dict[str, Any]) -> None:
    collector.request("td_search", f"{TD_BASE}/v2/search", {"postStr": td_poststr(payload), "type": "query"}, "Tianditu lon/lat; local checks WGS84", query_name=query_name)


def amap_page_search(collector: ValidationCollector, query_name: str, params: dict[str, Any], around: bool = False) -> None:
    url = f"{AMAP_V5}/place/around" if around else f"{AMAP_V5}/place/text"
    for page in range(1, MAX_PAGES + 1):
        page_params = {**params, "page_size": 25, "page_num": page, "show_fields": DETAIL_FIELDS}
        data, event = collector.request("amap_poi_around" if around else "amap_poi_text", url, page_params, "AMap GCJ-02; local checks WGS84", query_name=query_name)
        if event["status"] != "success_nonempty" or len(data.get("pois") or []) < 25:
            break


def detail_top_ids(collector: ValidationCollector, boundary: Any, limit: int = 100) -> None:
    ids: list[str] = []
    for row in collector.records:
        row = classify_scope_row(row, boundary)
        if row.get("provider") == "amap" and row.get("scope_bucket") in {"project_local", "township_local", "county_local"}:
            poi_id = str(row.get("id") or "")
            if poi_id and poi_id not in ids:
                ids.append(poi_id)
    for batch_start in range(0, min(len(ids), limit), 10):
        batch = ids[batch_start:batch_start + 10]
        collector.request("amap_poi_detail", f"{AMAP_V5}/place/detail", {"id": ",".join(batch), "show_fields": DETAIL_FIELDS, "langCode": "zh"}, "AMap response GCJ-02; local checks WGS84", query_name="行政阶段Top-K POI详情")


def run_amap_admin(collector: ValidationCollector, context: dict[str, Any]) -> None:
    anchor_wgs = (116.044146, 24.818629)
    for address in ("广东省梅州市平远县泗水镇金田村", "广东省梅州市平远县泗水镇"):
        collector.request("amap_geocode", f"{AMAP_V3}/geocode/geo", {"address": address, "city": "441400"}, "AMap response GCJ-02; local checks WGS84", query_name=address)
    collector.request("amap_district_tree", f"{AMAP_V3}/config/district", {"keywords": "441400", "subdistrict": "3", "extensions": "all"}, "AMap response GCJ-02; local checks WGS84", query_name="梅州市行政树")
    for scope_name, polygons in (("project", context["polygon_strings_gcj02"]), ("expanded", context["expanded_polygon_strings_gcj02"])):
        for index, polygon in enumerate(polygons, 1):
            for shard, types in PLACE_TYPE_SHARDS.items():
                amap_page_search(collector, f"金田村-{scope_name}-polygon-{index}-{shard}", {"polygon": polygon, "types": types}, False)
    for radius in (3000, 10000):
        for shard, types in PLACE_TYPE_SHARDS.items():
            amap_page_search(collector, f"金田村-around-{radius}-{shard}", {"location": gcj_point(*anchor_wgs), "radius": radius, "types": types, "sortrule": "distance"}, True)
    for index, point in enumerate(context["sample_points_gcj02"], 1):
        collector.request("amap_regeo_boundary", f"{AMAP_V3}/geocode/regeo", {"location": f"{point[0]:.6f},{point[1]:.6f}", "extensions": "all", "roadlevel": "0", "radius": "300"}, "AMap request/response GCJ-02; local checks WGS84", query_name=f"边界采样-{index}")
    for mode in ("driving", "walking", "bicycling", "electrobike"):
        collector.request("amap_route_admin", f"{AMAP_V5}/direction/{mode}", {"origin": gcj_point(*anchor_wgs), "destination": gcj_point(116.029180, 24.749940), "alternative_route": "3", "show_fields": "cost,polyline,tmcs,navi"}, "AMap request/response GCJ-02; local checks WGS84", query_name=f"行政锚点-{mode}")
    detail_top_ids(collector, context["boundary_geometry_wgs84"])


def run_tianditu_admin(collector: ValidationCollector, context: dict[str, Any]) -> None:
    bbox = context["bbox_wgs84"]
    polygon = polygon_wgs84_string(context)
    for address in ("广东省梅州市平远县泗水镇金田村", "广东省梅州市平远县泗水镇"):
        collector.request("tianditu_geocode", f"{TD_BASE}/geocoder", {"ds": td_poststr({"keyWord": address})}, "Tianditu lon/lat; local checks WGS84", query_name=address)
    collector.request("tianditu_admin", f"{TD_BASE}/v2/administrative", {"keyword": "广东省梅州市平远县泗水镇金田村", "extensions": "true"}, "Tianditu lon/lat; local checks WGS84", query_name="金田村行政边界")
    for query_type, label in ((12, "行政区"), (1, "普通"), (7, "地名"), (10, "多边形"), (13, "分类"), (14, "统计")):
        if query_type in {13, 14}:
            payload = {"queryType": query_type, "start": 0, "count": 300, "specify": "平远县", "dataTypes": "公园"}
            if query_type == 14:
                payload["keyWord"] = "公园"
        else:
            payload = {"keyWord": "村", "queryType": query_type, "start": 0, "count": 300, "mapBound": ",".join(map(str, bbox))}
        if query_type in {1, 7}:
            payload["level"] = 12
        if query_type in {12, 13, 14}:
            payload["specify"] = "平远县"
        if query_type == 10:
            payload["polygon"] = polygon
        td_search(collector, f"天地图-{label}", payload)
    for layer in ("TDTService:HYDA", "TDTService:HYDL", "TDTService:LRDL", "TDTService:RESA", "TDTService:RESP"):
        collector.request("tianditu_wfs", TD_WFS, {"SERVICE": "WFS", "VERSION": "1.0.0", "REQUEST": "GetFeature", "TYPENAME": layer, "MAXFEATURES": 5000, "BBOX": ",".join(map(str, bbox)), "OUTPUTFORMAT": "application/json"}, "Tianditu WFS documented CRS/GeoJSON; local checks WGS84", query_name=layer)
    for point in context["sample_points_wgs84"][:240]:
        collector.request("tianditu_regeo", f"{TD_BASE}/geocoder", {"postStr": td_poststr({"lon": point[0], "lat": point[1], "ver": 1}), "type": "geocode"}, "Tianditu lon/lat; local checks WGS84", query_name="边界及网格采样")
    for route_type in (0, 1, 2, 3):
        collector.request("tianditu_route", f"{TD_BASE}/drive", {"postStr": td_poststr({"orig": "116.044146,24.818629", "dest": "116.029180,24.749940", "style": str(route_type)}), "type": "search"}, "Tianditu lon/lat; local checks WGS84", query_name=f"行政锚点路线-{route_type}")


def run_tencent_admin(collector: ValidationCollector, context: dict[str, Any]) -> None:
    bbox = context["bbox_wgs84"]
    anchor = (116.044146, 24.818629)
    for address in ("广东省梅州市平远县泗水镇金田村", "广东省梅州市平远县泗水镇"):
        collector.request("tencent_geocode", f"{TX_BASE}/geocoder/v1", {"address": address, "output": "json", "callback": ""}, "Tencent coord_type=wgs84; request lat,lng", query_name=address)
    for query in ("梅州市", "平远县", "泗水镇", "金田村"):
        for page in range(1, 16):
            params = {"keyword": query, "boundary": f"region({query},0,{anchor[1]},{anchor[0]})", "page_size": 20, "page_index": page, "coord_type": "wgs84"}
            _, event = collector.request("tencent_region_search", f"{TX_BASE}/place/v1/search", params, "Tencent coord_type=wgs84; request lat,lng", query_name=query)
            if event["status"] != "success_nonempty" or event["record_count"] < 20:
                break
    for keyword in ("村", "学校", "医院", "公交站", "村委会", "道路", "河", "公园", "停车场"):
        collector.request("tencent_suggestion", f"{TX_BASE}/place/v1/suggestion", {"keyword": keyword, "region": "梅州市", "location": f"{anchor[1]},{anchor[0]}"}, "Tencent coord_type=wgs84; request lat,lng", query_name=keyword)
        for index, (lon, lat) in enumerate(_grid_points(bbox, 1000), 1):
            boundary = f"nearby({lat},{lon},1000,0)"
            collector.request("tencent_nearby", f"{TX_BASE}/place/v1/search", {"keyword": keyword, "boundary": boundary, "page_size": 20, "page_index": 1, "coord_type": "wgs84", "orderby": "_distance"}, "Tencent coord_type=wgs84; request lat,lng", query_name=f"{keyword}-网格-{index}")
    collector.request("tencent_rectangle", f"{TX_BASE}/place/v1/search", {"keyword": "村", "boundary": f"rectangle({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]})", "page_size": 20, "page_index": 1, "coord_type": "wgs84"}, "Tencent coord_type=wgs84; request lat,lng", query_name="金田村矩形范围")
    for route in ("driving", "walking", "bicycling"):
        collector.request("tencent_route", f"{TX_BASE}/direction/v1/{route}/", {"from": f"{anchor[1]},{anchor[0]}", "to": "24.749940,116.029180", "output": "json"}, "Tencent coord_type=wgs84; request lat,lng", query_name=f"行政锚点路线-{route}")
    collector.request("tencent_poi_detail", f"{TX_BASE}/place/v1/detail", {}, "Tencent documented public detail capability not confirmed", unsupported_reason="当前仓库/官方 WebService 文档未确认通用 POI detail 端点")


def _grid_points(bbox: list[float], step_m: float) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_step = step_m / 111000.0
    lon_step = step_m / max(1.0, 111000.0 * abs(math.cos(math.radians((min_lat + max_lat) / 2))))
    points: list[tuple[float, float]] = []
    lon = min_lon
    while lon <= max_lon + 1e-9:
        lat = min_lat
        while lat <= max_lat + 1e-9:
            points.append((lon, lat))
            lat += lat_step
        lon += lon_step
    return points


def run_l1_provider(collector: ValidationCollector, context: dict[str, Any]) -> dict[str, Any]:
    ref_path, blob_path, descriptor, payload = load_latest_l1()
    names, excluded = collect_l1_place_names(payload)
    write_json(collector.run_dir / "l1_place_names.json", names)
    write_json(collector.run_dir / "l1_excluded_names.json", excluded)
    polygon = polygon_wgs84_string(context)
    anchor = (116.044146, 24.818629)
    for item in names:
        name = item["name"]
        if collector.provider == "amap":
            collector.request("amap_l1_inputtips", f"{AMAP_V3}/assistant/inputtips", {"keywords": name, "city": "441400", "citylimit": "true", "datatype": "all", "location": gcj_point(*anchor)}, "AMap request/response GCJ-02; local checks WGS84", query_name=name)
            amap_page_search(collector, name, {"keywords": name, "region": "441400", "city_limit": "true"})
            collector.request("amap_l1_geocode", f"{AMAP_V3}/geocode/geo", {"address": f"广东省梅州市平远县泗水镇金田村{name}", "city": "441400"}, "AMap request/response GCJ-02; local checks WGS84", query_name=name)
        elif collector.provider == "tianditu":
            td_search(collector, name, {"keyWord": name, "queryType": 7, "level": 12, "start": 0, "count": 300, "mapBound": ",".join(map(str, context["bbox_wgs84"]))})
            td_search(collector, name, {"keyWord": name, "queryType": 10, "start": 0, "count": 300, "polygon": polygon})
            collector.request("tianditu_l1_geocode", f"{TD_BASE}/geocoder", {"ds": td_poststr({"keyWord": f"广东省梅州市平远县泗水镇金田村{name}"})}, "Tianditu lon/lat; local checks WGS84", query_name=name)
        else:
            collector.request("tencent_l1_suggestion", f"{TX_BASE}/place/v1/suggestion", {"keyword": name, "region": "梅州市", "location": f"{anchor[1]},{anchor[0]}"}, "Tencent coord_type=wgs84; request lat,lng", query_name=name)
            for page in range(1, 16):
                _, event = collector.request("tencent_l1_region_search", f"{TX_BASE}/place/v1/search", {"keyword": name, "boundary": f"region(梅州市,0,{anchor[1]},{anchor[0]})", "page_size": 20, "page_index": page, "coord_type": "wgs84"}, "Tencent coord_type=wgs84; request lat,lng", query_name=name)
                if event["status"] != "success_nonempty" or event["record_count"] < 20:
                    break
            collector.request("tencent_l1_geocode", f"{TX_BASE}/geocoder/v1", {"address": f"广东省梅州市平远县泗水镇金田村{name}", "output": "json"}, "Tencent coord_type=wgs84; request lat,lng", query_name=name)
    return {
        "l1_source": {"ref_path": str(ref_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "blob_path": str(blob_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), "descriptor_digest": descriptor.get("digest"), "location_mentions_count": len(payload.get("location_mentions") or [])},
        "place_like_name_count": len(names),
        "excluded_non_place_count": len(excluded),
    }


def run(
    provider: str,
    stage: str,
    refresh: bool,
    min_interval: float,
    *,
    boundary_scope: Any | None = None,
) -> Path:
    if boundary_scope is None:
        raise ValueError("provider collection requires an admitted boundary_scope")
    if provider == "tianditu":
        from scripts.collect_tianditu_full import TiandituCollectorConfig, TiandituFullCollector

        full_stage = "01_admin_scope" if stage == "01_admin_scope" else "02_l1_place_names"
        config = TiandituCollectorConfig(
            min_interval=min_interval,
            boundary_scope=boundary_scope,
        )
        return TiandituFullCollector(config, refresh=refresh).collect(full_stage)
    if provider == "amap":
        canonical = AmapJintianCollector(
            refresh=refresh,
            min_interval=min_interval,
            root=OUTPUT_ROOT / "amap",
            expand_admin=True,
            boundary_scope=boundary_scope,
        )
        return canonical.collect(stage)
    context = load_admin_boundary_context(boundary_scope=boundary_scope)
    collector = ValidationCollector(
        provider,
        stage,
        refresh,
        min_interval,
        boundary_context=context,
    )
    if stage == "01_admin_scope":
        if provider == "amap":
            run_amap_admin(collector, context)
        elif provider == "tianditu":
            run_tianditu_admin(collector, context)
        else:
            run_tencent_admin(collector, context)
        manifest = {"purpose": "三 provider 行政基线：仅使用已知梅州市/平远县/泗水镇/金田村行政范围和本地边界几何", "scope": ADMIN_SCOPE, "expanded": True, "boundary_context": {key: value for key, value in context.items() if not key.endswith("_geometry_wgs84")}}
    else:
        l1_meta = run_l1_provider(collector, context)
        manifest = {"purpose": "三 provider L1 地名检索：使用最新有效 L1Snapshot，查询从项目范围逐级扩展至梅州市", "scope": ADMIN_SCOPE, **l1_meta}
    return collector.finish(manifest, ScopeClassifier(context["boundary_geometry_wgs84"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("amap", "tianditu", "tencent", "all"), default="all")
    parser.add_argument("--stage", choices=("admin", "l1", "all"), default="all")
    parser.add_argument("--refresh", action="store_true", help="显式重试成功缓存；失败响应默认下次自动重试")
    parser.add_argument("--min-interval", type=float, default=0.35)
    parser.add_argument("--boundary-artifact-root", type=Path, help="CAS root containing an admitted BoundaryScopeArtifact")
    parser.add_argument("--boundary-run-id", help="DATA admission run id whose named boundary scope is used")
    parser.add_argument("--boundary-branch-id", default="main")
    return parser.parse_args()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
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
    providers = ("amap", "tianditu", "tencent") if args.provider == "all" else (args.provider,)
    stages = ("01_admin_scope", "02_l1_place_names") if args.stage == "all" else ("01_admin_scope" if args.stage == "admin" else "02_l1_place_names",)
    for provider in providers:
        for stage in stages:
            print(run(provider, stage, args.refresh, args.min_interval, boundary_scope=boundary_scope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
