"""Socket.IO host for local play and reproducible research sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import signal
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import socketio
from aiohttp import web

from pyautobattle.src import AutoBattlerGame
from recording import DecisionJournal

ROOT = Path(__file__).resolve().parent
MAX_CLIENTS = 32
MAX_GAMES = 8
MAX_USERS = 10000
MAX_HISTORY = 200
MAX_GAME_TICKS = 60 * 90 * 200
ID_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
logger = logging.getLogger(__name__)


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(ID_PATTERN.fullmatch(value)) and value not in (".", "..")


def _single(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return value[0]
    return value


class GameServer:
    """Host bounded sessions, preserving the existing agent event interface.

    Parameters
    ----------
    data_dir : Path, optional
        Parent of db, replay and log directories; defaults to the repository.
    seed : int, default 0
        Nonnegative 32-bit game seed.
    ruleset : {'research', 'legacy'}, default 'research'
        Progression profile supplied to every newly created game.
    decision_mode : bool, default True
        Hold preparation until an active player sends advance_round.
    token : str, default ''
        Readiness token used by an owning local launcher.
    fast : bool, default False
        Run the same simulation ticks without wall-clock combat delays.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        seed: int = 0,
        ruleset: str = "research",
        decision_mode: bool = True,
        token: str = "",
        fast: bool = False,
    ):
        if not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
            raise ValueError("Seed must be between 0 and 2**32-1")
        if ruleset not in ("research", "legacy"):
            raise ValueError("Unknown ruleset")
        self.data_dir = Path(data_dir or ROOT).resolve()
        self.user_db_path = self.data_dir / "db/user.json"
        self.replay_path = self.data_dir / "replay"
        self.user_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.replay_path.mkdir(parents=True, exist_ok=True)
        self.seed, self.ruleset, self.decision_mode = seed, ruleset, decision_mode
        self.token = token
        self.fast = fast
        self.clients: set[str] = set()
        self.sid_to_user: dict[str, str] = {}
        self.games: dict[str, AutoBattlerGame] = {}
        self.rooms: dict[str, list[str]] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.wakeups: dict[str, asyncio.Event] = {}
        self.journals: dict[str, DecisionJournal] = {}
        self.user_info = self._load_users()
        self.sio = socketio.AsyncServer(async_mode="aiohttp", max_http_buffer_size=16384)
        self.app = web.Application(client_max_size=16384)
        self.sio.attach(self.app)
        self.app.router.add_get("/health", self._health)
        self.app.on_cleanup.append(self._cleanup)
        self._register_events()

    def _load_users(self) -> dict[str, Any]:
        if not self.user_db_path.exists():
            return {}
        if self.user_db_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("User database exceeds 8 MiB")
        users = json.loads(self.user_db_path.read_text(encoding="utf-8"))
        if not isinstance(users, dict) or len(users) > MAX_USERS:
            raise ValueError("Invalid or oversized user database")
        for user_id, info in list(users.items())[:MAX_USERS]:
            if not _identifier(user_id) or not isinstance(info, dict):
                raise ValueError("Invalid user database entry")
            info.update(playing=False, game_id=None)
            info["match_results"] = info.get("match_results", [])[-MAX_HISTORY:]
        return users

    def _register_events(self) -> None:
        events = {
            "connect": self.connect,
            "disconnect": self.disconnect,
            "login": self.login,
            "register_game": self.register_game,
            "start_game": self.start_game,
            "quit_game": self.quit_game,
            "advance_round": self.advance_round,
            "reroll": self.reroll,
            "buy_exp": self.buy_exp,
            "buy_unit": self.buy_unit,
            "sell_unit": self.sell_unit,
            "move_unit": self.move_unit,
        }
        for name, handler in tuple(events.items())[:16]:
            self.sio.on(name, handler=handler)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "application": "LLM4TFT",
                "token": self.token,
                "seed": self.seed,
                "ruleset": self.ruleset,
                "decision_mode": self.decision_mode,
                "fast": self.fast,
            }
        )

    async def _cleanup(self, app: web.Application) -> None:
        tasks = tuple(self.tasks.values())[:MAX_GAMES]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for game_id in tuple(self.games)[:MAX_GAMES]:
            self._try_record_outcome(game_id, "interrupted")
            await self.sio.emit(
                "session_outcome",
                {
                    "game_id": game_id,
                    "reason": "interrupted",
                    "round": self.games[game_id].round,
                    "ranking": [],
                },
                to=self.rooms[game_id],
            )
        self.save_user_db()

    async def connect(self, sid: str, environ: dict[str, Any], auth: Any = None) -> bool:
        """Accept a connection while the bounded local session has capacity."""
        if len(self.clients) >= MAX_CLIENTS:
            return False
        self.clients.add(sid)
        return True

    async def disconnect(self, sid: str, reason: Any = None) -> None:
        """Release the disconnected player's game and identity."""
        await self.quit_game(sid)
        self.sid_to_user.pop(sid, None)
        self.clients.discard(sid)

    async def login(self, sid: str, user_id: Any) -> bool:
        """Log in a unique bounded identifier; no credentials are required locally."""
        user_id = _single(user_id)
        if not _identifier(user_id):
            return await self._reject(sid, "Use 1–64 letters, digits, underscores, dots or hyphens")
        if user_id in self.sid_to_user.values() and self.sid_to_user.get(sid) != user_id:
            return await self._reject(sid, "That player is already connected")
        if sid in self.sid_to_user:
            return self.sid_to_user[sid] == user_id
        if user_id not in self.user_info and len(self.user_info) >= MAX_USERS:
            return await self._reject(sid, "User database limit reached")
        self.sid_to_user[sid] = user_id
        self.user_info.setdefault(
            user_id,
            {
                "user_id": user_id,
                "score": 100,
                "playing": False,
                "game_id": None,
                "match_results": [],
            },
        )
        self.save_user_db()
        await self.send_user_state(sid)
        await self.send_home_state()
        return True

    def save_user_db(self) -> None:
        """Atomically persist the bounded user database."""
        temporary = self.user_db_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.user_info, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(self.user_db_path)

    async def _reject(self, sid: str, message: str) -> bool:
        await self.sio.emit("response", {"ok": False, "message": message}, to=sid)
        return False

    async def register_game(self, sid: str, game_id: Any = None) -> bool:
        """Create or join a lobby, automatically starting eight-player rooms."""
        game_id = _single(game_id)
        if game_id is None:
            game_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        user_id = self.sid_to_user.get(sid)
        if user_id is None or not _identifier(game_id):
            return await self._reject(sid, "Log in and choose a valid game ID")
        if self.user_info[user_id]["game_id"] is not None:
            return await self._reject(sid, "Leave your current game first")
        if game_id not in self.games:
            if len(self.games) >= MAX_GAMES:
                return await self._reject(sid, "Game limit reached")
            self.games[game_id] = AutoBattlerGame(
                game_id, seed=self.seed, ruleset=self.ruleset, decision_mode=self.decision_mode
            )
            self.rooms[game_id] = []
        game = self.games[game_id]
        if game.running or len(game.current_players) >= 8:
            return await self._reject(sid, "Game is running or full")
        game.register(user_id)
        self.rooms[game_id].append(sid)
        self.user_info[user_id]["game_id"] = game_id
        await self.send_user_state(sid)
        await self.send_lobby_state(game_id)
        await self.send_home_state()
        # Historical multi-agent experiments rely on an eight-user lobby
        # starting automatically. Solo play still starts explicitly.
        if len(game.current_players) == 8 and not game.running:
            return await self.start_game(sid)
        return True

    async def start_game(self, sid: str, game_id: Any = None) -> bool:
        """Start the caller's game with active baseline opponents in empty slots."""
        game_id = await self.get_game_id(sid)
        game = self.games.get(game_id) if game_id is not None else None
        if game is None or game.running:
            return await self._reject(sid, "No waiting game to start")
        path = self.replay_path / f"{game_id}.decisions.jsonl"
        if path.exists():
            return await self._reject(sid, "This game ID already has a recording; choose a new one")
        if len(self.journals) >= MAX_GAMES:
            return await self._reject(
                sid, "Recording capacity reached; inspect server log and restart"
            )
        try:
            game.start()
            self.journals[game_id] = DecisionJournal(
                path,
                {
                    "game_id": game_id,
                    "seed": game.seed,
                    "ruleset": self.ruleset,
                    "decision_mode": self.decision_mode,
                    "players": sorted(game.current_players),
                    "opponents": "scripted-baseline",
                    "ruleset_version": 1,
                    "application_version": "0.2.0",
                },
            )
        except (OSError, RuntimeError, ValueError):
            logger.exception("Could not start recording for game %s", game_id)
            await self._reject(sid, "Could not start recording; inspect server log")
            await self.remove_game(game_id, "recording_error")
            return False
        self.wakeups[game_id] = asyncio.Event()
        self.tasks[game_id] = asyncio.create_task(self.run_battle(game_id))
        await self.send_game_state(game_id)
        await self.send_home_state()
        return True

    async def advance_round(self, sid: str) -> bool:
        """Start combat explicitly, without charging LLM latency against planning."""
        game_id = await self.get_game_id(sid)
        game = self.games.get(game_id) if game_id is not None else None
        player = await self.get_player(sid)
        if (
            game_id is None
            or game is None
            or player is None
            or not player.active
            or not player.is_alive()
        ):
            return await self._reject(sid, "Only an active player can start combat")
        if game.state.name != "READY":
            return await self._reject(sid, "Combat is already running")
        if not await self._ensure_recording_capacity(sid, game_id):
            return False
        before = player.observe()
        game.advance()
        self.wakeups[game_id].set()
        if not await self._try_record_decision(
            game_id, player, "advance_round", (), before, {"ok": True}
        ):
            return False
        await self.send_game_state(game_id)
        return True

    async def run_battle(self, game_id: str) -> None:
        """Run bounded 60 Hz simulation ticks, waiting for explicit preparation."""
        game = self.games[game_id]
        try:
            for tick in range(MAX_GAME_TICKS):
                if game_id not in self.games or not game.running:
                    break
                await self._wait_preparation(game_id, game)
                phase = game.state
                result = game.step(60)
                if result:
                    await self.sio.emit(
                        "round_result", ". ".join(result["message"]), to=self.rooms[game_id]
                    )
                if result or game.state != phase or (not self.fast and tick % 6 == 0):
                    await self.send_game_state(game_id)
                await asyncio.sleep(0 if self.fast else 1 / 60)
            if game_id in self.games:
                await self._finish_game(game_id)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError, IndexError, KeyError):
            logger.exception("Game %s failed", game_id)
            if game_id in self.games:
                await self.sio.emit(
                    "response",
                    {"ok": False, "message": "Session stopped; see server log"},
                    to=self.rooms[game_id],
                )
                await self.remove_game(game_id, "error")

    async def _wait_preparation(self, game_id: str, game: AutoBattlerGame) -> None:
        if not game.decision_mode or game.state.name != "READY":
            return
        awaiting_player = any(
            player.player_id in game.current_players and player.is_alive() and not player.is_bot
            for player in game.players
        )
        if awaiting_player:
            wakeup = self.wakeups[game_id]
            wakeup.clear()
            await wakeup.wait()

    async def _finish_game(self, game_id: str) -> None:
        game = self.games[game_id]
        ranking = game.get_winner()
        if len(ranking) != 8:
            ranking = [row["id"] for row in game.get_rank()]
        self._try_record_outcome(game_id, "completed", ranking)
        replay = {
            "metadata": {"seed": game.seed, "ruleset": self.ruleset},
            "history": game.get_replay(),
        }
        (self.replay_path / f"{game_id}.json").write_text(json.dumps(replay), encoding="utf-8")
        for position, user_id in enumerate(ranking[:8]):
            if user_id in self.user_info:
                user = self.user_info[user_id]
                user["match_results"] = (user["match_results"] + [position + 1])[-MAX_HISTORY:]
                user["score"] += 4 - position if position < 4 else 3 - position
        await self.remove_game(game_id, "completed", ranking)

    def _record_outcome(
        self, game_id: str, reason: str, ranking: Optional[list[str]] = None
    ) -> None:
        journal = self.journals.get(game_id)
        if journal is not None:
            game = self.games[game_id]
            journal.write(
                {
                    "type": "outcome",
                    "reason": reason,
                    "round": game.round,
                    "ranking": ranking or [],
                    "privileged_final_state": game.to_json(),
                }
            )
            self.journals.pop(game_id)

    def _try_record_outcome(
        self, game_id: str, reason: str, ranking: Optional[list[str]] = None
    ) -> bool:
        try:
            self._record_outcome(game_id, reason, ranking)
            return True
        except (OSError, RuntimeError, ValueError):
            logger.exception("Could not record outcome for game %s", game_id)
            return False

    async def send_game_state(self, game_id: str) -> None:
        """Publish the existing game/player envelope for clients and inspectors."""
        game = self.games.get(game_id)
        if game is None:
            return
        snapshot = game.to_json()
        for sid in tuple(self.rooms[game_id])[:8]:
            user_id = self.sid_to_user.get(sid)
            if user_id is None:
                continue
            player = game.get_player_by_user_id(user_id)
            if player is not None:
                if not self.user_info[user_id]["playing"]:
                    self.user_info[user_id]["playing"] = True
                    await self.send_user_state(sid)
                await self.sio.emit(
                    "update_game", {"game": snapshot, "player": player.to_json()}, to=sid
                )

    async def send_lobby_state(self, game_id: str) -> None:
        """Publish the participants of an existing lobby."""
        game = self.games.get(game_id)
        if game is None:
            return
        users = [
            {"user_id": uid, "score": self.user_info[uid]["score"]}
            for uid in sorted(game.current_players)[:8]
        ]
        await self.sio.emit(
            "update_lobby", {"game_id": game_id, "players": users}, to=self.rooms[game_id]
        )

    async def send_home_state(self) -> None:
        """Publish available lobbies to connected clients."""
        games = [gid for gid, game in tuple(self.games.items())[:MAX_GAMES] if not game.running]
        await self.sio.emit("update_home", {"games": games}, to=list(self.clients))

    async def send_user_state(self, sid: str) -> None:
        """Send the caller's registration and match state."""
        user_id = self.sid_to_user.get(sid)
        if user_id in self.user_info:
            await self.sio.emit("update_user", self.user_info[user_id], to=sid)

    async def remove_game(
        self, game_id: str, reason: str = "abandoned", ranking: Optional[list[str]] = None
    ) -> None:
        """Flush a terminal record, release players and stop the match task."""
        game = self.games.get(game_id)
        if game is None:
            return
        game.stop()
        recorded = self._try_record_outcome(game_id, reason, ranking)
        for user_id in tuple(game.current_players)[:8]:
            self.user_info[user_id].update(game_id=None, playing=False)
        recipients = self.rooms.pop(game_id, [])
        self.games.pop(game_id)
        task = self.tasks.pop(game_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.wakeups.pop(game_id, None)
        if not recorded:
            await self.sio.emit(
                "response",
                {"ok": False, "message": "Could not save outcome; inspect server log"},
                to=recipients,
            )
        for sid in recipients[:8]:
            await self.send_user_state(sid)
        await self.sio.emit("update_game", {}, to=recipients)
        await self.sio.emit(
            "session_outcome",
            {
                "game_id": game_id,
                "reason": reason if recorded else "recording_error",
                "round": game.round,
                "ranking": ranking or [],
            },
            to=recipients,
        )
        await self.sio.emit("game_end", to=recipients)
        await self.sio.emit("game_over", to=recipients)
        self.save_user_db()
        await self.send_home_state()

    async def quit_game(self, sid: str) -> bool:
        """Leave the lobby or finish an abandoned single-player session."""
        user_id = self.sid_to_user.get(sid)
        game_id = await self.get_game_id(sid)
        game = self.games.get(game_id) if game_id is not None else None
        if game is not None and user_id is not None and game_id is not None:
            game.quit(user_id)
            wakeup = self.wakeups.get(game_id)
            if wakeup is not None:
                wakeup.set()
            if not game.current_players:
                await self.remove_game(game_id)
            else:
                self.rooms[game_id] = [value for value in self.rooms[game_id] if value != sid]
                await self.sio.emit(
                    "session_outcome",
                    {"game_id": game_id, "reason": "abandoned", "round": game.round, "ranking": []},
                    to=sid,
                )
                if not game.running:
                    await self.send_lobby_state(game_id)
        if user_id in self.user_info:
            self.user_info[user_id].update(game_id=None, playing=False)
            self.save_user_db()
            await self.send_user_state(sid)
        await self.sio.emit("game_end", to=sid)
        return True

    async def reroll(self, sid: str) -> dict[str, Any]:
        """Request a paid shop refresh."""
        return await self.player_action(sid, "reroll")

    async def buy_exp(self, sid: str) -> dict[str, Any]:
        """Request one four-gold XP purchase."""
        return await self.player_action(sid, "purchase_exp")

    async def buy_unit(self, sid: str, index: Any) -> dict[str, Any]:
        """Request a unit in a validated shop slot."""
        return await self.player_action(sid, "purchase_unit", _single(index))

    async def sell_unit(self, sid: str, source_type: Any, index: Any = None) -> dict[str, Any]:
        """Request a sale from a bench or field slot."""
        if isinstance(source_type, list) and len(source_type) == 2:
            source_type, index = source_type
        return await self.player_action(sid, "sell_unit", source_type, index)

    async def move_unit(self, sid: str, *data: Any) -> dict[str, Any]:
        """Request a move using the existing four-argument client protocol."""
        if len(data) == 1 and isinstance(data[0], list):
            data = tuple(data[0])
        return await self.player_action(sid, "move_unit", *data)

    async def player_action(self, sid: str, action: str, *args: Any) -> dict[str, Any]:
        """Validate and record accepted and rejected player decisions."""
        game_id = await self.get_game_id(sid)
        player = await self.get_player(sid)
        if player is None or game_id is None:
            return {"ok": False, "message": "Join and start a game first"}
        if not await self._ensure_recording_capacity(sid, game_id):
            return {"ok": False, "message": "Recording limit reached; session stopped"}
        before = player.observe()
        if not player.active or not player.is_alive():
            result = {"ok": False, "message": "Actions require an alive player in preparation"}
        else:
            result = self._apply_action(player, action, args)
        if not await self._try_record_decision(game_id, player, action, args, before, result):
            return {"ok": False, "message": "Recording failed; session stopped"}
        await self.sio.emit("response", result, to=sid)
        await self.send_game_state(game_id)
        return result

    async def _ensure_recording_capacity(self, sid: str, game_id: str) -> bool:
        journal = self.journals.get(game_id)
        if journal is None or journal.can_record_decision():
            return True
        await self._reject(sid, "Recording limit reached; session stopped before applying action")
        await self.remove_game(game_id, "recording_limit")
        return False

    async def _try_record_decision(
        self,
        game_id: str,
        player: Any,
        action: str,
        args: tuple[Any, ...],
        before: dict[str, Any],
        result: dict[str, Any],
    ) -> bool:
        try:
            self._record_decision(game_id, player, action, args, before, result)
            return True
        except (OSError, RuntimeError, ValueError):
            logger.exception("Could not record decision for game %s", game_id)
            await self.sio.emit(
                "response",
                {"ok": False, "message": "Recording failed; session stopped; inspect server log"},
                to=self.rooms[game_id],
            )
            await self.remove_game(game_id, "recording_error")
            return False

    def _apply_action(self, player: Any, action: str, args: tuple[Any, ...]) -> dict[str, Any]:
        try:
            checked = _validate_args(action, args)
            methods = {
                "reroll": player.reroll,
                "purchase_exp": player.purchase_exp,
                "purchase_unit": player.purchase_unit,
                "sell_unit": player.sell_unit,
                "move_unit": player.move_unit,
            }
            if action not in methods:
                raise ValueError("Unsupported action")
            before = player.to_json()
            message = methods[action](*checked)
            return {"ok": before != player.to_json(), "message": message}
        except (ValueError, TypeError, IndexError) as error:
            return {"ok": False, "message": str(error)}

    def _record_decision(
        self,
        game_id: str,
        player: Any,
        action: str,
        args: tuple[Any, ...],
        before: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        journal = self.journals.get(game_id)
        if journal is None:
            return
        game = self.games[game_id]
        journal.write(
            {
                "type": "decision",
                "player_id": player.player_id,
                "round": game.round,
                "phase": "READY" if action == "advance_round" else game.state.name,
                "observation": before,
                "action": {"name": action, "args": args},
                "result": result,
                "next_observation": player.observe(),
            }
        )

    async def get_user_id(self, sid: str) -> Optional[str]:
        """Return the authenticated local identity, if present."""
        return self.sid_to_user.get(sid)

    async def get_game_id(self, sid: str) -> Optional[str]:
        """Return the game associated with the caller."""
        user_id = self.sid_to_user.get(sid)
        return self.user_info.get(user_id, {}).get("game_id") if user_id is not None else None

    async def get_player(self, sid: str) -> Any:
        """Resolve the caller to the authoritative engine player."""
        game_id = await self.get_game_id(sid)
        user_id = self.sid_to_user.get(sid)
        game = self.games.get(game_id) if game_id is not None else None
        return (
            game.get_player_by_user_id(user_id)
            if game is not None and user_id is not None
            else None
        )


def _validate_args(action: str, args: tuple[Any, ...]) -> tuple[Any, ...]:
    counts = {"reroll": 0, "purchase_exp": 0, "purchase_unit": 1, "sell_unit": 2, "move_unit": 4}
    if action not in counts or len(args) != counts[action]:
        raise ValueError("Invalid action arguments")
    if action in ("reroll", "purchase_exp"):
        return args
    if action == "purchase_unit":
        return (_index(args[0], 5),)
    locations = {"b": "bench", "bench": "bench", "f": "field", "field": "field"}
    if not isinstance(args[0], str) or args[0] not in locations:
        raise ValueError("Choose bench or field")
    source = locations[args[0]]
    if action == "sell_unit":
        return source, _index(args[1], 9 if source == "bench" else 28)
    if not isinstance(args[1], str) or args[1] not in locations:
        raise ValueError("Choose bench or field")
    target = locations[args[1]]
    return (
        source,
        target,
        _index(args[2], 9 if source == "bench" else 28),
        _index(args[3], 9 if target == "bench" else 28, allow_empty=True),
    )


def _index(value: Any, slots: int, allow_empty: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError("Slot index must be an integer")
    index = int(value)
    if not (-1 if allow_empty else 0) <= index < slots:
        raise ValueError("Slot index is outside the board")
    return index


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse bounded server configuration without starting a process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ruleset", choices=("research", "legacy"), default="research")
    parser.add_argument("--timed", action="store_true", help="Automatically finish preparation")
    parser.add_argument(
        "--fast", action="store_true", help="Simulate combat without wall-clock waits"
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535 or not 0 <= args.seed <= 2**32 - 1:
        parser.error("Invalid port or seed")
    return args


async def _serve(args: argparse.Namespace) -> None:
    server = GameServer(
        args.data_dir, args.seed, args.ruleset, not args.timed, args.token, args.fast
    )
    runner = web.AppRunner(server.app, shutdown_timeout=2)
    await runner.setup()
    try:
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()
        host, port = runner.addresses[0][:2]
        url = f"http://{host}:{port}"
        if args.ready_file is not None:
            temporary = args.ready_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"url": url}), encoding="utf-8")
            temporary.replace(args.ready_file)
        print(f"LLM4TFT ready at {url}", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        if hasattr(loop, "add_signal_handler") and hasattr(signal, "SIGTERM"):
            try:
                loop.add_signal_handler(signal.SIGTERM, stop.set)
            except NotImplementedError:
                logger.info("Signal callbacks unavailable on this platform")
        await stop.wait()
    finally:
        await runner.cleanup()


def main() -> None:
    """Run the explicit server entry point; ordinary desktop play uses app.py."""
    args = parse_args()
    (args.data_dir / "log").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.data_dir / "log/server.log", level=logging.INFO)
    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
