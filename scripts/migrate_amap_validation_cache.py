"""Migrate legacy AMap validation caches into the unified audit format.

This command is deliberately offline.  It reads the legacy request logs and
raw response envelopes, writes a new provider/stage projection, and never
constructs an HTTP client or calls an AMap endpoint.  Legacy failures remain
``failed``; successful empty responses remain ``missing``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.collect_amap_jintian_validation import (  # noqa: E402
    SCOPE_BUCKETS,
    candidate_quality,
    load_admin_boundary_context,
    normalize_name,
    write_json,
    write_jsonl,
)
from scripts.collect_three_provider_validation import (  # noqa: E402
    classify_scope_row,
    gcj02_to_wgs84,
    request_key,
)


LEGACY_ROOT = PROJECT_ROOT / "output" / "amap_validation"
UNIFIED_ROOT = PROJECT_ROOT / "output" / "map_validation" / "amap"
STAGES = ("01_admin_scope", "02_l1_place_names")
SUCCESS_STATUSES = {"1", "10000", "OK"}
SECRET_KEYS = {"key", "tk", "sig"}
SECRET_QUERY_RE = re.compile(r"([?&](?:key|tk|sig)=)[^&\s)]+", re.IGNORECASE)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def sanitized_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in SECRET_KEYS}


def scrub_secrets(value: Any) -> Any:
    if isinstance(value, str):
        return SECRET_QUERY_RE.sub(r"\1<redacted>", value)
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_secrets(item) for key, item in value.items() if key not in SECRET_KEYS}
    return value


def envelopes_from_file(path: Path) -> list[dict[str, Any]]:
    value = load_json(path)
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def raw_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    value = envelope.get("response_json")
    return value if isinstance(value, dict) else {}


def api_success(envelope: dict[str, Any]) -> bool:
    if envelope.get("error"):
        return False
    if envelope.get("http_status") != 200:
        return False
    payload = raw_payload(envelope)
    return str(payload.get("status")) in SUCCESS_STATUSES and str(payload.get("infocode", "10000")) in {"", "10000"}


def extract_records(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Flatten useful response records without discarding the raw payload."""

    records: list[tuple[str, dict[str, Any]]] = []
    for key in ("pois", "tips", "geocodes", "roads", "roadinters", "districts", "aois"):
        values = payload.get(key)
        if isinstance(values, list):
            records.extend((key, item) for item in values if isinstance(item, dict))

    regeocode = payload.get("regeocode")
    if isinstance(regeocode, dict):
        component = regeocode.get("addressComponent")
        if isinstance(component, dict):
            records.append(("regeo_address_component", {**component, "formatted_address": regeocode.get("formatted_address", "")}))
        for key in ("roads", "roadinters", "pois", "aois"):
            values = regeocode.get(key)
            if isinstance(values, list):
                records.extend((f"regeo_{key}", item) for item in values if isinstance(item, dict))

    route = payload.get("route")
    if isinstance(route, dict):
        paths = route.get("paths")
        if isinstance(paths, list):
            for path_index, path in enumerate(paths):
                if not isinstance(path, dict):
                    continue
                records.append(("route_path", {**path, "path_index": path_index}))
                steps = path.get("steps")
                if isinstance(steps, list):
                    records.extend(
                        ("route_step", {**step, "path_index": path_index, "step_index": step_index})
                        for step_index, step in enumerate(steps)
                        if isinstance(step, dict)
                    )

    if not records:
        metadata = {
            "status",
            "info",
            "infocode",
            "count",
            "message",
            "pois",
            "tips",
            "geocodes",
            "roads",
            "roadinters",
            "districts",
            "aois",
        }
        meaningful_keys = set(payload) - metadata
        if meaningful_keys or str(payload.get("count", "")) not in {"", "0"}:
            records.append(("response_summary", payload))

    return records


def infer_query_name(event: dict[str, Any], normalized_names: dict[str, str]) -> str | None:
    request_key_value = str(event.get("request_key") or "")
    if normalized_names.get(request_key_value):
        return normalized_names[request_key_value]
    params = event.get("params") or {}
    for key in ("keywords", "address", "keyword"):
        if params.get(key):
            return str(params[key])
    return None


def source_run_index(stage_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, dict[str, str]]]:
    events_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_meta: dict[str, dict[str, Any]] = {}
    normalized_names: dict[str, dict[str, str]] = defaultdict(dict)
    for run_dir in sorted((stage_dir / "runs").glob("*")):
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "manifest.json"
        manifest = load_json(manifest_path) if manifest_path.exists() else {}
        run_meta[run_dir.name] = {
            "complete": manifest_path.exists(),
            "manifest": manifest,
            "source_run": run_dir.name,
        }
        for event in read_jsonl(run_dir / "requests.jsonl"):
            key = str(event.get("request_key") or "")
            if key:
                events_by_key[key].append({**event, "source_run": run_dir.name})
        for row in read_jsonl(run_dir / "normalized.jsonl"):
            key = str(row.get("request_key") or "")
            name = row.get("query_name")
            if key and name:
                normalized_names[run_dir.name][key] = str(name)
    return events_by_key, run_meta, normalized_names


