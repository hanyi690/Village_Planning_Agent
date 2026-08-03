"""Compatibility import for the semantic-to-GIS bundle binder.

The implementation lives in ``app.modules.spatial_ops.bundle_binder`` so it
can be reused outside the GIS agent.  Keep this module while external callers
transition to the canonical import path.
"""

from app.modules.spatial_ops.bundle_binder import (
    DeterministicBundleBinder,
    bind_exploration_to_bundle,
)

__all__ = ["DeterministicBundleBinder", "bind_exploration_to_bundle"]
