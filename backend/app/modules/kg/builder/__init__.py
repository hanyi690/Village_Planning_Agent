"""PlanningKG builder subpackage - four-layer construction.

Exports:
  PlanningKG - main KG class
  KGInputParcels - typed parcel container
  Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin
  DlqCategory, DlqEntry, DlqReport - dead letter queue types

Note: intent_converter (parse_contracts -> context_contracts pure mapping)
will be added here once spatial_ops/grounding.py is implemented.
See spatial_ops/README.md and parse/README.md for the v5.0 design.
"""
from .base import PlanningKG, KGInputParcels
from .mixins import Layer1Mixin, Layer2Mixin, Layer3Mixin, Layer4Mixin, QueryMixin
from app.modules.kg.dlq import DlqCategory, DlqEntry, DlqReport

__all__ = [
    "PlanningKG", "KGInputParcels",
    "Layer1Mixin", "Layer2Mixin", "Layer3Mixin", "Layer4Mixin", "QueryMixin",
    "DlqCategory", "DlqEntry", "DlqReport",
]
