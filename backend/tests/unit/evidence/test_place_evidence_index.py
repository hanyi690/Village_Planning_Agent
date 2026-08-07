"""Tests for PlaceEvidenceIndex.build + resolve_mention + candidate_bsms.

Covers the seven acceptance cases from docs/design/12_PLACE_NAME_RESOLUTION.md
§8 using an in-memory PlanningContext with a fake gazetteer, fake L1 location
facts and a fake bundle carrying POI annotations.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.context.planning_context import PlanningContext
from app.modules.kg.gazetteer import Gazetteer, GazetteerEntry
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import AnnotationFeature
from app.modules.spatial_ops.evidence import PlaceEvidenceIndex


def _fact(normalized_name, role="village", aliases=None, source_span=None, dimension_key="d1"):
    return SimpleNamespace(
        normalized_name=normalized_name,
        role=role,
        aliases=list(aliases or []),
        source_span=source_span or {"start": 0, "end": len(normalized_name)},
        dimension_key=dimension_key,
        confidence=0.8,
    )


def _poi(text, category="现状设施点"):
    return AnnotationFeature(
        geometry={"type": "Point", "coordinates": [116.04, 24.81]},
        layer_type="current_annotation",
        text=text,
        category=category,
    )


def _bundle_with_pois(pois):
    bundle = VillageBundle(village_name="test")
    for p in pois:
        bundle.points.add(p)
    return bundle


class _Entry:
    """A plain gazetteer entry wrapper so tests read clearly."""

    def __init__(self, name, bsms, aliases=None):
        self.name = name
        self.bsms = list(bsms)
        self.aliases = list(aliases or [])


def _make_gazetteer(entries):
    inner = [GazetteerEntry(name=e.name, aliases=e.aliases, bsms=e.bsms) for e in entries]
    return Gazetteer(entries=inner)


def _context(**overrides):
    fields = dict(
        session_id="sess-evidence",
        village_name="test",
        version=3,
        kg_version=1,
        gazetteer=None,
        location_facts=[],
        bundle=None,
    )
    fields.update(overrides)
    return PlanningContext(**fields)


def _build(gazetteer=None, facts=None, pois=None):
    bundle = _bundle_with_pois(pois or [])
    context = _context(
        gazetteer=gazetteer,
        location_facts=facts or [],
        bundle=bundle,
    )
    return PlaceEvidenceIndex.build(context)


class TestAC1KgCanonicalExactMatch:
    def test_exact_canonical_resolves_to_expected_bsms(self):
        gaz = _make_gazetteer([_Entry("肩丰", ["P001", "P002"])])
        index = _build(gazetteer=gaz)

        result = index.resolve_mention("肩丰", role="village")

        assert result.status == "resolved"
        assert result.selected_entity_ref == "肩丰"
        assert result.candidates[0].canonical_name == "肩丰"
        assert index.candidate_bsms("肩丰") == ["P001", "P002"]


class TestAC2L1FactAliasMatch:
    def test_alias_match_resolves_via_alias(self):
        facts = [_fact("肩丰村", aliases=["肩丰"])]
        index = _build(facts=facts)

        result = index.resolve_mention("肩丰", role="village")

        assert result.status == "resolved"
        assert result.candidates[0].canonical_name == "肩丰村"
        assert "l1_fact" in result.candidates[0].evidence_refs


class TestAC3SameNameDifferentEntityType:
    def test_type_filter_resolves_intended_village(self):
        # Same name "园寨" exists as both a village (gazetteer, within bundle)
        # and a facility (L1 fact). The role filter must pick the village.
        gaz = _make_gazetteer([_Entry("园寨", ["P010"])])
        facts = [_fact("园寨", role="facility")]
        index = _build(gazetteer=gaz, facts=facts)

        result = index.resolve_mention("园寨", role="village")

        assert result.status == "resolved"
        assert result.candidates[0].source_bsms == ["P010"]
        assert index.candidate_bsms("园寨") == ["P010"]

    def test_facility_role_resolves_facility_entity(self):
        facts = [_fact("园寨", role="facility")]
        index = _build(facts=facts)

        result = index.resolve_mention("园寨", role="facility")

        assert result.status == "resolved"
        assert result.candidates[0].entity_type == "facility"


class TestAC4ShortNameMultipleCandidates:
    def test_short_name_ambiguous(self):
        # Short mention "园" only substring-matches two facility L1 facts (never
        # exact). With role=village requested, neither reaches the resolved
        # threshold and the two weak candidates sit within the gap -> ambiguous.
        facts = [_fact("园寨小学", role="facility"), _fact("园东小学", role="facility")]
        index = _build(facts=facts)

        result = index.resolve_mention("园", role="village")

        assert result.status == "ambiguous"
        assert len(result.candidates) >= 2
        assert index.candidate_bsms("园") == []


class TestAC5KgVsL1FactConflict:
    def test_deterministic_outcome(self):
        gaz = _make_gazetteer([_Entry("甲村", ["P100"])])
        facts = [_fact("甲村")]
        index = _build(gazetteer=gaz, facts=facts)

        first = index.resolve_mention("甲村", role="village")
        second = index.resolve_mention("甲村", role="village")

        assert first.status in ("resolved", "ambiguous")
        assert first.selected_entity_ref == second.selected_entity_ref
        assert [c.canonical_name for c in first.candidates] == [
            c.canonical_name for c in second.candidates
        ]
        assert first.evidence_refs

    def test_conflict_resolution_is_stable_and_prioritises_gazetteer(self):
        gaz = _make_gazetteer([_Entry("甲村", ["P100"])])
        facts = [_fact("甲村")]
        index = _build(gazetteer=gaz, facts=facts)

        result = index.resolve_mention("甲村", role="village")

        # Same canonical name across sources: gazetteer (registered first) wins
        # deterministically and carries the bundle BSM set.
        assert result.status == "resolved"
        assert result.candidates[0].canonical_name == "甲村"
        assert result.candidates[0].source_bsms == ["P100"]


class TestAC6OnlyExternalGeocoder:
    def test_no_session_evidence_never_auto_resolves(self):
        pois = [_poi("园寨第二小学", category="现状设施点")]
        index = _build(pois=pois)

        result = index.resolve_mention("园寨", role="village")

        assert result.status in ("ambiguous", "unresolved")
        assert result.status != "resolved"
        assert index.candidate_bsms("园寨") == []


class TestAC7UnresolvableMention:
    def test_unknown_mention_unresolved(self):
        gaz = _make_gazetteer([_Entry("肩丰", ["P001"])])
        index = _build(gazetteer=gaz)

        result = index.resolve_mention("完全不存在的地点", role="village")

        assert result.status == "unresolved"
        assert result.candidates == []
        assert index.candidate_bsms("完全不存在的地点") == []


class TestBuildMetadata:
    def test_version_reflects_context(self):
        context = _context(version=7, kg_version=2)
        index = PlaceEvidenceIndex.build(context)
        assert index.context.session_id == "sess-evidence"
        assert index.version == (7, 2)

    def test_candidate_ordering_descending_by_score(self):
        gaz = _make_gazetteer([_Entry("肩丰村", ["P001"]), _Entry("肩丰尾", ["P002"])])
        index = _build(gazetteer=gaz)

        result = index.resolve_mention("肩丰", role="unknown")

        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)