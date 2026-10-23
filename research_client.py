"""Run bounded, headless single-player research matches.

Examples
--------
``uv run python research_client.py --policy baseline --seed 7 --games 1``
``uv run python research_client.py --policy openai --model YOUR_MODEL --agent-log``

OpenAI is optional and reads OPENAI_API_KEY only when that policy is selected.
The owned server runs fixed-step combat as fast as possible. The authoritative
server writes replay/<game_id>.decisions.jsonl; optional
agent logs contain private prompts and usage, never credentials. Remote mode
requires an explicit-decision server with session_outcome support and does not
manage its process, simulation speed, or seed.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

import socketio

from launcher import ROOT, LocalServer

MAX_GAMES = 100
MAX_ROUNDS = 200
MAX_PREPARATION_ACTIONS = 20
MAX_SESSION_UPDATES = MAX_ROUNDS * 1000
MAX_MODEL_ATTEMPTS = 3
MAX_RESPONSE_CHARS = 4096
MAX_AGENT_LOG_BYTES = 32 * 1024 * 1024
RPC_TIMEOUT = 10.0
SYSTEM_PROMPT = """Choose exactly one action for this simplified autobattler.
Return a JSON object only, without explanations or reasoning. Use only observed
mechanics, gold, unit stats, and the legal_actions economy/shop mask. There are
no spells, item effects or trait bonuses. Never act during combat.
Actions and exact keys:
{"action":"buy_unit","index":0}
{"action":"buy_exp"}
{"action":"reroll"}
{"action":"move_unit","source":"bench","target":"field","source_index":0,"target_index":0}
{"action":"sell_unit","source":"bench","index":0}
{"action":"advance_round"}
Locations are bench or field; indices are zero based. Move target_index -1 means
first empty slot. Respect field max_units. Finish preparation with advance_round.
You receive only your own private state and public round/rules metadata.
"""


@dataclass(frozen=True)
class Action:
    """Represent an allowlisted Socket.IO action and ordered arguments."""

    name: str
    args: tuple[Any, ...] = ()


class Policy(Protocol):
    """Choose one action from a private, current preparation observation."""

    # quality: ignore[POT05] - CLI/JSON/RPC boundaries validate inputs; protocol and callbacks need no duplicate checks
    async def choose(self, observation: dict[str, Any]) -> Action:
        """Return one validated action without changing the observation."""
        ...


def private_observation(packet: dict[str, Any]) -> dict[str, Any]:
    """Copy own state and public rules metadata, excluding all opponent shops."""
    state = packet["game"]["state"]
    public_keys = ("round", "current_state", "decision_mode", "ruleset", "seed", "ruleset_version")
    public = {key: state[key] for key in public_keys if key in state}
    return {"state": public, "player": copy.deepcopy(packet["player"])}


def _ready(observation: dict[str, Any]) -> bool:
    player = observation["player"]
    return (
        observation["state"]["current_state"] == "READY"
        and player.get("active") is True
        and player.get("hp", 0) > 0
    )


def _index(value: Any, slots: int, allow_empty: bool = False) -> int:
    if type(value) is not int or not (-1 if allow_empty else 0) <= value < slots:
        raise ValueError("Invalid slot index")
    return int(value)


def _location(value: Any) -> str:
    if value not in ("bench", "field"):
        raise ValueError("Location must be bench or field")
    return str(value)


def _slot_action(data: dict[str, Any], player: dict[str, Any]) -> Action:
    name, source = data["action"], _location(data["source"])
    source_units = player[source]["units"]
    source_key = "source_index" if name == "move_unit" else "index"
    index = _index(data[source_key], len(source_units))
    if source_units[index] is None:
        raise ValueError("Source slot is empty")
    if name == "sell_unit":
        return Action(name, (source, index))
    target = _location(data["target"])
    target_units = player[target]["units"]
    target_index = _index(data["target_index"], len(target_units), allow_empty=True)
    resolved = target_index
    if resolved == -1:
        resolved = next((slot for slot, unit in enumerate(target_units[:28]) if unit is None), -1)
    if resolved == -1 or (source == target and resolved == index):
        raise ValueError("Move has no valid destination")
    occupied = sum(unit is not None for unit in target_units[:28])
    if (
        source != target
        and target_units[resolved] is None
        and occupied >= player[target]["max_units"]
    ):
        raise ValueError("Destination is at capacity")
    return Action(name, (source, target, index, target_index))


def parse_action(text: str, observation: dict[str, Any]) -> Action:
    """Validate strict JSON, argument types, occupancy and observed legal masks.

    Raises
    ------
    ValueError
        If the response is malformed, unavailable now, or contains extra keys.
    """
    if not isinstance(text, str) or len(text) > MAX_RESPONSE_CHARS or not _ready(observation):
        raise ValueError("Action requires bounded JSON and an alive player in preparation")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Action is not valid JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("action"), str):
        # Invalid decoded JSON is a value error at this string parsing boundary.
        raise ValueError("Response must contain a JSON action object")  # noqa: TRY004
    name = data["action"]
    schemas = {
        "advance_round": {"action"},
        "buy_exp": {"action"},
        "reroll": {"action"},
        "buy_unit": {"action", "index"},
        "sell_unit": {"action", "source", "index"},
        "move_unit": {"action", "source", "target", "source_index", "target_index"},
    }
    if name not in schemas or set(data) != schemas[name]:
        raise ValueError("Unsupported action or unexpected keys")
    player = observation["player"]
    legal = player.get("legal_actions", {})
    if name == "advance_round":
        return Action(name)
    if name in ("buy_exp", "reroll"):
        if legal.get(name) is not True:
            raise ValueError("Action is not currently legal")
        return Action(name)
    if name == "buy_unit":
        index = _index(data["index"], 5)
        if index not in legal.get("buy_unit", []):
            raise ValueError("Shop slot is not currently affordable and available")
        return Action(name, (index,))
    return _slot_action(data, player)


class BaselinePolicy:
    """Deploy units, buy legal offers and spend surplus gold deterministically."""

    async def choose(self, observation: dict[str, Any]) -> Action:
        """Choose a useful deterministic action or finish preparation."""
        player = observation["player"]
        field, bench = player["field"], player["bench"]
        deployed = sum(unit is not None for unit in field["units"][:28])
        if deployed < field["max_units"]:
            index = next((i for i, unit in enumerate(bench["units"][:9]) if unit is not None), -1)
            if index >= 0:
                return Action("move_unit", ("bench", "field", index, -1))
        legal = player["legal_actions"]
        if legal.get("buy_unit"):
            return Action("buy_unit", (legal["buy_unit"][0],))
        if player.get("gold", 0) >= 10 and legal.get("buy_exp"):
            return Action("buy_exp")
        if player.get("gold", 0) >= 10 and legal.get("reroll"):
            return Action("reroll")
        return Action("advance_round")


class AgentLog:
    """Write optional local inference metadata with a strict 32 MiB ceiling."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass
        self.bytes_written = 0

    def write(self, record: dict[str, Any]) -> None:
        """Append one record or fail visibly before exceeding the file bound."""
        encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        if self.bytes_written + len(encoded) > MAX_AGENT_LOG_BYTES:
            raise RuntimeError("Agent log exceeded its 32 MiB limit")
        with self.path.open("ab") as stream:
            stream.write(encoded)
        self.bytes_written += len(encoded)


