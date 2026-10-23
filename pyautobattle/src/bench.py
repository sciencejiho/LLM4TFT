"""Fixed-slot unit containers shared by benches, shops and fields."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .base import Base
from .unit import Unit

MAX_SLOTS = 28


class Bench(Base):
    """Own a fixed set of slots with independent deployment capacity."""

    def __init__(self) -> None:
        self.max_units = 9
        self.num_slots = 9
        self.units: list[Unit | None] = [None] * self.num_slots

    def find_empty(self) -> int:
        """Return the first free physical slot, or -1."""
        return next((index for index, unit in enumerate(self.units) if unit is None), -1)

    def __getitem__(self, index: int) -> Unit | None:
        return self.units[index]

    def __iter__(self) -> Iterator[Unit | None]:
        return iter(self.units)

    def add(self, unit: Unit | None) -> int:
        """Insert a unit when both physical space and team capacity permit."""
        if unit is None or self.is_full():
            return -1
        index = self.find_empty()
        self.units[index] = unit
        return index

    def pop(self, index: int) -> Unit | None:
        """Remove a slot's contents without changing container length."""
        unit = self.units[index]
        self.units[index] = None
        return unit

    def insert(self, index: int, unit: Unit | None) -> None:
        """Fill a physical slot without shifting or growing the board."""
        if not 0 <= index < self.num_slots:
            raise ValueError("Unit slot is outside the container")
        if self.units[index] is None and unit is not None and self.is_full():
            raise ValueError("Unit container is at capacity")
        self.units[index] = unit

    def to_json(self) -> dict[str, Any]:
        """Serialize slot limits and complete metadata for occupied slots."""
        return {
            "max_units": self.max_units,
            "num_slots": self.num_slots,
            "units": [unit.to_json() if unit is not None else None for unit in self.units],
        }

    def __len__(self) -> int:
        return len(self.units)

    def observe(self) -> dict[str, Any]:
        """Return structured role-rich observations for all slots."""
        return self.to_json()

    def is_full(self) -> bool:
        """Return whether deployment capacity has been reached."""
        return sum(unit is not None for unit in self.units) >= self.max_units

    def count(self, unit: Unit) -> int:
        """Count matching unit IDs and star levels."""
        return sum(
            candidate is not None
            and candidate.unit_id == unit.unit_id
            and candidate.level == unit.level
            for candidate in self.units
        )

    def remove(self, unit: Unit) -> Unit | None:
        """Remove one matching star-level unit, preserving slot structure."""
        for index in range(self.num_slots):
            candidate = self.units[index]
            if (
                candidate is not None
                and candidate.unit_id == unit.unit_id
                and candidate.level == unit.level
            ):
                return self.pop(index)
        return None