def status_for(envelope: dict[str, Any], record_count: int) -> tuple[str, str | None]:
    if api_success(envelope):
        return ("success_nonempty", None) if record_count else ("missing", None)
    payload = raw_payload(envelope)
    info = payload.get("info") or payload.get("message") or envelope.get("error") or "legacy_provider_error"
    return "failed", str(scrub_secrets(info))


def failure_retryable(envelope: dict[str, Any]) -> bool:
    """Allow future retries for transient failures, not stable request failures."""

    http_status = envelope.get("http_status")
    payload = raw_payload(envelope)
    infocode = str(payload.get("infocode") or "")
    info = str(payload.get("info") or "").upper()
    error = str(envelope.get("error") or "").lower()
    if http_status in {400, 401, 403, 404, 413, 414, 422}:
        return False
    if infocode in {"10012"} or "INSUFFICIENT_PRIVILEGES" in info:
        return False
    if any(token in error for token in ("proxy", "ssl", "timeout", "connection", "tempor")):
        return True
    return True


def normalize_amap_record(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    location = record.get("location")
    if isinstance(location, str) and "," in location:
        try:
            lon, lat = (float(part) for part in location.split(",", 1))
        except ValueError:
            pass
        else:
            wgs_lon, wgs_lat = gcj02_to_wgs84(lon, lat)
            row["location_gcj02"] = [lon, lat]
            row["location_wgs84"] = [wgs_lon, wgs_lat]
            row["location_crs"] = "GCJ-02"
    if "location_wgs84" not in row:
        row["location_wgs84"] = None
        row["location_crs"] = "unknown"
    return row


def migration_request(
    stage: str,
    key: str,
    envelope: dict[str, Any],
    source_events: list[dict[str, Any]],
    normalized_names: dict[str, str],
    raw_ref: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    request = envelope.get("request") or {}
    url = str(request.get("url") or "")
    params = sanitized_params(request.get("params") or {})
    operation = str(request.get("operation") or (source_events[0].get("operation") if source_events else "legacy_unknown"))
    records = extract_records(raw_payload(envelope))
    status, error = status_for(envelope, len(records))
    source_runs = sorted({str(event.get("source_run")) for event in source_events if event.get("source_run")})
    query_name = infer_query_name(source_events[0] if source_events else {"params": params, "request_key": key}, normalized_names)
    retryable = failure_retryable(envelope) if status == "failed" else False
    event = {
        "provider": "amap",
        "stage": stage,
        "operation": operation,
        "query_name": query_name,
        "url": url,
        "params": params,
        "request_key": key,
        "status": status,
        "cache_hit": True,
        "cache_origin": "legacy_amap_validation",
        "attempted": True,
        "retry_count": None,
        "legacy_attempt_count": None,
        "legacy_attempt_history_available": False,
        "http_status": envelope.get("http_status"),
        "api_status": raw_payload(envelope).get("status"),
        "api_infocode": raw_payload(envelope).get("infocode"),
        "record_count": len(records),
        "error": error,
        "retryable": retryable,
        "coordinate_contract": "request/response GCJ-02; local checks WGS84",
        "raw_response": raw_ref,
        "source_runs": source_runs,
        "source_run_complete": all(bool(event.get("complete")) for event in source_events) if source_events else False,
    }
    attempt = {
        "provider": "amap",
        "stage": stage,
        "operation": operation,
        "request_key": key,
        "attempt": None,
        "attempt_source": "legacy_final_response_observation",
        "retry_history_available": False,
        "http_status": envelope.get("http_status"),
        "success": status == "success_nonempty" or (status == "missing" and api_success(envelope)),
        "status": status,
        "error": error,
        "retryable": retryable,
    }
    return event, [attempt]


def candidate_rows(
    stage: str,
    request_events: list[dict[str, Any]],
    raw_by_key: dict[str, dict[str, Any]],
    raw_refs: dict[str, str],
    boundary: Any,
    query_roles: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    for event in request_events:
        if event["status"] != "success_nonempty":
            continue
        key = event["request_key"]
        payload = raw_payload(raw_by_key[key])
        extracted = extract_records(payload)
        for index, (record_kind, raw_record) in enumerate(extracted):
            row = normalize_amap_record(raw_record)
            row = classify_scope_row(row, boundary)
            query_name = event.get("query_name")
            role = query_roles.get(str(query_name))
            score, flags = candidate_quality(row, query_name, role)
            row.update(
                {
                    "provider": "amap",
                    "stage": stage,
                    "record_kind": record_kind,
                    "query_name": query_name,
                    "request_key": key,
                    "raw_response": raw_refs[key],
                    "record_index": index,
                    "poi_id": raw_record.get("id"),
                    "quality_score": score,
                    "quality_flags": flags,
                    "retained": False,
                }
            )
            all_rows.append(row)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for row in all_rows:
        bucket = row.get("scope_bucket")
        if bucket not in {"project_local", "township_local", "county_local"}:
            row["rejection_reasons"] = [str(bucket or "unknown_scope")]
            rejected.append(row)
            continue
        if "parent_fallback" in row.get("quality_flags", []):
            row["rejection_reasons"] = ["parent_fallback"]
            rejected.append(row)
            continue
        grouped[str(row.get("query_name") or "__unscoped__")].append(row)

    retained: list[dict[str, Any]] = []
    for query_name, rows in grouped.items():
        rows.sort(key=lambda item: (-int(item.get("quality_score", -100)), str(item.get("poi_id") or item.get("name") or "")))
        chosen = rows[:20] if query_name != "__unscoped__" else rows[:20]
        for row in chosen:
            row["retained"] = True
            retained.append(row)
        for row in rows[len(chosen) :]:
            row["rejection_reasons"] = ["top_k_overflow"]
            rejected.append(row)
    return all_rows, retained + rejected


def migrate_stage(stage: str, migration_run_id: str) -> dict[str, Any]:
    legacy_stage = LEGACY_ROOT / stage
    stage_dir = UNIFIED_ROOT / stage
    run_dir = stage_dir / "runs" / migration_run_id
    cache_dir = stage_dir / "cache"
    raw_dir = stage_dir / "raw_responses"
    run_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    events_by_key, run_meta, normalized_names_by_run = source_run_index(legacy_stage)
    normalized_names: dict[str, str] = {}
    for names in normalized_names_by_run.values():
        normalized_names.update(names)

    source_files = sorted((legacy_stage / "responses").glob("*.json"))
    raw_by_key: dict[str, dict[str, Any]] = {}
    raw_refs: dict[str, str] = {}
    source_file_count = 0
    malformed_files: list[str] = []
    for source_file in source_files:
        envelopes = envelopes_from_file(source_file)
        if not envelopes:
            malformed_files.append(str(source_file.relative_to(PROJECT_ROOT)).replace("\\", "/"))
            continue
        for envelope in envelopes:
            request = envelope.get("request") or {}
            url = str(request.get("url") or "")
            params = sanitized_params(request.get("params") or {})
            key = request_key(url, params)
            if not key:
                malformed_files.append(str(source_file.relative_to(PROJECT_ROOT)).replace("\\", "/"))
                continue
            if key not in raw_by_key:
                raw_by_key[key] = envelope
                target = raw_dir / f"{key}.json"
                raw_ref = str(target.relative_to(PROJECT_ROOT)).replace("\\", "/")
                migrated = scrub_secrets(envelope)
                record_count = len(extract_records(raw_payload(envelope)))
                migrated_status, migrated_error = status_for(envelope, record_count)
                migrated.update(
                    {
                        "provider": "amap",
                        "stage": stage,
                        "url": url,
                        "params": params,
                        "coordinate_contract": "request/response GCJ-02; local checks WGS84",
                        "status": migrated_status,
                        "attempted": True,
                        "retry_count": None,
                        "api_status": raw_payload(envelope).get("status"),
                        "api_infocode": raw_payload(envelope).get("infocode"),
                        "record_count": record_count,
                        "legacy_error": scrub_secrets(envelope.get("error")),
                        "error": migrated_error,
                        "retryable": failure_retryable(envelope) if migrated_status == "failed" else False,
                    }
                )
                migrated["migration"] = {
                    "source_stage": stage,
                    "source_file": str(source_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "source_request_key": str(envelope.get("request", {}).get("request_key") or ""),
                    "api_calls_during_migration": 0,
                }
                write_json(target, migrated)
                write_json(cache_dir / f"{key}.json", {"raw_response": raw_ref, "request_key": key, "status": migrated_status, "retryable": migrated.get("retryable", False), "cache_origin": "legacy_amap_validation"})
                raw_refs[key] = raw_ref
                source_file_count += 1

    boundary = load_admin_boundary_context()["boundary_geometry_wgs84"]
    migration_events: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for key in sorted(raw_by_key):
        source_events = []
        for source_event in events_by_key.get(key, []):
            source_event = dict(source_event)
            source_event["complete"] = bool(run_meta.get(str(source_event.get("source_run")), {}).get("complete"))
            source_events.append(source_event)
        event, event_attempts = migration_request(
            stage,
            key,
            raw_by_key[key],
            source_events,
            normalized_names,
            raw_refs[key],
        )
        migration_events.append(event)
        attempts.extend(event_attempts)
        write_json(cache_dir / f"{key}.json", {"raw_response": raw_refs[key], "request_key": key, "status": event["status"], "retryable": event["retryable"], "cache_origin": "legacy_amap_validation"})

    query_roles: dict[str, str] = {}
    if stage == "02_l1_place_names":
        l1_path = legacy_stage / "runs" / "20260828T085421Z" / "l1_place_names.json"
        if l1_path.exists():
            for item in load_json(l1_path):
                if isinstance(item, dict):
                    roles = item.get("roles") or []
                    if roles:
                        query_roles[str(item.get("name"))] = str(roles[0])
    all_rows, retained_plus_rejected = candidate_rows(stage, migration_events, raw_by_key, raw_refs, boundary, query_roles)
    retained = [row for row in retained_plus_rejected if row.get("retained")]
    rejected = [row for row in retained_plus_rejected if not row.get("retained")]
    write_jsonl(run_dir / "requests.jsonl", migration_events)
    write_jsonl(run_dir / "attempts.jsonl", attempts)
    write_jsonl(run_dir / "normalized_all.jsonl", all_rows)
    write_jsonl(run_dir / "retained_candidates.jsonl", retained)
    write_jsonl(run_dir / "rejected_candidates.jsonl", rejected)

    bucket_counts = {bucket: 0 for bucket in SCOPE_BUCKETS}
    for row in all_rows:
        bucket = str(row.get("scope_bucket", "unknown_scope"))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    status_counts = {status: sum(event["status"] == status for event in migration_events) for status in ("success_nonempty", "missing", "failed")}
    operation_status: dict[str, dict[str, int]] = {}
    for event in migration_events:
        operation_status.setdefault(event["operation"], {status: 0 for status in ("success_nonempty", "missing", "failed")})
        operation_status[event["operation"]][event["status"]] += 1
    source_runs = []
    for run_id, metadata in sorted(run_meta.items()):
        manifest = metadata.get("manifest") or {}
        source_runs.append({
            "run_id": run_id,
            "complete": metadata["complete"],
            "request_count": manifest.get("request_count"),
            "successful_requests": manifest.get("successful_requests"),
            "failed_requests": manifest.get("failed_requests"),
        })
    manifest = {
        "provider": "amap",
        "stage": stage,
        "run_id": migration_run_id,
        "run_kind": "offline_legacy_cache_migration",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_calls": 0,
        "refresh": False,
        "request_count": len(migration_events),
        "successful_nonempty": status_counts["success_nonempty"],
        "missing": status_counts["missing"],
        "failed": status_counts["failed"],
        "cache_hits": len(migration_events),
        "legacy_response_file_count": len(source_files),
        "migrated_response_count": source_file_count,
        "malformed_source_files": malformed_files,
        "source_runs": source_runs,
        "raw_response_directory": str(raw_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "cache_directory": str(cache_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "normalized_record_count": len(all_rows),
        "retained_candidate_count": len(retained),
        "rejected_record_count": len(rejected),
        "scope_bucket_counts": bucket_counts,
        "operation_status": operation_status,
        "coordinate_contract": "legacy AMap location is GCJ-02; converted exactly once to location_wgs84 for local checks",
        "failure_missing_contract": "failed means attempted provider/API failure; missing means successful empty response",
    }
    write_json(run_dir / "scope_summary.json", {"scope_bucket_counts": bucket_counts, "top_k": {"per_query": 20}})
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline migration of legacy AMap validation caches")
    parser.add_argument("--run-id", default="legacy-migration-20260828")
    parser.add_argument("--stage", choices=STAGES, action="append")
    args = parser.parse_args()
    selected = args.stage or list(STAGES)
    reports = {stage: migrate_stage(stage, args.run_id) for stage in selected}
    report = {
        "run_kind": "offline_legacy_cache_migration",
        "api_calls": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stages": reports,
        "policy": {
            "no_network": True,
            "failed_preserved_as_failed": True,
            "successful_empty_preserved_as_missing": True,
            "incomplete_source_runs_not_marked_complete": True,
            "response_json_payload_unchanged": True,
        },
        "gaps_not_retried": [
            "new unified requests absent from legacy cache",
            "legacy per-request retry history unavailable",
            "public AMap basemap label enumeration",
        ],
    }
    write_json(UNIFIED_ROOT / "migration_report.json", report)
    print(json.dumps({"api_calls": 0, "stages": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
