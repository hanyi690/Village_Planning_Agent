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
                # P6.5: 无 BSM 时按类别 typing_rules(dlbm_in) 自动选 parcels（语义规则选择）
                selected = self._select_by_rules(category)
            if not selected:
                continue
            merged = unary_union([p["geometry"] for p in selected])
            if protection is not None and merged.intersects(protection):
                audit.record(
                    f"functional_zone.{target.category_code}",
                    ProvenanceSource.CUSTOM_VOCABULARY,
                    parcel_count=len(selected),
                    note="blocked: protection_line_conflict",
                )
                continue
            zones.append(
                {
                    "entity_type": EntityTypes.FunctionalZone,
                    "pln:vocabulary_name": self.vocabulary.name,
                    "pln:category_code": target.category_code,
                    "pln:category_name_zh": category.name_zh,
                    "pln:color": category.color,
                    "pln:target_bsms": [p["bsm"] for p in selected],
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
        """Select parcels by the category's typing_rules (dlbm_in) when no
        target_bsms were provided — semantic rule selection."""
        codes = set()
        for rule in category.typing_rules or []:
            if rule.kind == "dlbm_in":
                codes.update(str(v) for v in (rule.value or []))
        if not codes:
            return []
        return [p for p in self.parcels if str(p.get("dlbm", "")) in codes]

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