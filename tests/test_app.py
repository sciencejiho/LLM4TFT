"""Exercise a real desktop/socket/server lifecycle without a graphical display."""

import asyncio
import json
import os

# quality: ignore[PY001] - select offscreen Qt before importing Qt in GUI tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import GameUI
from client.socket import SocketThread
from launcher import LocalServer

MAX_GUI_POLLS = 1000


def _until(application, predicate):
    for _ in range(MAX_GUI_POLLS):
        application.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Desktop state did not arrive within ten seconds")


def test_desktop_local_match_and_shutdown(tmp_path):
    application = QApplication.instance() or QApplication([])
    with LocalServer(data_dir=tmp_path, seed=11) as local:
        window = GameUI(asyncio.new_event_loop(), local.url)
        try:
            _until(application, lambda: window.socket_thread.sio.connected)
            worker = window.socket_thread
            window.login_screen.username_input.setText("desktop-test")
            window.login_screen.login()
            assert window.stacked_widget.currentWidget() is window.login_screen
            _until(application, lambda: worker.state["user"].get("user_id") == "desktop-test")
            _until(application, lambda: window.stacked_widget.currentWidget() is window.home_screen)
            window.run_async(worker.send_command("register_game", "desktop-match"))
            _until(application, lambda: bool(worker.state["lobby"]))
            _until(
                application, lambda: window.stacked_widget.currentWidget() is window.lobby_screen
            )
            window.lobby_screen.start_game()
            assert window.stacked_widget.currentWidget() is window.lobby_screen
            _until(application, lambda: window.game_screen.state is not None)
            assert window.stacked_widget.currentWidget() is window.game_screen
            assert window.game_screen.btn_combat.isEnabled()
            window.game_screen.btn_combat.click()
            _until(
                application,
                lambda: worker.state["game"]["game"]["state"]["current_state"] == "BATTLE",
            )
            assert not window.game_screen.btn_combat.isEnabled()
        finally:
            window.close()
            _until(application, lambda: not window.socket_thread.isRunning())
            window.deleteLater()
            application.processEvents()
    rows = [
        json.loads(line)
        for line in (tmp_path / "replay/desktop-match.decisions.jsonl").read_text().splitlines()
    ]
    assert rows[-1]["type"] == "outcome"
    assert rows[-1]["reason"] in ("abandoned", "interrupted")


def test_close_while_connection_is_unavailable():
    application = QApplication.instance() or QApplication([])
    window = GameUI(asyncio.new_event_loop(), "http://127.0.0.1:1")
    QTest.qWait(20)
    window.close()
    assert not window.socket_thread.isRunning()
    window.deleteLater()
    application.processEvents()


def test_worker_shutdown_handles_canceled_transport():
    application = QApplication.instance() or QApplication([])
    loop = asyncio.new_event_loop()
    worker = SocketThread(None, loop, "http://127.0.0.1:1")
    worker.sio.connected = True
    worker.sio.eio.state = "connected"
    task = loop.create_task(asyncio.sleep(60))
    worker.sio.eio.read_loop_task = task
    task.cancel()
    try:
        loop.run_until_complete(worker._shutdown())
        assert worker.sio.eio.state == "disconnected"
    finally:
        loop.close()
        worker.deleteLater()
        application.processEvents()
