"""Contract tests for DualPayload, TokenBudget, TopKSampler (design doc §九)."""
import pytest


class TestDualPayload:
    def test_default_construction(self):
        from app.modules.kg.queries.contracts import DualPayload
        dp = DualPayload()
        assert dp.semantic == {}
        assert dp.structured == {}
        assert dp.token_estimate == 0
        assert dp.truncated is False
        assert dp.next_cursor is None

    def test_to_dict_roundtrip(self):
        from app.modules.kg.queries.contracts import DualPayload
        dp = DualPayload(semantic={"a": 1}, structured={"b": 2}, token_estimate=42)
        d = dp.to_dict()
        assert d["semantic"] == {"a": 1}
        assert d["structured"] == {"b": 2}
        assert d["token_estimate"] == 42
        assert d["truncated"] is False
        assert d["next_cursor"] is None


class TestTokenBudget:
    def test_estimate_cjk(self):
        from app.modules.kg.queries.contracts import TokenBudget
        est = TokenBudget.estimate("\u91d1\u7530\u6751")
        assert est == 3

    def test_estimate_ascii(self):
        from app.modules.kg.queries.contracts import TokenBudget
        est = TokenBudget.estimate("hello")
        assert est == 1

    def test_estimate_empty(self):
        from app.modules.kg.queries.contracts import TokenBudget
        assert TokenBudget.estimate("") == 0

    def test_estimate_dict(self):
        from app.modules.kg.queries.contracts import TokenBudget
        est = TokenBudget.estimate_dict({"key": "\u91d1\u7530"})
        assert est > 0

    def test_paginate_within_budget(self):
        from app.modules.kg.queries.contracts import TokenBudget
        entities = ["a", "b", "c", "d"]
        selected, cursor = TokenBudget.paginate(entities, 100, lambda e: e)
        assert selected == entities
        assert cursor is None

    def test_paginate_truncates(self):
        from app.modules.kg.queries.contracts import TokenBudget
        entities = ["aaaa", "bbbb", "cccc"]
        selected, cursor = TokenBudget.paginate(entities, 2, lambda e: e)
        assert len(selected) < len(entities)
        assert cursor is not None
        assert cursor.startswith("offset=")

    def test_within_budget(self):
        from app.modules.kg.queries.contracts import TokenBudget
        assert TokenBudget.within_budget(100, hard_limit=200) is True
        assert TokenBudget.within_budget(300, hard_limit=200) is False

    def test_soft_hard_limits(self):
        from app.modules.kg.queries.contracts import TokenBudget
        assert TokenBudget.SOFT_LIMIT == 4000
        assert TokenBudget.HARD_LIMIT == 6000


class TestTopKSampler:
    def test_empty_returns_empty(self):
        from app.modules.kg.queries.contracts import TopKSampler
        assert TopKSampler.sample([]) == []

    def test_stratified_by_label(self):
        from app.modules.kg.queries.contracts import TopKSampler
        entities = [
            {"bsm": "P1", "area_ha": 1.0, "has_semantic_label": "\u6c34\u7530", "lon": 113.0, "lat": 23.0},
            {"bsm": "P2", "area_ha": 2.0, "has_semantic_label": "\u6c34\u7530", "lon": 113.1, "lat": 23.1},
            {"bsm": "P3", "area_ha": 0.5, "has_semantic_label": "\u4f4f\u5b85\u57fa\u5730", "lon": 113.2, "lat": 23.2},
        ]
        result = TopKSampler.sample(entities, k_budget=40)
        bsms = {e["bsm"] for e in result}
        assert "P1" in bsms
        assert "P3" in bsms

    def test_respects_k_budget(self):
        from app.modules.kg.queries.contracts import TopKSampler
        entities = [{"bsm": f"P{i}", "area_ha": float(i), "has_semantic_label": "L"} for i in range(100)]
        result = TopKSampler.sample(entities, k_budget=10)
        assert len(result) <= 10