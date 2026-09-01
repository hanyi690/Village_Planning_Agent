"""Deterministic selection of a purpose-specific DATA representation.

An entity may have several source features (locator point, legal polygon,
network centerline, or derived service area).  GROUND must select a
representation for the requested purpose without treating insertion order or
the first geometry returned by a catalog as authoritative.
"""

from __future__ import annotations

from typing import Any


_PURPOSE_TOKENS: dict[str, tuple[str, ...]] = {
    "map_label": ("locator", "label", "point", "centroid"),
    "statutory_overlap": ("legal", "extent", "boundary", "polygon", "constraint"),
    "execution_geometry": ("execution", "footprint", "source_geometry", "centerline"),
    "network_path": ("network", "centerline", "corridor", "line"),
    "service_area": ("service", "catchment", "buffer", "area"),
}


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _representation_attrs(feature: Any) -> dict[str, Any]:
    raw = getattr(feature, "raw_attributes", None) or {}
    return raw if isinstance(raw, dict) else {}


def _purpose_score(representation: Any, feature: Any, purpose: str) -> int:
    purpose_text = _text(purpose)
    if not purpose_text:
        return 0
    rep_purpose = _text(getattr(representation, "purpose", ""))
    attrs = _representation_attrs(feature)
    declared = " ".join(
        _text(attrs.get(key))
        for key in ("representation_purpose", "geometry_role", "role", "layer_ref")
        if attrs.get(key) not in (None, "")
    )
    # A feature can own several representations.  Feature-level attributes
    # therefore cannot override a representation's explicit purpose; they are
    # only a fallback for older records that did not declare one.
    haystack = rep_purpose or declared
    if purpose_text in haystack:
        return 0
    tokens = _PURPOSE_TOKENS.get(purpose_text, (purpose_text,))
    return 1 if any(token in haystack for token in tokens) else 2


def _accepted_score(representation: Any, feature: Any) -> int:
    attrs = _representation_attrs(feature)
    status = _text(getattr(representation, "status", "available"))
    accepted = _text(
        attrs.get("acceptance_status")
        or attrs.get("validity_status")
        or attrs.get("authority_status")
    )
    if status == "available" and accepted in {"", "accepted", "authoritative", "valid", "verified"}:
        return 0
    if status == "available":
        return 1
    return 2


def _geometry_score(representation: Any, required_geometry_kind: str) -> int:
    wanted = _text(required_geometry_kind)
    if not wanted:
        return 0
    actual = _text(getattr(representation, "geometry_kind", ""))
    return 0 if actual == wanted else 1


def _derived_score(representation: Any) -> int:
    return 1 if getattr(representation, "derived_from", None) else 0


def select_representation(
    catalog: Any,
    *,
    feature_ref: str,
    dataset_ref: str = "",
    purpose: str = "",
    required_geometry_kind: str = "",
) -> Any | None:
    """Return the stable best representation for one DATA feature.

    The result is sorted by semantic compatibility first and representation
    reference last.  No LLM output or source insertion order participates in
    the decision.
    """

    if catalog is None or not str(feature_ref).strip():
        return None
    requested_ref = str(feature_ref).strip()
    requested_dataset = str(dataset_ref or "").strip()
    get_feature = getattr(catalog, "get_feature", lambda _ref, **_kwargs: None)
    lookup_ref = requested_ref
    qualified_prefix = f"{requested_dataset}:" if requested_dataset else ""
    if qualified_prefix and requested_ref.startswith(qualified_prefix):
        lookup_ref = requested_ref[len(qualified_prefix):]
    try:
        feature = get_feature(lookup_ref, dataset_ref=requested_dataset)
    except TypeError:
        feature = get_feature(lookup_ref)
    if feature is None and lookup_ref != requested_ref:
        try:
            feature = get_feature(requested_ref)
        except TypeError:
            feature = None
    if feature is None:
        return None
    resolved_dataset = str(
        getattr(feature, "dataset_ref", "") or requested_dataset
    ).strip()
    resolved_feature_ref = str(
        getattr(feature, "source_feature_ref", "") or requested_ref
    ).strip()

    # DATA admission is authoritative for current-world representations.  A
    # catalog may still retain excluded/planned rows for audit, but GROUND
    # must not choose one of those rows as executable evidence.
    snapshot = getattr(catalog, "snapshot", None)
    admission_index = None
    if snapshot is not None:
        try:
            from app.data.admission import (
                assert_current_world_catalog,
                build_admission_index,
                feature_admission_verdict,
            )

            assert_current_world_catalog(snapshot)
            admission_index = build_admission_index(snapshot)
            if not feature_admission_verdict(snapshot, feature).admitted:
                return None
        except (TypeError, ValueError):
            return None
    representations_for_feature = getattr(
        catalog,
        "representations_for_feature",
        lambda _ref, **_kwargs: [],
    )
    try:
        representations = list(
            representations_for_feature(
                resolved_feature_ref,
                dataset_ref=resolved_dataset,
            )
            or []
        )
    except TypeError:
        representations = list(representations_for_feature(resolved_feature_ref) or [])
    if admission_index is not None:
        from app.data.admission import is_admitted_representation

        representations = [
            item
            for item in representations
            if is_admitted_representation(snapshot, item, index=admission_index)
        ]
    if not representations:
        return None
    ranked = sorted(
        representations,
        key=lambda item: (
            _purpose_score(item, feature, purpose),
            _accepted_score(item, feature),
            _geometry_score(item, required_geometry_kind),
            0 if _text(getattr(item, "crs", "")) else 1,
            _derived_score(item),
            str(getattr(item, "representation_ref", "")),
        ),
    )
    return ranked[0]


__all__ = ["select_representation"]
