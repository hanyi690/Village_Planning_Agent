"""Closed relation catalogue used by Target Projection.

The catalogue is intentionally declarative.  It is the single place where
the compiler learns which typed parameters, target kinds and evaluator a
relation template requires.  It does not create geometry or infer numeric
thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationTemplateSpec:
    template: str
    subject_kinds: frozenset[str]
    object_kinds: frozenset[str]
    object_ref_kinds: frozenset[str]
    parameter_types: frozenset[str]
    evaluator_key: str
    default_criticality: str = "soft"
    geometry_scope: str = "pair"

    @property
    def requires_parameters(self) -> bool:
        return bool(self.parameter_types)


@dataclass(frozen=True)
class RelationCandidate:
    """One relation choice exposed to a claim compiler."""

    template: str
    subject_kind: str
    object_kinds: frozenset[str]
    object_ref_kinds: frozenset[str]
    parameter_types: frozenset[str]
    criticality: str


_TARGETS = frozenset({"site_area", "zone", "facility", "road", "linear", "axis", "action"})
_SPATIAL_TARGETS = frozenset(_TARGETS - {"action"})
_ANY_OBJECT = frozenset({"target", "entity", "place_hint", "constraint"})


RELATION_CATALOG: dict[str, RelationTemplateSpec] = {
    "within_allowed_area": RelationTemplateSpec(
        "within_allowed_area", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint", "constraint"}),
        frozenset({"allowed_area"}), "geometry.within", "hard", "subject",
    ),
    "avoid_constraint": RelationTemplateSpec(
        "avoid_constraint", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint", "constraint"}),
        frozenset({"avoid_constraint"}), "geometry.avoid", "hard", "subject",
    ),
    "near": RelationTemplateSpec(
        "near", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"distance", "co_locate"}), "geometry.distance", "soft", "pair",
    ),
    "serve": RelationTemplateSpec(
        "serve", frozenset({"facility"}), frozenset({"site_area", "zone", "facility"}),
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"service"}), "network.service_coverage", "hard", "network",
    ),
    "provide_access": RelationTemplateSpec(
        "provide_access", frozenset({"facility", "site_area", "zone"}), _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"access"}), "network.access", "hard", "network",
    ),
    "connect_network": RelationTemplateSpec(
        "connect_network", frozenset({"road", "linear"}), _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"connect"}), "network.connect", "hard", "network",
    ),
    "follow_alignment": RelationTemplateSpec(
        "follow_alignment", frozenset({"road", "linear", "axis"}), _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"alignment"}), "geometry.alignment", "soft", "pair",
    ),
    "preserve_existing": RelationTemplateSpec(
        "preserve_existing", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"existing_asset"}), "asset.preserve", "hard", "subject",
    ),
    "upgrade_existing": RelationTemplateSpec(
        "upgrade_existing", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"existing_asset"}), "asset.upgrade", "hard", "subject",
    ),
    "part_of": RelationTemplateSpec(
        "part_of", _SPATIAL_TARGETS, _TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"part_of"}), "topology.part_of", "hard", "pair",
    ),
    "co_locate": RelationTemplateSpec(
        "co_locate", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"co_locate", "distance"}), "geometry.distance", "soft", "pair",
    ),
    "mutually_exclusive": RelationTemplateSpec(
        "mutually_exclusive", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        frozenset({"target", "entity", "place_hint"}),
        frozenset({"mutually_exclusive"}), "allocation.exclusive", "hard", "pair",
    ),
    "precedes": RelationTemplateSpec(
        "precedes", _TARGETS, _TARGETS,
        frozenset({"target"}), frozenset({"precedes"}),
        "execution.precedes", "hard", "global",
    ),
    "contains": RelationTemplateSpec(
        "contains", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        _ANY_OBJECT, frozenset({"empty"}), "geometry.contains", "hard", "pair",
    ),
    "located_in": RelationTemplateSpec(
        "located_in", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        _ANY_OBJECT, frozenset({"empty"}), "geometry.within", "hard", "pair",
    ),
    "adjacent_to": RelationTemplateSpec(
        "adjacent_to", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        _ANY_OBJECT, frozenset({"empty"}), "geometry.adjacent", "soft", "pair",
    ),
    "intersects": RelationTemplateSpec(
        "intersects", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        _ANY_OBJECT, frozenset({"empty"}), "geometry.intersects", "hard", "pair",
    ),
    "overlaps": RelationTemplateSpec(
        "overlaps", _SPATIAL_TARGETS, _SPATIAL_TARGETS,
        _ANY_OBJECT, frozenset({"empty"}), "geometry.overlaps", "soft", "pair",
    ),
}


def relation_spec(template: str) -> RelationTemplateSpec | None:
    """Return the closed specification, or ``None`` for an unsupported name."""

    return RELATION_CATALOG.get(template)


def relation_options(subject_kind: str) -> tuple[RelationCandidate, ...]:
    """Return only catalog relations legal for one typed subject."""

    subject = str(subject_kind or "").strip()
    options = [
        RelationCandidate(
            template=spec.template,
            subject_kind=subject,
            object_kinds=spec.object_kinds,
            object_ref_kinds=spec.object_ref_kinds,
            parameter_types=spec.parameter_types,
            criticality=spec.default_criticality,
        )
        for spec in RELATION_CATALOG.values()
        if subject in spec.subject_kinds
    ]
    return tuple(sorted(options, key=lambda item: item.template))


__all__ = [
    "RelationCandidate",
    "RelationTemplateSpec",
    "RELATION_CATALOG",
    "relation_options",
    "relation_spec",
]
