"""Persistent preparation slots and command routing shared by board zones."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QGridLayout, QSizePolicy, QWidget

from .drag_widget import DraggableLabel


class UnitZone(QWidget):
    """Keep a bounded set of inspectable, draggable slots for one location."""

    def __init__(self, parent: Any, source: str, count: int, columns: int) -> None:
        super().__init__()
        if not 1 <= count <= 28 or not 1 <= columns <= 9:
            raise ValueError("Preparation zones require 1–28 slots and 1–9 columns")
        self.controller = parent
        self.source = source
        self.unit_layout = QGridLayout(self)
        self.unit_layout.setContentsMargins(0, 0, 0, 0)
        self.unit_layout.setSpacing(5)
        self.buttons: list[DraggableLabel] = []
        for index in range(28):
            if index >= count:
                break
            button = DraggableLabel(self, source=source, index=index)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            button.clicked.connect(
                lambda checked=False, i=index: self.controller.view_unit(self.source, i)
            )
            row = (3 - index // 7) if source == "field" else index // columns
            self.unit_layout.addWidget(button, row, index % columns)
            self.buttons.append(button)
        self.unit_buttons = self.buttons

    def update_state(self, data: dict[str, Any]) -> None:
        """Refresh all zone slots and their editability in place."""
        units = data.get("units", [])
        for index in range(28):
            if index >= len(self.buttons):
                break
            unit = units[index] if index < len(units) else None
            self.buttons[index].set_unit(unit, self.controller.can_edit())

    def dropped(self, data: dict[str, Any]) -> None:
        """Route a validated card drag to the existing engine command contract."""
        if data["source"] == "shop":
            self.controller.send_command("buy_unit", data["index"])
        else:
            self.controller.send_command(
                "move_unit", data["source"], self.source, data["index"], data["target_index"]
            )
