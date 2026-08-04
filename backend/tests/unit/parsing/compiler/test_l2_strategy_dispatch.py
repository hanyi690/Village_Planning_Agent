"""L2_STRATEGY compilation profile dispatch tests."""
from __future__ import annotations

import pytest
from app.modules.schema.contracts.parsing_contracts import CompilationProfile
from app.modules.schema.contracts.l1_contracts import L1DimensionFragment
from app.modules.parsing.compiler.core import compile_dimension_report


def test_l2_strategy_enum_value():
    assert CompilationProfile.L2_STRATEGY == "l2_strategy"


def test_l2_strategy_dispatch_raises_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        compile_dimension_report(
            CompilationProfile.L2_STRATEGY,
            dimension_key="planning_strategies",
            content="x",
            instruction="",
        )


def test_l1_observation_dispatch_still_works():
    frag = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        dimension_key="land_use",
        content="### 用地结构\n|地类|面积|\n|耕地|120|\n",
        instruction="",
    )
    assert isinstance(frag, L1DimensionFragment)


def test_l3_planning_still_wave_f():
    with pytest.raises(NotImplementedError):
        compile_dimension_report(
            CompilationProfile.L3_PLANNING,
            dimension_key="x",
            content="x",
            instruction="",
        )


def test_revision_still_wave_f():
    with pytest.raises(NotImplementedError):
        compile_dimension_report(
            CompilationProfile.REVISION,
            dimension_key="x",
            content="x",
            instruction="",
        )
