"""detect_conflicts tool — cross-dimension conflict detection and resolution.

Merges:
  - layout/conflict/detector.py  (ConflictDetector)
  - layout/conflict/resolver.py  (ConflictResolver)
  - tools/gis/layout_tools.py    (detect_conflicts @tool)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Re-export from the existing modules for backward compatibility
from app.modules.gis.analysis.conflict.detector import (
    ConflictDetector,
    ConflictReport,
    MetricConflict,
    ConstraintViolation,
    SpatialConflict,
)
from app.modules.gis.analysis.conflict.resolver import (
    ConflictResolver,
    ResolutionReport,
)


from app.tools.helpers import make_result, to_tool_message


@tool
def detect_conflicts(
    summaries: Annotated[Dict[str, Dict[str, Any]], InjectedState("summaries")],
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Detect cross-dimension conflicts between planning dimension summaries.

    Returns conflict report with metric conflicts, constraint violations,
    and spatial conflicts. Data auto-injected from state.
    """
    detector = ConflictDetector()
    report = detector.detect_all(summaries)

    resolution_report = None
    if report.has_conflicts:
        resolver = ConflictResolver()
        resolution_report = resolver.resolve(report)

    result = make_result(True, data={
        "conflict_count": report.total_count,
        "has_conflicts": report.has_conflicts,
        "summary": report.summary(),
        "resolved": resolution_report is not None,
    })

    return Command(update={
        "messages": [to_tool_message(result, tool_call_id)],
    })
