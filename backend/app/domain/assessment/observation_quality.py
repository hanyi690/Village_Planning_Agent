"""Observation quality validation for L1/L2 structured LLM output.

A dimension that returns observations with a high ratio of missing spatial
fields (location/relation) is a quality defect, not a valid completion: it
would feed incomplete facts downstream.  The worker validates before marking
the dimension complete; a defect is surfaced through ``dimension_failures``
and retried once with corrective feedback instead of silently consuming the
gap (design: validation step after every LLM call; quality failures retried
with feedback, per exa/LangGraph fault-tolerance guidance).
"""
from __future__ import annotations


def validate_observations(
    observations: list,
    *,
    max_defect_ratio: float = 0.5,
) -> dict:
    """Return a quality report for a list of observation rows.

    A row is defective when it carries no name, or carries neither a
    ``location`` nor a ``relation`` (i.e. no spatial anchor at all).  Empty
    observation lists are allowed (the dimension simply observed no entities).
    """
    total = len(observations or [])
    if total == 0:
        return {"ok": True, "total": 0, "missing_name": 0, "no_place": 0, "defect_ratio": 0.0, "feedback": ""}

    missing_name: list[int] = []
    no_place: list[int] = []
    for index, item in enumerate(observations):
        name = _text(item.get("name"))
        location = _text(item.get("location"))
        relation = _text(item.get("relation"))
        if not name:
            missing_name.append(index)
        if not location and not relation:
            no_place.append(index)

    defects = len(set(missing_name) | set(no_place))
    ratio = round(defects / total, 3)
    feedback = ""
    if ratio >= max_defect_ratio:
        feedback = (
            f"????????? {total} ??{len(missing_name)} ?? name?"
            f"{len(no_place)} ?? location ?? relation???????????? {ratio:.0%}?"
            "???????????? name?????? location ? relation ?????"
        )
    return {
        "ok": ratio < max_defect_ratio,
        "total": total,
        "missing_name": len(missing_name),
        "no_place": len(no_place),
        "defect_ratio": ratio,
        "feedback": feedback,
    }


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = ["validate_observations"]
