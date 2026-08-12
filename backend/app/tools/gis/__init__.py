"""GIS adapters used by data/spatial delivery code.

Interactive layout/validation tools were removed when PARSE, EXECUTE and
DELIVER became explicit stages.  The package now exposes no Agent-owned GIS
state bundle; delivery uses ``static_render`` with a materialized snapshot.
"""

__all__ = []
