"""Tests for REVISION profile dispatch + provenance source_module generalization.

Wave F: REVISION profile is a stub raising NotImplementedError; provenance
accepts a source_module keyword so each profile stamps its own source/module.
"""
from __future__ import annotations

import pytest

from app.modules.parsing.compiler.core import compile_dimension_report
from app.modules.parsing.compiler.provenance import build_fragment_provenance
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def test_revision_dispatch_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        compile_dimension_report(
            CompilationProfile.REVISION,
            dimension_key="land_use",
            content="",
            instruction="",
            summary="",
        )


def test_compile_revision_stub_raises_not_implemented():
    from app.modules.parsing.compiler.profiles.revision import compile_revision

    with pytest.raises(NotImplementedError):
        compile_revision(
            revision_request=None,
            base_result=None,
            dimension_key="land_use",
            content="",
            instruction="",
        )


def test_build_fragment_provenance_source_module():
    prov = build_fragment_provenance(
        "dim", "rpt", "run", [], source_module="l3_plan"
    )
    assert prov.source == "l3_plan"
    assert prov.module == "l3_plan"


def test_build_fragment_provenance_default_source_module():
    prov = build_fragment_provenance("dim", "rpt", "run", [])
    assert prov.source == "l1_observe"
    assert prov.module == "l1_observe"


def test_l1_dispatch_still_works(land_use_report):
    from app.modules.schema.contracts.l1_contracts import L1DimensionFragment

    frag = compile_dimension_report(
        CompilationProfile.L1_OBSERVATION,
        **land_use_report,
        run_id="r1",
    )
    assert isinstance(frag, L1DimensionFragment)
    assert frag.dimension_key == "land_use"
    assert frag.provenance is not None
    assert frag.provenance.module == "l1_observe"
