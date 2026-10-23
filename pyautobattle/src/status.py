"""Numeric combat statistics with independent current and maximum health."""

from __future__ import annotations

import copy
from typing import Any

from .base import Base


class Status(Base):
    """Store basic attack stats; magic fields remain legacy metadata only."""

    def __init__(
        self,
        hp: float,
        mp: float,
        attack: float,
        defense: float,
        attackSpeed: float,
        specialAttack: float,
        specialDefense: float,
        criticalRate: float,
        criticalDamage: float,
        attackRange: float,
    ):
        self.max_hp = float(hp)
        self.hp = float(hp)
        self.mp = float(mp)
        self.attack = float(attack)
        self.defense = float(defense)
        self.attackSpeed = float(attackSpeed)
        self.specialAttack = float(specialAttack)
        self.specialDefense = float(specialDefense)
        self.criticalRate = float(criticalRate)
        self.criticalDamage = float(criticalDamage)
        self.attackRange = int(attackRange)

    def observe(self) -> dict[str, Any]:
        """Return all numeric fields for agents and compatibility callers."""
        return dict(self.__dict__)

    def to_json(self) -> dict[str, Any]:
        """Return current health and complete scaled combat statistics."""
        return self.observe()

    def __add__(self, other: Status) -> Status:
        if not isinstance(other, Status):
            return NotImplemented
        return self._combine(other, 1)

    def __sub__(self, other: Status) -> Status:
        if not isinstance(other, Status):
            return NotImplemented
        return self._combine(other, -1)

    def _combine(self, other: Status, sign: int) -> Status:
        keys = (
            "hp",
            "mp",
            "attack",
            "defense",
            "attackSpeed",
            "specialAttack",
            "specialDefense",
            "criticalRate",
            "criticalDamage",
            "attackRange",
        )
        return Status(*[getattr(self, key) + sign * getattr(other, key) for key in keys])

    def __deepcopy__(self, memo: dict[int, Any]) -> Status:
        result = type(self).__new__(type(self))
        memo[id(self)] = result
        result.__dict__ = copy.deepcopy(self.__dict__, memo)
        return result
