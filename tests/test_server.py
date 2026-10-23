"""Verify player commands, local research flow and flushed decision records."""

import asyncio
import json
from dataclasses import replace

import pytest
import socketio
from aiohttp import web


def test_socket_session_and_decision_recording(tmp_path):
    asyncio.run(_session(tmp_path))


async def _session(tmp_path):
    from server import GameServer

    server = GameServer(data_dir=tmp_path, seed=23, decision_mode=True)
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    client = socketio.AsyncClient()
    states = []
    outcomes = []
    user_states = []
    client.on("update_game", lambda state: states.append(state))
    client.on("session_outcome", lambda outcome: outcomes.append(outcome))
    client.on("update_user", lambda state: user_states.append(state))
    try:
        await client.connect(f"http://127.0.0.1:{port}")
        assert await client.call("login", "researcher", timeout=3)
        assert not await client.call("register_game", "../unsafe", timeout=3)
        assert await client.call("register_game", "session-23", timeout=3)
        assert await client.call("start_game", timeout=3)
        assert user_states[-1]["playing"] is True
        game = server.games["session-23"]
        assert game.state.name == "READY"
        result = await client.call("buy_unit", 0, timeout=3)
        assert result["ok"]
        player = game.get_player_by_user_id("researcher")
        assert player.gold >= 0
        assert not (await client.call("buy_unit", -1, timeout=3))["ok"]
        assert await client.call("advance_round", timeout=3)
        assert game.state.name == "BATTLE"
        assert not (await client.call("reroll", timeout=3))["ok"]
        rows = [
            json.loads(line)
            for line in (tmp_path / "replay/session-23.decisions.jsonl").read_text().splitlines()
        ]
        assert rows[0]["type"] == "metadata"
        assert rows[0]["seed"] == 23
        decisions = [row for row in rows if row["type"] == "decision"]
        assert decisions[0]["observation"]["gold"] == 3
        assert decisions[0]["next_observation"]["gold"] < 3
        assert "players" not in decisions[0]["observation"]
        assert any(not row["result"]["ok"] for row in decisions)
        assert states[-1]["game"]["state"]["ruleset"] == "research"
        assert await client.call("quit_game", timeout=3)
        rows = [
            json.loads(line)
            for line in (tmp_path / "replay/session-23.decisions.jsonl").read_text().splitlines()
        ]
        assert rows[-1]["type"] == "outcome"
        assert rows[-1]["reason"] == "abandoned"
        assert outcomes == [
            {"game_id": "session-23", "reason": "abandoned", "round": 0, "ranking": []}
        ]
        assert user_states[-1]["playing"] is False
        assert user_states[-1]["game_id"] is None
    finally:
        await client.disconnect()
        await runner.cleanup()


def test_disconnected_session_cannot_reuse_user_identity(tmp_path):
    asyncio.run(_identity(tmp_path))


def test_eight_registered_agents_start_without_an_external_controller(tmp_path):
    asyncio.run(_full_lobby(tmp_path))


def test_last_living_planner_leaving_wakes_remaining_bots(tmp_path):
    asyncio.run(_planner_leaves(tmp_path))


async def _planner_leaves(tmp_path):
    from server import GameServer

    server = GameServer(data_dir=tmp_path, fast=True)
    try:
        for user_id in ("alive", "dead"):
            assert await server.login(user_id, user_id)
            assert await server.register_game(user_id, "planner-leaves")
        assert await server.start_game("alive")
        game = server.games["planner-leaves"]
        game.get_player_by_user_id("dead").hp = 0
        await asyncio.sleep(0)
        assert game.timer == 0
        await server.quit_game("alive")
        await asyncio.sleep(0)
        assert game.timer > 0
        assert game.current_players == {"dead"}
    finally:
        await server._cleanup(server.app)


async def _full_lobby(tmp_path):
    from server import GameServer

    server = GameServer(data_dir=tmp_path, decision_mode=False)
    try:
        for index in range(8):
            sid = f"legacy-{index}"
            assert await server.login(sid, sid)
            assert await server.register_game(sid, "legacy-full-room")
        assert server.games["legacy-full-room"].running
        assert "legacy-full-room" in server.journals
    finally:
        await server._cleanup(server.app)


