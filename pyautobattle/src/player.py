"""Player decisions, economy and finite-pool unit ownership."""

from __future__ import annotations

from collections import deque
from typing import Any

from .base import Base
from .bench import Bench
from .field import Field
from .pool import Pool
from .rules import Rules, resolve_rules
from .shop import Shop
from .unit import Unit
from .util import role_for_status

MSG = "message"
ERROR = "error"
MAX_LEVEL = 10
MAX_ACTION_HISTORY = 4096


class Player(Base):
    """Own a team and shop under a versioned economy profile."""

    def __init__(self, player_id: str, name: str, pool: Pool, rules: Rules | None = None):
        self.player_id, self.name = player_id, name
        self.rules = resolve_rules(rules)
        self.hp = self.rules.starting_hp
        self.field, self.bench, self.shop = Field(), Bench(), Shop()
        self.pool = pool
        self.gold, self.level = self.rules.starting_gold, self.rules.starting_level
        self.field.max_units = self.level
        self.exp = 0
        self.req_exp_list = [0, 2, 2, 6, 10, 20, 36, 48, 76, 84, float("inf")]
        self.streak = 0
        self.active = False
        self.is_bot = False
        self.income_turn = 0
        self.log: deque[dict[str, Any]] = deque(maxlen=MAX_ACTION_HISTORY)
        self.combat_result_list: list[int] = []
        self.interest_list: list[int] = []
        self.streak_gold_list: list[int] = []
        self.turn_gold_list: list[int] = []

    def is_alive(self) -> bool:
        """Return whether this player remains in the match."""
        return self.hp > 0

    def get_damage(self, amount: int) -> None:
        """Apply nonnegative damage, clamping displayed health at zero."""
        self.hp = max(0, self.hp - max(0, amount))

    def observe(self) -> dict[str, Any]:
        """Expose this player's own decision state with role-rich units."""
        return self.to_json()

    def economy(self) -> dict[str, int]:
        """Forecast next preparation income from current gold and streak."""
        base = self.rules.base_income(self.income_turn)
        interest = min(max(self.gold, 0) // 10, 5)
        streak = self.rules.streak_income(self.streak)
        next_interest = min((interest + 1) * 10, 50)
        return {
            "base": base,
            "interest": interest,
            "streak": streak,
            "total": base + interest + streak,
            "next_interest": next_interest,
        }

    def to_json(self) -> dict[str, Any]:
        """Serialize current resources, private shop and available decisions."""
        return {
            "id": self.player_id,
            "name": self.name,
            "level": self.level,
            "hp": self.hp,
            "field": self.field.to_json(),
            "bench": self.bench.to_json(),
            "shop": self.shop.to_json(),
            "gold": self.gold,
            "exp": self.exp,
            "req_exp": self.get_required_exp() if self.level < MAX_LEVEL else None,
            "unit_rate": self.get_appearance_rate(),
            "streak": self.streak,
            "active": self.active,
            "ruleset": self.rules.name,
            "economy": self.economy(),
            "is_bot": self.is_bot,
            "legal_actions": self.legal_actions(),
        }

    def legal_actions(self) -> dict[str, Any]:
        """Describe economy/shop actions only; move and sale legality is not enumerated."""
        enabled = self.active and self.is_alive()
        offers = []
        for index, unit in enumerate(self.shop.units):
            if unit is None or unit.cost > self.gold or not enabled:
                continue
            has_room = not self.bench.is_full()
            can_merge = self.bench.count(unit) + self.field.count(unit) >= 2
            if has_room or can_merge:
                offers.append(index)
        return {
            "scope": "economy_and_shop",
            "reroll": enabled and self.gold >= 2,
            "buy_exp": enabled and self.gold >= 4 and self.level < MAX_LEVEL,
            "buy_unit": offers,
        }

    def get_required_exp(self) -> float:
        """Return experience needed for the next level."""
        return self.req_exp_list[self.level]

    def player_level_up(self) -> str:
        """Spend accumulated experience for one level and team slot."""
        self.exp -= int(self.get_required_exp())
        self.field.level_up()
        self.level += 1
        self.log.append({"type": "level_up", "args": self.level})
        return f"{self.name} level up to {self.level}"

    def purchase_exp(self) -> dict[str, list[str]]:
        """Buy four experience for four gold when alive and below max level."""
        if not self.is_alive() or self.level >= MAX_LEVEL or self.gold < 4:
            return {MSG: [f"{self.name} cannot buy EXP"]}
        self.gold -= 4
        self.log.append({"type": "buy_exp", "args": 4})
        return self.give_exp(4)

    def give_exp(self, exp_amount: int) -> dict[str, list[str]]:
        """Grant experience and perform at most ten level transitions."""
        if not self.is_alive() or self.level >= MAX_LEVEL:
            return {MSG: [f"{self.name} cannot gain EXP"]}
        self.exp += max(0, exp_amount)
        messages = [f"{self.name} get {exp_amount} EXP"]
        self.log.append({"type": "get_exp", "args": exp_amount})
        for _ in range(MAX_LEVEL):
            if self.level >= MAX_LEVEL or self.exp < self.get_required_exp():
                return {MSG: messages}
            messages.append(self.player_level_up())
        raise RuntimeError("Player exceeded the bounded level progression")

    def swap(self, where: list[Unit | None], source_index: int, target_index: int) -> None:
        """Swap occupied slots without changing container length."""
        where[source_index], where[target_index] = where[target_index], where[source_index]

    def _container(self, source_type: str) -> Bench | None:
        if source_type in ("bench", "b"):
            return self.bench
        if source_type in ("field", "f"):
            return self.field
        return None

    def move_unit(
        self, source_type: str, target_type: str, source_index: int, target_index: int
    ) -> dict[str, list[str]]:
        """Move or swap slots atomically after validating board capacity."""
        source, target = self._container(source_type), self._container(target_type)
        if not self.is_alive() or source is None or target is None:
            return {MSG: [f"{self.name} invalid move"]}
        if not 0 <= source_index < source.num_slots:
            return {MSG: [f"{self.name} invalid source index"]}
        if target_index == -1:
            target_index = target.find_empty()
        if not 0 <= target_index < target.num_slots or source[source_index] is None:
            return {MSG: [f"{self.name} invalid target or empty source"]}
        if source is not target and target[target_index] is None and target.is_full():
            return {MSG: [f"{self.name} {target_type} is full"]}
        source.units[source_index], target.units[target_index] = (
            target.units[target_index],
            source.units[source_index],
        )
        self.log.append(
            {"type": "move_unit", "args": [source_type, target_type, source_index, target_index]}
        )
        return {MSG: [f"{self.name} moved unit"]}

    def upgrade(self, unit: Unit) -> Unit | None:
        """Merge three matching units without changing reserved base copies."""
        matches = [
            (container, index)
            for container in (self.field, self.bench)
            for index, candidate in enumerate(container.units)
            if candidate is not None
            and candidate.unit_id == unit.unit_id
            and candidate.level == unit.level
        ]
        if len(matches) < 3 or unit.level >= 3:
            return None
        upgraded = self.pool.get_unit(unit.name, unit.level + 1)
        for container, index in matches[:3]:
            container.units[index] = None
        container, index = matches[0]
        container.units[index] = upgraded
        return upgraded

    def reroll(self) -> dict[str, list[str]]:
        """Refresh the shop for two gold."""
        if not self.is_alive() or self.gold < 2:
            return {MSG: [f"{self.name} cannot reroll"]}
        self.gold -= 2
        self.refresh_shop()
        self.log.append({"type": "reroll"})
        return {MSG: [f"{self.name} reroll"]}

    def get_appearance_rate(self) -> list[float]:
        """Return level-dependent cost-tier probabilities."""
        rates = (
            (1, 0, 0, 0, 0),
            (1, 0, 0, 0, 0),
            (0.75, 0.25, 0, 0, 0),
            (0.55, 0.30, 0.15, 0, 0),
            (0.45, 0.33, 0.20, 0.02, 0),
            (0.30, 0.40, 0.25, 0.05, 0),
            (0.19, 0.30, 0.40, 0.10, 0.01),
            (0.18, 0.25, 0.32, 0.22, 0.03),
            (0.15, 0.20, 0.25, 0.30, 0.10),
            (0.05, 0.10, 0.20, 0.40, 0.25),
        )
        return list(rates[self.level - 1])

    def get_turn_gold(self, turn: int) -> None:
        """Pay base income plus capped interest and bounded streak rewards."""
        self.income_turn = turn
        income = self.economy()
        self.interest_list.append(income["interest"])
        self.streak_gold_list.append(income["streak"])
        self.turn_gold_list.append(income["base"])
        self.gold += income["total"]
        self.income_turn = turn + 1

    def win(self) -> None:
        """Record a win and its one-gold combat reward."""
        self.combat_result_list.append(1)
        self.gold += 1
        self.streak = max(0, self.streak) + 1

    def lose(self) -> None:
        """Record a loss and update consecutive-loss streak."""
        self.combat_result_list.append(-1)
        self.streak = min(0, self.streak) - 1

    def draw(self) -> None:
        """Record a draw and reset the streak."""
        self.combat_result_list.append(0)
        self.streak = 0

    def get_turn_exp(self) -> None:
        """Grant the two natural experience points earned after combat."""
        self.give_exp(2)

    def refresh_shop(self) -> None:
        """Return unsold offers and reserve up to five independent replacements."""
        for unit in self.shop.units:
            if unit is not None:
                self.pool.add_unit(unit)
        self.shop.units = []
        rates = self.get_appearance_rate()
        for _ in range(self.shop.num_slots):
            costs = [
                cost
                for cost in range(1, 6)
                if rates[cost - 1] > 0
                and any(count > 0 for count in self.pool.available_units[cost].values())
            ]
            if not costs:
                self.shop.units.append(None)
                continue
            cost = self.pool.rng.choices(costs, weights=[rates[tier - 1] for tier in costs], k=1)[0]
            self.shop.units.append(self.pool.sample(cost))

    def _make_purchase_room(self, unit: Unit) -> bool:
        if not self.bench.is_full():
            self.bench.add(unit)
            return True
        matches = [
            (container, index)
            for container in (self.field, self.bench)
            for index, owned in enumerate(container.units)
            if owned is not None and owned.unit_id == unit.unit_id and owned.level == 1
        ]
        if len(matches) < 2:
            return False
        for container, index in matches[:2]:
            container.units[index] = None
        container, index = matches[0]
        container.units[index] = self.pool.get_unit(unit.name, 2)
        return True

    def purchase_unit(self, shop_idx: int) -> dict[str, list[str]]:
        """Buy a reserved offer, merging three copies when space is available."""
        if not self.is_alive() or not 0 <= shop_idx < self.shop.num_slots:
            return {MSG: [f"{self.name} invalid shop index"]}
        unit = self.shop.units[shop_idx]
        if unit is None or self.gold < unit.cost:
            return {MSG: [f"{self.name} cannot buy this unit"]}
        if not self._make_purchase_room(unit):
            return {MSG: [f"{self.name} does not have enough bench room"]}
        self.gold -= unit.cost
        self.shop.units[shop_idx] = None
        self.log.append({"type": "buy_unit", "args": unit.unit_id})
        for level in range(1, 3):
            upgraded = self.upgrade(self.pool.get_unit(unit.name, level))
            if upgraded is not None:
                self.log.append({"type": "upgrade_unit", "args": upgraded.unit_id})
        return {MSG: [f"{self.name} successfully bought {unit.unit_id}"]}

    def sell_unit(self, source_type: str, index: int) -> dict[str, list[str]]:
        """Sell an owned unit and return its represented copies to the pool."""
        source = self._container(source_type)
        if not self.is_alive() or source is None or not 0 <= index < source.num_slots:
            return {MSG: [f"{self.name} invalid sale"]}
        unit = source.units[index]
        if unit is None:
            return {MSG: [f"{self.name} has no unit at index {index}"]}
        source.units[index] = None
        self.gold += unit.get_sell_gold()
        self.pool.add_unit(unit)
        self.log.append({"type": "sell_unit", "args": unit.unit_id})
        return {MSG: [f"{self.name} sold {unit.unit_id}"]}

    def add_gold(self, amount: int) -> dict[str, list[str]]:
        """Apply an explicit gold grant used by existing debug callers."""
        self.gold += int(amount)
        return {MSG: [f"{self.name} gold + {amount}"]}

    def play_randomly(self) -> None:
        """Run the deterministic filler policy, preserving the legacy entrypoint."""
        if not self.is_bot or not self.is_alive():
            return
        for index in range(self.shop.num_slots):
            self.purchase_unit(index)
        if self.gold >= 8 and self.level < MAX_LEVEL:
            self.purchase_exp()
        self._deploy_best_team()

    def _deploy_best_team(self) -> None:
        owned = [unit for unit in self.field.units + self.bench.units if unit is not None]
        owned.sort(
            key=lambda unit: (
                unit.status.hp
                * unit.status.attack
                * unit.status.attackSpeed
                * (1 + unit.status.defense / 100)
            ),
            reverse=True,
        )
        selected = owned[: self.field.max_units]
        reserves = owned[self.field.max_units :]
        self.field.units = [None] * self.field.num_slots
        self.bench.units = reserves + [None] * (self.bench.num_slots - len(reserves))
        # Home rows 0..3 run from the back line toward the enemy. Select
        # unoccupied preferred slots so mixed-role teams never overwrite units.
        front = tuple(row * 7 + col for row in (3, 2, 1, 0) for col in range(7))
        back = tuple(range(28))
        for unit in selected:
            ranged = role_for_status(unit.status.attackRange, unit.status.defense) == "marksman"
            preferred = back if ranged else front
            slot = next(index for index in preferred if self.field.units[index] is None)
            self.field.units[slot] = unit
        self.log.append({"type": "bot_deploy", "args": [unit.unit_id for unit in selected]})

    def release_holdings(self) -> None:
        """Return eliminated players' shop, bench and team copies exactly once."""
        for container in (self.shop, self.bench, self.field):
            for index, unit in enumerate(container.units):
                if unit is not None:
                    self.pool.add_unit(unit)
                    container.units[index] = None

    def get_history(self) -> dict[str, Any]:
        """Return legacy-compatible action and economy history."""
        return {
            "log": list(self.log),
            "combat": self.combat_result_list,
            "interest": self.interest_list,
            "streak_gold": self.streak_gold_list,
            "turn_gold": self.turn_gold_list,
        }
