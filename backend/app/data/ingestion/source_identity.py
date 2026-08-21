"""Stable identity for source-backed GeoJSON features.

The identity is deliberately based only on ingestion provenance and source
content.  It is not a name, coordinate, centroid, parcel, or geometry
selection heuristic.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import quote
from typing import Any


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_content_digest(feature_collection: dict[str, Any]) -> str:
    """Return a deterministic digest for the complete source payload."""
    return _digest(feature_collection)


def source_feature_identity(
    *,
    source_uri: str | None,
    feature_collection: dict[str, Any],
    layer_type: str,
    feature_index: int,
    feature: dict[str, Any],
    content_digest: str | None = None,
) -> dict[str, Any] | None:
    """Build an auditable source feature key when provenance is available.

    ``source_uri`` is mandatory.  A bare feature ordinal is not an identity:
    it becomes stable only in combination with the source URI, complete
    content digest, layer, and feature geometry digest.
    """
    uri = str(source_uri or "").strip()
    if not uri or feature_index < 0:
        return None
    content_digest = content_digest or source_content_digest(feature_collection)
    geometry_digest = _digest(feature.get("geometry"))
    properties = feature.get("properties") or {}
    raw_label = str(properties.get("注记") or properties.get("text") or "").strip()
    encoded_uri = quote(uri, safe="")
    feature_id = (
        "http://village-planning.org/source-feature/v1/"
        f"{quote(str(layer_type), safe='-._~')}/"
        f"{content_digest}/{feature_index}/{geometry_digest}"
        f"?source={encoded_uri}"
    )
    return {
        "source_feature_id": feature_id,
        "source_uri": uri,
        "source_content_digest": content_digest,
        "source_feature_index": feature_index,
        "source_geometry_digest": geometry_digest,
        "source_label": raw_label,
    }


__all__ = ["source_content_digest", "source_feature_identity"]
