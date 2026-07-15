"""Semantic validation + area_ratio normalization for structured parse results.

Schema compliance is handled by Instructor (max_retries=3).
This module handles semantic issues that schemas cannot express:
- area_ratio total must be ~1.0
- Anchored value cross-checks
- Required zone existence
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Result of semantic validation."""

    passed: bool = True
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
        }


# Land use types classified as "construction" for cross-check
_CONSTRUCTION_TYPES = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}

# Minimum required land use types
_REQUIRED_TYPES = {"农业用地"}


def semantic_validate(
    intent_output: Any,
    anchors: Optional[Any] = None,
    tolerance: float = 0.05,
) -> ValidationResult:
    """Validate semantic correctness of parsed intent.

    Args:
        intent_output: IntentOutput Pydantic instance.
        anchors: MetricAnchors (optional, for cross-check).
        tolerance: Allowed deviation from expected values (default 5%).

    Returns:
        ValidationResult with passed=True/False and violations list.
    """
    violations = []

    # 1. area_ratio total must be ~1.0
    zones = getattr(intent_output, "zones", [])
    total = sum(z.area_ratio for z in zones)
    if abs(total - 1.0) > tolerance:
        violations.append(f"area_ratio total={total:.4f}, expected ~1.0 (tolerance {tolerance})")

    # 2. Anchored value cross-check (if anchors provided)
    if anchors is not None and hasattr(anchors, "zone_ratios") and anchors.zone_ratios:
        construction_ratio = sum(
            z.area_ratio for z in zones
            if z.land_use in _CONSTRUCTION_TYPES
        )
        expected = anchors.zone_ratios.get("村庄建设区", 0)
        if abs(construction_ratio - expected) > tolerance:
            violations.append(
                f"Construction ratio: LLM={construction_ratio:.4f}, anchor={expected:.4f}"
            )

    # 3. Required zone types exist
    present = {z.land_use for z in zones}
    for req in _REQUIRED_TYPES:
        if req not in present:
            violations.append(f"Missing required zone type: {req}")

    # 4. At least 3 zones
    if len(zones) < 3:
        violations.append(f"Only {len(zones)} zones (minimum 3)")

    return ValidationResult(passed=len(violations) == 0, violations=violations)


def normalize_area_ratios(
    intent_output: Any,
    tolerance: float = 0.05,
) -> Any:
    """Normalize area_ratio values to sum=1.0 if total deviates.

    This is the preserved normalization logic from _postprocess_llm_response.
    Each zone's ratio is divided by total, then residual is added to the first zone.

    Args:
        intent_output: IntentOutput Pydantic instance (mutable).
        tolerance: Only normalize if deviation > tolerance.

    Returns:
        Modified intent_output (same instance).
    """
    zones = getattr(intent_output, "zones", [])
    if not zones:
        return intent_output

    total = sum(z.area_ratio for z in zones)
    if abs(total - 1.0) <= tolerance:
        return intent_output  # No need to normalize

    logger.info("[normalize] area_ratio total=%.4f, normalizing", total)

    # Divide each by total
    for z in zones:
        z.area_ratio = round(z.area_ratio / total, 4)

    # Fix residual
    new_sum = sum(z.area_ratio for z in zones)
    if abs(new_sum - 1.0) > 0.001 and zones:
        diff = 1.0 - new_sum
        zones[0].area_ratio = round(zones[0].area_ratio + diff, 4)

    return intent_output
