"""Unit tests for the structured summary generator.

All LLM interactions are mocked — no real Instructor / DashScope calls
are made so tests stay fast and network-independent.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.modules.parsing import summary_generator as sg
from app.modules.parsing.schemas import LandUsePlanningSummary


@pytest.mark.asyncio
async def test_regex_metrics_extraction():
    content = (
        "本村现状建设用地 12.5公顷，耕地保有量 30公顷。"
        "户籍人口 350人，共 120户。森林覆盖率 45%。"
    )
    regex_metrics = sg._extract_metrics_regex(content)
    assert regex_metrics["area_ha"] == 12.5
    assert regex_metrics["population"] == 350
    assert regex_metrics["households"] == 120
    assert regex_metrics["percentage"] == 45

    dim_metrics = sg._extract_dimension_metrics("land_use_planning", content)
    assert dim_metrics["建设用地规模_公顷"] == 12.5
    assert dim_metrics["耕地保有量_公顷"] == 30


@pytest.mark.asyncio
async def test_key_points_extraction():
    content = (
        "### 村庄区位优越\n"
        "### 交通便利\n"
        "### 基础设施完善\n"
        "**人口结构年轻**\n"
        "**主导产业为农业**\n"
    )
    points = sg._extract_key_points_regex(content)
    assert len(points) >= 4
    assert "村庄区位优越" in points
    assert "交通便利" in points
    assert "人口结构年轻" in points


@pytest.mark.asyncio
async def test_instructor_generate_success():
    fake_summary = LandUsePlanningSummary(
        dimension_key="land_use_planning",
        layer=3,
        word_count=100,
        key_points=["优化用地布局", "保障粮食安全"],
        text_summary="本村规划以乡村振兴为目标，优化产业布局。",
        metrics={"current_construction_ha": 12.5},
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_summary

    with patch(
        "app.core.instructor_client.get_instructor_client",
        return_value=fake_client,
    ), patch(
        "app.core.instructor_client.get_flash_model",
        return_value="qwen-flash",
    ):
        out = await sg.generate_structured_summary(
            "land_use_planning", 3, "本村建设用地 12.5公顷。"
        )

    data = json.loads(out)
    assert data["dimension_key"] == "land_use_planning"
    assert data["layer"] == 3
    assert "key_points" in data
    assert "text_summary" in data
    assert "metrics" in data
    assert data["key_points"] == ["优化用地布局", "保障粮食安全"]
    assert data["metrics"]["current_construction_ha"] == 12.5


@pytest.mark.asyncio
async def test_fallback_on_instructor_failure():
    content = "### 用地紧张\n**发展需求旺盛**\n建设用地 12.5公顷"
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("llm down")

    with patch(
        "app.core.instructor_client.get_instructor_client",
        return_value=fake_client,
    ):
        out = await sg.generate_structured_summary("land_use_planning", 3, content)

    data = json.loads(out)
    assert data["dimension_key"] == "land_use_planning"
    assert data["metrics"]["建设用地规模_公顷"] == 12.5
    assert "用地紧张" in data["key_points"]
    assert data["text_summary"].startswith(content[:10])


@pytest.mark.asyncio
async def test_empty_content_returns_default():
    out = await sg.generate_structured_summary("land_use", 1, "")
    data = json.loads(out)
    assert data["dimension_key"] == "land_use"
    assert data["layer"] == 1
    assert data["word_count"] == 0
