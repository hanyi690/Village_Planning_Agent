from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.spatial.grounding.flash_mention_extractor import (
    SemanticPlaceEntity,
    SemanticPlaceEntitySet,
    _parse_structured_payload,
)


def _span(text: str, mention: str, *, start: int | None = None, quote_hash: str | None = None) -> dict[str, object]:
    offset = text.index(mention) if start is None else start
    quoted = text[offset : offset + len(mention)]
    return {
        'segment_id': 'query',
        'start': offset,
        'end': offset + len(mention),
        'quote_hash': quote_hash or hashlib.sha256(quoted.encode('utf-8')).hexdigest(),
    }


def _entity_payload(text: str, mention: str, *, entity_type: str = 'facility', role: str = 'facility') -> dict[str, object]:
    return {
        'mention': mention,
        'entity_type': entity_type,
        'role': role,
        'source_span': _span(text, mention),
        'confidence': 0.8,
    }


def test_semantic_place_entity_contract_forbids_extra_fields():
    text = '金田河'

    with pytest.raises(ValidationError):
        SemanticPlaceEntity.model_validate(
            {
                **_entity_payload(text, '金田河', entity_type='water', role='water'),
                'canonical_name': '金田河',
            }
        )


def test_semantic_place_entity_set_requires_explicit_abstention():
    with pytest.raises(ValidationError):
        SemanticPlaceEntitySet.model_validate({'entities': []})

    model = SemanticPlaceEntitySet.model_validate(
        {'status': 'no_spatial_entity', 'entities': []}
    )
    assert model.status == 'no_spatial_entity'
    assert model.entities == []


@pytest.mark.parametrize(
    ('label', 'payload'),
    [
        (
            'invalid-span',
            lambda text: {
                'status': 'entities',
                'entities': [
                    {
                        **_entity_payload(text, '金田河', entity_type='water', role='water'),
                        'source_span': _span(text, '金田河', start=1),
                    }
                ],
            },
        ),
        (
            'quote-hash-mismatch',
            lambda text: {
                'status': 'entities',
                'entities': [
                    {
                        **_entity_payload(text, '金田河', entity_type='water', role='water'),
                        'source_span': _span(text, '金田河', quote_hash='0' * 64),
                    }
                ],
            },
        ),
        (
            'extra-field',
            lambda text: {
                'status': 'entities',
                'entities': [
                    {
                        **_entity_payload(text, '金田河', entity_type='water', role='water'),
                        'canonical_name': '金田河',
                    }
                ],
            },
        ),
        (
            'illegal-role',
            lambda text: {
                'status': 'entities',
                'entities': [
                    {
                        **_entity_payload(text, '金田河', entity_type='water'),
                        'role': 'river',
                    }
                ],
            },
        ),
        (
            'duplicate',
            lambda text: {
                'status': 'entities',
                'entities': [
                    _entity_payload(text, '金田河', entity_type='water', role='water'),
                    _entity_payload(text, '金田河', entity_type='water', role='water'),
                ],
            },
        ),
    ],
    ids=lambda item: item[0] if isinstance(item, tuple) else None,
)
def test_parse_structured_payload_rejects_invalid_batch(label, payload):
    text = '金田河穿村而过'

    mentions = _parse_structured_payload(payload(text), text)

    assert mentions == []


def test_parse_structured_payload_rejects_abstain_with_entities():
    text = '祠堂位于村口'
    payload = {
        'status': 'no_spatial_entity',
        'entities': [_entity_payload(text, '祠堂')],
    }

    assert _parse_structured_payload(payload, text) == []
