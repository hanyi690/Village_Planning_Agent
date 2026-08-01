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


def _supplement_by_area(
    selected: List[dict],
    target_ha: float,
    parcels: Iterable[dict],
    rules=None,
    contexts=None,
) -> Tuple[List[dict], bool]:
    """命中不足时从候选池补足至目标面积的 ±30% 区间（用户确认的近似策略）。

    候选池排序：规则部分命中数降序（语义接近优先）→ 面积降序。
    返回 (补足后的地块列表, 是否发生了补充)。
    """
    target = max(float(target_ha or 0), 0.0)
    if target <= 0:
        return selected, False
    total = sum(float(p.get("area_ha", 0) or 0) for p in selected)
    if total >= 0.7 * target:
        return selected, False
    chosen_bsms = {p["bsm"] for p in selected}
    pool = [
        p for p in parcels
        if p["bsm"] not in chosen_bsms and float(p.get("area_ha", 0) or 0) > 0
    ]

    def _score(p):
        if rules and contexts:
            from app.agent.gis.vocab.rules import rule_to_condition
            hit = 0
            for r in rules:
                try:
                    if rule_to_condition(r).evaluate(contexts[p["bsm"]]):
                        hit += 1
                except Exception:
                    pass
            return (hit, float(p.get("area_ha", 0) or 0))
        return (0, float(p.get("area_ha", 0) or 0))

    pool.sort(key=_score, reverse=True)
    supplemented = False
    for p in pool:
        if total >= 0.7 * target:
            break
        selected.append(p)
        total += float(p.get("area_ha", 0) or 0)
        supplemented = True
    return selected, supplemented


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
            # v5: 面积目标对齐 — 规则选中的地块按面积累加到 target，超出即停；
            # 命中不足时按用户确认的近似策略从候选池补足至 ±30% 区间
            supplemented = False
            if target.area_target_ha:
                selected = _truncate_by_area(selected, target.area_target_ha)
                if not selected:
                    continue
                selected, supplemented = _supplement_by_area(
                    selected,
                    target.area_target_ha,
                    self.parcels,
                    rules=category.typing_rules or None,
                    contexts=getattr(self, "_parcel_contexts", None),
                )
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
            decided_by = "supplement" if supplemented else (target.decided_by or "rule")
            confidence = round((target.confidence or 0.7) * (0.7 if supplemented else 1.0), 3)
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
                    "pln:decided_by": decided_by,
                    "pln:confidence": confidence,
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
        """Select parcels by the category's typing_rules — unified expr_eval DSL.

        v5 multi-factor: dlbm_in / within_zone / not_within_zone /
        slope_lt / road_distance_lt / near_poi + and/any/not composites.
        Evaluation delegates to ``app.agent.gis.vocab.rules`` (expr_eval),
        removing the previous duplicate hand-rolled evaluator.
        """
        from app.agent.gis.vocab.rules import evaluate_rules, parcel_to_context

        rules = category.typing_rules or []
        if not rules:
            return []
        contexts = self._parcel_contexts
        if not contexts:
            contexts = {
                p["bsm"]: parcel_to_context(p)
                for p in self.parcels
            }
            self._parcel_contexts = contexts
        return [
            p for p in self.parcels
            if evaluate_rules(rules, contexts[p["bsm"]])
        ]

    _parcel_contexts: dict = None

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