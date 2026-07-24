"""Schema — unified data definitions, encodings, and output specifications.

Top-level shared contract for all spatial planning data types.
Consumed by: Data, KG, Agent, Tools — depends on nothing.

Sub-packages:
  types/        — spatial feature types (Group A~E), canonical containers, raster types
  encodings/    — classification schemas, code sets, YAML dictionaries
  contracts/    — cross-layer data contracts (PARSE, EXECUTE, LAYOUT)
  output/       — GDB layer registry, zone coloring schemes
  utils/        — pure computation utilities (zero external deps)
"""

from __future__ import annotations

# ── Sub-package re-exports ──────────────────────────────────────────
from .types import *  # noqa: F401,F403
from .encodings import *  # noqa: F401,F403
from .contracts import *  # noqa: F401,F403
from .output import *  # noqa: F401,F403
from .utils import *  # noqa: F401,F403
