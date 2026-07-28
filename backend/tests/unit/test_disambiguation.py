"""Tests for disambiguation models — Candidate, DisambiguationContext, DisambiguationDecision.

Trimmed in V4 audit: TestCandidateEngineL2 moved to test_encoding_consistency.py
(merges with TestCandidateEngineResolve for L0/L1/L3 paths).
Kept: Pydantic model construction, validation, serialization round-trips.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.schema.encodings.dicts.disambiguation import (
    Candidate,
    DisambiguationContext,
    DisambiguationDecision,
)


class TestCandidate:
    def test_minimal(self):
        c = Candidate(code="0901")
        assert c.code == "0901"
        assert c.when is None
        assert c.surviving_evidence == []

    def test_with_evidence(self):
        c = Candidate(code="0901", surviving_evidence=["poi:超市", "poi:商场"])
        assert len(c.surviving_evidence) == 2

    def test_empty_code_rejected(self):
        with pytest.raises(ValidationError):
            Candidate(code="")


class TestDisambiguationContext:
    def test_minimal(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1", "DLMC": "商服用地"},
            candidates=[Candidate(code="0901")],
        )
        assert ctx.source_system == "sddlbm"
        assert ctx.source_code == "05H1"
        assert len(ctx.candidates) == 1

    def test_empty_candidates_rejected(self):
        with pytest.raises(ValidationError, match="candidates"):
            DisambiguationContext(
                source_system="sddlbm",
                source_code="05H1",
                parcel_attrs={},
                candidates=[],
            )

    def test_serialization_roundtrip(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1"},
            candidates=[Candidate(code="0901"), Candidate(code="0902")],
            poi_hits=[{"name": "超市", "type": "shop"}],
            zone_membership=["YJJBNT"],
            village_profile="平原村，以农业为主",
        )
        dumped = ctx.model_dump(mode="json")
        loaded = DisambiguationContext.model_validate(dumped)
        assert loaded.source_code == "05H1"
        assert len(loaded.candidates) == 2
        assert loaded.candidates[0].code == "0901"

    def test_with_neighbors(self):
        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={},
            neighbors=[{"bsm": "001", "dlbm": "0703"}],
            candidates=[Candidate(code="0901")],
        )
        assert len(ctx.neighbors) == 1
        assert ctx.neighbors[0]["bsm"] == "001"


class TestDisambiguationDecision:
    def test_minimal(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="high",
            rationale="POI confirmed commercial use",
        )
        assert dec.chosen_code == "0901"
        assert dec.confidence == "high"
        assert dec.decided_by == "llm"
        assert dec.reviewed is False

    def test_decided_by_rule(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="high",
            rationale="Single target",
            decided_by="rule",
        )
        assert dec.decided_by == "rule"

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValidationError):
            DisambiguationDecision(
                chosen_code="0901",
                confidence="very_high",
                rationale="test",
            )

    def test_model_version(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="medium",
            rationale="test",
            model="qwen-flash",
        )
        assert dec.model == "qwen-flash"

    def test_serialization_roundtrip(self):
        dec = DisambiguationDecision(
            chosen_code="0901",
            confidence="medium",
            rationale="POI 辅助判断",
            evidence=["poi:超市"],
            decided_by="llm",
            model="qwen-flash",
            reviewed=False,
        )
        dumped = dec.model_dump(mode="json")
        loaded = DisambiguationDecision.model_validate(dumped)
        assert loaded.chosen_code == "0901"
        assert loaded.evidence == ["poi:超市"]


class TestResolutionNeedsLlm:
    def test_needs_llm_factory(self):
        from app.modules.schema.encodings.dicts.candidate_engine import Resolution
        from app.modules.schema.encodings.dicts.disambiguation import (
            Candidate, DisambiguationContext,
        )

        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={"DLBM": "05H1"},
            candidates=[Candidate(code="0901"), Candidate(code="0902")],
        )
        resolution = Resolution.needs_llm(ctx)
        assert resolution.kind == "llm"
        assert resolution.chosen_code == ""
        assert resolution.disambiguation_ctx is not None
        assert resolution.disambiguation_ctx["source_code"] == "05H1"

    def test_needs_llm_serialization(self):
        from app.modules.schema.encodings.dicts.candidate_engine import Resolution
        from app.modules.schema.encodings.dicts.disambiguation import (
            Candidate, DisambiguationContext,
        )

        ctx = DisambiguationContext(
            source_system="sddlbm",
            source_code="05H1",
            parcel_attrs={},
            candidates=[Candidate(code="0901")],
        )
        resolution = Resolution.needs_llm(ctx)
        dumped = resolution.model_dump(mode="json")
        loaded = Resolution.model_validate(dumped)
        assert loaded.kind == "llm"
        assert loaded.disambiguation_ctx is not None
        assert loaded.disambiguation_ctx["source_code"] == "05H1"