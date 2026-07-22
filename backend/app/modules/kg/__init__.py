"""Planning Knowledge Graph module.

Independently-scoped KG for village planning context and constraints.
Consumed by GIS tools (kg.py, parse_tools.py), PARSE Agent, and future
EXECUTE_OPS Agent — not confined to the GIS subpackage.
"""
from .builder import PlanningKG
from .query import QUERY_TEMPLATES, query_kg
from .ontology import PLN, GEO, EntityTypes, Relations

__all__ = ["PlanningKG", "QUERY_TEMPLATES", "query_kg", "PLN", "GEO", "EntityTypes", "Relations"]
