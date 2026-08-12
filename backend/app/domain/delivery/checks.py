"""DELIVER checks — deterministic exit-gate + statutory completeness checks.

Each check returns a list of HumanItem; empty means the check passed.
Blocking items gate "完整法定成果" (complete statutory output). No LLM,
no KG and no cross-system mapping lookup — pure container math only.
"""

from __future__ import annotations

from app.modules.schema.contracts.delivery_manifest_contracts import HumanItem
from app.modules.schema.contracts.reconciliation_contracts import CoverageMatrix
from app.modules.schema.contracts.validation_report_contracts import ValidationReport

# Required statutory output layers (from GDB_LAYER_REGISTRY / LAYER_GIS_KEY_MAP).
REQUIRED_STATUTORY_LAYERS = (
    "admin_area",
    "current_landuse",
    "planned_landuse",
    "ecological_redline",
    "farmland_protection",
    "construction_zone",
)

_BLOCKING_LAYER_DESC = "导出结果缺少法定图层"
_BLOCKING_LAYER_REASON = "export_delivery_package 未产出完整法定图层"


def _statutory_source_for(layer: str) -> str:
    """Map a statutory layer key to its exported source path.

    The export package writes files at GDB_LAYER_REGISTRY sources (e.g.
    ``current/boundary.geojson``), which differ from the layer keys used in
    ``REQUIRED_STATUTORY_LAYERS``. Matching against the real source path keeps
    the check aligned with what ``export_delivery_package`` actually writes.
    """
    try:
        from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

        entry = GDB_LAYER_REGISTRY.get(layer)
        if entry is not None:
            return str(entry.get("source", "") or "")
    except Exception:
        pass
    return layer


def check_statutory_layers_complete(
    export_result: dict | None,
    *,
    required: bool = True,
) -> list[HumanItem]:
    """Check the export package contains all required statutory layers."""
    if not required:
        return []
    if export_result is None:
        return [
            HumanItem(
                item_id="hi-layers-none-0",
                description="导出结果缺失",
                reason="export_delivery_package 未运行",
                blocking=True,
            )
        ]
    exported = list(export_result.get("exported_files", []) or [])
    exported_text = "\n".join(str(f) for f in exported)
    missing = [
        layer
        for layer in REQUIRED_STATUTORY_LAYERS
        if _statutory_source_for(layer) not in exported_text
    ]
    if not missing:
        return []
    return [
        HumanItem(
            item_id=f"hi-layers-{layer}",
            description=f"{_BLOCKING_LAYER_DESC}: {layer}",
            reason=_BLOCKING_LAYER_REASON,
            blocking=True,
        )
        for layer in missing
    ]


def check_traceability_complete(coverage_matrix: CoverageMatrix) -> list[HumanItem]:
    """Warn when any intervention's chain is not fully covered (non-blocking)."""
    rows = list(getattr(coverage_matrix, "rows", None) or [])
    items: list[HumanItem] = []
    for row in rows:
        if row.status != "covered":
            items.append(
                HumanItem(
                    item_id=f"hi-trace-{row.intervention_id}",
                    description=f"溯源链不完整: {row.intervention_id}",
                    reason=f"status={row.status}",
                    blocking=False,
                )
            )
    return items


def check_classification_for_statutory(
    validation_report: ValidationReport | dict | None,
) -> list[HumanItem]:
    """Block statutory output when a non-preserve parcel lacks planning_land_use."""
    if validation_report is None:
        return []
    checks = list(getattr(validation_report, "checks", None) or [])
    if isinstance(validation_report, dict):
        checks = list(validation_report.get("checks", []) or [])
    for check in checks:
        check_id = getattr(check, "check_id", None)
        if check_id is None and isinstance(check, dict):
            check_id = check.get("check_id")
        if check_id != "classification_missing":
            continue
        passed = getattr(check, "passed", None)
        if passed is None and isinstance(check, dict):
            passed = check.get("passed")
        if not passed:
            return [
                HumanItem(
                    item_id="hi-class-0",
                    description="补充规划分类编码",
                    reason="未明确规划分类",
                    blocking=True,
                )
            ]
        return []
    return []


__all__ = [
    "REQUIRED_STATUTORY_LAYERS",
    "check_statutory_layers_complete",
    "check_traceability_complete",
    "check_classification_for_statutory",
]
