"""P1: get_any_kg removed; session_kg must not leak across sessions."""
import importlib

import pytest


def test_get_any_kg_removed():
    mod = importlib.import_module("app.modules.kg.manager")
    assert not hasattr(mod.KGManager, "get_any_kg"), (
        "get_any_kg must be removed - it can return another session's KG"
    )


def test_session_kg_returns_none_when_no_session_kg(monkeypatch):
    from app.tools.access import shared

    class FakeManager:
        def get_session_kg(self, session_id):
            return None

    monkeypatch.setattr(
        "app.modules.kg.manager.KGManager",
        lambda: FakeManager(),
    )

    result = shared.session_kg("session-A")
    assert result is None, (
        "session_kg must return None when no KG is registered for the session, "
        "not fall back to another session's KG"
    )


def test_session_kg_returns_correct_kg(monkeypatch):
    from app.tools.access import shared

    class FakeKG:
        pass

    fake_kg = FakeKG()

    class FakeManager:
        def get_session_kg(self, session_id):
            if session_id == "session-A":
                return fake_kg
            return None

    monkeypatch.setattr(
        "app.modules.kg.manager.KGManager",
        lambda: FakeManager(),
    )

    result = shared.session_kg("session-A")
    assert result is fake_kg

    result_b = shared.session_kg("session-B")
    assert result_b is None
