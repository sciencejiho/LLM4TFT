"""Resolve public unit metadata from rich observations or CSV defaults."""

from __future__ import annotations

import csv
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


class TEAM(Enum):
    """Identify the two sides of a combat arena."""

    HOME = "home"
    AWAY = "away"


ROLE_DESCRIPTIONS = MappingProxyType(
    {
        "tank": "Durable front-line unit that absorbs physical attacks.",
        "fighter": "Close-range unit that deals physical basic attacks.",
        "marksman": "Ranged unit that deals physical basic attacks.",
    }
)


def role_for_status(attack_range: float, defense: float) -> str:
    """Infer implemented role from basic attack range and durability."""
    if attack_range >= 3:
        return "marksman"
    return "tank" if defense >= 35 else "fighter"


def _load_units() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "unit.csv"
    with path.open(newline="", encoding="utf-8") as source:
        return {row["unit_id"]: row for row in csv.DictReader(source)}


unit_info = _load_units()


def get_unit_dict() -> dict[str, dict[str, Any]]:
    """Return known unit definitions including role metadata."""
    return {key: get_info({"id": key}) for key in unit_info}


def get_info(unit: dict[str, Any] | None) -> dict[str, Any]:
    """Merge live unit metadata with CSV defaults for older observations."""
    info = dict(unit_info.get((unit or {}).get("id", ""), {}))
    info.update(unit or {})
    status = dict(info)
    status.update(info.get("status", {}))
    role = info.get("role") or role_for_status(
        float(status.get("attackRange", 0)), float(status.get("defense", 0))
    )
    info.setdefault("name", "Unknown")
    info.setdefault("cost", 0)
    info["role"] = role
    info["role_description"] = info.get("role_description", ROLE_DESCRIPTIONS[role])
    return info


def get_name(unit: dict[str, Any] | None) -> str:
    """Return the public name or Unknown for an empty slot."""
    return str(get_info(unit)["name"])


def get_cost(unit: dict[str, Any] | None) -> int:
    """Return unit cost from rich data or the bundled definition."""
    return int(get_info(unit)["cost"])


def get_price(unit: dict[str, Any]) -> int:
    """Return the existing sale-price formula for a serialized unit."""
    cost = get_cost(unit)
    level = int(unit.get("level", 1))
    return cost * 3 ** (level - 1) - int(cost > 1 and level > 1)
