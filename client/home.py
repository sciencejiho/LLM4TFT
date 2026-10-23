"""Match discovery and creation using the existing lobby protocol."""

from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QListWidget, QPushButton, QVBoxLayout

from .baseWidget import BaseWidget


class HomeScreen(BaseWidget):
    """Create a research match or join a selected existing room."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 40, 50, 40)
        layout.setSpacing(18)
        eyebrow = QLabel("LLM4TFT / PLAY")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Your next experiment starts here.")
        title.setObjectName("title")
        hint = QLabel(
            "Create a match to play against baseline bots, or select an existing room to join."
        )
        hint.setObjectName("muted")
        self.game_list = QListWidget()
        self.game_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.btn_register = QPushButton("Create a new match  →")
        self.btn_register.setObjectName("primary")
        self.btn_register.clicked.connect(self.register_game)
        self.game_list.itemSelectionChanged.connect(self._selection_changed)
        self.game_list.itemDoubleClicked.connect(lambda item: self.register_game())
        for widget in (eyebrow, title, hint, self.game_list, self.btn_register):
            layout.addWidget(widget)

    def _selection_changed(self) -> None:
        self.btn_register.setText(
            "Join selected match  →" if self.game_list.selectedItems() else "Create a new match  →"
        )

    def register_game(self) -> None:
        """Register with a selected room or create a distinct local room ID."""
        selected = self.game_list.selectedItems()
        game_id = (
            selected[0].text() if selected else datetime.now().strftime("research_%Y%m%d_%H%M%S_%f")
        )
        self.controller.run_async(
            self.controller.socket_thread.send_command("register_game", game_id)
        )

    def update_state(self, data: dict[str, Any]) -> None:
        """Apply the available match list from a home snapshot."""
        if "games" in data:
            self.update_game_list(data["games"])

    def update_game_list(self, games: list[str]) -> None:
        """Retain selection while refreshing the bounded visible room list."""
        selected = self.game_list.currentItem()
        previous = selected.text() if selected else None
        if len(games) > 100:
            self.btn_register.setToolTip("Showing the first 100 available rooms")
        self.game_list.clear()
        for game in games[:100]:
            self.game_list.addItem(str(game))
        matches = self.game_list.findItems(previous, Qt.MatchFlag.MatchExactly) if previous else []
        if matches:
            self.game_list.setCurrentItem(matches[0])
