"""Provider-facing L1 dual-response drafts (normalized into L1 contracts)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class L1ObservationDraft(BaseModel):
    """Provider-facing L1 现状 observation before domain normalization.

    The L1 LLM returns these structured rows as part of the dual-response
    output; they are compiled into ``L1LocationFact`` (with a typed role) by the
    observation profile, replacing the legacy markdown-table parsing.
    """

    entity_type: str = ""  # 现状设施 / 现状项目 / 现状分区 / 道路 / 水系 / 地物
    name: str = ""
    location: str = ""
    relation: str = ""  # 与其他地点的空间关系（位于X村中部/沿石窟河/汇入石窟河/通往X村）
    description: str = ""
    scale: str = ""


class L1DimensionOutput(BaseModel):
    """Dual-response L1 output: narrative report body + structured observations."""

    report_body: str = Field(min_length=1)
    observations: list[L1ObservationDraft] = Field(default_factory=list)


__all__ = ["L1DimensionOutput", "L1ObservationDraft"]
