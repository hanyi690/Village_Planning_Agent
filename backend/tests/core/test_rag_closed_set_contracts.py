from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def test_metadata_inference_uses_typed_output_and_pending_on_failure(monkeypatch):
    from app.infrastructure.rag.utils import metadata_extractor
    from app.infrastructure.llm import factory

    class Structured:
        async def ainvoke(self, _prompt):
            return {"doc_type": "standard", "keywords": ["国土空间"]}

    class LLM:
        def with_structured_output(self, model, **_kwargs):
            assert model is metadata_extractor.DocumentTypeProposal
            return Structured()

    monkeypatch.setattr(factory, "create_flash_llm", lambda **_: LLM())
    accepted = asyncio.run(
        metadata_extractor.MetadataExtractor.infer_doc_type_with_llm(
            "技术规范",
            "正文",
        )
    )
    assert accepted == {
        "status": "accepted",
        "doc_type": "standard",
        "keywords": ["国土空间"],
    }

    class BrokenLLM:
        def with_structured_output(self, _model):
            raise ValueError("provider returned untyped text")

    monkeypatch.setattr(factory, "create_flash_llm", lambda **_: BrokenLLM())
    pending = asyncio.run(
        metadata_extractor.MetadataExtractor.infer_doc_type_with_llm(
            "未知文档",
            "正文",
        )
    )
    assert pending["status"] == "pending"
    assert pending["doc_type"] == ""


def test_rag_query_generation_uses_bounded_typed_batch(monkeypatch):
    from app.contracts.llm.rag_contracts import RagQueryBatch
    from app.infrastructure.rag import service as rag_service

    calls: list[dict] = []

    async def fake_run(response_model, messages, **kwargs):
        calls.append({"response_model": response_model, "messages": messages, **kwargs})
        return RagQueryBatch(queries=["村庄 公共服务 规划标准", "道路 交通 规范"])

    monkeypatch.setattr(rag_service, "create_flash_llm", lambda **_: object())
    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        fake_run,
    )

    service = rag_service.RagService.__new__(rag_service.RagService)
    cfg = SimpleNamespace(
        key="public_services",
        name="公共服务",
        rag_query="检索公共服务设施规划标准",
        phase_id="layer1",
        depends_on=[],
        layer_depends_on=[],
        phase_depends_on=[],
    )
    from app.infrastructure.context import planning_context_factory

    monkeypatch.setattr(
        planning_context_factory,
        "get_cached_context",
        lambda _session_id: SimpleNamespace(
            session_id="test",
            village_name="测试村",
            version=1,
            content_hash="snapshot",
        ),
    )
    queries = asyncio.run(service.generate_queries(cfg, {"session_id": "test"}))

    assert queries == ["村庄 公共服务 规划标准", "道路 交通 规范"]
    assert calls[0]["response_model"] is RagQueryBatch
    assert calls[0]["contract_key"] == "rag.query_batch"
    assert calls[0]["max_retries"] == 0


def test_outline_proposal_uses_stable_heading_ids_and_exact_coverage(monkeypatch):
    from app.infrastructure.rag.context import LLMOutlineCorrector, OutlineLevelBatch

    corrector = LLMOutlineCorrector(batch_size=10)
    prompts: list[str] = []

    class Structured:
        def invoke(self, prompt):
            text = prompt[0]["content"] if isinstance(prompt, list) else prompt
            prompts.append(text)
            ids = [line.split(" ", 1)[0].split("=", 1)[1] for line in text.splitlines() if line.startswith("heading_id=")]
            return OutlineLevelBatch.model_validate(
                {
                    "items": [
                        {"heading_id": ids[0], "level": 1, "heading_type": "chapter"},
                        {"heading_id": ids[1], "level": 2, "heading_type": "section"},
                    ]
                }
            )

    class LLM:
        def with_structured_output(self, model, **_kwargs):
            assert model is OutlineLevelBatch
            return Structured()

    corrector._llm = LLM()
    source = "# 标题一\n\n正文\n\n## 标题二\n\n正文"
    corrected, headings = corrector.correct(source, "doc.md")
    assert "index" not in prompts[0]
    assert all(item["heading_id"].startswith("heading:") for item in headings)
    assert corrected.startswith("# 标题一")
    assert "## 标题二" in corrected


def test_outline_proposal_with_missing_heading_is_rejected(monkeypatch):
    from app.infrastructure.rag.context import LLMOutlineCorrector

    class Structured:
        def invoke(self, _prompt):
            return {"items": [{"heading_id": "not-in-input", "level": 1, "heading_type": "chapter"}]}

    class LLM:
        def with_structured_output(self, _model, **_kwargs):
            return Structured()

    corrector = LLMOutlineCorrector(batch_size=10)
    corrector._llm = LLM()
    source = "# 标题一\n\n正文\n\n## 标题二\n\n正文"
    corrected, headings = corrector.correct(source, "doc.md")
    assert corrected == source
    assert all("inferred_level" not in item for item in headings)


def test_candidate_engine_never_uses_mapping_default_for_unresolved_choice():
    from app.data.encodings.dicts.candidate_engine import CandidateEngine

    class Table:
        def propose(self, _source_code):
            return {
                "decision": "context",
                "default": "wrong-default",
                "targets": [
                    {"code": "candidate-a", "when": {"kind": "comparison", "field": "x", "op": "==", "value": 1}},
                    {"code": "candidate-b", "when": {"kind": "comparison", "field": "x", "op": "==", "value": 2}},
                ],
            }

    class Center:
        def get_mapping(self, _name):
            return Table()

    engine = CandidateEngine(Center())
    unresolved = engine.resolve("source", "target", "code")
    assert unresolved.kind == "manual"
    assert unresolved.chosen_code == ""
    assert unresolved.candidate_set_digest


def test_disambiguation_decision_requires_runtime_closed_set_validation():
    from app.data.encodings.dicts.disambiguation import (
        Candidate,
        DisambiguationContext,
        DisambiguationDecision,
        validate_disambiguation_decision,
    )

    context = DisambiguationContext(
        source_system="source",
        source_code="code",
        candidates=[Candidate(code="candidate-a")],
    )
    with pytest.raises(ValueError):
        DisambiguationDecision(
            status="selected",
            chosen_code="candidate-a",
            confidence="high",
            rationale="selected",
            candidate_set_digest=context.candidate_set_digest,
            decided_by="default",
        )

    decision = DisambiguationDecision(
        status="selected",
        chosen_code="unknown",
        confidence="low",
        rationale="provider proposal",
        candidate_set_digest=context.candidate_set_digest,
        decided_by="llm",
    )
    result = validate_disambiguation_decision(context, decision)
    assert result.status == "ambiguous"
    assert result.selected_candidate_id is None
