"""Shared fixtures for L1 OBSERVE unit tests."""
from __future__ import annotations

import pytest

from app.modules.schema.contracts.l1_contracts import L1DimensionFragment
from app.modules.schema.contracts.parsing_contracts import CompilationProfile, CompilerTrace


@pytest.fixture
def sample_fragments() -> list[L1DimensionFragment]:
    return [
        L1DimensionFragment(
            dimension_key="socio_economic",
            facts=["[socio_economic] 人口: 村域人口 3200 人"],
            constraints=[],
            issues=[],
            opportunities=[],
            evidence_gaps=[],
            classification_refs=[],
            spatial_facts=[],
            provenance=None,
            trace=CompilerTrace(profile=CompilationProfile.L1_OBSERVATION, steps=["c1"]),
        ),
        L1DimensionFragment(
            dimension_key="land_use",
            facts=["[land_use] 用地结构: 水田 120 公顷"],
            constraints=["基本农田保护红线"],
            issues=[],
            opportunities=["闲置宅基地可盘活"],
            evidence_gaps=[],
            classification_refs=[],
            spatial_facts=["设施 文化礼堂 1 处"],
            provenance=None,
            trace=CompilerTrace(profile=CompilationProfile.L1_OBSERVATION, steps=["c2"]),
        ),
    ]
