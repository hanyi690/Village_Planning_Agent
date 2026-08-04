"""validate_layout tool — spatial layout validation against constraints and standards.

Merges:
  - app.agent.validate.aggregate           (validate_aggregate, 8 checks)
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

from app.agent.validate.aggregate import validate_aggregate


from app.tools.helpers import make_result, to_tool_message


@tool
def validate_layout(
    layout_configs: Annotated[Optional[List[Dict[str, Any]]], InjectedState("layout_configs")],
    kg_constraints: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_constraints")] = None,
    kg_protected_parcels_detail: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_protected_parcels_detail")] = None,
    kg_vne_summary: Annotated[Optional[List[Dict[str, Any]]], InjectedState("kg_vne_summary")] = None,
    auto_retry: bool = True,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Validate the generated layout against planning standards.

    Checks: zone area ratios, completeness, overlaps, protected parcels,
    minimum areas, adjacency compatibility, spatial compactness, VNE compliance.

    Phase 5: uses KG protected_parcels_detail for spatial containment checks
    and KG vne_summary for VNE classification compliance.

    Args:
        auto_retry: Generate retry suggestions if True.
    """
    if not layout_configs:
        return Command(update={
            "messages": [to_tool_message(
                make_result(False, error="No layout to validate"), tool_call_id
            )],
        })

    report = validate_aggregate(
        planned_state=None,
        changeset=None,
        layout_configs=layout_configs,
        intent=None,
        constraint_index=None,
        run_id="",
    )

    result = {
        "status": "pass" if report.overall_passed else "fail",
        "checks": [{"name": c.check_name, "passed": c.passed, "violations": len(c.affected_parcels)} for c in report.checks],
        "total_checks": len(report.checks),
        "passed_checks": sum(1 for c in report.checks if c.passed),
    }

    # Step 3: Build structured adjustments from violations
    adjustments = getattr(report, "adjustments", None) or []
    if adjustments:
        result["adjustments"] = [
            {"zone": a.zone, "action": a.action, "delta_ha": a.delta_ha,
             "reason": a.reason, "priority": a.priority}
            for a in adjustments
        ]

    if not report.overall_passed and auto_retry:
        result["retry_suggestions"] = [
            f"{c.check_name}: {c.fix_suggestion}" if c.fix_suggestion else f"{c.check_name}: adjust"
            for c in report.checks if not c.passed
        ]

    update_payload = {
        "messages": [to_tool_message(make_result(True, data=result), tool_call_id)],
    }
    # Store adjustments in state for allocate feedback (Step 3)
    if adjustments:
        update_payload["constraint_adjustments"] = [
            {"zone": a.zone, "action": a.action, "delta_ha": a.delta_ha,
             "reason": a.reason, "priority": a.priority}
            for a in adjustments
        ]

    return Command(update=update_payload)
