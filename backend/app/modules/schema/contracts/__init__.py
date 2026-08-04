"""Cross-layer data contracts — PARSE, EXECUTE, LAYOUT, and spatial cognition.

- parse_contracts.py:     PARSE output (text -> intent)
- execution_contracts.py: EXECUTE input (intent -> spatial)
- validation_contracts.py: validation loop (results -> compliance)
- layout_contracts.py:    LAYOUT tools (intent + pipeline output)
- context_contracts.py:   spatial cognition cards (ContextBlock-based)
- context_ref_contracts.py: run/dataset context references
- workflow_contracts.py:  workflow control (run requests, routing, gates, feedback)
- evidence_contracts.py:  evidence exploration and bundles
- l1_contracts.py:        L1 baseline snapshot
- l2_contracts.py:        L2 development strategy
- l3_contracts.py:        L3 planning program and interventions
"""

from .contract_meta import *  # noqa: F401,F403
from .provenance import *  # noqa: F401,F403
from .classification_ref import *  # noqa: F401,F403
from .parse_contracts import *  # noqa: F401,F403
from .execution_contracts import *  # noqa: F401,F403
from .validation_contracts import *  # noqa: F401,F403
from .layout_contracts import *  # noqa: F401,F403
from .context_contracts import *  # noqa: F401,F403
from .context_ref_contracts import *  # noqa: F401,F403
from .workflow_contracts import *  # noqa: F401,F403
from .evidence_contracts import *  # noqa: F401,F403
from .l1_contracts import *  # noqa: F401,F403
from .l2_contracts import *  # noqa: F401,F403
from .l3_contracts import *  # noqa: F401,F403
from .constraint_contracts import *  # noqa: F401,F403
from .spatial_reference_contracts import *  # noqa: F401,F403
from .parse_result_contracts import *  # noqa: F401,F403
from .grounding_contracts import *  # noqa: F401,F403
from .selection_contracts import *  # noqa: F401,F403
