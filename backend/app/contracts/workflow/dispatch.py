"""Dispatch contracts (blueprint M0/M5 boundary).

The canonical policy implementation lives in ``app.workflow.dispatch``; this
module is the stable contract import path for application and workflow code.
"""

from __future__ import annotations

from app.workflow.dispatch import (
    DispatchAction,
    DispatchCommand,
    DispatchDecision,
    DispatchDiagnostic,
    DispatchDiagnosticCode,
    DispatchPolicy,
    DispatchPolicyDecision,
    DispatchProposal,
    evaluate_dispatch,
    parse_and_evaluate_dispatch,
)

__all__ = [
    "DispatchAction",
    "DispatchCommand",
    "DispatchDecision",
    "DispatchDiagnostic",
    "DispatchDiagnosticCode",
    "DispatchPolicy",
    "DispatchPolicyDecision",
    "DispatchProposal",
    "evaluate_dispatch",
    "parse_and_evaluate_dispatch",
]
