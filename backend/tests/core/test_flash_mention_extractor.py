"""Tests for the GROUND flash-LLM mention enhancer and resolver integration."""

from __future__ import annotations

import asyncio
import hashlib

from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from app.spatial.grounding.flash_mention_extractor import (
    MentionCache,
    SemanticPlaceEntity,
    SemanticPlaceEntitySet,
    _parse_structured_payload,
    extract_mentions,
    extract_spatial_reference_spec,
)


def _span(text: str, mention: str, *, start: int | None = None) -> dict[str, object]:
    offset = text.index(mention) if start is None else start
    quoted = text[offset : offset + len(mention)]
    return {
        'segment_id': 'query',
        'start': offset,
        'end': offset + len(mention),
        'quote_hash': hashlib.sha256(quoted.encode('utf-8')).hexdigest(),
    }


class _FakeStructuredModel:
    def __init__(self, owner, payload):
        self._owner = owner
        self._payload = payload

    async def ainvoke(self, messages):
        self._owner.calls += 1
        return self._payload


class _FakeStructuredLLM:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def with_structured_output(self, schema, method='function_calling'):
        return _FakeStructuredModel(self, self._payload)


def test_extract_mentions_caches_by_content():
    text = '金田河祠堂'
    llm = _FakeStructuredLLM(
        SemanticPlaceEntitySet(
            status='entities',
            entities=[
                SemanticPlaceEntity(
                    mention='金田河',
                    entity_type='water',
                    role='water',
                    source_span=_span(text, '金田河'),
                    confidence=0.9,
                ),
                SemanticPlaceEntity(
                    mention='祠堂',
                    entity_type='facility',
                    role='facility',
                    source_span=_span(text, '祠堂'),
                    confidence=0.8,
                ),
            ],
        )
    )
    cache = MentionCache(path=None)

    async def run():
        first = await extract_mentions(text, cache=cache, llm=llm)
        second = await extract_mentions(text, cache=cache, llm=llm)
        return first, second

    first, second = asyncio.run(run())
    assert [m.mention for m in first] == ['金田河', '祠堂']
    assert [m.mention for m in second] == ['金田河', '祠堂']
    assert second[1].canonical_name == '祠堂'
    assert second[1].evidence['quote_hash'] == _span(text, '祠堂')['quote_hash']
    assert llm.calls == 1


def test_extract_mentions_ignores_invalid_cached_shape_and_recomputes():
    text = '沿金田河发展'
    cache = MentionCache(path=None)
    cache.put(
        text,
        [
            {
                'mention': '金田河',
                'entity_type': 'water',
                'role': 'water',
                'confidence': 0.7,
                'canonical_name': 'legacy-cache-entry',
            }
        ],
    )
    llm = _FakeStructuredLLM(
        SemanticPlaceEntitySet(
            status='entities',
            entities=[
                SemanticPlaceEntity(
                    mention='金田河',
                    entity_type='water',
                    role='water',
                    source_span=_span(text, '金田河'),
                    confidence=0.9,
                )
            ],
        )
    )

    mentions = asyncio.run(extract_mentions(text, cache=cache, llm=llm))

    assert [m.mention for m in mentions] == ['金田河']
    assert mentions[0].canonical_name == '金田河'
    assert llm.calls == 1


