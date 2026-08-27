"""Static input defaults for the current 金田村 real-data runner."""

from __future__ import annotations

from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATUS_REPORT_PATH = (
    _PROJECT_ROOT
    / "docs"
    / "MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md"
)

JINTIAN_VILLAGE_DATA: dict[str, str] = {}
if _STATUS_REPORT_PATH.exists():
    JINTIAN_VILLAGE_DATA = {
        "status_report": _STATUS_REPORT_PATH.read_text(encoding="utf-8"),
        "village_name": "金田村",
    }

DEFAULT_TASK_DESCRIPTION = (
    "编制梅州市金田村村庄规划，"
    "涵盖国土空间布局、产业发展、人居环境、设施配套、历史文化保护等方面。"
)

DEFAULT_CONSTRAINTS = (
    "1. 耕地保有量不低于85.2公顷，永久基本农田78.83公顷；\n"
    "2. 生态保护红线362.02公顷；\n"
    "3. 村庄建设用地规模30.5公顷；\n"
    "4. 林地保有量不低于423.6公顷；\n"
    "5. 符合梅州市国土空间总体规划要求。"
)


__all__ = [
    "DEFAULT_CONSTRAINTS",
    "DEFAULT_TASK_DESCRIPTION",
    "JINTIAN_VILLAGE_DATA",
]
