"""External retrieval provider adapters; nothing here contacts the network."""

from .exa_adapter import FakeExternalSearchAdapter

__all__ = ["FakeExternalSearchAdapter"]
