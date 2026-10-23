"""Launch the LLM4TFT desktop workbench and its owned local server."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Coroutine
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QStackedWidget, QVBoxLayout

from client import BaseWidget, GameScreen, HomeScreen, LobbyScreen, LoginScreen, SocketThread
from launcher import ROOT, LocalServer


class GameUI(BaseWidget):
    """Compose the game screens and coordinate signals on the GUI thread.

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        Fresh worker event loop.
    server_url : str, default 'http://localhost:5000'
        Server verified by the launcher or selected explicitly by the user.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, server_url: str = "http://localhost:5000"):
        super().__init__()
        self.setWindowTitle("LLM4TFT · Research Workbench")
        self.resize(1440, 960)
        self.setMinimumSize(1100, 760)
        self.loop = loop
        self.socket_thread = SocketThread(self, loop, server_url)
        self.stacked_widget = QStackedWidget()
        self.login_screen = LoginScreen(self)
        self.home_screen = HomeScreen(self)
        self.lobby_screen = LobbyScreen(self)
        self.game_screen = GameScreen(self)
        for screen in (self.login_screen, self.home_screen, self.lobby_screen, self.game_screen):
            self.stacked_widget.addWidget(screen)
        self.connection_status = QLabel(f"Connecting to {server_url}")
        self.connection_status.setObjectName("connectionStatus")
        self.message_label = QLabel("Local research · decisions are recorded automatically")
        self.message_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.connection_status)
        layout.addWidget(self.stacked_widget, 1)
        layout.addWidget(self.message_label)
        worker = self.socket_thread
        worker.update_ui.connect(self.update_interface)
        worker.connection_status.connect(self.connection_status.setText)
        worker.server_message.connect(self.message_label.setText)
        worker.game_ended.connect(self._game_ended)
        worker.session_finished.connect(self._session_finished)
        self.stacked_widget.setCurrentWidget(self.login_screen)
        self.socket_thread.start()

    def update_interface(self, data: dict[str, Any]) -> None:
        """Apply a detached network snapshot to the relevant screen."""
        current = self.stacked_widget.currentWidget()
        if data.get("user", {}).get("user_id") and current is self.login_screen:
            self.stacked_widget.setCurrentWidget(self.home_screen)
        if data.get("game"):
            self.game_screen.update_state(data["game"])
            self.stacked_widget.setCurrentWidget(self.game_screen)
        if "lobby" in data:
            self.lobby_screen.update_state(data["lobby"])
            if current in (self.home_screen, self.lobby_screen):
                self.stacked_widget.setCurrentWidget(self.lobby_screen)
        if "home" in data:
            self.home_screen.update_state(data["home"])

    def _game_ended(self) -> None:
        self.game_screen.state = None
        self.game_screen.player_id = None
        self.game_screen.view_player = None
        self.stacked_widget.setCurrentWidget(self.home_screen)

    def _session_finished(self, outcome: dict[str, Any]) -> None:
        reason = outcome.get("reason", "unknown")
        ranking = outcome.get("ranking", [])
        user_id = self.socket_thread.state.get("user", {}).get("user_id")
        if reason == "completed" and user_id in ranking:
            placement = ranking.index(user_id) + 1
            self.message_label.setText(
                f"Match complete · Placement {placement} / {len(ranking)} · Decisions saved"
            )
        else:
            self.message_label.setText(
                f"Session ended: {reason}. Inspect the replay and server log for details."
            )

    def run_async(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        """Schedule an existing client command on the socket worker's loop."""
        if self.loop.is_closed() or not self.socket_thread.isRunning():
            coroutine.close()
            raise RuntimeError("The connection worker has stopped; restart the application")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:
        """Wait for cooperative socket shutdown before destroying Qt objects."""
        if event is None:
            return
        if self.socket_thread.stop():
            event.accept()
        else:
            self.message_label.setText("Waiting for connection shutdown…")
            event.ignore()
            QTimer.singleShot(100, self.close)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse local launch options or an explicit remote server URL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server", help="Connect to this HTTP(S) endpoint without starting a server"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ruleset", choices=("research", "legacy"), default="research")
    parser.add_argument("--timed", action="store_true", help="Use timed preparation locally")
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if not 0 <= args.seed <= 2**32 - 1:
        parser.error("Seed must be between 0 and 2**32-1")
    if args.server:
        url = urlparse(args.server)
        if url.scheme not in ("http", "https") or not url.hostname:
            parser.error("--server requires an HTTP(S) URL")
    return args


def main(argv: Optional[list[str]] = None) -> int:
    """Run a local owned session by default, or connect to an explicit server."""
    args = parse_args(argv)
    qt_app = QApplication([sys.argv[0]])
    local = None
    window = None
    try:
        if args.server:
            server_url = args.server
        else:
            local = LocalServer(
                data_dir=args.data_dir, seed=args.seed, ruleset=args.ruleset, timed=args.timed
            )
            server_url = local.start()
        window = GameUI(asyncio.new_event_loop(), server_url)
        window.show()
        return qt_app.exec()
    except (RuntimeError, OSError) as error:
        QMessageBox.critical(None, "LLM4TFT could not start", str(error))
        return 1
    finally:
        if window is not None:
            window.socket_thread.stop()
        if local is not None:
            local.stop()


if __name__ == "__main__":
    sys.exit(main())
