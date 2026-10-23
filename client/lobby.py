"""Pre-match player list and explicit start controls."""

from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout

from .baseWidget import BaseWidget


class LobbyScreen(BaseWidget):
    """Display match participants and explain automatic baseline opponents."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(18)
        eyebrow = QLabel("LLM4TFT / MATCH LOBBY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Ready your strategy.")
        title.setObjectName("title")
        self.game_id_label = QLabel()
        self.game_id_label.setObjectName("muted")
        self.user_list = QListWidget()
        hint = QLabel(
            "Open seats are filled by baseline bots when you start.\nDuring preparation, recruit units, drag them onto the board, then start combat."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.btn_start = QPushButton("Start match  →")
        self.btn_start.setObjectName("primary")
        self.btn_start.clicked.connect(self.start_game)
        self.btn_quit = QPushButton("Back to matches")
        self.btn_quit.clicked.connect(self.quit)
        controls = QHBoxLayout()
        controls.addWidget(self.btn_quit)
        controls.addWidget(self.btn_start)
        for widget in (eyebrow, title, self.game_id_label, self.user_list, hint):
            layout.addWidget(widget)
        layout.addLayout(controls)

    def start_game(self) -> None:
        """Start the room through the existing Socket.IO event."""
        self.controller.run_async(self.controller.socket_thread.send_command("start_game"))

    def update_state(self, data: dict[str, Any]) -> None:
        """Refresh room identity and participants from a lobby snapshot."""
        if "game_id" in data:
            self.game_id_label.setText(f"Match room · {data['game_id']}")
        if "players" in data:
            self.update_user_list(data["players"])

    def update_user_list(self, users: list[dict[str, Any]]) -> None:
        """Show up to eight room members with their recorded scores."""
        self.user_list.clear()
        if len(users) > 8:
            raise ValueError("Lobby snapshot exceeds eight supported players")
        for user in users[:8]:
            self.user_list.addItem(f"{user['user_id']}     ·     Score {user.get('score', 0)}")

    def quit(self) -> None:
        """Leave the room and return to available matches."""
        self.controller.run_async(self.controller.socket_thread.send_command("quit_game", None))
        self.controller.socket_thread.state["game"] = {}
        self.controller.stacked_widget.setCurrentWidget(self.controller.home_screen)
