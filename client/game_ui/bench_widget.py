"""Nine persistent reserve slots."""

from typing import Any

from .zone_widget import UnitZone


class BenchWidget(UnitZone):
    """Display and rearrange units held in reserve."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "bench", 9, 9)
