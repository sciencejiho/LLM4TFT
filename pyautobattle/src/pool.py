"""Finite shared unit supply with independent sampled unit instances."""

from __future__ import annotations

import copy
import csv
import json
import random
from itertools import islice
from pathlib import Path

from .status import Status
from .unit import Unit

MAX_UNIT_DEFINITIONS = 1000


class Pool:
    """Track reserved copies in shops, benches and deployed teams."""

    def __init__(self, unit_file: str, synergy_file: str, rng: random.Random | None = None):
        self.rng = rng if rng is not None else random.Random(0)
        self.unit_counts = [0, 22, 20, 17, 10, 9]
        self.unit_dict: dict[str, Unit] = {}
        self.available_units: list[dict[str, int]] = [{} for _ in range(6)]
        self.synergy_dict: dict[str, list[str]] | None = None
        self.register_unit(unit_file)

    def register_unit(self, unit_csv_file_name: str) -> None:
        """Load immutable base definitions and initialize finite supply."""
        path = Path(unit_csv_file_name)
        if not path.is_absolute() and not path.exists():
            path = Path(__file__).resolve().parents[2] / path
        with path.open(newline="", encoding="utf-8") as source:
            rows = list(islice(csv.DictReader(source), MAX_UNIT_DEFINITIONS + 1))
            if not rows or len(rows) > MAX_UNIT_DEFINITIONS:
                raise ValueError("Unit catalog must contain between 1 and 1000 definitions")
            for row in rows:
                status = Status(
                    *[
                        float(row[key])
                        for key in (
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
                    ]
                )
                name, cost = row["name"], int(row["cost"])
                if not 1 <= cost <= 5 or name in self.unit_dict:
                    raise ValueError("Unit definitions require unique names and costs from 1 to 5")
                self.unit_dict[name] = Unit(row["unit_id"], name, cost, 1, status, [])
                self.available_units[cost][name] = self.unit_counts[cost]

    def register_synergy(self, synergy_file: str) -> None:
        """Load legacy metadata; these labels do not implement combat effects."""
        with open(synergy_file, encoding="utf-8") as source:
            self.synergy_dict = json.load(source)
        if len(self.synergy_dict) > MAX_UNIT_DEFINITIONS:
            raise ValueError("Too many synergy metadata labels")
        for synergy, names in self.synergy_dict.items():
            if len(names) > MAX_UNIT_DEFINITIONS:
                raise ValueError("Too many units in synergy metadata")
            for name in names:
                self.unit_dict[name].synergy.append(synergy)

    def get_unit(self, unit_name: str, unit_level: int) -> Unit:
        """Create scaled unit stats without reserving additional supply."""
        if not 1 <= unit_level <= 3:
            raise ValueError("Unit level must be between 1 and 3")
        unit = copy.deepcopy(self.unit_dict[unit_name])
        unit.level = unit_level
        coefficient = 1.8 ** (unit_level - 1)
        unit.status.hp = unit.status.max_hp = int(unit.status.hp * coefficient)
        unit.status.attack = int(unit.status.attack * coefficient)
        return unit

    def remove_unit(self, unit: Unit) -> None:
        """Reserve represented base copies, rejecting an exhausted supply."""
        count = 3 ** (unit.level - 1)
        if self.available_units[unit.cost][unit.name] < count:
            raise ValueError(f"Insufficient copies of {unit.name}")
        self.available_units[unit.cost][unit.name] -= count

    def add_unit(self, unit: Unit) -> None:
        """Return all base copies represented by a unit to supply."""
        self.available_units[unit.cost][unit.name] += 3 ** (unit.level - 1)

    def sample(self, cost: int) -> Unit | None:
        """Reserve a weighted random copy, or return None if the tier is empty."""
        names = [name for name, count in self.available_units[cost].items() if count > 0]
        if not names:
            return None
        weights = [self.available_units[cost][name] for name in names]
        unit = self.get_unit(self.rng.choices(names, weights=weights, k=1)[0], 1)
        self.remove_unit(unit)
        return unit
