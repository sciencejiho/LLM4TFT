"""Combat cards reuse the same presentation as preparation cards."""

from __future__ import annotations

from typing import Any

from .drag_widget import DraggableLabel


class BattleUnitWidget(DraggableLabel):
    """A non-draggable card retaining its live HP and role across battle ticks."""

    def __init__(self, parent: Any, index: int) -> None:
        super().__init__(parent, source="battle", index=index, dragable=False)
        self.setMinimumHeight(36)

    def update_state(self, unit: dict[str, Any] | None) -> None:
        """Refresh combat stats without replacing the button."""
        self.set_unit(unit)
