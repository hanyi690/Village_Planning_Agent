"""D 子任务：L1 prompt 注入 EXPLORE brief 单测。"""
import pytest

from app.agent.analysis.node import _build_prompt
from app.config import get_dimension_config

BRIEF_SECTION = (
    "**【EXPLORE 空间基础（供分析参考）】**\n"
    "- 村域概况：金田村，总面积200公顷\n"
    "- 关键实体（村内）：田坑自然村\n"
)


def test_build_prompt_l1_injects_brief_before_skeleton():
    cfg = get_dimension_config("land_use")
    prompt = _build_prompt(
        cfg,
        {"dimension_key": "land_use", "config": {}},
        "",
        "",
        "",
        explore_brief_section=BRIEF_SECTION,
    )
    assert "**输出骨架**" in prompt
    assert prompt.index(BRIEF_SECTION) < prompt.index("**输出骨架**")


def test_build_prompt_l1_empty_brief_is_noop():
    cfg = get_dimension_config("land_use")
    prompt_a = _build_prompt(cfg, {"dimension_key": "land_use", "config": {}}, "", "", "")
    prompt_b = _build_prompt(
        cfg, {"dimension_key": "land_use", "config": {}}, "", "", "",
        explore_brief_section="",
    )
    assert prompt_a == prompt_b
    assert "EXPLORE 空间基础" not in prompt_a


def test_build_prompt_l2_ignores_brief():
    cfg = get_dimension_config("development_goals")
    layer = getattr(cfg, "layer", 2)
    if layer != 2:
        pytest.skip("dimension not L2")
    prompt = _build_prompt(
        cfg,
        {"dimension_key": "development_goals", "config": {}},
        "",
        "",
        "",
        explore_brief_section=BRIEF_SECTION,
    )
    assert "EXPLORE 空间基础" not in prompt