def test_extract_mentions_empty_without_llm(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('no model')

    monkeypatch.setattr(
        'app.spatial.grounding.flash_mention_extractor.create_flash_llm', boom
    )
    assert asyncio.run(extract_mentions('任意文本')) == []


def test_real_flash_spatial_calls_are_opt_in(monkeypatch):
    monkeypatch.delenv('GROUND_LLM_ENABLED', raising=False)
    monkeypatch.delenv('DISABLE_GROUND_LLM', raising=False)
    monkeypatch.delenv('DISABLE_GROUND_REPORT_LLM', raising=False)

    def unexpected_factory(*args, **kwargs):
        raise AssertionError('default-off spatial path must not create a provider')

    monkeypatch.setattr(
        'app.spatial.grounding.flash_mention_extractor.create_flash_llm',
        unexpected_factory,
    )
    assert asyncio.run(extract_mentions('任意文本')) == []
    assert asyncio.run(extract_spatial_reference_spec('甲村附近道路')) is None


def test_parse_structured_payload_handles_model():
    text = '石窟河流经村边'
    payload = SemanticPlaceEntitySet(
        status='entities',
        entities=[
            SemanticPlaceEntity(
                mention='石窟河',
                entity_type='water',
                role='water',
                source_span=_span(text, '石窟河'),
                confidence=0.9,
            )
        ],
    )

    mentions = _parse_structured_payload(payload, text)

    assert len(mentions) == 1
    assert mentions[0].canonical_name == '石窟河'
    assert mentions[0].confidence == 0.9


def test_parse_structured_payload_rejects_untyped_json_string():
    text = '祠堂位于村口'
    raw = (
        '{"status":"entities","entities":[{"mention":"祠堂","entity_type":"facility",'
        '"role":"facility","source_span":{"segment_id":"query","start":0,"end":2,'
        '"quote_hash":"deadbeef"},"confidence":0.7}]}'
    )

    mentions = _parse_structured_payload(raw, text)

    assert mentions == []


def test_extract_mentions_prefers_structured_output():
    text = '沿金田河及Y122乡道发展'
    payload = SemanticPlaceEntitySet(
        status='entities',
        entities=[
            SemanticPlaceEntity(
                mention='金田河',
                entity_type='water',
                role='water',
                source_span=_span(text, '金田河'),
                confidence=0.9,
            ),
            SemanticPlaceEntity(
                mention='Y122乡道',
                entity_type='road',
                role='road',
                source_span=_span(text, 'Y122乡道'),
                confidence=0.8,
            ),
        ],
    )
    llm = _FakeStructuredLLM(payload)

    mentions = asyncio.run(extract_mentions(text, llm=llm))

    by_name = {m.mention: m for m in mentions}
    assert by_name['金田河'].role == 'water'
    assert by_name['金田河'].confidence == 0.9
    assert by_name['Y122乡道'].canonical_name == 'Y122乡道'
    assert by_name['Y122乡道'].evidence['source'] == 'flash_llm_structured'


def test_extract_spatial_reference_spec_accepts_closed_set_semantics():
    spec = SpatialReferenceSpec(
        type='composed',
        op='and',
        semantic_terms=['甲村', '道路'],
        retrieval_scopes=['roads', 'parcels'],
        children=[
            SpatialReferenceSpec(type='directional', direction='W'),
            SpatialReferenceSpec(
                type='attributive',
                reference=RefObject(
                    kind='entity_type',
                    filter={'label_contains': '道路'},
                ),
            ),
        ],
    )
    parsed = asyncio.run(
        extract_spatial_reference_spec(
            '甲村靠山一侧的一条道路',
            llm=_FakeStructuredLLM(spec),
        )
    )
    assert parsed is not None
    assert parsed.children[0].direction == 'W'
    assert parsed.children[1].reference.filter['label_contains'] == '道路'
    assert parsed.semantic_terms == ['甲村', '道路']
    assert parsed.all_retrieval_scopes() == ['roads', 'parcels']


def test_extract_spatial_reference_spec_rejects_invented_semantic_probe():
    spec = SpatialReferenceSpec(
        type='attributive',
        semantic_terms=['炉池自然村'],
        retrieval_scopes=['hazards', 'parcels'],
    )

    parsed = asyncio.run(
        extract_spatial_reference_spec(
            '社前村的地块',
            llm=_FakeStructuredLLM(spec),
        )
    )

    assert parsed is None


def test_extract_spatial_reference_spec_rejects_geometry_identity_fields():
    spec = SpatialReferenceSpec(
        type='attributive',
        attr_filter={'bsm': '44142621100000000001'},
    )
    parsed = asyncio.run(
        extract_spatial_reference_spec(
            '甲村的一块地',
            llm=_FakeStructuredLLM(spec),
        )
    )
    assert parsed is None
