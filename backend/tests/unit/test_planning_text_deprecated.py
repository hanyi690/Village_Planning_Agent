"""Tests that PlanningTextGenerator is marked as deprecated (Wave O)."""

import pytest

from app.modules.planning_text.config import PlanningTextConfig
from app.modules.planning_text.generator import PlanningTextGenerator


def test_planning_text_generator_emits_deprecation_warning():
    config = PlanningTextConfig(session_id="s1")
    with pytest.warns(DeprecationWarning, match="PlanningTextGenerator is deprecated"):
        PlanningTextGenerator(config)
