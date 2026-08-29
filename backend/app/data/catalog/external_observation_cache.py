"""Read-only loader for already collected AMap/Tianditu/Tencent caches.

This module intentionally has no HTTP/provider imports.  It turns normalized
JSONL records into provenance-bearing observations used by Evidence and
Cognition; it never mutates a VillageBundle or creates planning geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from app.contracts.evidence.external_observation_contracts import (
    ExternalObservation,
    ExternalObservationSnapshot,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "output" / "map_validation"
DEFAULT_PROVIDERS = ("amap", "tianditu", "tencent")
DEFAULT_STAGES = ("01_admin_scope", "02_l1_place_names")
DEFAULT_SCOPES = frozenset({"project_local", "township_local", "county_local"})


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


def _location_pair(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        try:
            return float(value["lng"]), float(value["lat"])
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, str) and "," in value:
        try:
            left, right = value.split(",", 1)
            return float(left.strip()), float(right.strip())
        except ValueError:
            return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


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


def _run_candidates(root: Path, provider: str, stage: str) -> list[Path]:
    run_root = root / provider / stage / "runs"
    if not run_root.is_dir():
        return []
    candidates: list[tuple[int, int, Path]] = []
    for path in run_root.iterdir():
        if not path.is_dir():
            continue
        normalized = path / "normalized_all.jsonl"
        if not normalized.is_file():
            continue
        manifest = path / "manifest.json"
        manifest_count = 0
        if manifest.is_file():
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                manifest_count = int(payload.get("normalized_record_count") or 0)
            except (OSError, ValueError, TypeError):
                manifest_count = 0
        try:
            mtime = int(path.stat().st_mtime_ns)
        except OSError:
            mtime = 0
        rows = len(_jsonl_rows(normalized))
        if manifest_count or rows:
            # Complete manifests win over a dry-run or empty partial run; the
            # mtime then gives deterministic preference to the newest run.
            candidates.append((1 if manifest.is_file() else 0, mtime, path))
    return [item[2] for item in sorted(candidates, reverse=True)]


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


def _as_observation(
    provider: str,
    stage: str,
    row: dict[str, Any],
    index: int,
    project_name: str,
    root: Path,
) -> ExternalObservation:
    role = _role(row)
    wgs84 = _location_pair(row.get("location_wgs84"))
    native = _location_pair(row.get("location_gcj02")) or _location_pair(row.get("location")) or _location_pair(row.get("lonlat"))
    name = str(row.get("name") or row.get("title") or "").strip()
    aliases: list[str] = []
    for value in (row.get("alias"), row.get("aliases"), row.get("query_name")):
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and text != name and text not in aliases:
                aliases.append(text)
    raw_ref = str(row.get("raw_response") or row.get("raw_response_ref") or "").strip()
    if raw_ref and not Path(raw_ref).is_absolute():
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
    status = str(row.get("status") or "success_nonempty")
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
    contract = str(row.get("coordinate_contract") or row.get("location_crs") or "unknown").strip()
    return ExternalObservation(
        observation_id=_observation_id(provider, stage, row, index),
        provider=provider,
        stage=stage,
        operation=str(row.get("operation") or row.get("record_kind") or "").strip(),
        status=status,
        attempted=bool(row.get("attempted", True)),
        scope_bucket=str(row.get("scope_bucket") or "unknown_scope"),
        observed_name=name,
        aliases=aliases,
        observed_type=role,
        location_wgs84=wgs84,
        location_native=native,
        coordinate_contract=contract,
        geometry=geometry,
        geometry_semantics=_geometry_semantics(row, role),
        raw_response_ref=raw_ref,
        source_record_ref=source_ref,
        request_key=str(row.get("request_key") or ""),
        query_name=str(row.get("query_name") or ""),
        metadata={"project_name": project_name, "cache_root": str(root), **metadata},
    )


def _distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.asin(min(1.0, math.sqrt(value)))


def cluster_external_observations(
    observations: Iterable[ExternalObservation],
    *,
    tolerance_m: float = 30.0,
) -> dict[str, str]:
    """Return observation→cluster IDs without deleting individual observations."""

    items = [item for item in observations if item.location_wgs84 is not None]
    parents = {item.observation_id: item.observation_id for item in items}

    def find(value: str) -> str:
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = parents[value]
        return value

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right)] = min(root_left, root_right)

    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            if _distance_m(left.location_wgs84, right.location_wgs84) <= tolerance_m:
                union(left.observation_id, right.observation_id)
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
) -> ExternalObservationSnapshot:
    """Load the newest usable normalized caches without contacting providers."""

    cache_root = Path(root) if root is not None else DEFAULT_CACHE_ROOT
    allowed_scopes = {str(value) for value in scopes}
    observations: list[ExternalObservation] = []
    provider_runs: list[dict[str, Any]] = []
    excluded_counts: dict[str, int] = {}
    complete = True
    for provider in providers:
        for stage in stages:
            run = _select_run(cache_root, str(provider), str(stage))
            if run is None:
                provider_runs.append({"provider": provider, "stage": stage, "status": "not_attempted"})
                complete = False
                continue
            manifest_path = run / "manifest.json"
            manifest: dict[str, Any] = {}
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    manifest = {}
            else:
                complete = False
            rows = _jsonl_rows(run / "normalized_all.jsonl")
            provider_runs.append({
                "provider": provider,
                "stage": stage,
                "run_id": str(manifest.get("run_id") or run.name),
                "path": str(run),
                "status": "complete" if manifest else "partial",
                "normalized_record_count": len(rows),
                "retained_candidate_count": int(manifest.get("retained_candidate_count") or 0),
            })
            for index, row in enumerate(rows):
                scope = str(row.get("scope_bucket") or "unknown_scope")
                if scope not in allowed_scopes:
                    excluded_counts[scope] = excluded_counts.get(scope, 0) + 1
                    continue
                observations.append(_as_observation(str(provider), str(stage), row, index, project_name, cache_root))
    unique: dict[str, ExternalObservation] = {}
    for item in observations:
        unique.setdefault(item.observation_id, item)
    observations = list(unique.values())[: max(1, int(max_records))]
    cluster_ids = cluster_external_observations(observations)
    observations = [item.model_copy(update={"cluster_id": cluster_ids.get(item.observation_id, "")}) for item in observations]
    payload = "|".join(sorted(item.observation_id for item in observations))
    snapshot_key = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return ExternalObservationSnapshot(
        snapshot_id=f"external-map-{project_name or 'project'}-{snapshot_key}",
        project_name=project_name,
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
