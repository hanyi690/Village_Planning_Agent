from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_data_exports_provider_acquisition_contract_only():
    import app.contracts.data as data_contracts

    from app.contracts.data import (
        ProviderAcquisitionPlan,
        build_provider_acquisition_plan,
    )

    assert ProviderAcquisitionPlan.__name__ == "ProviderAcquisitionPlan"
    assert callable(build_provider_acquisition_plan)
    assert not hasattr(data_contracts, "ProviderQueryPlan")


@pytest.mark.parametrize(
    "relative",
    (
        "scripts/collect_amap_jintian_validation.py",
        "scripts/collect_three_provider_validation.py",
        "scripts/collect_tianditu_full.py",
    ),
)
def test_provider_collectors_use_data_acquisition_naming(relative: str):
    source = (ROOT / relative).read_text(encoding="utf-8")

    assert "provider_acquisition_plans" in source
    assert "provider_query_plans" not in source
    assert "provider_acquisition_plan" in source
    assert "provider_query_plan" not in source
