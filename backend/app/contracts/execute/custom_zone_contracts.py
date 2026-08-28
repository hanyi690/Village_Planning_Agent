import hashlib
import json
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.classification_ref import ClassificationDecision


class TypingRule(BaseModel):
    """Rule for classifying parcels into a vocabulary category.

    v5 multi-factor: kinds form a small expression DSL —
      leaf: dlbm_in / field_equals / within_zone / not_within_zone /
            slope_lt / road_distance_lt / near_poi
      composite: and / any / not (children)
    ``value`` carries the operands; leaf rules evaluate against the parcel
    context (dlbm, area_ha, slope_deg, road_distance_m, zone_membership,
    poi_hits).
    """

    kind: Literal[
        "dlbm_in", "field_equals", "within_zone", "not_within_zone",
        "slope_lt", "road_distance_lt", "near_poi", "and", "any", "not",
    ]
    value: object = None
    children: List["TypingRule"] = Field(default_factory=list)


class VocabularyCategory(BaseModel):
    code: str
    name_zh: str
    name_en: Optional[str] = None
    color: str = "#888888"
    typing_rules: List[TypingRule] = Field(default_factory=list)
    # 保护类功能区（生态保护区/农田保护区等）本身与三线重合，
    # 不参与 protection_line_conflict 拦截；建设类功能区必须避开三线。
    is_protection: bool = False


class Vocabulary(BaseModel):
    name: str
    description: Optional[str] = None
    categories: List[VocabularyCategory] = Field(default_factory=list)
    incompatibilities: List[List[str]] = Field(default_factory=list)


class CustomZoneTarget(BaseModel):
    target_id: str = ""
    vocabulary_name: str
    category_code: str
    target_bsms: List[str] = Field(default_factory=list)
    target_bbox: Optional[List[float]] = None
    spatial_preference: Optional[Literal["near", "far", "central", "edge"]] = None
    density: Optional[str] = None
    # v5: L3 报告分区表的面积目标（公顷）— 规则选择地块后按此截断对齐
    area_target_ha: Optional[float] = None
    decided_by: Literal["llm", "human", "rule"] = "llm"
    confidence: float = 0.85
    classification_decision: ClassificationDecision | None = None

    @model_validator(mode="after")
    def assign_target_id(self) -> "CustomZoneTarget":
        if self.target_id:
            return self
        identity = {
            "area_target_ha": self.area_target_ha,
            "category_code": self.category_code,
            "density": self.density,
            "spatial_preference": self.spatial_preference,
            "target_bbox": self.target_bbox,
            "target_bsms": sorted(str(bsm) for bsm in self.target_bsms),
            "vocabulary_name": self.vocabulary_name,
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        self.target_id = f"custom-zone:{digest}"
        return self
