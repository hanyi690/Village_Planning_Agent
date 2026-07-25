"""PipelineTrace — full process recording for parse→layout→validate pipeline."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ParseTrace(BaseModel):
    source: str = ""  # "db_reports" | "jintian_reports" | "planning_text"
    llm_model: str = ""
    llm_prompt: str = ""
    llm_response: str = ""
    llm_retry_count: int = 0
    correction_round: bool = False
    correction_prompt: str = ""
    correction_response: str = ""
    anchors: Dict[str, Any] = {}
    anchor_confidence: str = ""  # "high" | "medium" | "low"
    semantic_validation_passed: bool = True
    semantic_violations: List[str] = []
    timing_ms: int = 0


class KGTrace(BaseModel):
    built: bool = False
    parcel_count: int = 0
    triple_count: int = 0
    constraint_count: int = 0
    indicator_count: int = 0
    adjacency_edge_count: int = 0
    triples_sample: List[Dict] = []
    constraints_detail: Dict[str, Any] = {}
    timing_ms: int = 0


class ConflictTrace(BaseModel):
    metric_conflicts: List[Dict] = []
    constraint_violations: List[Dict] = []
    resolution_applied: List[Dict] = []
    timing_ms: int = 0


class MIPTrace(BaseModel):
    mode: str = ""  # "KG-driven" | "DLBM-only"
    solver_status: str = ""  # "Optimal" | "Not Solved" | ...
    variable_count: int = 0
    binary_variable_count: int = 0
    objective_value: float = 0.0
    time_limit_seconds: int = 0
    zone_targets: Dict[str, float] = {}
    zone_actual: Dict[str, float] = {}
    zone_deviations: Dict[str, float] = {}
    kg_slack_values: Dict[str, float] = {}
    adjacency_pairs: int = 0
    changed_parcels: int = 0
    changed_pct: float = 0.0
    timing_ms: int = 0
    metadata: Dict[str, Any] = {}  # density_hints, adjacency_rules, parse_constraint_count


class ValidationRound(BaseModel):
    round_number: int = 0
    total_violations: int = 0
    violations: List[Dict] = []
    adjustments: Dict[str, float] = {}
    damping: float = 0.0
    timing_ms: int = 0


class ValidationLoopTrace(BaseModel):
    rounds: List[ValidationRound] = []
    final_status: str = ""  # "pass" | "warning" | "fail"


class PipelineTrace(BaseModel):
    parse: Optional[ParseTrace] = None
    kg: Optional[KGTrace] = None
    conflicts: Optional[ConflictTrace] = None
    mip: Optional[MIPTrace] = None
    validation: Optional[ValidationLoopTrace] = None
    total_timing_ms: int = 0
