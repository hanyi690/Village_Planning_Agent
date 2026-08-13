"""Tests for the GROUND flash-LLM mention enhancer and resolver integration.

The enhancer only rewrites text; BSMs still come from the evidence index.
A fake LLM object is used so no real model call happens in unit tests.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.spatial.grounding.flash_mention_extractor import (
    MentionCache,
    _parse_response,
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