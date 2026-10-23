"""Seeded, bounded autobattler simulation with explicit planning control."""

from __future__ import annotations

import copy
import random
from enum import Enum
from typing import Any

from .astar import search
from .base import Base
from .player import Player
from .pool import Pool
from .rules import resolve_rules
from .unit import Unit
from .util import TEAM

MSG = "message"
ROW = 8
COL = 7
MAX_BOT_ID_ATTEMPTS = 9


class GameState(Enum):
    """Represent planning and combat phases."""

    READY = "ready"
    BATTLE = "battle"


class BattleState(Enum):
    """Represent the result of one player's current combat."""

    WIN = "win"
    LOSE = "lose"
    DRAW = "draw"
    INBATTLE = "inbattle"


class AutoBattlerGame(Base):
    """Run one game with local randomness and versioned progression rules.

    Parameters
    ----------
    game_id : str
        Stable game identifier used by existing clients.
    unit_file, synergy_file : str
        Legacy data paths. Synergy labels have no implemented combat effects.
    seed : int, default 0
        Seed for this game's shops, pairings and critical hits.
    ruleset : {'research', 'legacy'}, default 'research'
        Economy, health and timing profile.
    decision_mode : bool, default False
        Wait for ``advance()`` while a registered player is alive and connected.
        Planning uses the profile timer when only scripted opponents remain.
    """

    def __init__(
        self,
        game_id: str,
        unit_file: str = "pyautobattle/data/unit.csv",
        synergy_file: str = "pyautobattle/data/synergy.json",
        seed: int = 0,
        ruleset: str = "research",
        decision_mode: bool = False,
    ):
        self.game_id, self.seed = game_id, seed
        self.rules = resolve_rules(ruleset)
        self.ruleset = self.rules.name
        self.decision_mode = decision_mode
        self.rng = random.Random(seed)
        self.pool = Pool(unit_file, synergy_file, rng=self.rng)
        self.round = 0
        self.timer = 0.0
        self.state_time = self.rules.preparation_seconds
        self.winner: list[str] | None = None
        self.players: list[Player] = []
        self.current_players: set[str] = set()
        self.running = False
        self.matchup: list[tuple[Player, Player]] | None = None
        self.arena: list[list[dict[str, Any]]] = []
        self.state = GameState.READY
        self.battle_state: dict[str, BattleState] = {}
        self.lose_player: list[str] = []
        self.replay: list[dict[str, Any]] = []
        self._ghost_ids: set[str] = set()

    def register(self, user_id: str) -> None:
        """Register a human or agent before the game starts."""
        if self.running:
            raise ValueError("Cannot register after the game starts")
        if len(self.current_players) >= 8 and user_id not in self.current_players:
            raise ValueError("At most eight players may register")
        self.current_players.add(user_id)

    def quit(self, user_id: str) -> int:
        """Remove a connected user and return the remaining connection count."""
        self.current_players.discard(user_id)
        return len(self.current_players)

    def start(self) -> None:
        """Initialize registered users and active scripted filler opponents."""
        if self.running:
            return
        if self.players:
            raise ValueError("A completed game cannot be restarted")
        for user_id in sorted(self.current_players):
            self.players.append(Player(user_id, user_id, self.pool, self.rules))
        for index in range(len(self.players), 8):
            player_id = self._bot_identifier(index)
            player = Player(player_id, player_id, self.pool, self.rules)
            player.is_bot = True
            self.players.append(player)
        for player in self.players:
            player.bench.add(self.pool.sample(1))
            player.refresh_shop()
            player.play_randomly()
        self.running = True
        self.setActive(True)

    def _bot_identifier(self, index: int) -> str:
        used = {player.player_id for player in self.players}
        base = f"{self.game_id}-{index}"
        for suffix in range(MAX_BOT_ID_ATTEMPTS):
            candidate = base if suffix == 0 else f"{base}-bot-{suffix}"
            if candidate not in used:
                return candidate
        raise RuntimeError("Could not assign a unique baseline player identifier")

    def next_round(self) -> None:
        """Pay survivors, grant experience and prepare their next shops."""
        for player in self.get_live_players():
            player.get_turn_exp()
            player.get_turn_gold(self.round)
            player.refresh_shop()
            player.play_randomly()
        self.round += 1

    def setActive(self, value: bool = True) -> None:
        """Update legacy action availability for living players."""
        for player in self.players:
            player.active = value and player.is_alive() and self.running

    def advance(self) -> dict[str, list[str]]:
        """Start combat when a running game is waiting for planning decisions."""
        if not self.running or self.state != GameState.READY:
            return {MSG: ["Combat can only start during active preparation"]}
        self.next_state()
        return {MSG: ["Combat started"]}

    def next_state(self) -> dict[str, list[str]] | None:
        """Transition phases and settle combat before granting next-round income."""
        self.timer = 0.0
        if self.state == GameState.READY:
            self.setActive(False)
            self.state = GameState.BATTLE
            self.state_time = self.rules.combat_seconds
            self.force_placement()
            self.start_battle()
            return None
        result = self.end_battle()
        self.round += 1
        if self.check_end():
            return result
        self.round -= 1
        self.next_round()
        self.state = GameState.READY
        self.state_time = self.rules.preparation_seconds
        self.setActive(True)
        return result

    def observe(self) -> dict[str, Any]:
        """Return legacy full-engine observations; player.observe is private scope."""
        return {"players": [player.observe() for player in self.players]}

    def to_json(self) -> dict[str, Any]:
        """Serialize the privileged game state for existing server consumers."""
        return {
            "players": self.player_to_dict(),
            "state": {
                "round": self.round,
                "time": self.timer,
                "current_state": self.state.name,
                "state_time": self.state_time,
                "ruleset": self.ruleset,
                "decision_mode": self.decision_mode,
                "seed": self.seed,
                "ruleset_version": 1,
            },
            "rank": self.get_rank(),
            "battle": self.battle_to_json(),
        }

    def player_to_dict(self) -> dict[str, dict[str, Any]]:
        """Index serialized players by their unchanged identifiers."""
        return {player.player_id: player.to_json() for player in self.players}

    def get_rank(self) -> list[dict[str, Any]]:
        """Rank players by remaining health, using stable order for ties."""
        return sorted(
            [{"id": player.player_id, "hp": player.hp} for player in self.players],
            key=lambda player: player["hp"],
            reverse=True,
        )

    def get_player_by_index(self, index: int) -> Player:
        """Return the player at a legacy seat index."""
        return self.players[index]

    def get_player_by_user_id(self, user_id: str) -> Player | None:
        """Find a player by ID, or return None for an unknown identifier."""
        return next((player for player in self.players if player.player_id == user_id), None)

    def get_winner(self) -> list[str]:
        """Return all survivors in rank order followed by eliminated players."""
        survivors = sorted(self.get_live_players(), key=lambda player: player.hp, reverse=True)
        return [player.player_id for player in survivors] + self.lose_player[::-1]

    def step(self, frame: int) -> dict[str, list[str]] | None:
        """Advance exactly one simulation tick at the supplied ticks per second."""
        if frame <= 0:
            raise ValueError("Simulation frame rate must be positive")
        if not self.running or self.check_end():
            return None
        awaiting_player = self.decision_mode and any(
            player.player_id in self.current_players and player.is_alive() and not player.is_bot
            for player in self.players
        )
        if self.state == GameState.READY and awaiting_player:
            return None
        elapsed = 1 / frame
        self.timer += elapsed
        if self.state == GameState.BATTLE:
            for arena in self.arena:
                self.step_battle(arena, elapsed)
        if self.timer + 1e-9 >= self.state_time:
            return self.next_state()
        return None

    def check_end(self) -> bool:
        """Stop after one survivor or the profile's explicit round ceiling."""
        if len(self.get_live_players()) > 1 and self.round < self.rules.max_rounds:
            return False
        self.winner = self.get_winner()
        self.stop()
        return True

    def stop(self) -> None:
        """Stop simulation and disable player actions."""
        self.running = False
        self.setActive(False)

    def get_live_players(self) -> list[Player]:
        """Return surviving players in seat order."""
        return [player for player in self.players if player.is_alive()]

    def force_placement(self) -> None:
        """Deploy available bench units into empty team slots before combat."""
        for player in self.get_live_players():
            for index, unit in enumerate(player.bench):
                if player.field.is_full():
                    break
                if unit is not None:
                    player.move_unit("bench", "field", index, -1)

    def start_battle(self) -> None:
        """Seed pairings and build detached combat snapshots, including odd ghosts."""
        live = self.get_live_players()
        self.rng.shuffle(live)
        self._ghost_ids = set()
        if len(live) % 2:
            ghost = copy.copy(live[0])
            ghost.player_id = f"ghost:{live[0].player_id}"
            self._ghost_ids.add(ghost.player_id)
            live.append(ghost)
        self.matchup = list(zip(live[::2], live[1::2]))
        self.arena = []
        self.battle_state = {}
        for home, away in self.matchup:
            self.arena.append(self.set_arena(copy.deepcopy(home.field), copy.deepcopy(away.field)))
            for player in (home, away):
                if player.player_id not in self._ghost_ids:
                    self.battle_state[player.player_id] = BattleState.INBATTLE

    def set_arena(self, home_field: Any, away_field: Any) -> list[dict[str, Any]]:
        """Place detached teams in mirrored halves of the existing 8-by-7 board."""
        arena = []
        for team, field in ((TEAM.HOME, home_field), (TEAM.AWAY, away_field)):
            for index, unit in enumerate(field):
                if unit is None:
                    continue
                unit.team = team
                pos = [index // COL, index % COL]
                if team == TEAM.AWAY:
                    pos = [ROW - 1 - pos[0], COL - 1 - pos[1]]
                arena.append({"unit": unit, "pos": pos})
        return arena

    def battle_to_json(self) -> dict[str, Any]:
        """Serialize each player's combat perspective without duplicate ghost results."""
        battles: dict[str, Any] = {player.player_id: None for player in self.players}
        for (home, away), arena in zip(self.matchup or [], self.arena):
            units = [
                {"unit": entry["unit"].to_json("battle"), "pos": entry["pos"]} for entry in arena
            ]
            for player, team in ((home, TEAM.HOME), (away, TEAM.AWAY)):
                if player.player_id in self._ghost_ids:
                    continue
                battles[player.player_id] = {
                    "team": team.value,
                    "arena": units,
                    "state": self.battle_state[player.player_id].value,
                }
        return battles

    def step_battle(self, arena: list[dict[str, Any]], elapsed_seconds: float = 1 / 60) -> None:
        """Advance living units with physical attacks and bounded grid movement."""
        for entry in arena:
            unit: Unit = entry["unit"]
            if not unit.alive():
                continue
            unit.update(elapsed_seconds)
            enemies = [
                enemy
                for enemy in arena
                if enemy["unit"].alive() and enemy["unit"].team != unit.team
            ]
            if not enemies:
                continue
            target = min(enemies, key=lambda enemy: _distance(entry["pos"], enemy["pos"]))
            if _distance(entry["pos"], target["pos"]) <= unit.status.attackRange:
                if unit.cooldowned():
                    unit.hit(target["unit"], self.rng)
            elif unit.move():
                obstacles = [other["pos"] for other in arena if other["unit"].alive()]
                _, directions = search(entry["pos"], target["pos"], obstacles)
                if directions:
                    entry["pos"][0] += directions[0][0]
                    entry["pos"][1] += directions[0][1]
        arena[:] = [entry for entry in arena if entry["unit"].alive()]

    def _arena_result(
        self, arena: list[dict[str, Any]]
    ) -> tuple[BattleState, BattleState, int, int]:
        home = sum(entry["unit"].team == TEAM.HOME for entry in arena)
        away = sum(entry["unit"].team == TEAM.AWAY for entry in arena)
        base = self.rules.round_damage(self.round)
        if home and not away:
            return BattleState.WIN, BattleState.LOSE, 0, base + home
        if away and not home:
            return BattleState.LOSE, BattleState.WIN, base + away, 0
        damage = max(1, base)
        return BattleState.DRAW, BattleState.DRAW, damage, damage

    def end_battle(self) -> dict[str, list[str]]:
        """Settle one result per real player and return eliminated unit holdings."""
        messages = []
        for (home, away), arena in zip(self.matchup or [], self.arena):
            home_state, away_state, home_damage, away_damage = self._arena_result(arena)
            for player, result, damage in (
                (home, home_state, home_damage),
                (away, away_state, away_damage),
            ):
                if player.player_id in self._ghost_ids:
                    continue
                self.battle_state[player.player_id] = result
                if result == BattleState.WIN:
                    player.win()
                elif result == BattleState.LOSE:
                    player.lose()
                else:
                    player.draw()
                player.get_damage(damage)
                messages.append(f"{player.player_id}: {result.value}, takes {damage} damage")
                if not player.is_alive():
                    self.lose_player.append(player.player_id)
                    player.release_holdings()
                    messages.append(f"{player.player_id} was eliminated")
        return {MSG: messages}

    def get_replay(self) -> dict[str, Any]:
        """Return bounded per-player legacy histories, separate from observations."""
        return {player.player_id: player.get_history() for player in self.players}


def _distance(first: list[int], second: list[int]) -> int:
    return abs(first[0] - second[0]) + abs(first[1] - second[1])
