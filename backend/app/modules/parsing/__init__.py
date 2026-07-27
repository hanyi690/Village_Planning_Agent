"""Unified parsing module — deterministic + LLM-based text extraction.

Key components:
  - markdown_parser.py:       Deterministic markdown table parsing (zero LLM)
  - section_classifier.py:    Keyword-based document section classification
  - regulation_extractor.py:  Regex-based constraint/regulation extraction
  - admin_code_loader.py:     Administrative code loading for gazetteer
  - gazetteer.py:             Place name resolution (Tier 0-2)
  - semantics.py:             MetricConcept + ValueSemantics for conflict detection
  - schemas.py:               Pydantic output schemas (kept for backward compat)
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
