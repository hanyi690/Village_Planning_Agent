"""State builder for fluent state update API.

Lightweight utility class for unified state dictionary update patterns.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from langchain_core.messages import AIMessage, HumanMessage

T = TypeVar("T", bound=dict[str, Any])


class StateBuilder(Generic[T]):
    """State builder with fluent API for state updates.

    Used to build state update dictionaries with support for method chaining.

    Example:
        >>> builder = StateBuilder()
        >>> updates = builder.set("key1", "value1").set("key2", "value2").build()
        >>> print(updates)
        {'key1': 'value1', 'key2': 'value2'}
    """

    def __init__(self, original_state: T | None = None) -> None:
        """Initialize the state builder.

        Args:
            original_state: Original state (optional, only used for build_full())
        """
        self.original_state = original_state or {}
        self.updates: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> StateBuilder[T]:
        """Set a field value.

        Args:
            key: Field name
            value: Field value

        Returns:
            Self for method chaining
        """
        self.updates[key] = value
        return self

    def set_multiple(self, updates: dict[str, Any]) -> StateBuilder[T]:
        """Set multiple fields at once.

        Args:
            updates: Dictionary of field updates

        Returns:
            Self for method chaining
        """
        self.updates.update(updates)
        return self

    def add_message(self, content: str, role: str = "ai") -> StateBuilder[T]:
        """Add a message to the messages list.

        Args:
            content: Message content
            role: Role ("ai" or "human")

        Returns:
            Self for method chaining
        """
        if "messages" not in self.updates:
            self.updates["messages"] = []

        msg = AIMessage(content=content) if role == "ai" else HumanMessage(content=content)
        self.updates["messages"].append(msg)
        return self

    def append_to(self, key: str, value: Any) -> StateBuilder[T]:
        """Append a value to a list field.

        Args:
            key: Field name (must be a list)
            value: Value to append

        Returns:
            Self for method chaining
        """
        if key not in self.updates:
            self.updates[key] = []
        elif not isinstance(self.updates[key], list):
            self.updates[key] = [self.updates[key]]

        self.updates[key].append(value)
        return self

    def merge(self, other_updates: dict[str, Any]) -> StateBuilder[T]:
        """Merge another state update dictionary.

        Args:
            other_updates: Another state update dictionary

        Returns:
            Self for method chaining
        """
        self.updates = {**self.updates, **other_updates}
        return self

    def build(self) -> dict[str, Any]:
        """Build the state update (contains only changes).

        Returns:
            Dictionary containing only the changes
        """
        return self.updates

    def build_full(self) -> dict[str, Any]:
        """Build the full state (original + updates).

        Returns:
            Complete dictionary with original state and updates merged
        """
        return {**self.original_state, **self.updates}

    def has_updates(self) -> bool:
        """Check if there are pending updates.

        Returns:
            True if there are updates, False otherwise
        """
        return len(self.updates) > 0

    def clear(self) -> StateBuilder[T]:
        """Clear all updates.

        Returns:
            Self for method chaining
        """
        self.updates.clear()
        return self

    def __repr__(self) -> str:  # pragma: no cover
        return f"StateBuilder(updates={self.updates})"


__all__ = ["StateBuilder"]
