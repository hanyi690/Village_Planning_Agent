"""Schema — unified data definitions, encodings, and output specifications.

Top-level shared contract for all spatial planning data types.
Consumed by: Data, KG, Agent, Tools — depends on nothing.

Sub-packages:
  encodings/           — classification schemas, code sets, YAML dictionaries
  advisory_crosswalks/ — cross-system advisory mapping tables
  utils/               — pure computation utilities (zero external deps)

Folded out (v5 refactor): types/ → app.data.model; output/ → app.infrastructure
(export + rendering); provenance/ → app.data.model; layers.py → app.workflow.layers;
contracts/ → app/contracts (T9a).
"""

from __future__ import annotations

# ── Sub-package re-exports ──────────────────────────────────────────
from .encodings import *  # noqa: F401,F403
from .advisory_crosswalks import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
