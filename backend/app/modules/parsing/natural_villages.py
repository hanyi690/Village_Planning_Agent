"""Known natural-village closed set for parsing and domain consumers.

Pulled out of ``app.modules.kg.enrichment.report_entity_enrichment`` so
``parsing`` never depends on the kg graph layer at import time.  The loader
(``app.modules.kg.village_name_registry``) is a pure villages.yaml reader
(leaf→leaf, acceptable during migration).
"""

from __future__ import annotations

from app.modules.kg.village_name_registry import load_all_village_names

_KNOWN_NATURAL_VILLAGES = set(load_all_village_names())
