from __future__ import annotations

from types import SimpleNamespace

from app.contracts.domain.l1_contracts import L1Fact
from app.contracts.domain.l1_contracts import L1LocationFact


def _fact(**overrides):
    values = {
        'mention': '祠堂',
        'normalized_name': '祠堂',
        'role': 'facility',
        'aliases': ['祠', '宗祠'],
        'spatial_hint': 'xx村',
        'related_mentions': ['xx村'],
        'source_report_ref': 'report:current.md',
        'dimension_key': 'infrastructure',
        'source_span': 'xx村现状设施包括祠堂和卫生室',
        'evidence_refs': ['report:current.md#infrastructure'],
        'confidence': 0.94,
    }
    values.update(overrides)
    return L1LocationFact(**values)


def test_l1_scope_preserves_village_context_for_facility_mentions():
    from app.evidence.retrieval.l1_scope import build_l1_semantic_scopes

    facts = [
        _fact(
            mention='xx村',
            normalized_name='xx村',
            role='village',
            aliases=['xx'],
            spatial_hint='xx村',
            related_mentions=[],
            source_span='xx村现状设施包括祠堂和卫生室',
            confidence=0.98,
        ),
        _fact(),
    ]

    scopes = build_l1_semantic_scopes(
        facts,
        session_id='session-1',
        l1_snapshot_ref='l1-digest-1',
    )

    assert len(scopes) == 1
    scope = scopes[0]
    assert scope.village_mentions == ['xx村']
    assert scope.object_mentions[0].normalized_name == '祠堂'
    assert scope.object_mentions[0].role == 'facility'
    assert scope.relation_hints == [
        {
            'subject': '祠堂',
            'predicate': 'located_in',
            'object': 'xx村',
            'source_fact_ref': scope.object_mentions[0].mention_ref,
        }
    ]
    assert 'report:current.md#infrastructure' in scope.evidence_refs
    assert scope.scope_id.startswith('l1-scope:')


def test_l1_scope_keeps_multiple_villages_ambiguous_instead_of_merging():
    from app.evidence.retrieval.l1_scope import build_l1_semantic_scopes

    facts = [
        _fact(
            mention='甲村',
            normalized_name='甲村',
            role='village',
            aliases=['甲'],
            spatial_hint='甲村',
            related_mentions=[],
        ),
        _fact(
            mention='乙村',
            normalized_name='乙村',
            role='village',
            aliases=['乙'],
            spatial_hint='乙村',
            related_mentions=[],
        ),
        _fact(
            spatial_hint='甲村、乙村',
            related_mentions=['甲村', '乙村'],
            source_span='甲村、乙村均有祠堂设施',
        ),
    ]

    scopes = build_l1_semantic_scopes(facts, session_id='session-2')

    assert [scope.village_mentions for scope in scopes] == [['甲村'], ['乙村']]
    assert all(scope.object_mentions[0].normalized_name == '祠堂' for scope in scopes)
    assert all('multiple_village_context' in scope.unresolved_reasons for scope in scopes)


def test_l1_scope_reports_missing_village_context_without_inventing_geometry():
    from app.evidence.retrieval.l1_scope import build_l1_semantic_scopes

    scopes = build_l1_semantic_scopes(
        [_fact(spatial_hint='', related_mentions=[], source_span='现状设施包括祠堂')],
        session_id='session-3',
    )

    assert len(scopes) == 1
    assert scopes[0].village_mentions == []
    assert scopes[0].object_mentions[0].normalized_name == '祠堂'
    assert scopes[0].unresolved_reasons == ['missing_village_context']
    assert scopes[0].geometry_refs == []


def test_place_index_prefers_typed_l1_records_when_legacy_location_projection_exists():
    from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

    typed_village = L1Fact(
        fact_id='l1:typed:village',
        statement='xx村是行政村',
        fact_kind='spatial_observation',
        semantic_type='village',
        attributes={
            'mention': 'xx村',
            'normalized_name': 'xx村',
            'spatial_hint': 'xx村',
        },
        source_refs=['report:typed'],
    )
    typed_facility = L1Fact(
        fact_id='l1:typed:facility',
        statement='xx村有祠堂',
        fact_kind='spatial_observation',
        semantic_type='facility',
        attributes={
            'mention': '祠堂',
            'normalized_name': '祠堂',
            'spatial_hint': 'xx村',
        },
        source_refs=['report:typed'],
    )
    index = PlaceEvidenceIndex.build(SimpleNamespace(
        context_version='',
        version=1,
        kg_version=1,
        session_id='typed-precedence',
        gazetteer=None,
        kg=None,
        current_parcels=lambda: [],
        workspace=None,
        location_facts=[_fact()],
        l1_fact_records=[typed_village, typed_facility],
    ))

    assert len(index.semantic_scopes) == 1
    scope = index.semantic_scopes[0]
    assert scope.village_fact_refs == ['l1-fact:l1:typed:village']
    assert [item.mention_ref for item in scope.object_mentions] == [
        'l1-fact:l1:typed:facility'
    ]
