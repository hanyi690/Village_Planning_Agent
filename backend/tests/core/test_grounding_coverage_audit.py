"""Deterministic Task 3 audit of the real L1-to-grounding MVP fixture path."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('fastapi')

from tests.acceptance.test_grounding_anchors_fixture import (  # noqa: E402
    FIXTURE,
    _uploads,
)
from tests.fixtures.db import make_session_with_uploads  # noqa: E402


class _FixtureGroundingLLM:
    """Provider substitute for bounded structured selection, not grounding logic."""

    def __init__(self, report_text: str) -> None:
        self.mapping: dict[str, dict[str, list[int]]] = {}
        self.report_text = report_text

    def with_structured_output(self, response_model, **_kwargs):
        provider = self

        class _Structured:
            async def ainvoke(self, prompt):
                prompt = str(prompt)
                if response_model.__name__ == 'CandidateSelectionProposal':
                    candidate_ids = re.findall(r'candidate_id=([^\s]+)', prompt)
                    assert candidate_ids, prompt
                    digest = re.search(r'input_digest=([0-9a-f]+)', prompt).group(1)
                    return response_model.model_validate({
                        'status': 'selected',
                        'selected_candidate_id': candidate_ids[0],
                        'input_digest': digest,
                    })

                entity_lines = [
                    line.strip()
                    for line in prompt.splitlines()
                    if line.strip().startswith('- entity_ref=')
                ]
                candidate_ids = re.findall(r'candidate_id=([^\s]+)', prompt)
                decisions = []
                for line in entity_lines:
                    entity_ref = line.split('entity_ref=', 1)[1].split()[0]
                    name = line.split('mention=', 1)[1].strip()
                    indexes = provider.mapping.get(name, {}).get('cluster_indexes', [])
                    selected = [candidate_ids[index] for index in indexes]
                    start = provider.report_text.find(name)
                    if start < 0:
                        start = provider.report_text.find(name.removesuffix('村'))
                    quote = provider.report_text[start:start + len(name)] if start >= 0 else ''
                    decisions.append({
                        'entity_ref': entity_ref,
                        'status': 'mapped' if selected and quote else 'unresolved',
                        'candidate_ids': selected,
                        'source_span': ({
                            'segment_id': 'report',
                            'start': start,
                            'end': start + len(name),
                            'quote_hash': hashlib.sha256(quote.encode('utf-8')).hexdigest(),
                        } if selected and quote else None),
                        'reason_code': '' if selected and quote else 'source_span_invalid',
                    })
                return response_model.model_validate({'decisions': decisions})

        return _Structured()


def _audit_observations() -> list[dict]:
    observations = [{
        'fact_type': 'spatial_entity',
        'status': 'confirmed',
        'entity_type': '现状分区',
        'name': '金田村',
        'source_segment_ids': ['report:scope'],
        'source_quote': '金田村位于泗水镇最北端',
    }, {
        'fact_type': 'spatial_entity',
        'status': 'confirmed',
        'entity_type': '道路',
        'name': '122乡道',
        'source_segment_ids': ['report:road'],
        'source_quote': '122 乡道是金田村主要的对外交通道路',
        'spatial_mentions': [{
            'target_name': '122乡道',
            'role': 'road',
            'resolution_state': 'needs_retrieval',
        }],
    }, {
        'fact_type': 'spatial_entity',
        'status': 'confirmed',
        'entity_type': '水系',
        'name': '金田河',
        'source_segment_ids': ['report:water'],
        'source_quote': '其中，金田河由西南至东北贯穿金田村，汇入石窟河。',
        'spatial_mentions': [{
            'target_name': '金田河',
            'role': 'water',
            'resolution_state': 'needs_retrieval',
        }],
    }]
    observations.extend({
        'fact_type': 'spatial_entity',
        'status': 'confirmed',
        'entity_type': '自然村',
        'name': scope,
        'source_segment_ids': [f'report:{scope}'],
        'source_quote': scope,
    } for scope in ('社前村', '黄竹村', '田坑村'))
    observations.append({
        'fact_type': 'spatial_entity',
        'status': 'confirmed',
        'entity_type': '现状设施',
        'name': '祠堂',
        'source_segment_ids': ['report:halls'],
        'source_quote': '社前村，黄竹村，田坑村具有三座祠堂',
        'spatial_mentions': [
        {
            'target_name': '祠堂',
            'role': 'facility',
            'village_scopes': [scope],
            'instance_label': f'{scope}-祠堂',
            'instance_count': '1座',
            'resolution_state': 'needs_retrieval',
        }
        for scope in ('社前村', '黄竹村', '田坑村')
        ],
    })
    return observations


def _source_geometry_type(anchor, bundle) -> str:
    if str(anchor.geometry_ref or '').startswith('boundary:'):
        return str((bundle.boundary.geometry or {}).get('type') or '')
    feature_bsm = str(anchor.feature_bsm or '')
    for groups in (bundle.points, bundle.lines, bundle.polygons):
        for layer_name in groups.keys():
            for feature in groups.get(layer_name) or []:
                if str(getattr(feature, 'bsm', '') or '') == feature_bsm:
                    return str((getattr(feature, 'geometry', None) or {}).get('type') or '')
    return ''


@pytest.mark.asyncio
async def test_mvp_l1_grounding_coverage_audit(sqlite_db, pipeline_reset):
    """Every compiled work item reaches a typed final grounding state."""
    setup, teardown = sqlite_db
    await setup()
    try:
        session_id = f'task-3-grounding-audit-{uuid.uuid4().hex[:8]}'
        await make_session_with_uploads(session_id, '金田村', uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.contracts.evidence.source_semantic_contracts import (
            SourceFeatureSemanticDecision,
        )
        from app.data.ingestion.compiler.profiles.l1_observation import (
            compile_l1_observation,
        )
        from app.domain.ground.anchors import ground_l1_anchors
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.kg.manager import KGManager
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            assign_water_bodies,
            build_landuse_bodies,
            build_village_clusters,
        )

        report_text = (FIXTURE / 'current_report.md').read_text(encoding='utf-8')
        snapshot = compile_l1_observation(
            dimension_key='historical_culture',
            content=report_text,
            instruction=json.dumps({'observations': _audit_observations()}, ensure_ascii=False),
            report_id='report:mvp-grounding-audit',
        )
        facts = snapshot.location_facts
        assert facts
        assert all(fact.provenance.source_quote for fact in facts)
        assert {
            tuple(fact.village_scopes)
            for fact in facts
            if fact.target_name == '祠堂'
        } == {('社前村',), ('黄竹村',), ('田坑村',)}
        assert all(
            fact.provenance.source_quote in report_text
            for fact in facts
            if fact.target_name == '祠堂'
        )

        bundle = await build_session_bundle(session_id)
        kg = KGManager().get_or_build_kg('金田村', bundle=bundle, session_id=session_id)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get('landuse_current') or [])
        hall_fact_refs = [
            str(ref)
            for fact in facts
            if fact.target_name == '祠堂'
            for ref in (fact.evidence_refs or [])
        ]
        source_semantic_decisions = {}
        for feature in bundle.points.get('annotations_current') or []:
            raw = getattr(feature, '_raw', {}) or {}
            source_feature_id = str(raw.get('source_feature_id') or '').strip()
            raw_label = str(
                (getattr(feature, 'properties', {}) or {}).get('注记')
                or getattr(feature, 'text', '')
                or ''
            ).strip()
            if source_feature_id and raw_label == '祠':
                source_semantic_decisions[source_feature_id] = (
                    SourceFeatureSemanticDecision(
                        source_feature_id=source_feature_id,
                        raw_label=raw_label,
                        semantic_type='祠堂',
                        status='accepted',
                        authority='inferred_current',
                        candidate_ref='l1:task3:祠堂:entity',
                        supporting_fact_refs=hall_fact_refs,
                    )
                )
        assert source_semantic_decisions
        llm = _FixtureGroundingLLM(report_text)
        villages = sorted({fact.normalized_name for fact in facts if fact.role == 'village'})
        water_names = sorted({fact.normalized_name for fact in facts if fact.role == 'water'})
        clusters = build_village_clusters(parcels)
        water_bodies = build_landuse_bodies(
            parcels, ('水域', '河流', '水库', '坑塘', '沟渠', '水利设施')
        )
        llm.mapping = {
            name: {'cluster_indexes': [index % len(clusters)]}
            for index, name in enumerate(villages)
        }
        for entry in await assign_villages_to_clusters(
            gazetteer, parcels, villages, report_text, llm=llm
        ):
            gazetteer.upsert(entry)
        llm.mapping.update({
            name: {'cluster_indexes': [index % len(water_bodies)]}
            for index, name in enumerate(water_names)
        })
        for entry in await assign_water_bodies(
            gazetteer, parcels, water_names, report_text, llm=llm
        ):
            gazetteer.upsert(entry)

        context = SimpleNamespace(
            session_id=session_id,
            version=1,
            kg_version=1,
            village_name='金田村',
            gazetteer=gazetteer,
            kg=kg,
            workspace=bundle,
            location_facts=facts,
            reports={'current_report': report_text},
            source_semantic_decisions=source_semantic_decisions,
        )
        context.current_parcels = lambda: parcels

        anchors = await ground_l1_anchors(context, session_id, llm=llm, bump=False)
        unresolved = list(context.grounding_unresolved)
        # Coverage is a partition: every L1 work item is resolved/inferred or
        # retained as an explicit diagnostic; coordinate dedup may not erase it.
        assert len(anchors) + len(unresolved) == len(facts), {
            'facts': [
                (fact.normalized_name, fact.role, tuple(fact.village_scopes))
                for fact in facts
            ],
            'anchors': [
                (anchor.normalized_name, anchor.role, anchor.feature_bsm)
                for anchor in anchors
            ],
            'unresolved': [
                (item['mention'], item['role']) for item in unresolved
            ],
        }
        assert all(anchor.status in {'resolved', 'ambiguous'} for anchor in anchors)
        assert all(
            anchor.status == 'resolved' or anchor.best_effort
            for anchor in anchors
        )
        assert all(
            item['code'].startswith('grounding_')
            and item['mention']
            and item['role']
            and item['reason']
            and item['trace']
            for item in unresolved
        )

        # Grounded records retain L1 source provenance and the EvidenceGraph
        # query trace that explains their final state.
        assert all(
            anchor.source_report_ref == 'report:mvp-grounding-audit'
            and anchor.source_span
            and anchor.query_trace
            and anchor.query_trace[0]['step'] == 'resolve'
            for anchor in anchors
        )

        def trace_scope_names(record):
            trace = (
                record.query_trace
                if hasattr(record, 'query_trace')
                else record.get('trace', [])
            )
            return {
                scope
                for step in trace
                if step.get('step') == 'supporting_evidence_start'
                for scope in step.get('scope_names', [])
            }

        hall_facts = [fact for fact in facts if fact.target_name == '祠堂']
        hall_anchors = [anchor for anchor in anchors if anchor.normalized_name == '祠堂']
        hall_unresolved = [item for item in unresolved if item['mention'] == '祠堂']
        assert len(hall_anchors) + len(hall_unresolved) == len(hall_facts)
        assert {
            scope
            for anchor in hall_anchors
            for scope in trace_scope_names(anchor)
        } | {
            scope
            for item in hall_unresolved
            for scope in trace_scope_names(item)
        } == {'社前村', '黄竹村', '田坑村'}
        hall_records = [*hall_anchors, *hall_unresolved]
        assert all(len(trace_scope_names(record)) == 1 for record in hall_records)
        hall_scopes = [
            next(iter(trace_scope_names(record)))
            for record in hall_records
        ]
        assert len(hall_scopes) == len(set(hall_scopes)) == len(hall_facts)
        exact_halls = [
            anchor
            for anchor in hall_anchors
            if anchor.geometry_granularity == 'exact_feature'
        ]
        assert len({anchor.feature_bsm for anchor in exact_halls}) == len(exact_halls)
        assert all(anchor.feature_bsm for anchor in exact_halls)
        assert all(len(trace_scope_names(anchor)) == 1 for anchor in hall_anchors)

        polygon = next(
            anchor for anchor in anchors if anchor.role == 'administrative_village'
        )
        assert _source_geometry_type(polygon, bundle) in {'Polygon', 'MultiPolygon'}
        assert polygon.geometry_granularity == 'exact_feature'

        # A typed non-village anchor is exact only when its source feature is
        # recoverable from the Bundle.  Scope/parcel support remains a gap or
        # an explicitly best-effort village inference; it never becomes a
        # point-shaped road or river.
        typed_roles = {'facility', 'landmark', 'road', 'axis', 'water'}
        for anchor in anchors:
            if anchor.role not in typed_roles:
                continue
            assert anchor.geometry_granularity == 'exact_feature'
            geometry_type = _source_geometry_type(anchor, bundle)
            if anchor.role in {'facility', 'landmark'}:
                assert geometry_type in {'Point', 'MultiPoint'}
            elif anchor.role in {'road', 'axis'}:
                assert geometry_type in {'LineString', 'MultiLineString'}
            else:
                assert geometry_type in {
                    'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon'
                }

        assert any(item['role'] == 'road' for item in unresolved)
        assert any(item['role'] == 'water' for item in unresolved)
    finally:
        await teardown()
