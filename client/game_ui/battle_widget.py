"""An eight-by-seven combat arena with a fixed widget population."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from .battle_unit_widget import BattleUnitWidget


class BattleWidget(QWidget):
    """Show either team's perspective using 56 persistent card widgets."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.unit_layout = QGridLayout(self)
        self.unit_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_layout.setSpacing(4)
        self.unit_buttons: list[BattleUnitWidget] = []
        for index in range(56):
            button = BattleUnitWidget(self, index)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            button.clicked.connect(lambda checked=False, i=index: self._select(i))
            self.unit_layout.addWidget(button, index // 7, index % 7)
            self.unit_buttons.append(button)

    def _select(self, index: int) -> None:
        self.controller.view_unit("battle", index)

    def update_state(self, data: dict[str, Any] | None) -> None:
        """Map an arena snapshot to reusable cards, including an empty snapshot."""
        units: list[dict[str, Any] | None] = [None] * 56
        if data:
            if len(data.get("arena", [])) > 56:
                raise ValueError("Combat snapshot exceeds the 56-slot arena")
            for item in data.get("arena", [])[:56]:
                row, col = item["pos"]
                if not 0 <= row < 8 or not 0 <= col < 7:
                    continue
                row, col = (7 - row, col) if data.get("team") == "home" else (row, 6 - col)
                unit = dict(item["unit"])
                own_team = data.get("team", "home")
                unit["team"] = "home" if unit.get("team", own_team) == own_team else "away"
                units[row * 7 + col] = unit
        for index in range(56):
            self.unit_buttons[index].update_state(units[index])
