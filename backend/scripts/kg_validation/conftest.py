"""Pytest collection guard — test_kg_answers.py is a top-level KG verification
script (module-level execution builds a real cached KG), not a pytest test.
Run it directly: python scripts/kg_validation/test_kg_answers.py"""

collect_ignore = ["test_kg_answers.py"]
