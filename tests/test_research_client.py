"""Exercise headless policies and the real Socket.IO research boundary."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp import web


# quality: ignore[POT05] - test assertions cover policy boundaries; static fixture builders require no defensive checks
def _observation():
    return {
        "state": {
            "round": 0,
            "current_state": "READY",
            "decision_mode": True,
            "ruleset": "research",
            "seed": 7,
        },
        "player": {
            "id": "own",
            "hp": 100,
            "active": True,
            "gold": 3,
            "level": 2,
            "field": {"max_units": 2, "units": [None] * 28},
            "bench": {"max_units": 9, "units": [None] * 9},
            "shop": {"units": [{"cost": 1}] * 5},
            "legal_actions": {"buy_unit": [0], "buy_exp": False, "reroll": True},
        },
    }


def test_baseline_buys_affordable_offer_then_finishes_when_mask_empty():
    from research_client import BaselinePolicy

    state = _observation()
    policy = BaselinePolicy()
    assert asyncio.run(policy.choose(state)).name == "buy_unit"
    state["player"]["legal_actions"] = {"buy_unit": [], "buy_exp": False, "reroll": False}
    assert asyncio.run(policy.choose(state)).name == "advance_round"


def test_policy_observation_drops_opponents_private_state():
    from research_client import private_observation

    state = _observation()
    packet = {
        "game": {
            "state": state["state"],
            "players": {"other": {"shop": "secret", "bench": "secret"}},
        },
        "player": state["player"],
    }
    clean = private_observation(packet)
    assert clean == state
    assert "secret" not in json.dumps(clean)
    clean["player"]["gold"] = 0
    assert packet["player"]["gold"] == 3


@pytest.mark.parametrize(
    "text",
    [
        '{"action":"__import__","index":0}',
        '{"action":"buy_unit","index":true}',
        '{"action":"buy_unit","index":4}',
        '{"action":"buy_exp"}',
        '{"action":"advance_round","reason":"hidden reasoning"}',
        '{"action":"sell_unit","source":"bench","index":0}',
        '{"action":"move_unit","source":"bench","target":"field","source_index":0,"target_index":0}',
        '```json\n{"action":"advance_round"}\n```',
    ],
)
def test_invalid_or_illegal_model_action_is_rejected(text):
    from research_client import parse_action

    with pytest.raises(ValueError):
        parse_action(text, _observation())


def test_valid_move_and_sale_use_socket_argument_order():
    from research_client import parse_action

    state = _observation()
    state["player"]["bench"]["units"][0] = {"cost": 1}
    move = parse_action(
        '{"action":"move_unit","source":"bench","target":"field",'
        '"source_index":0,"target_index":-1}',
        state,
    )
    assert move.args == ("bench", "field", 0, -1)
    sale = parse_action('{"action":"sell_unit","source":"bench","index":0}', state)
    assert sale.args == ("bench", 0)


def test_openai_policy_uses_explicit_model_and_private_prompt_with_bounded_attempts():
    from research_client import OpenAIPolicy

    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        text = '{"action":"unknown"}' if len(requests) == 1 else '{"action":"buy_unit","index":0}'
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    policy = OpenAIPolicy("explicit-test-model", client=client)
    result = asyncio.run(policy.choose(_observation()))
    assert result.name == "buy_unit"
    assert len(requests) == 2
    assert requests[0]["model"] == "explicit-test-model"
    assert json.loads(requests[0]["messages"][1]["content"])["player"]["id"] == "own"


def test_openai_policy_repeated_bad_actions_fail_visibly():
    from research_client import OpenAIPolicy

    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="bad"))], usage=None
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(RuntimeError, match="valid action"):
        asyncio.run(OpenAIPolicy("test", client=client).choose(_observation()))
    assert len(calls) == 3


@pytest.mark.parametrize(
    "argv",
    [
        ["--games", "0"],
        ["--games", "101"],
        ["--policy", "openai"],
        ["--inference-timeout", "121"],
        ["--inference-timeout", "nan"],
        ["--seed", "-1"],
    ],
)
def test_cli_rejects_unbounded_or_underspecified_runs(argv):
    from research_client import parse_args

    with pytest.raises(SystemExit):
        parse_args(argv)


def test_session_forces_advance_after_nineteen_policy_actions(monkeypatch):
    from research_client import Action, ResearchSession

    class _RepeatedPolicy:
        async def choose(self, observation):
            return Action("reroll")

    sent = []

    async def send(event, data=None):
        sent.append((event, data))
        return {"ok": True}

    async def run():
        session = ResearchSession("http://unused", _RepeatedPolicy())
        monkeypatch.setattr(session, "_call", send)
        for _ in range(25):
            # quality: ignore[CS20] - exercise the bounded planning unit while replacing only its transport boundary
            await session._act(_observation())

    asyncio.run(run())
    assert len(sent) == 20
    assert sent[-1] == ("advance_round", None)


def test_session_never_calls_policy_for_dead_or_combat_player():
    from research_client import ResearchSession

    class _ForbiddenPolicy:
        async def choose(self, observation):
            pytest.fail("Policy must not run for a dead or fighting player")

    async def run():
        session = ResearchSession("http://unused", _ForbiddenPolicy())
        dead = _observation()
        dead["player"]["hp"] = 0
        battle = _observation()
        battle["state"]["current_state"] = "BATTLE"
        # quality: ignore[CS20] - directly exercise the gate that must exclude eliminated players
        await session._act(dead)
        # quality: ignore[CS20] - directly exercise the gate that must exclude combat observations
        await session._act(battle)

    asyncio.run(run())


def test_session_inference_is_bounded():
    from research_client import ResearchSession

    class _SlowPolicy:
        async def choose(self, observation):
            await asyncio.sleep(1)

    async def run():
        session = ResearchSession("http://unused", _SlowPolicy(), inference_timeout=0.01)
        # quality: ignore[CS20] - isolate the per-inference timeout without a network dependency
        await session._act(_observation())

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())


def test_changed_private_observation_invalidates_inflight_decision(monkeypatch):
    from research_client import Action, ResearchSession

    sent = []

    async def run():
        class _UpdatingPolicy:
            async def choose(self, observation):
                refreshed = _observation()
                refreshed["player"]["gold"] = 2
                # quality: ignore[CS20] - simulate the incoming state callback during an awaited inference
                await session._update(
                    {"game": {"state": refreshed["state"]}, "player": refreshed["player"]}
                )
                return Action("advance_round")

        async def send(event, data=None):
            sent.append(event)
            return True

        session = ResearchSession("http://unused", _UpdatingPolicy())
        monkeypatch.setattr(session, "_call", send)
        # quality: ignore[CS20] - isolate rejection of an inference made stale by a changed observation
        await session._act(_observation())
        assert sent == []
        # quality: ignore[CS20] - an identical periodic snapshot must not invalidate a current inference
        await session._act(session.latest)

    asyncio.run(run())
    assert sent == ["advance_round"]


@pytest.mark.parametrize("remote", [False, True])
def test_cli_fast_local_ownership_and_explicit_remote_isolation(monkeypatch, remote):
    import research_client

    args = research_client.parse_args(["--server", "http://existing"] if remote else [])
    events = []

    class _OwnedServer:
        def __init__(self, **kwargs):
            assert kwargs["fast"] is True
            events.append("owned")

        def start(self):
            events.append("start")
            return "http://owned"

        def stop(self):
            events.append("stop")

    async def run_cli(args, url):
        events.append(url)

    monkeypatch.setattr(research_client, "parse_args", lambda: args)
    monkeypatch.setattr(research_client, "LocalServer", _OwnedServer)
    monkeypatch.setattr(research_client, "_run_cli", run_cli)
    research_client.main()
    assert events == (["http://existing"] if remote else ["owned", "start", "http://owned", "stop"])


def test_agent_log_limit_preserves_existing_records(tmp_path, monkeypatch):
    import research_client

    monkeypatch.setattr(research_client, "MAX_AGENT_LOG_BYTES", 64)
    path = tmp_path / "test.agent.jsonl"
    log = research_client.AgentLog(path)
    log.write({"tokens": 10})
    with pytest.raises(RuntimeError, match="limit"):
        log.write({"prompt": "x" * 100})
    assert json.loads(path.read_text()) == {"tokens": 10}
    assert path.stat().st_size < 64


def test_server_failure_is_not_reported_as_completed(tmp_path, monkeypatch):
    from research_client import BaselinePolicy, ResearchSession
    from server import GameServer

    async def run():
        host = GameServer(tmp_path)

        async def fail(game_id):
            await asyncio.sleep(0.05)
            await host.sio.emit(
                "response", {"ok": False, "message": "Session stopped"}, to=host.rooms[game_id]
            )
            await host.remove_game(game_id, "error")

        monkeypatch.setattr(host, "run_battle", fail)
        runner = web.AppRunner(host.app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            session = ResearchSession(
                f"http://127.0.0.1:{runner.addresses[0][1]}", BaselinePolicy(), session_timeout=5
            )
            await session.run_game("failure-test", "failure-user")
        finally:
            await runner.cleanup()

    with pytest.raises(RuntimeError, match="error"):
        asyncio.run(run())


@pytest.mark.parametrize("reason", ["abandoned", "interrupted", "recording_limit"])
def test_terminal_outcome_during_inference_prevents_stale_action(tmp_path, monkeypatch, reason):
    from research_client import Action, ResearchSession
    from server import GameServer

    class _DelayedPolicy:
        async def choose(self, observation):
            await asyncio.sleep(0.1)
            return Action("advance_round")

    async def run():
        host = GameServer(tmp_path)

        async def abort(game_id):
            await asyncio.sleep(0.02)
            await host.remove_game(game_id, reason)

        monkeypatch.setattr(host, "run_battle", abort)
        runner = web.AppRunner(host.app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            session = ResearchSession(
                f"http://127.0.0.1:{runner.addresses[0][1]}", _DelayedPolicy(), session_timeout=5
            )
            await session.run_game("interrupted-test", "interrupted-user")
        finally:
            await runner.cleanup()

    with pytest.raises(RuntimeError, match=reason):
        asyncio.run(run())
    rows = [
        json.loads(row)
        for row in (tmp_path / "replay/interrupted-test.decisions.jsonl").read_text().splitlines()
    ]
    assert not any(row["type"] == "decision" for row in rows)


def test_baseline_real_socket_match_completes_and_records_decisions(tmp_path, monkeypatch):
    import server as server_module
    from research_client import BaselinePolicy, ResearchSession

    original = server_module.AutoBattlerGame

    def fast_game(*args, **kwargs):
        game = original(*args, **kwargs)
        game.rules = replace(game.rules, combat_seconds=0.001)
        return game

    monkeypatch.setattr(server_module, "AutoBattlerGame", fast_game)

    async def run():
        host = server_module.GameServer(tmp_path, seed=7)
        runner = web.AppRunner(host.app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}"
        try:
            session = ResearchSession(url, BaselinePolicy(), session_timeout=20)
            result = await session.run_game("headless-test", "headless-user")
            assert result["status"] == "completed"
        finally:
            await runner.cleanup()

    asyncio.run(run())
    records = [
        json.loads(row)
        for row in (tmp_path / "replay/headless-test.decisions.jsonl").read_text().splitlines()
    ]
    assert any(row.get("action", {}).get("name") == "advance_round" for row in records)
    assert records[-1]["type"] == "outcome"
    assert records[-1]["reason"] == "completed"
    assert all("players" not in row["observation"] for row in records if row["type"] == "decision")
