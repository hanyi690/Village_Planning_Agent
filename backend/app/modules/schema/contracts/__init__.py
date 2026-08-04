"""Cross-layer data contracts — PARSE, EXECUTE, LAYOUT, and spatial cognition.

- parse_contracts.py:     PARSE output (text -> intent)
- execution_contracts.py: EXECUTE input (intent -> spatial)
- validation_contracts.py: validation loop (results -> compliance)
- layout_contracts.py:    LAYOUT tools (intent + pipeline output)
- context_contracts.py:   spatial cognition cards (ContextBlock-based)
"""

from .contract_meta import *  # noqa: F401,F403
from .provenance import *  # noqa: F401,F403
from .classification_ref import *  # noqa: F401,F403
from .parse_contracts import *  # noqa: F401,F403
from .execution_contracts import *  # noqa: F401,F403
from .validation_contracts import *  # noqa: F401,F403
from .layout_contracts import *  # noqa: F401,F403
from .context_contracts import *  # noqa: F401,F403
