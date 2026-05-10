"""
Test fixtures for session route endpoint tests.
"""
import sys
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create TestClient with mocked dependencies."""
    from unittest.mock import patch

    with (
        patch('app.services.runtime.PlanningRuntimeService._instance', None),
        patch('app.services.runtime.PlanningRuntimeService._initialized', True),
    ):
        from app.main import app
        yield TestClient(app)


@pytest.fixture
def sample_state():
    """Sample checkpoint state with reports across 3 layers."""
    return {
        "reports": {
            "layer1": {
                "location": "## 区位分析报告\n\n村庄位于...",
                "population": "## 人口分析报告\n\n人口数据...",
            },
            "layer2": {
                "industry": "## 产业分析报告\n\n产业现状...",
            },
            "layer3": {},
        }
    }


@pytest.fixture
def sample_revisions():
    """Sample DimensionRevision history."""
    return [
        {
            "id": 3,
            "session_id": "test-session-1",
            "layer": 1,
            "dimension_key": "location",
            "content": "## 区位分析 v3\n\n修订后内容...",
            "version": 3,
            "reason": "用户反馈修订",
            "created_at": "2026-05-10T12:00:00",
            "created_by": "user",
        },
        {
            "id": 2,
            "session_id": "test-session-1",
            "layer": 1,
            "dimension_key": "location",
            "content": "## 区位分析 v2\n\nAI自动优化...",
            "version": 2,
            "reason": "AI 自动优化",
            "created_at": "2026-05-10T11:00:00",
            "created_by": "ai",
        },
        {
            "id": 1,
            "session_id": "test-session-1",
            "layer": 1,
            "dimension_key": "location",
            "content": "## 区位分析 v1\n\n初始生成...",
            "version": 1,
            "reason": "初始生成",
            "created_at": "2026-05-10T10:00:00",
            "created_by": "ai",
        },
    ]
