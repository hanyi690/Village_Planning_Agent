"""Tests for the GROUND flash-LLM mention enhancer and resolver integration.

The enhancer only rewrites text; BSMs still come from the evidence index.
A fake LLM object is used so no real model call happens in unit tests.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.spatial.grounding.flash_mention_extractor import (
    MentionCache,
    SemanticPlaceEntity,
    SemanticPlaceEntitySet,
    _parse_response,
    _parse_structured_payload,
    extract_mentions,
)


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, content: str):
        self._content = content
        self.calls = 0

    async def ainvoke(self, prompt: str):
        self.calls += 1
        return _FakeResponse(self._content)


def test_parse_response_handles_mention_role_lines():
    raw = "石窟河|water\n砂石路|road\nNONE\n```\n祠堂|facility\n```\n 垃圾行 "
    mentions = _parse_response(raw)
    names = [m.mention for m in mentions]
    assert "石窟河" in names
    assert "砂石路" in names
    assert "祠堂" in names
    assert len(names) == 3


def test_parse_response_drops_noise_and_short_tokens():
    mentions = _parse_response("利\n建\n新|unknown\nNONE")
    assert mentions == []


def test_extract_mentions_caches_by_content():
    llm = _FakeLLM("金田河|water\n祠堂|facility")
    cache = MentionCache(path=None)

    async def run():
        first = [
            m.mention
            for m in await extract_mentions("沿金田河发展", cache=cache, llm=llm)
        ]
        second = [
            m.mention
            for m in await extract_mentions("沿金田河发展", cache=cache, llm=llm)
        ]
        return first, second

    first, second = asyncio.run(run())
    assert first == second == ["金田河", "祠堂"]
    assert llm.calls == 1  # second call served from cache


def test_extract_mentions_empty_without_llm(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(
        "app.spatial.grounding.flash_mention_extractor.create_flash_llm", boom
    )
    assert asyncio.run(extract_mentions("任意文本")) == []


class _FakeStructuredModel:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages):
        return self._payload


class _FakeStructuredLLM:
    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, schema, method="function_calling"):
        return _FakeStructuredModel(self._payload)


def test_parse_structured_payload_handles_model():
    payload = SemanticPlaceEntitySet(
        entities=[
            SemanticPlaceEntity(
                mention="石窟河",
                entity_type="water",
                role="water",
                canonical_name="石窟河",
                confidence=0.9,
            )
        ]
    )
    mentions = _parse_structured_payload(payload)
    assert len(mentions) == 1
    assert mentions[0].canonical_name == "石窟河"
    assert mentions[0].confidence == 0.9


def test_parse_structured_payload_handles_json_string():
    raw = (
        '{"entities": [{"mention": "祠堂", "entity_type": "facility", '
        '"role": "facility", "canonical_name": "祠堂", "confidence": 0.7}]}'
    )
    mentions = _parse_structured_payload(raw)
    assert len(mentions) == 1
    assert mentions[0].role == "facility"
    assert mentions[0].confidence == 0.7


def test_parse_structured_payload_drops_invalid_and_normalizes_role():
    payload = SemanticPlaceEntitySet(
        entities=[
            SemanticPlaceEntity(mention="", role="water"),
            SemanticPlaceEntity(mention="祠", role="facility"),
            SemanticPlaceEntity(mention="金田河", role="bogus"),
        ]
    )
    mentions = _parse_structured_payload(payload)
    assert [m.mention for m in mentions] == ["金田河"]
    assert mentions[0].role == "unknown"


def test_extract_mentions_prefers_structured_output():
    payload = SemanticPlaceEntitySet(
        entities=[
            SemanticPlaceEntity(
                mention="金田河", role="water", canonical_name="金田河", confidence=0.9
            ),
            SemanticPlaceEntity(
                mention="Y122乡道", role="road", canonical_name="122乡道", confidence=0.8
            ),
        ]
    )
    llm = _FakeStructuredLLM(payload)
    mentions = asyncio.run(extract_mentions("沿金田河及Y122乡道发展", llm=llm))
    by_name = {m.mention: m for m in mentions}
    assert by_name["金田河"].role == "water"
    assert by_name["金田河"].confidence == 0.9
    assert by_name["Y122乡道"].canonical_name == "122乡道"
    assert by_name["Y122乡道"].evidence["source"] == "flash_llm_structured"