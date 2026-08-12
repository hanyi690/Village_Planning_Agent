"""Unified parsing module — deterministic + LLM-based text extraction.

Key components:
  - admin_code_loader.py:     Administrative code loading for gazetteer
  - gazetteer.py:             Place name resolution (Tier 0-2)
  - semantics.py:             MetricConcept + ValueSemantics for conflict detection
  - schemas.py:               Pydantic input/data schemas
  - tables.py:                Structured table detection/extraction (unit-level)
  - spatial_language.py:      Spatial relation language parsing
  - summary_generator.py:     Structured summary generation
  - summary_parser.py:        Structured summary parsing
  - table_schema_inference.py: Table schema inference
"""
