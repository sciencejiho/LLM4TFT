"""Units with honest physical combat roles and time-based attack cooldowns."""

from __future__ import annotations

import copy
import json
import random
from typing import Any

from .active import Active
from .status import Status
from .util import ROLE_DESCRIPTIONS, TEAM, role_for_status


class Unit(Active):
    """Represent one independent unit and its current combat state."""

    def __init__(
        self, unit_id: str, name: str, cost: int, level: int, status: Status, synergy: list[str]
    ):
        super().__init__()
        self.synergy = synergy
        self.unit_id = unit_id
        self.cost = cost
        self.name = name
        self.level = level
        self.status = status
        self.additional_status = Status(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        self.items: list[Any] = []
        self.cooldown_time = 0.0
        self.mana = 0
        self.live = True
        self.team = TEAM.HOME
        self.move_cool = 0.5
        self._rng = random.Random(0)

    def observe(self) -> dict[str, Any]:
        """Return mechanics implemented by this unit without invented abilities."""
        return self.to_json()

    def to_json(self, mode: str = "simple") -> dict[str, Any]:
        """Serialize identity, role and scaled stats in every observation mode."""
        role = role_for_status(self.status.attackRange, self.status.defense)
        info = {
            "id": self.unit_id,
            "name": self.name,
            "cost": self.cost,
            "level": self.level,
            "role": role,
            "role_description": ROLE_DESCRIPTIONS[role],
            "status": self.status.to_json(),
        }
        if mode == "battle":
            info["team"] = self.team.value
        return info

    def get_combat_mode(self) -> dict[str, Any]:
        """Return a detached JSON-compatible observation."""
        return json.loads(json.dumps(self.observe()))

    def get_sell_gold(self) -> int:
        """Return sale value, preserving the existing star-cost formula."""
        value = self.cost * 3 ** (self.level - 1)
        return value - int(self.cost > 1 and self.level > 1)

    def die(self) -> None:
        """Mark this unit as eliminated from combat."""
        self.live = False

    def alive(self) -> bool:
        """Return whether this unit can act."""
        return self.live

    def update(self, elapsed_seconds: float = 1 / 60) -> None:
        """Advance cooldowns by elapsed simulation seconds."""
        self.cooldown(elapsed_seconds)
        self.move_cool -= elapsed_seconds

    def move(self) -> bool:
        """Allow one movement step every half second."""
        if self.move_cool > 1e-9:
            return False
        self.move_cool = 0.5
        return True

    def cooldown(self, elapsed_seconds: float = 1 / 60) -> None:
        """Reduce attack cooldown measured in seconds."""
        self.cooldown_time -= elapsed_seconds

    def cooldowned(self) -> bool:
        """Return whether an attack is available."""
        return self.cooldown_time <= 1e-9 and self.status.attackSpeed > 0

    def hit(self, other: Unit, rng: random.Random | None = None) -> dict[str, Any]:
        """Apply a physical basic attack using an optional game-local RNG."""
        if not isinstance(other, Unit):
            raise TypeError("Attack target must be a Unit")
        generator = rng if rng is not None else self._rng
        critical = generator.random() < self.status.criticalRate / 100
        multiplier = self.status.criticalDamage if critical else 1.0
        damage = self.status.attack * 100 / (100 + other.status.defense) * multiplier
        other.status.hp -= damage
        self.mana += 20
        self.cooldown_time = 1 / max(self.status.attackSpeed, 0.01)
        killed = other.status.hp <= 0
        if killed:
            other.die()
        return {
            "attacker": (self.name, self.unit_id),
            "defender": (other.name, other.unit_id),
            "damage": round(damage),
            "critical": critical,
            "killed": killed,
        }

    def __deepcopy__(self, memo: dict[int, Any]) -> Unit:
        unit_copy = type(self).__new__(type(self))
        memo[id(self)] = unit_copy
        unit_copy.__dict__ = copy.deepcopy(self.__dict__, memo)
        return unit_copy
