"""Deterministic admission for L1 semantic spatial work items.

The L1 provider is allowed to *propose* that a source-backed phrase denotes a
spatial object.  It is not allowed to make that proposal authoritative merely
by selecting ``fact_type=spatial_entity``.  This module supplies the local,
format-neutral guard used by the provider boundary, the source validator, and
the L1 compiler backstop.

The guard deliberately knows generic semantic families (road, water,
facility, parcel, settlement, and so on), not bundle layer names or source
attribute names.  Unknown source schemas therefore remain usable.  Ambiguous
phrases remain ordinary facts/gaps instead of being promoted to GROUND work
items.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SpatialAdmissionDecision:
    """Result of one semantic spatial-admission check."""

    admitted: bool
    reason_code: str
    signals: tuple[str, ...] = ()


_ENTITY_TYPE_ALIASES = {
    "administrative_area": "administrative_area",
    "administrative_village": "settlement",
    "area": "zone",
    "building": "building",
    "facility": "facility",
    "hazard": "hazard",
    "hazard_site": "hazard",
    "land_parcel": "parcel",
    "landmark": "landmark",
    "natural_feature": "natural_feature",
    "natural_village": "settlement",
    "parcel": "parcel",
    "place": "place",
    "public_space": "public_space",
    "road": "road",
    "road_segment": "road",
    "settlement": "settlement",
    "utility": "utility",
    "water": "water",
    "water_body": "water",
    "zone": "zone",
    "区域": "zone",
    "地块": "parcel",
    "地标": "landmark",
    "建筑": "building",
    "村庄": "settlement",
    "水体": "water",
    "灾害点": "hazard",
    "设施": "facility",
    "道路": "road",
}

_ENTITY_TYPE_MARKERS = (
    "administrative",
    "building",
    "facility",
    "hazard",
    "landmark",
    "parcel",
    "place",
    "road",
    "settlement",
    "site",
    "utility",
    "water",
    "zone",
    "区域",
    "地块",
    "建筑",
    "村",
    "水",
    "灾害",
    "设施",
    "道路",
)

_SPATIAL_ROLES = frozenset(
    {
        "administrative_area",
        "administrative_village",
        "area",
        "building",
        "facility",
        "hazard",
        "landmark",
        "natural_feature",
        "natural_village",
        "parcel",
        "place",
        "public_space",
        "road",
        "settlement",
        "utility",
        "water",
        "zone",
        "区域",
        "地块",
        "地点",
        "建筑",
        "村庄",
        "水体",
        "灾害点",
        "设施",
        "道路",
    }
)

# These endings describe an analysis topic, state, action, capability, or
# planning judgement.  They are rejection evidence only; absence of such an
# ending never proves that a phrase is a place.
_ABSTRACT_TERMINALS = (
    "分析",
    "评估",
    "现状评估",
    "评价",
    "发展",
    "提升",
    "优化",
    "完善",
    "建设",
    "治理",
    "规划",
    "定位",
    "目标",
    "策略",
    "措施",
    "条件",
    "水平",
    "现状",
    "问题",
    "短板",
    "缺失",
    "不足",
    "需求",
    "诉求",
    "能力",
    "体系",
    "布局",
    "模式",
    "路径",
    "方向",
    "任务",
    "导向",
    "结构",
    "效率",
    "特征",
    "趋势",
    "情况",
    "概况",
)

_ABSTRACT_EXACT = frozenset(
    {
        "农业",
        "产业",
        "交通",
        "公共服务",
        "基础设施",
        "生态环境",
        "土地利用",
        "设施现状",
        "道路交通",
        "上位规划",
        "村民意愿",
    }
)

# A terminal physical designator prevents a legitimate proper name such as
# “农业发展大道” from being rejected merely because it contains an abstract
# word.  This is intentionally a semantic vocabulary, not a layer/field list.
_PHYSICAL_NAME_TERMINALS = (
    "村委会",
    "居委会",
    "服务站",
    "工作站",
    "卫生站",
    "卫生室",
    "学校",
    "小学",
    "中学",
    "幼儿园",
    "医院",
    "祠堂",
    "寺",
    "庙",
    "亭",
    "塔",
    "桥",
    "隧道",
    "大道",
    "公路",
    "道路",
    "路",
    "街",
    "巷",
    "道",
    "河",
    "江",
    "溪",
    "沟",
    "渠",
    "塘",
    "湖",
    "水库",
    "山",
    "岭",
    "坡",
    "谷",
    "村",
    "镇",
    "乡",
    "县",
    "区",
    "市",
    "站",
    "场",
    "园",
    "馆",
    "中心",
    "厂",
    "所",
    "院",
    "楼",
    "房",
    "坝",
    "井",
    "矿",
    "公园",
    "广场",
    "地块",
    "片区",
    "保护区",
    "灾害点",
)

_MULTI_TOPIC_SEPARATOR_RE = re.compile(r"[、,，;；|/]+")


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "").strip())


def _token(value: Any) -> str:
    return re.sub(r"[\s\-/]+", "_", _text(value).casefold())


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [_text(item) for item in value if _text(item)]
    return []


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def normalize_spatial_entity_family(value: Any) -> str:
    """Normalize a provider entity type to an open generic family."""

    raw = _token(value)
    if raw in _ENTITY_TYPE_ALIASES:
        return _ENTITY_TYPE_ALIASES[raw]
    for marker in _ENTITY_TYPE_MARKERS:
        if marker in raw:
            return _ENTITY_TYPE_ALIASES.get(marker, marker)
    return ""


def looks_like_abstract_topic(value: Any) -> bool:
    """Return whether a phrase positively describes a non-spatial topic."""

    name = re.sub(r"\s+", "", _text(value))
    if not name:
        return True
    if name.endswith(_PHYSICAL_NAME_TERMINALS):
        return False
    if name in _ABSTRACT_EXACT:
        return True
    parts = [part for part in _MULTI_TOPIC_SEPARATOR_RE.split(name) if part]
    if len(parts) > 1:
        return True
    return name.endswith(_ABSTRACT_TERMINALS)


def evaluate_location_name(
    name: Any,
    *,
    role: Any = "",
    relation: Any = "",
    source_feature_ids: Iterable[Any] = (),
    source_quote: Any = "",
) -> SpatialAdmissionDecision:
    """Admit one proposed named place/object without resolving its identity."""

    normalized = _text(name)
    if not normalized:
        return SpatialAdmissionDecision(False, "location_name_missing")
    if len(normalized) > 160:
        return SpatialAdmissionDecision(False, "location_name_too_long")
    if looks_like_abstract_topic(normalized):
        return SpatialAdmissionDecision(False, "abstract_topic_not_location")

    signals: list[str] = []
    if _values(source_feature_ids):
        signals.append("source_feature_ref")
    role_token = _token(role)
    if role_token in _SPATIAL_ROLES or normalize_spatial_entity_family(role_token):
        signals.append("spatial_role")
    if _text(relation):
        signals.append("spatial_relation")
    if normalized.endswith(_PHYSICAL_NAME_TERMINALS):
        signals.append("physical_name_designator")
    quote = re.sub(r"\s+", "", _text(source_quote))
    if quote and re.sub(r"\s+", "", normalized) in quote:
        signals.append("literal_source_quote")

    # ``place_names`` is already an explicit provider column.  A non-abstract,
    # bounded literal is a valid unresolved work item even when its exact type
    # is unknown; identity and geometry still remain for Evidence/GROUND.
    signals.append("explicit_location_column")
    return SpatialAdmissionDecision(
        True,
        "location_candidate_admitted",
        tuple(dict.fromkeys(signals)),
    )


def evaluate_spatial_entity(
    observation: Any = None,
    *,
    name: Any = "",
    entity_type: Any = "",
    role: Any = "",
    relation: Any = "",
    place_names: Iterable[Any] = (),
    source_feature_ids: Iterable[Any] = (),
    source_quote: Any = "",
) -> SpatialAdmissionDecision:
    """Admit a provider ``spatial_entity`` proposal as a semantic work item."""

    if observation is not None:
        name = _value(observation, "name", name)
        entity_type = _value(observation, "entity_type", entity_type)
        role = _value(observation, "role", role)
        source_quote = _value(observation, "source_quote", source_quote)
        locator = _value(observation, "locator", None)
        relation = _value(locator, "relation", relation)
        place_names = _value(locator, "place_names", place_names)
        source_feature_ids = [
            *_values(_value(observation, "source_feature_ids", ())),
            *_values(_value(locator, "source_feature_ids", source_feature_ids)),
        ]

    normalized_name = _text(name)
    if not normalized_name:
        return SpatialAdmissionDecision(False, "spatial_entity_name_missing")
    if looks_like_abstract_topic(normalized_name):
        return SpatialAdmissionDecision(False, "abstract_topic_not_spatial_entity")

    signals: list[str] = []
    family = normalize_spatial_entity_family(entity_type)
    if family:
        signals.append(f"entity_family:{family}")
    if _values(source_feature_ids):
        signals.append("source_feature_ref")
    if _values(place_names):
        signals.append("named_scope")
    if _text(relation):
        signals.append("spatial_relation")
    role_token = _token(role)
    if role_token in _SPATIAL_ROLES or normalize_spatial_entity_family(role_token):
        signals.append("spatial_role")
    if normalized_name.endswith(_PHYSICAL_NAME_TERMINALS):
        signals.append("physical_name_designator")
    quote = re.sub(r"\s+", "", _text(source_quote))
    if quote and re.sub(r"\s+", "", normalized_name) in quote:
        signals.append("literal_source_quote")

    if not signals or set(signals) == {"literal_source_quote"}:
        return SpatialAdmissionDecision(
            False,
            "spatial_entity_semantics_unverified",
            tuple(signals),
        )
    return SpatialAdmissionDecision(
        True,
        "spatial_entity_admitted",
        tuple(dict.fromkeys(signals)),
    )


def spatial_labels(observation: Any) -> tuple[str, ...]:
    """Return every label that a typed observation asks L1 to spatialize."""

    fact_type = _text(_value(observation, "fact_type", ""))
    labels: list[str] = []
    locator = _value(observation, "locator", None)
    if fact_type == "spatial_entity":
        labels.append(_text(_value(observation, "name", "")))
        labels.extend(_values(_value(locator, "place_names", ())))
    elif fact_type == "spatial_relation":
        labels.extend(
            (
                _text(_value(observation, "subject_ref", "")),
                _text(_value(observation, "object_ref", "")),
            )
        )
    elif fact_type in {"demand", "constraint", "risk", "opportunity"}:
        labels.extend(_values(_value(locator, "place_names", ())))
    return tuple(dict.fromkeys(label for label in labels if label))


def label_is_literal_in_source(label: Any, source_text: Any) -> bool:
    """Check literal source support with presentation-only normalization."""

    normalized_label = re.sub(r"\s+", "", _text(label))
    normalized_source = re.sub(r"\s+", "", _text(source_text))
    return bool(normalized_label and normalized_label in normalized_source)


__all__ = [
    "SpatialAdmissionDecision",
    "evaluate_location_name",
    "evaluate_spatial_entity",
    "label_is_literal_in_source",
    "looks_like_abstract_topic",
    "normalize_spatial_entity_family",
    "spatial_labels",
]