class OpenAIPolicy:
    """Request bounded JSON decisions using an explicitly selected model.

    Parameters
    ----------
    model : str
        Exact user-selected API model; no implicit default is used.
    timeout : float, default 30
        Overall inference timeout in seconds, including at most three attempts.
    client : optional
        Injected AsyncOpenAI-compatible client for offline tests.
    agent_log : AgentLog, optional
        Local private prompt, response, token and latency journal.
    """

    def __init__(
        self,
        model: str,
        timeout: float = 30,
        client: Any = None,
        agent_log: Optional[AgentLog] = None,
    ):
        if not model.strip() or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Specify a model and inference timeout in (0, 120]")
        self.model, self.timeout = model, timeout
        self.client, self.agent_log = client, agent_log
        self._owns_client = client is None

    def _get_client(self) -> Any:
        if self.client is None:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is required for --policy openai")
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(api_key=api_key, timeout=self.timeout, max_retries=0)
        return self.client

    async def choose(self, observation: dict[str, Any]) -> Action:
        """Return a legal action or raise after the bounded inference budget."""
        return await asyncio.wait_for(self._choose(observation), timeout=self.timeout)

    async def _choose(self, observation: dict[str, Any]) -> Action:
        from openai import APIError

        client = self._get_client()
        completions = client.chat.completions
        prompt = json.dumps(observation, ensure_ascii=False)
        for attempt in range(MAX_MODEL_ATTEMPTS):
            started = time.monotonic()
            try:
                response = await completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=256,
                )
            except APIError as error:
                raise RuntimeError(f"OpenAI request failed ({type(error).__name__})") from None
            text = response.choices[0].message.content if response.choices else ""
            self._log_attempt(prompt, text or "", response.usage, attempt, started)
            try:
                return parse_action(text or "", observation)
            except ValueError:
                continue
        raise RuntimeError(f"Model did not return a valid action in {MAX_MODEL_ATTEMPTS} attempts")

    def _log_attempt(
        self, prompt: str, response: str, usage: Any, attempt: int, started: float
    ) -> None:
        if self.agent_log is None:
            return
        tokens = (
            {"input": usage.prompt_tokens, "output": usage.completion_tokens}
            if usage is not None
            else None
        )
        self.agent_log.write(
            {
                "model": self.model,
                "system_prompt": SYSTEM_PROMPT,
                "prompt": prompt,
                "response": response[:MAX_RESPONSE_CHARS],
                "attempt": attempt + 1,
                "tokens": tokens,
                "latency_seconds": time.monotonic() - started,
            }
        )

    async def close(self) -> None:
        """Close only an SDK client created by this policy."""
        if self._owns_client and self.client is not None:
            await self.client.close()
            self.client = None


