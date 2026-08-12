from pathlib import Path
from typing import Optional

import yaml

from app.data.encodings import code_sets as cs
from app.data.model.audit import ProvenanceSource


_TUGUI_YAML = (
    Path(__file__).parents[2]
    / "data"
    / "encodings"
    / "dicts"
    / "encodings"
    / "tugui.yaml"
)


def _tugui_codes() -> set[str]:
    data = yaml.safe_load(_TUGUI_YAML.read_text(encoding="utf-8"))
    return {row["code"] for row in data.get("classes", []) if "code" in row}


_TUGUI_CODES: set[str] = _tugui_codes()
_GBT21010_CODES: set[str] = set(cs.DLBM_TO_DLMC.keys())
_APPENDIX5_CODES: set[str] = set(cs.GHYTBM_TO_GHYTMC.keys())
_VNE_CODES: set[str] = set(cs.VNE_CODE_TO_NAME.keys())


def detect_encoding(value: Optional[str]) -> Optional[ProvenanceSource]:
    """Detect which encoding system a DLBM-shaped value belongs to.

    Priority order:
    1. GB/T 21010 (现状法定底数)
    2. appendix5 (广东规划实践口径)
    3. tugui (土规字段)
    4. VNE (住建口子集)

    Returns None if value is empty or unrecognized.
    """
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v in _GBT21010_CODES:
        return ProvenanceSource.GBT21010
    if v in _APPENDIX5_CODES:
        return ProvenanceSource.PRACTICAL_APPENDIX5
    if v in _TUGUI_CODES:
        return ProvenanceSource.TUGUI
    if v in _VNE_CODES:
        return ProvenanceSource.VNE
    return None
