"""Unified parsing module — structured LLM output extraction.

Replaces the regex-based parsing in layout_tools.py and unifies
the Instructor-based extraction in summary/generator.py.

Key components:
- structured_output.py: Instructor-based structured parse (max_retries=3)
- metric_anchors.py:   Deterministic metric extraction (zero LLM)
- schemas.py:          Pydantic output schemas (IntentOutput + summary schemas)
- validator.py:        Semantic validation + area_ratio normalization
- prompts.py:          Unified prompt templates
"""
