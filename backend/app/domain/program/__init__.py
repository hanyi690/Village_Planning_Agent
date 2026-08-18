"""Program synthesis and assembly."""

from .assembler import assemble_planning_program
from .aggregate import l3_aggregate, merge_program_fragments
from .classification import (
    apply_classification_decisions,
    revise_program_with_decisions,
)
from .gate import evaluate_l3_gate
from .review import build_l3_review_package
from .worker import analyze_l3_dimension

__all__ = [
    "assemble_planning_program",
    "l3_aggregate",
    "merge_program_fragments",
    "apply_classification_decisions",
    "revise_program_with_decisions",
    "evaluate_l3_gate",
    "build_l3_review_package",
    "analyze_l3_dimension",
    "interventions_from_claims",
]
from .claim_adapter import interventions_from_claims
