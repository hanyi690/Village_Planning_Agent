"""Business-owned facade for dimension lifecycle side effects.

L1/L2/L3 may use these typed lifecycle hooks without importing the provider
and persistence implementation.  The implementation remains centralized in
the Evidence Runtime adapter.
"""

from app.infrastructure.evidence_runtime.dimension_runtime import (
    dimension_failure_attempt,
    is_provider_failure,
    is_provider_quota_exhausted,
    provider_failure_open,
    publish_dimension_complete,
    publish_dimension_delta,
    publish_dimension_start,
    save_report_immediate,
    save_step_report,
    strip_model_reasoning,
    trip_provider_failure,
)

__all__ = [
    "dimension_failure_attempt",
    "is_provider_failure",
    "is_provider_quota_exhausted",
    "provider_failure_open",
    "publish_dimension_complete",
    "publish_dimension_delta",
    "publish_dimension_start",
    "save_report_immediate",
    "save_step_report",
    "strip_model_reasoning",
    "trip_provider_failure",
]
