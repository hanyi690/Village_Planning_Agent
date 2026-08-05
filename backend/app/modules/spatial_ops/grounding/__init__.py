"""Spatial grounding subpackage — resolve spatial descriptions, bind to bundle.

Contains grounding.py (spatial description resolution), resolver.py
(SpatialResolver entry point) and bundle_binder.py (deterministic binding).
"""
from .grounding import *  # noqa: F401,F403
from .grounding import __all__  # noqa: F401
from .grounding import _parcel_centroid  # noqa: F401
from .resolver import *  # noqa: F401,F403
from .resolver import _extract_location_tokens  # noqa: F401
from .bundle_binder import *  # noqa: F401,F403
