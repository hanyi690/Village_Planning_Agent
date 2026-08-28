"""Closed relation catalogue used by Target Projection.

The catalogue is intentionally declarative.  It is the single place where
the compiler learns which typed parameters, target kinds and evaluator a
relation template requires.  It does not create geometry or infer numeric
thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
import json


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

_RELATION_SUBJECT_KIND_ALIASES = {
    "restoration_overlay": "site_area",
    "restorationoverlay": "site_area",
    "protection_overlay": "site_area",
    "protectionoverlay": "site_area",
    "land_use_assignment": "zone",
    "landuseassignment": "zone",
}


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


def normalize_relation_subject_kind(subject_kind: str) -> str:
    """Return the catalogue subject kind for one provider component kind."""

    normalized = str(subject_kind or "").strip().lower()
    return _RELATION_SUBJECT_KIND_ALIASES.get(normalized, normalized)


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


def relation_options_payload(
    subject_kinds: tuple[str, ...] = (
        "facility",
        "road",
        "linear",
        "axis",
        "site_area",
        "zone",
    ),
) -> dict[str, list[dict[str, object]]]:
    """Render the provider-facing relation catalogue from the same source."""

    payload: dict[str, list[dict[str, object]]] = {}
    for raw_kind in subject_kinds:
        kind = normalize_relation_subject_kind(raw_kind)
        payload[kind] = [
            {
                "relation_template": item.template,
                "object_ref_kinds": sorted(item.object_ref_kinds),
                "parameter_types": sorted(item.parameter_types),
                "default_criticality": item.criticality,
            }
            for item in relation_options(kind)
        ]
    return payload


def relation_options_prompt_payload(
    subject_kinds: tuple[str, ...] = (
        "facility",
        "road",
        "linear",
        "axis",
        "site_area",
        "zone",
    ),
) -> dict[str, object]:
    """Render a deduplicated relation catalogue for bounded prompts."""

    expanded = relation_options_payload(subject_kinds)
    options_by_subject_kind: dict[str, list[dict[str, str]]] = {}
    relation_specs: dict[str, dict[str, object]] = {}
    for subject_kind, options in expanded.items():
        options_by_subject_kind[subject_kind] = []
        for option in options:
            template = str(option["relation_template"])
            options_by_subject_kind[subject_kind].append({
                "relation_template": template,
            })
            relation_specs.setdefault(template, {
                "object_ref_kinds": option["object_ref_kinds"],
                "parameter_types": option["parameter_types"],
                "default_criticality": option["default_criticality"],
            })
    return {
        "relation_options_by_subject_kind": options_by_subject_kind,
        "relation_specs": relation_specs,
    }


def render_relation_options_contract(
    subject_kinds: tuple[str, ...] = (
        "facility",
        "road",
        "linear",
        "axis",
        "site_area",
        "zone",
    ),
) -> str:
    """Render an auditable explanation for the dynamic relation closed set."""

    payload = json.dumps(
        relation_options_payload(subject_kinds),
        ensure_ascii=False,
        sort_keys=True,
    )
    return (
        "【L3 relation_template 运行时闭集】\n"
        "relation_template 必须逐字复制当前 component_kind 对应的关系候选；"
        "object_ref_kind 和 parameters 也必须符合同一候选项。"
        "connect_network 是道路/线性设施的网络关系模板；connects 不是 relation_template，"
        "只能作为 road_parameters、linear_parameters 或 axis_parameters 中的端点/地点提示。"
        "没有合适关系时 relations 必须为 []，不得使用别名、自然语言或旧模板名。\n"
        + payload
    )


__all__ = [
    "RelationCandidate",
    "RelationTemplateSpec",
    "RELATION_CATALOG",
    "normalize_relation_subject_kind",
    "relation_options",
    "relation_options_payload",
    "relation_options_prompt_payload",
    "relation_spec",
    "render_relation_options_contract",
]
