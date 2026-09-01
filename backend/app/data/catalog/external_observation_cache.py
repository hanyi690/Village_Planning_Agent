"""Read-only loader for already collected AMap/Tianditu/Tencent caches.

This module intentionally has no HTTP/provider imports.  It turns normalized
JSONL records into provenance-bearing observations used by Evidence and
Cognition; it never mutates a VillageBundle or creates planning geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable

from pydantic import ValidationError

from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
    canonical_external_observation_payload,
    has_explicit_wgs84_direct_contract,
    is_wgs84_equivalent_crs,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "output" / "map_validation"
DEFAULT_PROVIDERS = ("amap", "tianditu", "tencent")
DEFAULT_STAGES = ("01_admin_scope", "02_l1_place_names")
DEFAULT_SCOPES = frozenset({"project_local", "township_local", "county_local"})

_ADMIN_FIELDS: dict[str, tuple[str, ...]] = {
    "province": ("province", "province_name", "pname"),
    "city": ("city", "city_name", "cityname"),
    "county": ("county", "county_name", "district", "adname"),
    "township": ("township", "town", "town_name", "township_name"),
    "village": ("village", "village_name"),
}


def _admin_token(value: Any) -> str:
    text = "".join(str(value or "").casefold().split())
    for suffix in (
        "特别行政区",
        "壮族自治区",
        "回族自治区",
        "维吾尔自治区",
        "自治区",
        "自治州",
        "自治县",
        "街道办事处",
        "街道",
        "地区",
        "省",
        "市",
        "县",
        "区",
        "镇",
        "乡",
        "村",
    ):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _admin_name_matches(observed: Any, expected: Any) -> bool:
    left = _admin_token(observed)
    right = _admin_token(expected)
    return bool(left and right and (left == right or left in right or right in left))


def _row_values(row: Mapping[str, Any], keys: Iterable[str]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = row.get(key)
        candidates = value if isinstance(value, (list, tuple, set)) else (value,)
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                values.append(text)
    return values


def _location_pair(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        try:
            longitude = value.get("lng")
            if longitude is None:
                longitude = value["lon"]
            pair = (
                float(longitude),
                float(value["lat"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
    elif isinstance(value, str) and "," in value:
        try:
            left, right = value.split(",", 1)
            pair = (float(left.strip()), float(right.strip()))
        except ValueError:
            return None
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            pair = (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not all(math.isfinite(value) for value in pair):
        return None
    return pair


def _validate_row_coordinates(row: Mapping[str, Any]) -> None:
    for key in ("location_wgs84", "location_gcj02", "location", "lonlat"):
        if key in row and row.get(key) is not None and _location_pair(row.get(key)) is None:
            raise ValueError(f"invalid coordinate field: {key}")


def _text_contract(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(
            str(item or "").strip()
            for item in value.values()
            if str(item or "").strip()
        )
    return str(value or "").strip()


def _first_text(row: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _coordinate_provenance(
    provider: str,
    row: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify coordinates only from an explicit, provider-compatible contract."""

    manifest = manifest or {}
    provider_name = str(provider or "").casefold()
    wgs84 = _location_pair(row.get("location_wgs84"))
    native = (
        _location_pair(row.get("location_gcj02"))
        or _location_pair(row.get("location"))
        or _location_pair(row.get("lonlat"))
    )
    row_contract = _text_contract(
        row.get("coordinate_contract")
        or row.get("coordinate_transform_contract")
        or row.get("location_crs")
        or row.get("crs")
    )
    manifest_contract_value = manifest.get("coordinate_contract")
    manifest_contract = ""
    if isinstance(manifest_contract_value, Mapping):
        manifest_contract = _text_contract(manifest_contract_value.get(provider_name))
    else:
        manifest_contract = _text_contract(manifest_contract_value)
    transform = _first_text(row, ("coordinate_transform", "crs_transform"))
    declaration = " ".join(
        value for value in (row_contract, manifest_contract, transform) if value
    )
    declaration_folded = declaration.casefold()
    source_crs = _first_text(row, ("coordinate_source_crs", "source_crs", "location_crs", "crs"))
    target_crs = _first_text(row, ("coordinate_target_crs", "target_crs"))
    if source_crs.casefold() in {"unknown", "none", "n/a"}:
        source_crs = ""
    if target_crs.casefold() in {"unknown", "none", "n/a"}:
        target_crs = ""
    explicit_trust = _first_text(row, ("coordinate_trust_status",))
    if explicit_trust in {"unverified", "missing"}:
        trust = explicit_trust
    else:
        source_folded = source_crs.casefold()
        is_gcj = "gcj-02" in source_folded or "gcj02" in source_folded
        declares_wgs84 = "wgs84" in declaration_folded or "wgs-84" in declaration_folded
        declares_conversion = bool(
            transform
            or any(
                token in declaration_folded
                for token in ("convert", "transformed", "converted", "一次", "normalized")
            )
        )
        target_is_wgs84 = not target_crs or is_wgs84_equivalent_crs(target_crs)
        bad_target = (
            (bool(target_crs) and not target_is_wgs84)
            or "epsg:3857" in declaration_folded
            or "epsg3857" in declaration_folded
            or "3857" in declaration_folded
        )
        # AMap's cache is transformed only when both source/target material and
        # the conversion contract are present.  A location_wgs84 key alone is
        # never evidence of a trustworthy transform.
        if provider_name == "amap" and wgs84 is not None and native is not None and is_gcj and declares_wgs84 and declares_conversion and target_is_wgs84 and not bad_target:
            trust = "verified_transformed"
            source_crs = source_crs or "GCJ-02"
            target_crs = target_crs or "WGS84"
            transform = transform or declaration
        # Tencent's manifest explicitly records coord_type=wgs84.  Tianditu's
        # current manifest says WGS84-compatible, which is not a conversion
        # contract and therefore cannot authorize spatial support.
        elif wgs84 is not None and not bad_target and (
            (
                row_contract
                and has_explicit_wgs84_direct_contract(row_contract)
                and is_wgs84_equivalent_crs(source_crs or "WGS84")
            )
            or (
                provider_name == "tencent"
                and "coord_type=wgs84" in declaration_folded
                and "lat,lng" in declaration_folded
                and "lon,lat" in declaration_folded
            )
        ):
            trust = "verified_direct"
            source_crs = source_crs or "WGS84"
            target_crs = target_crs or "WGS84"
        elif wgs84 is not None or native is not None:
            trust = "unverified"
        else:
            trust = "missing"
    if trust == "verified_transformed":
        source_crs = source_crs or "GCJ-02"
        target_crs = target_crs or "WGS84"
    elif trust == "verified_direct":
        source_crs = source_crs or "WGS84"
        target_crs = target_crs or "WGS84"
        transform = transform or "identity"
    return {
        "wgs84": wgs84,
        "native": native,
        "contract": declaration or "unknown",
        "source_crs": source_crs,
        "target_crs": target_crs,
        "transform": transform,
        "trust_status": trust,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _observation_times(
    row: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run_metadata: Mapping[str, Any],
) -> dict[str, datetime | None]:
    return {
        "observed_at": _parse_datetime(row.get("observed_at")),
        "collected_at": _parse_datetime(row.get("collected_at")),
        "provider_timestamp": _parse_datetime(
            row.get("provider_timestamp") or row.get("provider_time") or row.get("timestamp")
        ),
        "run_created_at": _parse_datetime(
            manifest.get("created_at") or run_metadata.get("run_created_at")
        ),
    }


def _row_scope_filter_reason(
    row: Mapping[str, Any],
    *,
    administrative_scope: Mapping[str, str],
    project_bbox_wgs84: tuple[float, float, float, float] | None,
    provider: str = "",
    manifest: Mapping[str, Any] | None = None,
) -> str:
    """Return an exclusion reason for a cache row outside this session.

    ``scope_bucket`` was computed by the collection run and is not a portable
    project identity.  Re-check the persisted administrative strings and the
    current DATA boundary so a cache collected for one village cannot be
    silently relabelled and consumed by another session.
    """

    scope_bucket = str(row.get("scope_bucket") or "unknown_scope")
    broad_text = _row_values(
        row,
        (
            "name",
            "title",
            "address",
            "query_name",
            "region",
            "pname",
            "cityname",
            "adname",
            "province",
            "city",
            "county",
            "district",
            "township",
            "town",
            "village",
        ),
    )
    for level in ("province", "city", "county"):
        expected = str(administrative_scope.get(level) or "").strip()
        if not expected:
            if level == "county" and scope_bucket == "county_local":
                return "administrative_scope_missing"
            continue
        explicit = _row_values(row, _ADMIN_FIELDS[level])
        if explicit and not all(_admin_name_matches(value, expected) for value in explicit):
            return f"admin_conflict_{level}"
        text_verified = bool(explicit) or any(
            _admin_name_matches(value, expected) for value in broad_text
        )
        if not text_verified:
            return f"admin_unverified_{level}"

    township = str(administrative_scope.get("township") or "").strip()
    if scope_bucket in {"township_local", "project_local"}:
        if not township and scope_bucket == "township_local":
            return "administrative_scope_missing"
        if not township:
            township = ""
        if not township:
            township_verified = True
        else:
            explicit_township = _row_values(row, _ADMIN_FIELDS["township"])
            if explicit_township and not all(
                _admin_name_matches(value, township) for value in explicit_township
            ):
                return "admin_conflict_township"
            township_verified = bool(explicit_township) or any(
                _admin_name_matches(value, township) for value in broad_text
            )
        if not township_verified:
            return "admin_unverified_township"

    if scope_bucket != "project_local":
        return ""
    village = str(administrative_scope.get("village") or "").strip()
    explicit_village = _row_values(row, _ADMIN_FIELDS["village"])
    if explicit_village and village and not all(
        _admin_name_matches(value, village) for value in explicit_village
    ):
        return "admin_conflict_village"
    village_verified = bool(explicit_village) or (
        bool(village) and any(_admin_name_matches(value, village) for value in broad_text)
    )
    if project_bbox_wgs84 is not None:
        provenance = _coordinate_provenance(provider, row, manifest)
        location = provenance["wgs84"]
        if (
            provenance["trust_status"] not in {"verified_direct", "verified_transformed"}
            or location is None
        ):
            return "project_scope_unverified"
        min_lon, min_lat, max_lon, max_lat = project_bbox_wgs84
        lon, lat = location
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            # The bbox verifies project-local position; only an explicit
            # village conflict is allowed to veto it (checked above).
            return ""
        return "outside_project_bbox"
    if village_verified:
        return ""
    if village:
        return "project_scope_unverified"
    return ""


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _has_jsonl_object(path: Path) -> bool:
    """Check whether a normalized file has one usable row without full parsing."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return True
    except OSError:
        return False
    return False


_RUN_STATUSES = frozenset(
    {
        "success_nonempty",
        "success_empty",
        "missing",
        "missing_capability",
        "failed",
        "not_attempted",
        "partial",
    }
)


def _read_manifest(path: Path) -> dict[str, Any]:
    """Read a run manifest without allowing malformed metadata to stop DATA.

    A manifest is provenance, not an observation.  Returning an empty mapping
    on a malformed file lets the caller retain the fact that the run was
    present while conservatively classifying it as partial/not attempted.
    """

    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _manifest_status_counts(manifest: dict[str, Any]) -> dict[str, int]:
    """Collect status counters from old and current provider manifests.

    Historical runs used top-level ``missing``/``failed`` counters, while
    newer runs use ``status_counts`` and some legacy migrations use
    ``operation_status``.  We retain all observed states but never infer a
    successful record from a counter alone.
    """

    counts: dict[str, int] = {}

    def add(status: Any, value: Any) -> None:
        key = str(status or "").strip()
        try:
            amount = int(value or 0)
        except (TypeError, ValueError):
            return
        if key and amount > 0:
            counts[key] = counts.get(key, 0) + amount

    status_counts = manifest.get("status_counts")
    if isinstance(status_counts, dict):
        for key, value in status_counts.items():
            add(key, value)
    operation_status = manifest.get("operation_status")
    if isinstance(operation_status, dict):
        for value in operation_status.values():
            if isinstance(value, dict):
                for key, amount in value.items():
                    add(key, amount)

    # Do not double-count a status that is already represented by a detailed
    # status_counts map.  Top-level counters are still needed by migrated
    # manifests which have no per-operation map.
    for key in (
        "success_nonempty",
        "successful_nonempty",
        "success_empty",
        "missing",
        "missing_capability",
        "not_attempted",
        "failed",
    ):
        if key in manifest and not status_counts and not operation_status:
            canonical = "success_nonempty" if key == "successful_nonempty" else key
            add(canonical, manifest.get(key))
    return counts


def _manifest_declared_status(manifest: dict[str, Any]) -> str:
    """Return an explicit status when a provider wrote one."""

    for key in ("status", "run_status"):
        value = str(manifest.get(key) or "").strip().lower()
        if value in _RUN_STATUSES:
            return value
        # ``complete``/``incomplete`` are run-level lifecycle labels, not
        # Evidence five-state values.  Keep them in manifest_status and let
        # the aggregate classifier inspect counters and normalized rows.
    return ""


def _int_value(value: Any) -> int:
    """Parse optional manifest counters without making metadata fatal."""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _classify_run_status(
    manifest: dict[str, Any],
    *,
    normalized_exists: bool,
    normalized_count: int,
) -> str:
    """Classify a cached run without inventing observations.

    ``status`` on ``provider_runs`` is intentionally a small, stable state
    machine.  A mixed run (for example Tencent's 66 successful requests,
    141 empty responses and 77 quota failures) is ``partial`` even when a
    manifest exists.  The raw lifecycle label and counters remain attached to
    the provider-run row for audit and later offline normalization.
    """

    declared = _manifest_declared_status(manifest)
    counts = _manifest_status_counts(manifest)
    if declared in {"failed", "missing", "missing_capability", "not_attempted"}:
        return declared
    if declared == "partial":
        return "partial"
    if declared in {"success_nonempty", "success_empty"}:
        # A declared non-empty run without normalized rows is not consumable;
        # preserve the declaration but expose the aggregate as partial.
        if declared == "success_nonempty" and normalized_count == 0:
            return "partial"
        if declared == "success_empty" and normalized_count > 0:
            return "partial"
        return declared

    failed = counts.get("failed", 0)
    missing_capability = counts.get("missing_capability", 0)
    not_attempted = counts.get("not_attempted", 0)
    missing = counts.get("missing", 0)
    success_nonempty = counts.get("success_nonempty", 0)
    # Legacy manifests call this ``successful_nonempty``; the helper normally
    # canonicalizes it, but retain this lookup for hand-written manifests.
    success_nonempty += counts.get("successful_nonempty", 0)
    success_empty = counts.get("success_empty", 0)
    attempted = sum(
        value
        for key, value in counts.items()
        if key not in {"not_attempted"}
    )

    if failed and not (success_nonempty or success_empty or missing or missing_capability):
        return "failed"
    if missing_capability and not (failed or success_nonempty or success_empty or missing):
        return "missing_capability"
    if not_attempted and not (failed or success_nonempty or success_empty or missing or missing_capability):
        return "not_attempted"
    if normalized_count > 0:
        return "partial" if (failed or missing or missing_capability or not_attempted) else "success_nonempty"
    if normalized_exists and manifest.get("dry_run") and normalized_count == 0:
        return "not_attempted"
    if normalized_exists and not (failed or missing_capability or not_attempted):
        # An existing, empty normalized file is an explicit successful-empty
        # result even when older manifests omitted status_counts.
        return "success_empty"
    if missing and not (failed or success_nonempty or success_empty):
        return "missing"
    if failed or missing_capability or not_attempted or success_nonempty or success_empty or attempted:
        return "partial"
    # A dry-run manifest with no request/attempt counters is a planned but
    # unissued operation, not an empty provider result.
    if manifest.get("dry_run") or manifest.get("planned_job_count"):
        return "not_attempted"
    return "partial"


def _role(row: dict[str, Any]) -> str:
    value = " ".join(
        str(row.get(key) or "")
        for key in ("record_kind", "operation", "type", "typecode", "poiType", "name", "query_name")
    ).lower()
    if any(token in value for token in ("road", "route", "道路", "乡道", "省道", "县道")):
        return "road"
    if any(token in value for token in ("water", "river", "河", "水库", "溪")):
        return "water"
    if any(token in value for token in ("facility", "school", "hospital", "医院", "学校", "村委", "服务")):
        return "facility"
    if any(token in value for token in ("admin", "district", "county", "town", "村", "镇", "县")):
        return "place"
    return "unknown"


def _geometry_semantics(row: dict[str, Any], role: str) -> str:
    geometry = row.get("source_geometry") or row.get("geometry")
    if isinstance(geometry, dict):
        kind = str(geometry.get("type") or "").strip().lower()
        if kind in {"linestring", "multilinestring"}:
            return "line_observation"
        if kind in {"polygon", "multipolygon"}:
            return "polygon_observation"
    if role == "road":
        return "road_nearest_point"
    if role == "water":
        return "water_name_observation"
    return "point_observation"


_COARSE_LEVELS = frozenset({
    "省", "市", "县", "区", "镇", "乡", "街道", "村", "村庄",
    "乡镇", "乡镇街道", "社区村落", "行政区", "行政区域",
})
_ADMIN_SUFFIXES = ("省", "市", "自治州", "地区", "县", "区", "镇", "乡", "街道", "村")


def _normalized_text(value: Any) -> str:
    return re.sub(r"[\s,，、;；|/\-]+", "", str(value or "").casefold())


def _returned_label(row: dict[str, Any]) -> str:
    for key in ("formatted_address", "label", "address"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    location = row.get("location")
    if isinstance(location, Mapping):
        for key in ("keyWord", "keyword", "formatted_address", "label", "address"):
            value = location.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _returned_level(row: dict[str, Any]) -> str:
    location = row.get("location")
    for value in (row.get("level"), location.get("level") if isinstance(location, Mapping) else ""):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _geocode_role(row: dict[str, Any], *, has_coordinates: bool) -> str:
    query = str(row.get("query_name") or "").strip()
    returned = _returned_label(row)
    level = _returned_level(row)
    query_norm = _normalized_text(query)
    returned_norm = _normalized_text(returned)
    level_norm = _normalized_text(level)
    coarse = level_norm in {_normalized_text(value) for value in _COARSE_LEVELS}
    query_is_admin = bool(query_norm) and any(query_norm.endswith(_normalized_text(suffix)) for suffix in _ADMIN_SUFFIXES)
    exact_return = bool(query_norm and returned_norm and query_norm in returned_norm and returned_norm)
    if query_is_admin and exact_return and (coarse or not level_norm):
        return "administrative_anchor" if has_coordinates else "name_only"
    if query_norm and returned_norm and query_norm in returned_norm and not coarse:
        return "feature_location" if has_coordinates else "name_only"
    return "coarse_geocode" if has_coordinates else ("name_only" if query or returned else "missing")


def _spatial_evidence_role(row: dict[str, Any], *, has_coordinates: bool) -> str:
    name = str(row.get("name") or row.get("title") or "").strip()
    operation = " ".join(
        str(row.get(key) or "") for key in ("record_kind", "operation", "api", "method")
    ).casefold()
    if any(token in operation for token in ("poi", "pois", "search", "tips", "tip")):
        return "feature_location" if name and has_coordinates else ("name_only" if name else "missing")
    if any(token in operation for token in ("geocode", "regeo", "reverse", "component", "boundary")):
        return _geocode_role(row, has_coordinates=has_coordinates)
    if name:
        return "name_only"
    return "coarse_geocode" if has_coordinates else "missing"


def _run_candidates(root: Path, provider: str, stage: str) -> list[Path]:
    run_root = root / provider / stage / "runs"
    if not run_root.is_dir():
        return []
    # Prefer a run with usable normalized rows, then an explicitly empty
    # normalized result, then a manifest/attempt-only run.  The last class is
    # important for interrupted providers (notably Tencent): its counters and
    # failure reason must remain visible even though no observation can be
    # fabricated from a manifest.
    candidates: list[tuple[int, int, int, int, Path]] = []
    for path in run_root.iterdir():
        if not path.is_dir():
            continue
        normalized = path / "normalized_all.jsonl"
        manifest = path / "manifest.json"
        payload = _read_manifest(manifest)
        manifest_count = _int_value(payload.get("normalized_record_count"))
        try:
            mtime = int(path.stat().st_mtime_ns)
        except OSError:
            mtime = 0
        normalized_exists = normalized.is_file()
        has_usable_rows = _has_jsonl_object(normalized) if normalized_exists else False
        has_attempt_log = any(
            (path / filename).is_file()
            for filename in ("requests.jsonl", "attempts.jsonl")
        )
        has_run_metadata = bool(
            manifest.is_file()
            or has_attempt_log
            or manifest_count
            or payload.get("request_count")
            or payload.get("attempt_count")
            or payload.get("raw_response_count")
            or payload.get("status_counts")
        )
        if not normalized_exists and not has_run_metadata:
            continue
        # Three tiers keep a newer dry-run/empty directory from hiding a
        # usable historical normalized cache, while still selecting a
        # manifest-only run when no normalized run exists.
        usable_tier = 3 if has_usable_rows else 2 if normalized_exists else 1
        manifest_tier = 1 if manifest.is_file() else 0
        candidates.append((usable_tier, manifest_tier, mtime, manifest_count, path))
    return [item[4] for item in sorted(candidates, reverse=True)]


def _select_run(root: Path, provider: str, stage: str) -> Path | None:
    candidates = _run_candidates(root, provider, stage)
    return candidates[0] if candidates else None


def _observation_id(
    provider: str,
    stage: str,
    row: dict[str, Any],
    index: int,
) -> str:
    material = "|".join(
        (
            provider,
            stage,
            str(row.get("request_key") or ""),
            str(row.get("source_record_ref") or row.get("id") or row.get("poi_id") or row.get("hotPointID") or ""),
            str(row.get("name") or row.get("query_name") or ""),
            str(index),
        )
    )
    return f"external-observation:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _observation_status(row: dict[str, Any]) -> str:
    """Return the Evidence state without reusing a provider payload status.

    Normalized rows are retained records, so their default state is
    ``success_nonempty``.  Provider payloads frequently use a generic
    ``status`` field for business codes (for example ``0``/``1`` or an error
    object); that field remains in metadata and must never enter the Evidence
    state machine.  Only explicitly named observation/request/cache status
    fields may override the default.
    """

    canonical = {
        "success_nonempty",
        "success_empty",
        "missing",
        "missing_capability",
        "failed",
        "not_attempted",
    }
    aliases = {
        "successful_nonempty": "success_nonempty",
        "successful_empty": "success_empty",
    }
    for key in ("observation_status", "request_status", "cache_status"):
        value = str(row.get(key) or "").strip().casefold()
        value = aliases.get(value, value)
        if value in canonical:
            return value
    return "success_nonempty"


def _as_observation(
    provider: str,
    stage: str,
    row: dict[str, Any],
    index: int,
    project_name: str,
    root: Path,
    *,
    manifest: Mapping[str, Any] | None = None,
    run_metadata: Mapping[str, Any] | None = None,
) -> ExternalObservation:
    manifest = manifest or {}
    run_metadata = run_metadata or {}
    provenance = _coordinate_provenance(provider, row, manifest)
    wgs84 = provenance["wgs84"]
    native = provenance["native"]
    name = str(row.get("name") or row.get("title") or "").strip()
    spatial_role = _spatial_evidence_role(
        row,
        has_coordinates=wgs84 is not None or native is not None,
    )
    role = _role(row)
    aliases: list[str] = []
    for value in (row.get("alias"), row.get("aliases"), row.get("query_name")):
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and text != name and text not in aliases:
                aliases.append(text)
    raw_ref = str(row.get("raw_response") or row.get("raw_response_ref") or "").strip()
    if raw_ref:
        raw_path = Path(raw_ref)
        if raw_path.is_absolute():
            try:
                raw_ref = raw_path.relative_to(root).as_posix()
            except ValueError:
                raw_ref = raw_path.name
        else:
            raw_ref = raw_ref.replace("\\", "/")
    source_ref = str(
        row.get("source_record_ref")
        or row.get("id")
        or row.get("poi_id")
        or row.get("hotPointID")
        or ""
    ).strip()
    if not source_ref:
        source_ref = f"{provider}:{stage}:{row.get('request_key', '')}:{index}"
    else:
        source_path = Path(source_ref)
        if source_path.is_absolute():
            try:
                source_ref = source_path.relative_to(root).as_posix()
            except ValueError:
                source_ref = source_path.name
        else:
            source_ref = source_ref.replace("\\", "/")
    status = _observation_status(row)
    metadata = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "name", "title", "alias", "aliases", "location", "location_wgs84",
            "location_gcj02", "lonlat", "source_geometry", "geometry", "raw_response",
        }
    }
    geometry = row.get("source_geometry") or row.get("geometry")
    if not isinstance(geometry, dict):
        geometry = None
    times = _observation_times(row, manifest, run_metadata)
    raw_admin_match = row.get("admin_match")
    admin_match = {
        str(key): bool(value)
        for key, value in raw_admin_match.items()
    } if isinstance(raw_admin_match, dict) else {}
    metadata.pop("cache_root", None)
    return ExternalObservation(
        observation_id=_observation_id(provider, stage, row, index),
        provider=provider,
        stage=stage,
        operation=str(row.get("operation") or row.get("record_kind") or "").strip(),
        status=status,
        attempted=(False if status == "not_attempted" else bool(row.get("attempted", True))),
        scope_bucket=str(row.get("scope_bucket") or "unknown_scope"),
        admin_match=admin_match,
        observed_name=name,
        aliases=aliases,
        observed_type=role,
        location_wgs84=wgs84,
        location_native=native,
        coordinate_contract=provenance["contract"],
        observed_at=times["observed_at"],
        collected_at=times["collected_at"],
        provider_timestamp=times["provider_timestamp"],
        run_created_at=times["run_created_at"],
        coordinate_source_crs=provenance["source_crs"],
        coordinate_target_crs=provenance["target_crs"],
        coordinate_transform=provenance["transform"],
        coordinate_trust_status=provenance["trust_status"],
        spatial_evidence_role=spatial_role,
        geometry=geometry,
        geometry_semantics=_geometry_semantics(row, role),
        raw_response_ref=raw_ref,
        source_record_ref=source_ref,
        request_key=str(row.get("request_key") or ""),
        query_name=str(row.get("query_name") or ""),
        metadata={"project_name": project_name, **metadata},
    )


def _distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.asin(min(1.0, math.sqrt(value)))


def _cluster_name_tokens(observation: ExternalObservation) -> set[str]:
    """Return identity-bearing labels without broad request terms."""

    query_token = _normalized_text(observation.query_name)
    return {
        token
        for token in (
            _normalized_text(value)
            for value in (observation.observed_name, *observation.aliases)
        )
        if token and token != query_token
    }


def _cluster_semantically_compatible(
    left: ExternalObservation,
    right: ExternalObservation,
) -> bool:
    left_tokens = _cluster_name_tokens(left)
    right_tokens = _cluster_name_tokens(right)
    return bool(left_tokens and right_tokens and left_tokens.intersection(right_tokens))


def cluster_external_observations(
    observations: Iterable[ExternalObservation],
    *,
    tolerance_m: float = 30.0,
) -> dict[str, str]:
    """Return observation→cluster IDs without deleting individual observations.

    Points are indexed in a regular grid over the unit sphere.  A geodesic
    distance threshold ``t`` has chord length ``2*sin(t/(2*R))``; therefore
    two points that can merge differ by at most one cell on every ECEF axis.
    Only the 27 neighbouring cells are checked, while the existing haversine
    function remains the authoritative distance test.  Invalid coordinates
    and tolerances fail closed instead of allowing a malformed cache row to
    affect another observation.
    """

    all_items = list(observations)
    parents = {item.observation_id: item.observation_id for item in all_items}
    items = [
        item
        for item in all_items
        if (
            item.status == "success_nonempty"
            and item.attempted
            and item.location_wgs84 is not None
            and item.coordinate_trust_status in {"verified_direct", "verified_transformed"}
            and item.spatial_evidence_role == "feature_location"
            and is_wgs84_equivalent_crs(item.coordinate_target_crs)
        )
    ]
    items_by_id = {item.observation_id: item for item in items}

    def find(value: str) -> str:
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right)] = min(root_left, root_right)

    # The old implementation naturally returned singleton clusters for a
    # negative/NaN tolerance.  Preserve that result without building a grid
    # (and avoid the accidental all-pairs behaviour of infinity).
    if not math.isfinite(tolerance_m) or tolerance_m <= 0:
        if tolerance_m == 0:
            # Exact coordinate equality is the zero-distance contract.  Do
            # not use the grid here: opposite representations of the same
            # meridian (180/-180) are intentionally not equal under the old
            # haversine calculation either.
            for index, left in enumerate(items):
                left_location = left.location_wgs84
                if not all(math.isfinite(float(value)) for value in left_location):
                    continue
                for right in items[index + 1 :]:
                    right_location = right.location_wgs84
                    if not all(math.isfinite(float(value)) for value in right_location):
                        continue
                    if (
                        left_location == right_location
                        and _cluster_semantically_compatible(left, right)
                    ):
                        union(left.observation_id, right.observation_id)
        return _cluster_ids(parents, find)

    radius = 6_371_000.0
    # Haversine distance is bounded by pi*R.  Beyond that threshold every
    # pair of finite valid points is a candidate, so the spatial hash cannot
    # improve the work and the exact legacy comparison is simplest.
    if tolerance_m >= math.pi * radius:
        for index, left in enumerate(items):
            left_location = left.location_wgs84
            if not _finite_location(left_location):
                continue
            for right in items[index + 1 :]:
                right_location = right.location_wgs84
                if (
                    _finite_location(right_location)
                    and _cluster_semantically_compatible(left, right)
                    and _distance_m(left_location, right_location) <= tolerance_m
                ):
                    union(left.observation_id, right.observation_id)
        return _cluster_ids(parents, find)

    chord = 2.0 * math.sin(tolerance_m / (2.0 * radius))
    # Round the cell width upward by one representable float so a pair lying
    # exactly on a cell boundary cannot be lost to floating-point rounding.
    cell_size = math.nextafter(chord, math.inf)
    buckets: dict[tuple[int, int, int], list[tuple[float, float, str]]] = {}

    def unit_ecef(location: tuple[float, float]) -> tuple[float, float, float] | None:
        if not _finite_location(location):
            return None
        longitude, latitude = location
        # Values outside WGS84 latitude are not meaningful ECEF positions for
        # this index.  They remain isolated rather than changing old distance
        # semantics through an approximate projection.
        if latitude < -90.0 or latitude > 90.0:
            return None
        longitude_radians = math.radians(longitude)
        latitude_radians = math.radians(latitude)
        cosine = math.cos(latitude_radians)
        return (
            cosine * math.cos(longitude_radians),
            cosine * math.sin(longitude_radians),
            math.sin(latitude_radians),
        )

    def cell(point: tuple[float, float, float]) -> tuple[int, int, int]:
        return tuple(math.floor(value / cell_size) for value in point)

    for left in items:
        left_location = left.location_wgs84
        left_point = unit_ecef(left_location)
        if left_point is None:
            # Invalid rows are fail-closed: retain their singleton cluster.
            continue
        left_cell = cell(left_point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for right_location, _right_point, right_id in buckets.get(
                        (left_cell[0] + dx, left_cell[1] + dy, left_cell[2] + dz),
                        (),
                    ):
                        right = items_by_id[right_id]
                        if (
                            _cluster_semantically_compatible(left, right)
                            and _distance_m(left_location, right_location) <= tolerance_m
                        ):
                            union(left.observation_id, right_id)
        buckets.setdefault(left_cell, []).append((left_location, left_point, left.observation_id))

    return _cluster_ids(parents, find)


def _finite_location(location: tuple[float, float]) -> bool:
    if not isinstance(location, (list, tuple)) or len(location) != 2:
        return False
    try:
        return all(math.isfinite(float(value)) for value in location)
    except (TypeError, ValueError):
        return False


def _cluster_ids(
    parents: dict[str, str],
    find: Any,
) -> dict[str, str]:
    """Build stable IDs from the union-find state (legacy algorithm)."""
    groups: dict[str, list[str]] = {}
    for observation_id in parents:
        groups.setdefault(find(observation_id), []).append(observation_id)
    result: dict[str, str] = {}
    for members in groups.values():
        cluster = hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()[:24]
        for member in members:
            result[member] = f"external-cluster:{cluster}"
    return result


def load_cached_external_observation_snapshot(
    project_name: str = "",
    *,
    root: Path | str | None = None,
    providers: Iterable[str] = DEFAULT_PROVIDERS,
    stages: Iterable[str] = DEFAULT_STAGES,
    scopes: Iterable[str] = DEFAULT_SCOPES,
    max_records: int = 5000,
    administrative_scope: Mapping[str, str] | None = None,
    project_bbox_wgs84: tuple[float, float, float, float] | None = None,
) -> ExternalObservationSnapshot:
    """Load the newest usable normalized caches without contacting providers."""

    cache_root = Path(root) if root is not None else DEFAULT_CACHE_ROOT
    resolved_admin_scope = {
        str(key): str(value or "").strip()
        for key, value in dict(administrative_scope or {}).items()
        if str(value or "").strip()
    }
    if project_name and not resolved_admin_scope.get("village"):
        resolved_admin_scope["village"] = str(project_name).strip()
    allowed_scopes = {str(value) for value in scopes}
    observations: list[ExternalObservation] = []
    provider_runs: list[dict[str, Any]] = []
    excluded_counts: dict[str, int] = {}
    complete = True
    for provider in providers:
        for stage in stages:
            run = _select_run(cache_root, str(provider), str(stage))
            if run is None:
                provider_runs.append({
                    "provider": provider,
                    "stage": stage,
                    "status": "not_attempted",
                    "cache_only": True,
                    "cache_reused": False,
                    "api_calls": 0,
                })
                complete = False
                continue
            manifest_path = run / "manifest.json"
            manifest = _read_manifest(manifest_path)
            normalized_path = run / "normalized_all.jsonl"
            normalized_exists = normalized_path.is_file()
            rows = _jsonl_rows(normalized_path) if normalized_exists else []
            status = _classify_run_status(
                manifest,
                normalized_exists=normalized_exists,
                normalized_count=len(rows),
            )
            normalized_status_counts: dict[str, int] = {}
            for row in rows:
                row_status = _observation_status(row)
                normalized_status_counts[row_status] = (
                    normalized_status_counts.get(row_status, 0) + 1
                )
            non_success_rows = sum(
                count
                for row_status, count in normalized_status_counts.items()
                if row_status != "success_nonempty"
            )
            if non_success_rows:
                status = "partial"
            manifest_status = str(
                manifest.get("status")
                or manifest.get("run_status")
                or ""
            ).strip()
            status_counts = _manifest_status_counts(manifest)
            # Keep provider-level lineage rich enough for an offline recovery
            # pass.  In particular, a run with request/raw files but no
            # normalized_all.jsonl is represented here and produces no
            # observations below.
            run_record: dict[str, Any] = {
                "provider": provider,
                "stage": stage,
                "run_id": str(manifest.get("run_id") or run.name),
                "path": str(run),
                "status": status,
                "manifest_present": manifest_path.is_file(),
                "manifest_status": manifest_status,
                "run_status": str(manifest.get("run_status") or "").strip(),
                "status_counts": status_counts,
                "normalized_status_counts": dict(sorted(normalized_status_counts.items())),
                "normalized_available": normalized_exists,
                "normalized_record_count": len(rows),
                "manifest_normalized_record_count": _int_value(manifest.get("normalized_record_count")),
                "retained_candidate_count": _int_value(manifest.get("retained_candidate_count")),
                "request_count": _int_value(manifest.get("request_count")),
                "attempt_count": _int_value(manifest.get("attempt_count")),
                "raw_response_count": _int_value(manifest.get("raw_response_count")),
                "completion_reason": str(manifest.get("completion_reason") or ""),
                "coordinate_contract": manifest.get("coordinate_contract") or "",
                "run_created_at": manifest.get("created_at") or "",
                "cache_only": True,
                "cache_reused": True,
                "api_calls": 0,
            }
            if manifest.get("l1_stage") is not None:
                run_record["l1_stage"] = manifest.get("l1_stage")
            if manifest.get("raw_response_directory"):
                run_record["raw_response_directory"] = manifest.get("raw_response_directory")
            if manifest.get("cache_directory"):
                run_record["cache_directory"] = manifest.get("cache_directory")
            provider_runs.append(run_record)
            if (
                status not in {"success_nonempty", "success_empty"}
                or not manifest_path.is_file()
                or not manifest
            ):
                complete = False
            for index, row in enumerate(rows):
                scope = str(row.get("scope_bucket") or "unknown_scope")
                if scope not in allowed_scopes:
                    excluded_counts[scope] = excluded_counts.get(scope, 0) + 1
                    continue
                try:
                    _validate_row_coordinates(row)
                except (TypeError, ValueError):
                    excluded_counts["invalid_observation"] = (
                        excluded_counts.get("invalid_observation", 0) + 1
                    )
                    continue
                exclusion_reason = _row_scope_filter_reason(
                    row,
                    administrative_scope=resolved_admin_scope,
                    project_bbox_wgs84=project_bbox_wgs84,
                    provider=str(provider),
                    manifest=manifest,
                )
                if exclusion_reason:
                    excluded_counts[exclusion_reason] = (
                        excluded_counts.get(exclusion_reason, 0) + 1
                    )
                    continue
                try:
                    observations.append(
                        _as_observation(
                            str(provider),
                            str(stage),
                            row,
                            index,
                            project_name,
                            cache_root,
                            manifest=manifest,
                            run_metadata=run_record,
                        )
                    )
                except (ValidationError, TypeError, ValueError):
                    excluded_counts["invalid_observation"] = (
                        excluded_counts.get("invalid_observation", 0) + 1
                    )
    unique: dict[str, ExternalObservation] = {}
    for item in observations:
        unique.setdefault(item.observation_id, item)
    observations = list(unique.values())[: max(1, int(max_records))]
    cluster_ids = cluster_external_observations(observations)
    observations = [item.model_copy(update={"cluster_id": cluster_ids.get(item.observation_id, "")}) for item in observations]
    # The snapshot identity must change when a run transitions from
    # not_attempted→partial/success_empty (or when its failure counters
    # change), even if the set of normalized observations is unchanged.
    payload = canonical_external_observation_payload(
        project_name=project_name,
        administrative_scope=resolved_admin_scope,
        scope_bbox_wgs84=project_bbox_wgs84,
        observations=observations,
        provider_runs=provider_runs,
        excluded_counts=excluded_counts,
        complete=complete and bool(provider_runs),
    )
    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    snapshot_key = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
    return ExternalObservationSnapshot(
        snapshot_id=f"external-map-{project_name or 'project'}-{snapshot_key}",
        project_name=project_name,
        administrative_scope=resolved_admin_scope,
        scope_bbox_wgs84=project_bbox_wgs84,
        observations=observations,
        provider_runs=provider_runs,
        excluded_counts=excluded_counts,
        complete=complete and bool(provider_runs),
    )


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "cluster_external_observations",
    "load_cached_external_observation_snapshot",
]
