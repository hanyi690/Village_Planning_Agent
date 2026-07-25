"""PlanningKG builder subpackage - four-layer construction.

Exports:
  PlanningKG - main KG class
  KGInputParcels - typed parcel container

Note: intent_converter (parse_contracts -> context_contracts pure mapping)
will be added here once spatial_ops/grounding.py is implemented.
See spatial_ops/README.md and parse/README.md for the v5.0 design.
"""
from .base import PlanningKG, KGInputParcels

__all__ = ["PlanningKG", "KGInputParcels"]
