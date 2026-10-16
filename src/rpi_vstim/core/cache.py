"""Small bounded caches used by hardware-independent preparation paths."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar


Key = TypeVar("Key", bound=Hashable)
Value = TypeVar("Value")


class BoundedCache(Generic[Key, Value]):
    """A bounded LRU cache with observable hit/miss/eviction counters."""

    def __init__(self, max_items: int, *, size_of: Callable[[Value], int] | None = None) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        self.max_items = max_items
        self._items: OrderedDict[Key, Value] = OrderedDict()
        self._size_of = size_of or (lambda value: 1)
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, key: Key) -> Value | None:
        value = self._items.get(key)
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        self._items.move_to_end(key)
        return value

    def put(self, key: Key, value: Value) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
            self.evictions += 1

    def __len__(self) -> int:
        return len(self._items)

    @property
    def memory_bytes(self) -> int:
        return sum(self._size_of(value) for value in self._items.values())

    def metrics(self) -> dict[str, int]:
        return {
            "items": len(self),
            "max_items": self.max_items,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "memory_bytes": self.memory_bytes,
        }
