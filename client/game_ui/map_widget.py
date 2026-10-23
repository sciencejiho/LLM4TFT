"""Compact, persistent roster controls for scouting other players."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class MapWidget(QFrame):
    """Show player health and immediately switch the board's scouting target."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.setObjectName("panel")
        self.setFixedWidth(175)
        layout = QVBoxLayout(self)
        title = QLabel("LOBBY ROSTER")
        title.setObjectName("eyebrow")
        layout.addWidget(title)
        self.buttons: list[QPushButton] = []
        for index in range(8):
            button = QPushButton()
            button.setObjectName("roster")
            button.clicked.connect(
                lambda checked=False, i=index: self.controller.set_view_player(i)
            )
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch()
        hint = QLabel("Click a player to scout.\nReturn to your board\nto make changes.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def update_state(self, data: list[dict[str, Any]]) -> None:
        """Refresh a bounded roster, including short lobbies and eliminated users."""
        if len(data) > 8:
            raise ValueError("Roster snapshot exceeds eight supported players")
        for index in range(8):
            button = self.buttons[index]
            button.setVisible(index < len(data))
            if index >= len(data):
                continue
            entry = data[index]
            player = self.controller.player_by_id(entry["id"])
            own = str(entry["id"]) == str(self.controller.player_id)
            name = player.get("name", str(entry["id"]))
            if player.get("is_bot"):
                name = f"Baseline {str(entry['id']).rsplit('-', 1)[-1]}"
            marker = "YOU" if own else f"#{index + 1}"
            button.setText(f"{marker}  {name[:16]}\n{max(0, entry['hp']):g} HP")
            selected = str(entry["id"]) == str(self.controller.view_player)
            button.setStyleSheet("border-color: #69c9c5; background: #204248;" if selected else "")
            button.setToolTip("Your board" if own else f"Scout {name}")
