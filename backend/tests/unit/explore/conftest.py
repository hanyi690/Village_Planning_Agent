"""Shared fixtures for EXPLORE service tests."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def mock_bundle():
    bundle = MagicMock()
    bundle.village_name = "田坑村"
    return bundle


@pytest.fixture
def mock_kg():
    return MagicMock()


@pytest.fixture
def mock_cognition():
    cog = MagicMock()
    cog.semantic = {
        "context_block": {
            "overview": "组团状分布",
            "parcel_count": 50,
            "total_area_ha": 320.0,
            "spatial_pattern": "组团状",
        },
        "constraint_block": {"constraint_coverage": "生态红线30%"},
    }
    return cog
