"""Shop offers expose inspection and explicit affordable purchase actions."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .drag_widget import DraggableLabel
from .util import get_cost


class ShopWidget(QWidget):
    """Five persistent shop offers and purchase buttons."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.buttons: list[DraggableLabel] = []
        self.buy_buttons: list[QPushButton] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for index in range(5):
            column = QVBoxLayout()
            card = DraggableLabel(self, source="shop", index=index)
            card.clicked.connect(lambda checked=False, i=index: parent.view_unit("shop", i))
            purchase = QPushButton("Buy")
            purchase.clicked.connect(
                lambda checked=False, i=index: parent.send_command("buy_unit", i)
            )
            column.addWidget(card, 1)
            column.addWidget(purchase)
            layout.addLayout(column, 1)
            self.buttons.append(card)
            self.buy_buttons.append(purchase)

    def update_state(self, data: dict[str, Any]) -> None:
        """Refresh offers with ownership, preparation and gold checks."""
        units = data.get("units", [])
        for index in range(5):
            unit = units[index] if index < len(units) else None
            affordable = self.controller.can_buy(index)
            self.buttons[index].set_unit(unit, self.controller.can_edit() and affordable)
            self.buy_buttons[index].setText(f"Buy · {get_cost(unit)} gold" if unit else "Sold")
            self.buy_buttons[index].setEnabled(self.controller.can_edit() and affordable)

    def dropped(self, data: dict[str, Any]) -> None:
        """Sell an owned unit dropped onto a shop offer."""
        if data["source"] in ("field", "bench"):
            self.controller.send_command("sell_unit", data["source"], data["index"])
