"""Fixed board slots whose deployment limit follows the player's level."""

from __future__ import annotations

import copy
from typing import Any

from .bench import Bench
from .unit import Unit


class Field(Bench):
    """Own the player's 4-by-7 half-board and deployable team slots."""

    def __init__(self) -> None:
        self.max_units = 1
        self.num_slots = 28
        self.units: list[Unit | None] = [None] * self.num_slots

    def get_combat_mode(self) -> list[dict[str, Any] | None]:
        """Serialize units and preserve empty board slots."""
        return [unit.get_combat_mode() if unit is not None else None for unit in self.units]

    def level_up(self) -> None:
        """Increase deployment capacity up to the supported player level cap."""
        self.max_units = min(10, self.max_units + 1)

    def update(self) -> None:
        """Advance occupied units by the legacy default simulation tick."""
        for index in range(self.num_slots):
            unit = self.units[index]
            if unit is not None:
                unit.update()

    def __deepcopy__(self, memo: dict[int, Any]) -> Field:
        result = type(self)()
        memo[id(self)] = result
        result.max_units = self.max_units
        result.num_slots = self.num_slots
        result.units = copy.deepcopy(self.units, memo)
        return result
