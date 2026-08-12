from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class Document(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str = ""
    doc_type: str = ""
    source: str = ""


class ReferencePlanningText(Document):
    doc_type: str = "planning_text"


class L3Report(Document):
    doc_type: str = "l3_report"
    structured_summary: Dict[str, Any] = Field(default_factory=dict)


__all__ = ["Document", "ReferencePlanningText", "L3Report"]