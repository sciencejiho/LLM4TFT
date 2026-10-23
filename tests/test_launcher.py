"""Exercise owned local server startup over a real process boundary."""

import json
import urllib.request
from pathlib import Path

import pytest


def test_owned_server_uses_free_port_and_stops(tmp_path):
    from launcher import LocalServer

    server = LocalServer(data_dir=tmp_path, seed=17)
    with server:
        assert server.url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(server.url + "/health", timeout=2) as response:
            health = json.load(response)
        assert health["application"] == "LLM4TFT"
        assert health["seed"] == 17
        assert health["decision_mode"] is True
        process = server.process
        assert process.poll() is None
    assert process.poll() is not None
    server.stop()


def test_startup_failure_reports_log_and_reaps_process(tmp_path):
    from launcher import LocalServer

    (tmp_path / "server.py").write_text("raise RuntimeError('startup sentinel')\n")
    server = LocalServer(project_dir=tmp_path, data_dir=tmp_path)
    with pytest.raises(RuntimeError, match="startup sentinel"):
        server.start()
    assert server.process.poll() is not None


def test_headless_server_enables_fast_simulation(tmp_path):
    from launcher import LocalServer

    with LocalServer(data_dir=tmp_path, fast=True) as server:
        with urllib.request.urlopen(server.url + "/health", timeout=2) as response:
            health = json.load(response)
        assert health["fast"] is True
        assert health["decision_mode"] is True


def test_remote_mode_does_not_construct_local_server():
    from app import parse_args

    args = parse_args(["--server", "https://example.org:5000"])
    assert args.server == "https://example.org:5000"
    assert args.seed == 0


def test_invalid_remote_url_is_rejected():
    from app import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--server", "file:///tmp/not-a-server"])


def test_recording_has_resource_ceiling(tmp_path):
    from recording import DecisionJournal

    journal = DecisionJournal(Path(tmp_path) / "decisions.jsonl", {"seed": 5}, max_records=3)
    journal.write({"type": "decision", "action": "reroll"})
    with pytest.raises(RuntimeError, match="limit"):
        journal.write({"type": "decision", "action": "reroll"})
    journal.write({"type": "outcome", "reason": "recording_limit"})
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert rows[0]["seed"] == 5
    assert rows[1]["action"] == "reroll"
    assert rows[-1]["type"] == "outcome"
