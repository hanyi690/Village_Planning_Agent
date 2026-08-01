from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TypingRule(BaseModel):
    """Single rule for classifying parcels into a vocabulary category.

    ``kind`` discriminates the rule type; ``value`` carries the operands.
    """

    kind: Literal["dlbm_in", "field_equals", "within_zone", "slope_lt", "road_distance_lt"]
    value: object


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
    vocabulary_name: str
    category_code: str
    target_bsms: List[str] = Field(default_factory=list)
    target_bbox: Optional[List[float]] = None
    spatial_preference: Optional[Literal["near", "far", "central", "edge"]] = None
    density: Optional[str] = None
    decided_by: Literal["llm", "human", "rule"] = "llm"
    confidence: float = 0.85