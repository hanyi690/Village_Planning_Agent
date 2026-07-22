"""validate_layout tool — spatial layout validation against constraints and standards.

Merges:
  - layout/validation/layout_validator.py  (LayoutValidator, 8 checks)
  - layout/validation/facility_validator.py (facility siting validation)
  - tools/gis/layout_tools.py              (validate_layout @tool)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Re-export existing validators
from app.modules.gis.analysis.validation.layout_validator import (
    LayoutValidator,
    ValidationReport,
    Violation,
    CheckResult,
)


from app.tools.helpers import make_result, to_tool_message


@tool
def validate_layout(
    layout_configs: Annotated[Optional[List[Dict[str, Any]]], InjectedState("layout_configs")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")] = None,
    auto_retry: bool = True,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Validate the generated layout against planning standards.

    Checks: zone area ratios, completeness, overlaps, protected parcels,
    minimum areas, adjacency compatibility, spatial compactness.

    Args:
        auto_retry: Generate retry suggestions if True.
    """
    if not layout_configs:
        return Command(update={
            "messages": [to_tool_message(
                make_result(False, error="No layout to validate"), tool_call_id
            )],
        })

    validator = LayoutValidator()
    report = validator.validate(layout_configs)

    result = {
        "status": report.status,
        "checks": [{"name": c.check_name, "passed": c.passed, "violations": len(c.violations)} for c in report.checks],
        "total_checks": len(report.checks),
        "passed_checks": sum(1 for c in report.checks if c.passed),
    }

    if report.status == "fail" and auto_retry:
        result["retry_suggestions"] = [
            f"{c.check_name}: {c.violations[0].message}" if c.violations else f"{c.check_name}: adjust"
            for c in report.checks if not c.passed
        ]

    return Command(update={
        "messages": [to_tool_message(make_result(True, data=result), tool_call_id)],
    })
