"""Preparation board and combat arena share an explicit phase switch."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from .battle_widget import BattleWidget
from .zone_widget import UnitZone


class FieldWidget(QWidget):
    """Retain preparation and battle widgets throughout a session."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.field_page = UnitZone(parent, "field", 28, 7)
        self.unit_buttons = self.field_page.buttons
        self.battle_page = BattleWidget(parent)
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(self.field_page)
        self.stacked_widget.addWidget(self.battle_page)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked_widget)

    def set_game_state(self, game_state: str) -> None:
        """Switch safely between preparation, battle and terminal phases."""
        self.stacked_widget.setCurrentWidget(
            self.battle_page if game_state == "BATTLE" else self.field_page
        )

    def update_state(self, data: dict[str, Any]) -> None:
        """Update the persistent preparation grid."""
        self.field_page.update_state(data)

    def update_battle(self, data: dict[str, Any] | None) -> None:
        """Update the persistent live combat grid."""
        self.battle_page.update_state(data)