async def _identity(tmp_path):
    from server import GameServer

    server = GameServer(data_dir=tmp_path)
    server.clients.update(("one", "two"))
    assert await server.login("one", "same-user")
    assert not await server.login("two", "same-user")
    assert not await server.login("two", "../../bad")


@pytest.mark.parametrize("command", ["buy_unit", "advance_round"])
@pytest.mark.parametrize("resource", ["rows", "bytes"])
def test_recording_limit_stops_before_mutation_and_keeps_terminal_record(
    tmp_path, command, resource, monkeypatch
):
    asyncio.run(_recording_limit(tmp_path, command, resource, monkeypatch))


async def _recording_limit(tmp_path, command, resource, monkeypatch):
    import recording
    from server import GameServer

    host = GameServer(tmp_path)
    await host.login("one", "human")
    await host.register_game("one", "limited")
    await host.start_game("one")
    journal = host.journals["limited"]
    assert (await host.buy_unit("one", 0))["ok"]
    if resource == "rows":
        journal.max_records = 3  # Metadata, one decision, terminal outcome.
    else:
        monkeypatch.setattr(
            recording,
            "MAX_JOURNAL_BYTES",
            journal.bytes_written + 2 * recording.MAX_RECORD_BYTES - 1,
        )
    game = host.games["limited"]
    player = await host.get_player("one")
    previous_gold = player.gold
    if command == "buy_unit":
        assert not (await host.buy_unit("one", 1))["ok"]
    else:
        assert not await host.advance_round("one")
    assert player.gold == previous_gold
    assert game.state.name == "READY"
    assert "limited" not in host.games
    assert "limited" not in host.tasks
    assert host.user_info["human"]["game_id"] is None
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert [row["type"] for row in rows] == ["metadata", "decision", "outcome"]
    assert rows[-1]["reason"] == "recording_limit"


def test_recording_io_failure_still_releases_game_and_reports_error(tmp_path, caplog):
    asyncio.run(_recording_io_failure(tmp_path))
    assert "outcome" in caplog.text.lower()


async def _recording_io_failure(tmp_path):
    from server import GameServer

    host = GameServer(tmp_path)
    await host.login("one", "human")
    await host.register_game("one", "broken")
    await host.start_game("one")
    journal = host.journals["broken"]
    journal.path = tmp_path  # A directory cannot accept an appended JSON row.
    await host.remove_game("broken")
    assert "broken" not in host.games
    assert "broken" not in host.tasks
    assert host.user_info["human"]["game_id"] is None
    assert host.journals["broken"] is journal


def test_initial_recording_failure_does_not_leave_an_unsteppable_game(tmp_path):
    asyncio.run(_initial_recording_failure(tmp_path))


async def _initial_recording_failure(tmp_path):
    from server import GameServer

    host = GameServer(tmp_path)
    await host.login("one", "human")
    await host.register_game("one", "failed-start")
    game = host.games["failed-start"]
    blocked = tmp_path / "blocked"
    blocked.write_text("A file cannot contain recording files.")
    host.replay_path = blocked
    assert not await host.start_game("one")
    assert not game.running
    assert "failed-start" not in host.games
    assert "failed-start" not in host.tasks
    assert host.user_info["human"]["game_id"] is None


def test_fast_match_waits_for_decisions_and_finishes_without_wall_clock_combat(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("server.MAX_GAME_TICKS", 1800)
    asyncio.run(_fast_match(tmp_path))


async def _fast_match(tmp_path):
    from server import GameServer

    host = GameServer(tmp_path, seed=3, fast=True)
    await host.login("one", "human")
    await host.register_game("one", "fast")
    game = host.games["fast"]
    game.rules = replace(game.rules, max_rounds=1)
    await host.start_game("one")
    task = host.tasks["fast"]
    try:
        await asyncio.sleep(0.02)
        assert game.round == 0 and game.timer == 0
        assert not task.done()
        assert await host.advance_round("one")
        await asyncio.wait_for(task, timeout=5)
        assert "fast" not in host.games
        rows = [
            json.loads(row)
            for row in (tmp_path / "replay/fast.decisions.jsonl").read_text().splitlines()
        ]
        assert rows[-1]["reason"] == "completed"
        assert rows[-1]["round"] == 1
        assert len(rows[-1]["ranking"]) == 8
    finally:
        await host._cleanup(host.app)
