"""DELIVER checks tests — statutory layers, traceability, classification."""

from app.agent.deliver.checks import (
    REQUIRED_STATUTORY_LAYERS,
    check_classification_for_statutory,
    check_statutory_layers_complete,
    check_traceability_complete,
)
from app.modules.schema.contracts.delivery_manifest_contracts import HumanItem
from app.modules.schema.contracts.reconciliation_contracts import CoverageMatrix, CoverageMatrixRow
from app.modules.schema.contracts.validation_report_contracts import ValidationCheck, ValidationReport


def test_statutory_layers_complete_passes():
    from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

    exported = "\n".join(
        GDB_LAYER_REGISTRY[l]["source"] for l in REQUIRED_STATUTORY_LAYERS
    )
    result = check_statutory_layers_complete({"exported_files": [exported]})
    assert result == []


def test_statutory_layers_complete_blocks_on_missing():
    from app.modules.schema.output.gdb import GDB_LAYER_REGISTRY

    exported = "\n".join(
        [
            GDB_LAYER_REGISTRY["admin_area"]["source"],
            GDB_LAYER_REGISTRY["planned_landuse"]["source"],
        ]
    )
    result = check_statutory_layers_complete({"exported_files": [exported]})
    assert len(result) > 0
    assert all(item.blocking for item in result)
    assert any("ecological_redline" in item.item_id for item in result)


def test_statutory_layers_complete_blocks_on_none_export():
    result = check_statutory_layers_complete(None)
    assert len(result) == 1
    assert result[0].item_id == "hi-layers-none-0"
    assert result[0].blocking is True


def test_traceability_complete_warns_on_partial():
    cm = CoverageMatrix(
        rows=[
            CoverageMatrixRow(intervention_id="iv-1", status="covered"),
            CoverageMatrixRow(intervention_id="iv-2", status="missing"),
        ]
    )
    result = check_traceability_complete(cm)
    assert len(result) == 1
    assert result[0].item_id == "hi-trace-iv-2"
    assert result[0].blocking is False


def test_traceability_complete_passes_on_all_covered():
    cm = CoverageMatrix(
        rows=[CoverageMatrixRow(intervention_id="iv-1", status="covered")]
    )
    assert check_traceability_complete(cm) == []


def test_classification_for_statutory_blocks_on_missing():
    vc = ValidationCheck(
        check_id="classification_missing",
        check_name="规划分类缺失",
        passed=False,
        responsible_stage="EXECUTE",
    )
    vr = ValidationReport(checks=[vc], overall_passed=False)
    result = check_classification_for_statutory(vr)
    assert len(result) == 1
    assert result[0].item_id == "hi-class-0"
    assert result[0].blocking is True
    assert result[0].description == "补充规划分类编码"


def test_classification_for_statutory_passes_when_complete():
    vc = ValidationCheck(check_id="classification_missing", passed=True)
    vr = ValidationReport(checks=[vc], overall_passed=True)
    assert check_classification_for_statutory(vr) == []


def test_classification_for_statutory_none_report():
    assert check_classification_for_statutory(None) == []


def test_classification_for_statutory_dict_report():
    vr = {
        "checks": [
            {
                "check_id": "classification_missing",
                "passed": False,
            }
        ]
    }
    result = check_classification_for_statutory(vr)
    assert len(result) == 1
    assert result[0].blocking is True
