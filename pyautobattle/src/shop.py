"""Five reserved unit offers using the shared slot-container interface."""

from __future__ import annotations

from .bench import Bench
from .unit import Unit


class Shop(Bench):
    """Hold at most five independent offers reserved from the unit pool."""

    def __init__(self) -> None:
        self.max_units = 5
        self.num_slots = 5
        self.units: list[Unit | None] = [None] * self.num_slots

    def clear(self) -> None:
        """Clear physical offers after the owner has returned reservations."""
        self.units = [None] * self.num_slots
