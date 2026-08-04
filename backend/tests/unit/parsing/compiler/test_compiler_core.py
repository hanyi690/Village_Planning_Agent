"""Tests for compiler core - profile dispatch, trace, provenance."""
from __future__ import annotations

import pytest

from app.modules.parsing.compiler.core import compile_dimension_report
from app.modules.parsing.compiler.provenance import build_fragment_provenance
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def test_compile_l1_observation_returns_fragment(land_use_report):
    frag = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        **land_use_report,
        run_id="r1",
    )
    assert frag is not None
    assert frag.dimension_key == "land_use"
    assert frag.provenance is not None
    assert frag.provenance.run_id == "r1"
    assert frag.trace is not None
    assert frag.trace.profile == CompilationProfile.L1_OBSERVATION


def test_compile_l3_planning_returns_fragment():
    from app.modules.schema.contracts.l3_contracts import L3ProgramFragment

    frag = compile_dimension_report(
        CompilationProfile.L3_PLANNING,
        dimension_key="land_use_planning",
        content="",
        instruction="",
        summary="",
    )
    assert isinstance(frag, L3ProgramFragment)
    assert frag.dimension_key == "land_use_planning"
    assert frag.trace is not None
    assert frag.trace.profile == CompilationProfile.L3_PLANNING


def test_compile_revision_not_implemented_in_wave_b():
    with pytest.raises(NotImplementedError):
        compile_dimension_report(
            CompilationProfile.REVISION,
            dimension_key="land_use",
            content="",
            instruction="",
            summary="",
        )


def test_build_fragment_provenance():
    prov = build_fragment_provenance(
        "land_use", "rpt-landuse-v1", "r1",
        section_locators=["# 现状用地", "## 用地结构"],
    )
    assert prov.module == "l1_observe"
    assert prov.run_id == "r1"
    assert prov.trace == ["land_use", "rpt-landuse-v1"]
