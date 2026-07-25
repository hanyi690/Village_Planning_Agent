"""Document types — 半结构化文本文档 (第四形态).

规划文本、L3 报告等非结构化/半结构化数据,
走与矢量/栅格/表格同样的抽象层级.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Document:
    """半结构化文本文档基类."""
    text: str = ""
    doc_type: str = ""
    source: str = ""
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class PlanningText(Document):
    """规划说明文本 (markdown)."""
    doc_type: str = "planning_text"


@dataclass
class L3Report(Document):
    """L3 维度报告 (JSON, 含结构化摘要 + 原文)."""
    doc_type: str = "l3_report"
    structured_summary: Dict[str, Any] = field(default_factory=dict)


__all__ = ["Document", "PlanningText", "L3Report"]