# quality: ignore[CS15] - this session owns connection, event mailbox and lifecycle behind one public run method
class ResearchSession:
    """Run one remote game with a coalesced, constant-size state mailbox.

    Parameters
    ----------
    url : str
        Existing Socket.IO server URL; this class never manages that process.
    policy : Policy
        Policy receiving exclusively private observations.
    inference_timeout : float, default 30
        Per-decision deadline, at most 120 seconds.
    session_timeout : float, default 7200
        Total match wall-clock deadline in seconds, at most 86400.
    """

    def __init__(
        self, url: str, policy: Policy, inference_timeout: float = 30, session_timeout: float = 7200
    ):
        if not math.isfinite(inference_timeout) or not 0 < inference_timeout <= 120:
            raise ValueError("Inference timeout must be in (0, 120]")
        if not math.isfinite(session_timeout) or not 0 < session_timeout <= 86400:
            raise ValueError("Session timeout must be in (0, 86400]")
        self.url, self.policy = url, policy
        self.inference_timeout, self.session_timeout = inference_timeout, session_timeout
        self.client = socketio.AsyncClient(reconnection=False)
        self.latest: Optional[dict[str, Any]] = None
        self.changed = asyncio.Event()
        self.ended = False
        self._game_id = ""
        self._outcome: Optional[dict[str, Any]] = None
        self._generation = 0
        self.last_round = -1
        self.preparation_actions = 0
        self.advanced_round = -1
        self.client.on("update_game", self._update)
        self.client.on("game_end", self._end)
        self.client.on("session_outcome", self._receive_outcome)
        self.client.on("disconnect", self._disconnect)

    async def _update(self, packet: dict[str, Any]) -> None:
        if packet.get("game") and packet.get("player"):
            observation = private_observation(packet)
            if observation != self.latest:
                self._generation += 1
            self.latest = observation
            self.changed.set()

    async def _receive_outcome(self, packet: dict[str, Any]) -> None:
        if packet.get("game_id") != self._game_id:
            return
        self._outcome = {
            "reason": packet.get("reason"),
            "round": packet.get("round"),
            "ranking": packet.get("ranking", [])[:8],
        }
        self.ended = True
        self.changed.set()

    async def _end(self, *args: Any) -> None:
        self.ended = True
        self.changed.set()

    async def _disconnect(self, *args: Any) -> None:
        self.changed.set()

    async def run_game(self, game_id: str, user_id: str) -> dict[str, Any]:
        """Connect, play one complete match and always release the connection."""
        try:
            return await asyncio.wait_for(self._run(game_id, user_id), timeout=self.session_timeout)
        finally:
            if self.client.connected:
                await asyncio.wait_for(self.client.disconnect(), timeout=RPC_TIMEOUT)

    async def _call(self, event: str, data: Any = None) -> Any:
        result = await self.client.call(event, data=data, timeout=RPC_TIMEOUT)
        if result is False or (isinstance(result, dict) and not result.get("ok")):
            raise RuntimeError(f"Server rejected {event}")
        return result

    async def _run(self, game_id: str, user_id: str) -> dict[str, Any]:
        self._game_id = game_id
        await self.client.connect(self.url, wait_timeout=RPC_TIMEOUT)
        await self._call("login", user_id)
        await self._call("register_game", game_id)
        await self._call("start_game")
        for _ in range(MAX_SESSION_UPDATES):
            await self.changed.wait()
            self.changed.clear()
            if self.ended:
                return self._terminal_result(game_id)
            if not self.client.connected:
                raise RuntimeError("Server disconnected before the match completed")
            if self.latest is not None:
                await self._act(self.latest)
        raise RuntimeError("Match exceeded the bounded update budget")

    def _terminal_result(self, game_id: str) -> dict[str, Any]:
        if self._outcome is None:
            raise RuntimeError("Server ended the session without an authoritative session_outcome")
        reason = self._outcome["reason"]
        if reason != "completed":
            raise RuntimeError(f"Server ended the session: {reason}")
        return {"game_id": game_id, "status": "completed", **self._outcome}

    async def _act(self, observation: dict[str, Any]) -> None:
        state = observation["state"]
        if state.get("decision_mode") is not True:
            raise RuntimeError(
                "Research client requires decision_mode; timed preparation is unsupported"
            )
        turn = state["round"]
        if type(turn) is not int or not 0 <= turn <= MAX_ROUNDS:
            raise RuntimeError("Match exceeded its 200-round bound")
        if turn != self.last_round:
            self.last_round, self.preparation_actions = turn, 0
        if not _ready(observation) or turn == self.advanced_round:
            return
        generation = self._generation
        if self.preparation_actions >= MAX_PREPARATION_ACTIONS - 1:
            action = Action("advance_round")
        else:
            action = await asyncio.wait_for(self.policy.choose(observation), self.inference_timeout)
        if self.ended or generation != self._generation:
            return
        if action.name == "advance_round":
            self.advanced_round = turn
        self.preparation_actions += 1
        data = action.args if action.args else None
        await self._call(action.name, data)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse finite experiment settings; OpenAI requires an exact model name."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=("baseline", "openai"), default="baseline")
    parser.add_argument("--model", help="Exact API model, required for --policy openai")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument(
        "--server", help="Use an existing decision-mode server without spawning one"
    )
    parser.add_argument("--ruleset", choices=("research", "legacy"), default="research")
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--inference-timeout", type=float, default=30)
    parser.add_argument("--session-timeout", type=float, default=7200)
    parser.add_argument(
        "--agent-log", action="store_true", help="Save private local .agent.jsonl logs"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.games <= MAX_GAMES or not 0 <= args.seed <= 2**32 - 1:
        parser.error("games must be 1..100 and seed must be an unsigned 32-bit integer")
    if args.policy == "openai" and (not args.model or not args.model.strip()):
        parser.error("--policy openai requires an explicit --model")
    if not math.isfinite(args.inference_timeout) or not 0 < args.inference_timeout <= 120:
        parser.error("inference-timeout must be in (0, 120]")
    if not math.isfinite(args.session_timeout) or not 0 < args.session_timeout <= 86400:
        parser.error("session-timeout must be in (0, 86400]")
    return args


async def _run_cli(args: argparse.Namespace, url: str) -> None:
    for game_number in range(MAX_GAMES):
        if game_number >= args.games:
            return
        identity = uuid.uuid4().hex
        game_id, user_id = f"research-{identity}", f"agent-{identity}"
        policy: Policy = BaselinePolicy()
        if args.policy == "openai":
            log = (
                AgentLog(args.data_dir / "replay" / f"{game_id}.agent.jsonl")
                if args.agent_log
                else None
            )
            policy = OpenAIPolicy(args.model, args.inference_timeout, agent_log=log)
        session = ResearchSession(url, policy, args.inference_timeout, args.session_timeout)
        print(json.dumps({"game_id": game_id, "server": url, "policy": args.policy}), flush=True)
        try:
            result = await session.run_game(game_id, user_id)
            print(json.dumps(result), flush=True)
        finally:
            if isinstance(policy, OpenAIPolicy):
                await policy.close()


def main() -> None:
    """Run sequential matches and stop only the local server owned by this CLI."""
    args = parse_args()
    owner = (
        None
        if args.server
        else LocalServer(data_dir=args.data_dir, seed=args.seed, ruleset=args.ruleset, fast=True)
    )
    try:
        url = owner.start() if owner is not None else args.server
        asyncio.run(_run_cli(args, url))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (
        OSError,
        RuntimeError,
        ValueError,
        asyncio.TimeoutError,
        socketio.exceptions.SocketIOError,
    ) as error:
        raise SystemExit(f"Research run failed: {error}") from None
    finally:
        if owner is not None:
            owner.stop()


if __name__ == "__main__":
    main()
