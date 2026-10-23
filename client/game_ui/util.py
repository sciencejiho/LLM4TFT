"""Normalize current and legacy unit payloads for presentation."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from pyautobattle.src.util import get_info as csv_info

ROLE_COLORS = MappingProxyType({"tank": "#69c9d0", "fighter": "#edb56a", "marksman": "#ac9fea"})
ROLE_DESCRIPTIONS = MappingProxyType(
    {
        "tank": "Absorbs damage with high defense. Place at the front to protect allies.",
        "fighter": "Deals damage in close combat. Place near the front beside a tank.",
        "marksman": "Attacks from range. Place at the back behind your front line.",
    }
)
COST_COLORS = ("#435366", "#879aa7", "#61bc9e", "#69a7e8", "#b194e0", "#e6bd69")


def unit_details(unit: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve role and scaled stats, preferring metadata supplied by the server.

    Parameters
    ----------
    unit : dict or None
        Current rich payload or legacy ``id``/``level`` payload.

    Returns
    -------
    dict
        Display metadata with numeric combat stats and an honest CSV fallback.
    """
    if not unit:
        return {"name": "Unknown unit", "level": 1, "cost": 0, "role": "fighter", "status": {}}
    try:
        base = dict(csv_info(unit))
    except (KeyError, TypeError):
        base = {}
    level = max(1, min(int(unit.get("level", 1)), 4))
    coefficient = 1.8 ** (level - 1)
    status = {
        key: float(base.get(key, 0))
        for key in (
            "hp",
            "attack",
            "defense",
            "attackSpeed",
            "attackRange",
            "criticalRate",
            "criticalDamage",
        )
    }
    status["hp"] = int(status["hp"] * coefficient)
    status["attack"] = int(status["attack"] * coefficient)
    status["max_hp"] = status["hp"]
    status.update(unit.get("status", {}))
    role = (
        "marksman"
        if status["attackRange"] >= 3
        else "tank"
        if status["defense"] >= 35
        else "fighter"
    )
    role = unit.get("role", role)
    if role not in ROLE_COLORS:
        role = "fighter"
    return {
        "name": unit.get(
            "name",
            "Unknown unit" if base.get("name") == "Unknown" else base.get("name", "Unknown unit"),
        ),
        "level": level,
        "cost": int(unit.get("cost", base.get("cost", 0))),
        "role": role,
        "role_description": unit.get("role_description", ROLE_DESCRIPTIONS[role]),
        "status": status,
    }


def get_info(unit: dict[str, Any] | None) -> dict[str, Any]:
    """Return normalized combat stats for compatibility with existing callers."""
    return unit_details(unit)["status"]


def get_cost(unit: dict[str, Any] | None) -> int:
    """Return the unit's purchase cost."""
    return int(unit_details(unit)["cost"])


def get_name(unit: dict[str, Any] | None) -> str:
    """Return a readable unit name."""
    return str(unit_details(unit)["name"])


def get_price(unit: dict[str, Any] | None) -> int:
    """Return the engine's sale value at the unit's current star level."""
    info = unit_details(unit)
    value = info["cost"] * 3 ** (info["level"] - 1)
    return max(0, value - int(info["cost"] > 1 and info["level"] > 1))


def get_color(unit: dict[str, Any] | None) -> tuple[str, str]:
    """Return a cost accent and hover color."""
    return COST_COLORS[max(0, min(5, get_cost(unit)))], "#314657"


def unit_to_text(unit: dict[str, Any] | None) -> str:
    """Format compact board text with role and stars."""
    if not unit:
        return ""
    info = unit_details(unit)
    return f"{info['name']}\n{info['role'].title()}  {'★' * info['level']}"


def unit_to_shop_text(unit: dict[str, Any] | None) -> str:
    """Format a shop card with its actual gold cost."""
    return f"{unit_to_text(unit)}\n{get_cost(unit)} gold" if unit else "Sold"
