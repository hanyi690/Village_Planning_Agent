"""Tests for the deterministic evidence scorer (design §4.2).

Covers ``score_candidate``, ``WEIGHTS`` and ``total`` from
``app.modules.spatial_ops.evidence.evidence_scorer``. The scorer is purely
deterministic and never writes into an LLM prompt; ``fuzzy_short_name`` is
prohibited from auto-passing and contributes nothing to the weighted total.
"""

from __future__ import annotations

import pytest

from app.modules.schema.contracts.place_resolution_contracts import (
    PlaceEvidenceEntry,
)
from app.modules.spatial_ops.evidence.evidence_scorer import (
    WEIGHTS,
    score_candidate,
    total,
)


def _entry(**overrides):
    fields = dict(
        canonical_name="肩丰",
        aliases=["肩丰村", "肩丰自然村"],
        entity_refs=["kg:jianfeng"],
        entity_types=["village"],
        role="village",
        source_bsms=["P001", "P002"],
        geometry_ref=None,
        provenance=["gazetteer"],
        confidence=0.9,
    )
    fields.update(overrides)
    return PlaceEvidenceEntry(**fields)


class TestExactMatch:
    def test_canonical_exact_match_scores_high(self):
        evidence = score_candidate("肩丰", _entry(), role="village")
        assert evidence["exact_canonical_alias"] == 1.0
        assert total(evidence) >= 1.0

    def test_alias_exact_match_scores_high(self):
        evidence = score_candidate("肩丰村", _entry(), role="village")
        assert evidence["exact_canonical_alias"] == 1.0
        assert total(evidence) >= 1.0

    def test_suffix_normalization_matches(self):
        evidence = score_candidate("肩丰自然村", _entry(), role="village")
        assert evidence["exact_canonical_alias"] == 1.0


class TestL1Provenance:
    def test_l1_fact_provenance_contributes(self):
        entry = _entry(provenance=["l1_fact"])
        evidence = score_candidate("肩丰", entry, role="unknown")
        assert evidence["l1_fact_exact"] == 1.0
        assert total(evidence) >= 2.0

    def test_no_l1_fact_contributes_zero(self):
        evidence = score_candidate("肩丰", _entry(), role="unknown")
        assert evidence["l1_fact_exact"] == 0.0


class TestEntityTypeRole:
    def test_role_match_scores_when_role_provided(self):
        evidence = score_candidate("肩丰", _entry(), role="village")
        assert evidence["entity_type_role"] == 0.5

    def test_role_mismatch_scores_zero(self):
        evidence = score_candidate("肩丰", _entry(), role="facility")
        assert evidence["entity_type_role"] == 0.0

    def test_unknown_role_auto_matches(self):
        evidence = score_candidate("肩丰", _entry(), role="unknown")
        assert evidence["entity_type_role"] == 0.5


class TestWithinBundle:
    def test_nonempty_source_bsms_contributes(self):
        evidence = score_candidate("肩丰", _entry(source_bsms=["P001"]), role="unknown")
        assert evidence["within_bundle"] == 0.5

    def test_empty_source_bsms_contributes_zero(self):
        evidence = score_candidate("肩丰", _entry(source_bsms=[]), role="unknown")
        assert evidence["within_bundle"] == 0.0


class TestExternalGeocoder:
    def test_poi_provenance_contributes_low(self):
        entry = _entry(provenance=["poi"], source_bsms=[])
        evidence = score_candidate("肩丰", entry, role="unknown")
        assert evidence["external_geocoder"] == 0.3
        assert total(evidence) == pytest.approx(1.8)

    def test_non_poi_provenance_contributes_zero(self):
        evidence = score_candidate("肩丰", _entry(), role="unknown")
        assert evidence["external_geocoder"] == 0.0


class TestFuzzyShortNameProhibited:
    def test_fuzzy_short_name_is_zero_and_excluded_from_total(self):
        entry = _entry(provenance=["poi"], source_bsms=[])
        evidence = score_candidate("肩", entry, role="unknown")
        # fuzzy/substring match still never auto-passes
        assert evidence["fuzzy_short_name"] == 0.0
        assert "fuzzy_short_name" not in WEIGHTS or WEIGHTS["fuzzy_short_name"] == 0.0
        # total must not include the prohibited dimension
        assert total(evidence) == total({k: v for k, v in evidence.items() if k != "fuzzy_short_name"})


class TestTotal:
    def test_total_is_weighted_sum_within_unit(self):
        entry = _entry(provenance=["l1_fact"])
        evidence = score_candidate("肩丰", entry, role="village")
        t = total(evidence)
        assert 0.0 <= t <= 3.0
        assert t == pytest.approx(sum(v for k, v in evidence.items() if WEIGHTS.get(k, 0.0) > 0.0))

    def test_total_weights_configured(self):
        assert WEIGHTS["exact_canonical_alias"] == 1.0
        assert WEIGHTS["l1_fact_exact"] == 1.0
        assert WEIGHTS["entity_type_role"] == 0.5
        assert WEIGHTS["within_bundle"] == 0.5
        assert WEIGHTS["external_geocoder"] == 0.3
        assert WEIGHTS["fuzzy_short_name"] == 0.0