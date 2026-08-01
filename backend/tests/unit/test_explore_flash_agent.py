"""Tests for ExploreFlashAgent — Stage-0 migration sanity.

Covers:
  - ``ExploreFlashAgent`` deterministic baseline (``llm=None``) runs without a
    session KG; the kg readiness check is the only KG touch.
  - Chunking / 6-domain classification / BSM extraction on a small Chinese
    planning snippet.
  - ``create_flash_llm`` constructs without error when
    ``GIS_EXPLORE_LLM_ENABLED=true`` (the default after this migration).
  - Stage-0 ``require_session_kg`` raises a clear ``LookupError`` when no
    session KG is registered.

These tests do NOT exercise the Flash LLM round-trip (kept offline to avoid
network in CI); production runs use ``qwen-flash`` per ``GIS_EXPLORE_*`` env.
"""

from __future__ import annotations

import pytest

from app.agent.explore import (
    ExploreFlashAgent,
    ExplorationInstruction,
    ExplorationInstructionCollection,
    SessionKGQuery,
    explore_planning_text,
)
from app.core.settings import (
    GIS_EXPLORE_LLM_ENABLED,
    GIS_EXPLORE_MAX_TOKENS,
    GIS_EXPLORE_MODEL,
    GIS_EXPLORE_TEMPERATURE,
)
from app.modules.kg import get_kg_manager, require_session_kg


def test_settings_explore_flash_defaults() -> None:
    """Stage-0 default: Flash LLM is ON, with the qwen-flash model."""
    assert GIS_EXPLORE_LLM_ENABLED is True
    assert GIS_EXPLORE_MODEL == "qwen-flash"
    assert GIS_EXPLORE_TEMPERATURE == 0.1
    assert GIS_EXPLORE_MAX_TOKENS == 1200


def test_require_session_kg_raises_for_missing_session() -> None:
    """``require_session_kg`` must raise a clear error for unknown sessions."""
    manager = get_kg_manager()
    manager.remove_session("explore-flash-no-session")

    with pytest.raises(LookupError, match="not initialized"):
        require_session_kg("explore-flash-no-session")


def test_explore_flash_agent_explicit_llm_is_used() -> None:
    """Passing a non-None ``llm`` overrides the env-flag auto-selection."""
    sentinel = object()
    agent = ExploreFlashAgent(
        session_id="explore-flash-explicit",
        village_name="测试村",
        llm=sentinel,  # type: ignore[arg-type]
    )
    assert agent.llm is sentinel
    assert agent.kg_tools.session_id == "explore-flash-explicit"


def test_explore_flash_agent_default_uses_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``llm`` is omitted, env ``GIS_EXPLORE_LLM_ENABLED`` controls init."""
    from app.core import settings as settings_mod

    monkeypatch.setattr(settings_mod, "GIS_EXPLORE_LLM_ENABLED", False)
    agent = ExploreFlashAgent(
        session_id="explore-flash-env-off",
        village_name="测试村",
    )
    assert agent.llm is None

    monkeypatch.setattr(settings_mod, "GIS_EXPLORE_LLM_ENABLED", True)
    agent_on = ExploreFlashAgent(
        session_id="explore-flash-env-on",
        village_name="测试村",
    )
    assert agent_on.llm is not None


def test_create_flash_llm_constructs_when_enabled() -> None:
    """``create_flash_llm`` should return a usable LLM instance under the env."""
    llm = ExploreFlashAgent.create_flash_llm()
    assert llm is not None


def test_chunking_and_domain_classification() -> None:
    """Deterministic path: chunk -> domain classification -> instruction."""
    sample = (
        "# 道路规划\n"
        "新建一条通村道路，连接村委会与村小学，BSM:A001 经过集中建设区北侧。\n\n"
        "# 设施布局\n"
        "新建村委会服务中心，配套卫生室与文化广场。\n\n"
        "# 用地\n"
        "建设用地占比需控制在 12% 以内，禁止占用耕地。\n"
    )

    # Stub the KG readiness check — we are only testing the deterministic
    # chunking + domain classification path here.
    class _FakeKG:
        pass

    manager = get_kg_manager()
    manager.register_session("explore-flash-chunk-test", _FakeKG())

    try:
        agent = ExploreFlashAgent(
            session_id="explore-flash-chunk-test",
            village_name="测试村",
            llm=None,
        )
        collection = agent.explore(sample)
    finally:
        manager.remove_session("explore-flash-chunk-test")

    assert isinstance(collection, ExplorationInstructionCollection)
    assert collection.session_id == "explore-flash-chunk-test"
    assert collection.village_name == "测试村"
    # Should produce at least one instruction per non-empty chunk.
    assert len(collection.instructions) >= 1
    domains = {i.domain for i in collection.instructions}
    assert domains <= {"road", "facility", "landuse", "zone", "regulation", "axis"}

    # BSM extraction should pick up A001 from the road chunk.
    road_instr = next((i for i in collection.instructions if i.domain == "road"), None)
    assert road_instr is not None
    assert "A001" in road_instr.candidate_bsm_list
    assert road_instr.action in {"new_connection", "road_requirement"}


def test_explore_planning_text_helper_does_not_require_session_kg_optional() -> None:
    """The helper should fail loud (not silently) when no KG is registered."""
    manager = get_kg_manager()
    manager.remove_session("explore-flash-helper-test")

    with pytest.raises(LookupError):
        explore_planning_text(
            session_id="explore-flash-helper-test",
            village_name="测试村",
            planning_text="新建一条通村道路。",
        )


def test_session_kg_query_lazy_loads() -> None:
    """``SessionKGQuery.kg`` must raise if no KG, not silently fall back."""
    manager = get_kg_manager()
    manager.remove_session("explore-flash-query-test")

    q = SessionKGQuery("explore-flash-query-test")
    with pytest.raises(LookupError):
        _ = q.kg


def test_explore_detects_project_domain_zone_mentions() -> None:
    """P2: 功能区/项目句不再被丢弃 — domain=project，提及含功能区名。"""
    sample = (
        "# 产业规划\n"
        "在田坑自然村新建南药产业园，占地0.15公顷，园寨自然村布局田园石参种植园。\n"
    )

    class _FakeKG:
        pass

    manager = get_kg_manager()
    manager.register_session("explore-flash-project-test", _FakeKG())

    try:
        agent = ExploreFlashAgent(
            session_id="explore-flash-project-test",
            village_name="测试村",
            llm=None,
        )
        collection = agent.explore(sample)
    finally:
        manager.remove_session("explore-flash-project-test")

    domains = {i.domain for i in collection.instructions}
    assert "project" in domains
    project_instr = next((i for i in collection.instructions if i.domain == "project"), None)
    assert project_instr is not None
    assert any("产业园" in m or "种植园" in m for m in project_instr.entity_mentions)


def test_contract_round_trip() -> None:
    """Pydantic contracts serialize / deserialize cleanly (round-trip JSON)."""
    raw = ExplorationInstruction(
        instruction_id="EXP-0001",
        source_chunk_id="chunk-0001",
        section_title="道路规划",
        source_page=1,
        evidence_text="新建通村道路",
        domain="road",
        action="new_connection",
        candidate_bsm_list=["A001"],
        confidence=0.82,
        requires_human_confirmation=False,
    )
    collection = ExplorationInstructionCollection(
        session_id="s",
        village_name="v",
        instructions=[raw],
    )
    payload = collection.model_dump_json()
    rebuilt = ExplorationInstructionCollection.model_validate_json(payload)
    assert rebuilt.instructions[0].candidate_bsm_list == ["A001"]
    assert rebuilt.schema_version == "exploration-instructions-v1"