from typing import Iterable, List, Tuple

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.modules.kg.ontology import EntityTypes, ThreeLineSubtypes
from app.modules.schema.contracts.custom_zone_contracts import (
    CustomZoneTarget,
    Vocabulary,
    VocabularyCategory,
)
from app.modules.schema.encodings.dicts.vocabularies.loader import get_vocabulary
from app.modules.schema.provenance import ProvenanceAudit, ProvenanceSource


def _truncate_by_area(parcels: List[dict], target_ha: float) -> List[dict]:
    """Select parcels until cumulative area reaches the target (hectares).

    Parcels without area are appended last; the tail is dropped once the
    cumulative sum passes the target so the zone area aligns with the L3
    report's 【土地用途分区表】 area column.
    """
    target = max(float(target_ha), 0.0)
    if target <= 0:
        return parcels
    ordered = sorted(
        parcels,
        key=lambda p: float(p.get("area_ha", 0) or 0),
        reverse=True,
    )
    chosen: List[dict] = []
    total = 0.0
    for p in ordered:
        area = float(p.get("area_ha", 0) or 0)
        if area <= 0:
            continue
        chosen.append(p)
        total += area
        if total >= target:
            break
    return chosen


class CustomZoningGenerator:
    """Generate L4 FunctionalZone nodes from a vocabulary + planner intent.

    Inputs:
      parcels: iterable of dicts with ``bsm``, ``geometry``, optional ``dlbm``
      intent: dict (or SpatialPlanningIntent-shaped) with ``vocabulary_name``
              and ``custom_zone_targets`` (list of CustomZoneTarget)
      three_lines: dict keyed by ThreeLineSubtypes → feature list (for
              protection-line intersection checks)

    Output:
      L4 FunctionalZone feature dicts with provenance. Targets whose merged
      geometry intersects ecological/farmland protection are blocked and
      recorded in audit.
    """

    def __init__(
        self,
        parcels: Iterable[dict],
        intent: dict,
        three_lines: dict | None = None,
    ) -> None:
        self.parcels = list(parcels)
        self.intent = intent
        # Session-level in-memory Vocabulary (LLM-extracted from L3 reports)
        # takes precedence; YAML vocabulary_name remains the fallback.
        vocab = intent.get("vocabulary")
        if vocab is None:
            vocab = get_vocabulary(intent["vocabulary_name"])
        self.vocabulary: Vocabulary = vocab if isinstance(vocab, Vocabulary) else Vocabulary(**vocab)
        self.three_lines = three_lines or {}
        self.parcel_by_bsm = {p["bsm"]: p for p in self.parcels}

    def generate(self) -> List[dict]:
        zones, _ = self.generate_with_validation()
        return zones

    def generate_with_validation(self) -> Tuple[List[dict], ProvenanceAudit]:
        audit = ProvenanceAudit()
        protection = self._protection_geometry()
        zones: List[dict] = []
        for raw in self.intent.get("custom_zone_targets", []) or []:
            target = raw if isinstance(raw, CustomZoneTarget) else CustomZoneTarget(**raw)
            category = self._category_by_code(target.category_code)
            if category is None:
                audit.record(
                    f"functional_zone.{target.category_code}",
                    ProvenanceSource.CUSTOM_VOCABULARY,
                    parcel_count=0,
                    note=f"unknown category_code in vocabulary {self.vocabulary.name}",
                )
                continue
            selected = [
                self.parcel_by_bsm[bsm]
                for bsm in target.target_bsms
                if bsm in self.parcel_by_bsm
            ]
            if not selected:
                # P6.5: 无 BSM 时按类别 typing_rules 表达式自动选 parcels（多因子语义选择）
                selected = self._select_by_rules(category)
            if not selected:
                continue
            # v5: 面积目标对齐 — 规则选中的地块按面积累加到 target，超出即停
            if target.area_target_ha:
                selected = _truncate_by_area(selected, target.area_target_ha)
                if not selected:
                    continue
            # 三线拦截改为图斑级：建设类功能区剔除与保护面相交的地块，保留其余
            # （保护类功能区本身与三线重合，跳过拦截）
            if not category.is_protection and protection is not None:
                kept = [p for p in selected if not p["geometry"].intersects(protection)]
                if len(kept) != len(selected):
                    audit.record(
                        f"functional_zone.{target.category_code}",
                        ProvenanceSource.CUSTOM_VOCABULARY,
                        parcel_count=len(selected) - len(kept),
                        note="excluded: protection_line_conflict (parcel-level)",
                    )
                selected = kept
                if not selected:
                    continue
            merged = unary_union([p["geometry"] for p in selected])
            zones.append(
                {
                    "entity_type": EntityTypes.FunctionalZone,
                    "pln:vocabulary_name": self.vocabulary.name,
                    "pln:category_code": target.category_code,
                    "pln:category_name_zh": category.name_zh,
                    "pln:color": category.color,
                    "pln:target_bsms": [p["bsm"] for p in selected],
                    "pln:area_target_ha": target.area_target_ha,
                    "pln:geometry": merged,
                    "pln:decided_by": target.decided_by,
                    "pln:confidence": target.confidence,
                    "pln:encoding_provenance": ProvenanceSource.CUSTOM_VOCABULARY.value,
                }
            )
            audit.record(
                f"functional_zone.{target.category_code}",
                ProvenanceSource.CUSTOM_VOCABULARY,
                parcel_count=len(selected),
            )
        return zones, audit

    def _category_by_code(self, code: str) -> VocabularyCategory | None:
        for c in self.vocabulary.categories:
            if c.code == code:
                return c
        return None

    def _select_by_rules(self, category: VocabularyCategory) -> List[dict]:
        """Select parcels by the category's typing_rules expression DSL.

        v5 multi-factor: dlbm_in / within_zone / not_within_zone /
        slope_lt / road_distance_lt / near_poi + and/any/not composites.
        Each parcel carries a context built by the caller:
          {dlbm, area_ha, slope_deg, road_distance_m, zone_membership, poi_hits}
        """
        rules = category.typing_rules or []
        if not rules:
            return []
        contexts = self._parcel_contexts
        if not contexts:
            contexts = {
                p["bsm"]: {
                    "dlbm": str(p.get("dlbm", "")),
                    "area_ha": float(p.get("area_ha", 0) or 0),
                    "slope_deg": float(p.get("slope_deg", 999) or 999),
                    "road_distance_m": float(p.get("road_distance_m", 99999) or 99999),
                    "zone_membership": list(p.get("zone_membership", []) or []),
                    "poi_hits": list(p.get("poi_hits", []) or []),
                }
                for p in self.parcels
            }
            self._parcel_contexts = contexts
        return [
            p for p in self.parcels
            if any(self._eval_rule(r, contexts[p["bsm"]]) for r in rules)
        ]

    _parcel_contexts: dict = None

    def _eval_rule(self, rule: "TypingRule", ctx: dict) -> bool:
        kind = rule.kind
        value = rule.value
        if kind == "and":
            return all(self._eval_rule(c, ctx) for c in (rule.children or []))
        if kind == "any":
            return any(self._eval_rule(c, ctx) for c in (rule.children or []))
        if kind == "not":
            return not (rule.children and self._eval_rule(rule.children[0], ctx))
        if kind == "dlbm_in":
            return str(ctx["dlbm"]) in [str(v) for v in (value or [])]
        if kind == "field_equals":
            return str(ctx.get(str(value.get("field", "")), "")) == str(value.get("value", ""))
        if kind == "within_zone":
            return value in ctx["zone_membership"]
        if kind == "not_within_zone":
            return value not in ctx["zone_membership"]
        if kind == "slope_lt":
            return ctx["slope_deg"] < float(value)
        if kind == "road_distance_lt":
            return ctx["road_distance_m"] < float(value)
        if kind == "near_poi":
            return any(
                str(value) in str(h.get("name", ""))
                for h in ctx["poi_hits"]
            )
        return False

    def _protection_geometry(self) -> BaseGeometry | None:
        geoms: List[BaseGeometry] = []
        for subtype in (
            ThreeLineSubtypes.ECOLOGICAL_REDLINE,
            ThreeLineSubtypes.FARMLAND_REDLINE,
        ):
            for f in self.three_lines.get(subtype, []) or []:
                g = f.get("geometry")
                if g is not None:
                    geoms.append(g)
        return unary_union(geoms) if geoms else None