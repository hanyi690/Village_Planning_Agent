"""Unified parsing module — deterministic + LLM-based text extraction.

Key components:
  - structured_output.py: Instructor-based structured parse (max_retries=3)
  - metric_anchors.py:   Deterministic metric extraction from GIS (zero LLM)
  - schemas.py:          Pydantic output schemas (ZoneOutput, IntentOutput)
  - semantics.py:        ValueSemantics enum + cross-dimension metric mapping
  - validator.py:        (removed — replaced by parse_agent validate_and_merge)
  - prompts.py:          (removed — replaced by parse_prompts.py)

  - markdown_parser.py:       Deterministic markdown table parsing (zero LLM)
  - section_classifier.py:    Keyword-based document section classification
  - regulation_extractor.py:  Regex-based constraint/regulation extraction

  - summary_generator.py:     Instructor-based summary generation (kept for
                               backward compat with report_store.py)
  - summary_parser.py:        Summary text parsing (kept for report_store.py)
"""

from .markdown_parser import parse_markdown_tables, split_by_headers, detect_table
from .section_classifier import classify_section, SECTION_KEYWORDS
from .regulation_extractor import extract_regulations_regex, REGULATION_PATTERNS

__all__ = [
    # Deterministic parsers
    "parse_markdown_tables",
    "split_by_headers",
    "detect_table",
    "classify_section",
    "SECTION_KEYWORDS",
    "extract_regulations_regex",
    "REGULATION_PATTERNS",
]
