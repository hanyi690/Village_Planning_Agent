"""EXECUTE contract schemas — data models for constraint compilation and execution.

Defines the input/output contracts for the EXECUTE layer:
  - MIPModel: constraint compiler output (KG semantic -> MIP numerical matrix)
  - ExecutionPlan: EXECUTE input contract (intent + constraints + data)
  - ConstraintAdjustment: validation feedback for re-execution
  - ChangelogEntry: traceability record for each spatial operation

Produced by: ConstraintCompiler, ExecuteAgent
Consumed by: MIP solver, validation loop, export

Separated from parse_contracts.py because EXECUTE has different concerns
(numerical optimization, validation, changelog) than PARSE (text understanding,
intent extraction). Design doc §5.3-5.6.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── MIP constraint model (ConstraintCompiler output) ────────────────


class MIPConstraint(BaseModel):
    """Single compiled MIP constraint.

    Translates one KG semantic constraint into a numerical MIP constraint.
    """

    constraint_type: Literal["hard", "soft"] = "hard"
    name: str = ""
    parcels: List[str] = Field(default_factory=list)
    zones: List[str] = Field(default_factory=list)
    coefficient: float = 0.0
    bound: float = 0.0
    sense: Literal["<=", ">=", "=="] = "<="
    source: str = ""  # "kg_protected" / "kg_three_lines" / "intent_target" / "intent_adjacency"


class MIPModel(BaseModel):
    """Compiled MIP optimization model — output of ConstraintCompiler.

    Design doc §5.4: KG semantic constraints compiled once into numerical
    matrix before MIP solver iteration begins.
    """

    # Decision variables: parcel_bsm -> list of candidate zone names
    variables: Dict[str, List[str]] = Field(default_factory=dict)

    # Hard constraints (locked parcels, spatial bounds, capacity limits)
    hard_constraints: List[MIPConstraint] = Field(default_factory=list)

    # Soft constraints (area target deviation, adjacency preferences)
    soft_constraints: List[MIPConstraint] = Field(default_factory=list)

    # Target map: zone_name -> target_area_ha
    target_map: Dict[str, float] = Field(default_factory=dict)

    # Adjacency cost matrix: parcel_bsm -> {neighbor_bsm -> cost}
    adjacency_cost_matrix: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    # Compilation metadata
    compile_elapsed_s: float = 0.0


# ── Execution plan (EXECUTE input) ──────────────────────────────────


class ExecutionPlan(BaseModel):
    """EXECUTE input contract — bundles all data needed for execution.

    Assembled by ConstraintCompiler from PARSE output + KG queries.
    Design doc §5.5: multi-strategy execution (MIP layout + facility + axis
    + road + atomic operations).
    """

    # SpatialPlanningIntent reference (PARSE output, not embedded)
    intent: Optional[Any] = None

    # Compiled MIP model for layout sub-task
    mip_model: Optional[MIPModel] = None

    # Atomic operations for create/split/merge sub-tasks
    # List[SpatialOperation] — typed as Any to avoid circular import with parse_contracts
    operations: List[Any] = Field(default_factory=list)

    # Spatial constraints from PARSE + YAML rules
    # List[SpatialConstraint] — typed as Any to avoid circular import
    constraints: List[Any] = Field(default_factory=list)

    # KG-derived spatial context (parcel adjacency, protected parcels, three lines)
    adjacency_map: Dict[str, List[str]] = Field(default_factory=dict)
    protected_parcels: List[str] = Field(default_factory=list)
    three_lines: List[Dict[str, Any]] = Field(default_factory=list)


# ── Validation feedback (for re-execution loop) ─────────────────────


class ConstraintAdjustment(BaseModel):
    """Validation feedback item — adjusts constraints for re-execution.

    Design doc §5.6: Worker-Evaluator retry loop. When validation fails,
    the Evaluator produces adjustments that the Worker applies before
    re-executing (max 3 rounds).
    """

    constraint_id: str = ""
    adjustment_type: Literal["relax", "tighten", "reallocate"] = "relax"
    original_value: Optional[float] = None
    adjusted_value: Optional[float] = None
    reason: str = ""
    source_check: str = ""  # which of the 8 validation checks triggered this


# ── Changelog / traceability ────────────────────────────────────────


class ChangelogEntry(BaseModel):
    """Traceability record for a single spatial operation.

    Design principle #7: every parcel change must be traceable to source text.
    Design doc §5.5: each operation (create/split/merge/modify/reclassify)
    writes a changelog entry.
    """

    entry_id: str = ""
    action: str = ""  # "create" / "split" / "merge" / "modify" / "reclassify"
    target_parcels: List[str] = Field(default_factory=list)
    before_state: Dict[str, Any] = Field(default_factory=dict)
    after_state: Dict[str, Any] = Field(default_factory=dict)
    article_ref: str = ""  # source article reference
    source_text: str = ""  # source text excerpt
    timestamp: str = ""
    execution_round: int = 0


__all__ = [
    "MIPConstraint",
    "MIPModel",
    "ExecutionPlan",
    "ConstraintAdjustment",
    "ChangelogEntry",
]
