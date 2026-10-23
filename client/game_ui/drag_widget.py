"""Persistent unit cards with safe drag payloads and role artwork."""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import QByteArray, QMimeData, QPoint, QRect, Qt
from PyQt6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication, QPushButton

from .role_icon import role_icon
from .util import ROLE_COLORS, get_color, unit_details


class DraggableLabel(QPushButton):
    """Paint a reusable unit card and route validated drags to its owning zone."""

    def __init__(
        self,
        parent: Any,
        text: str = "",
        source: str = "bench",
        index: int = -1,
        dragable: bool = True,
    ) -> None:
        super().__init__(text)
        self.owner = parent
        self.source = source
        self.index = index
        self.dragable = dragable
        self.unit: dict[str, Any] | None = None
        self.selected = False
        self.shop = source == "shop"
        self._origin = QPoint()
        self._info = unit_details(None)
        self._icon = role_icon("fighter")
        self.setObjectName("unitCard")
        self.setMinimumSize(58, 68 if not self.shop else 100)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_unit(self, unit: dict[str, Any] | None, editable: bool = False) -> None:
        """Update card content in place, retaining widget and signal identities."""
        if unit != self.unit:
            self.unit = unit
            self._info = unit_details(unit)
            self._icon = role_icon(self._info["role"])
        self.dragable = editable and unit is not None
        self.setToolTip(self._tooltip() if unit else "Empty slot — drag a unit here")
        self.setAccessibleName(
            self._tooltip() if unit else f"Empty {self.source} slot {self.index + 1}"
        )
        self.update()

    def _tooltip(self) -> str:
        info = self._info
        status = info["status"]
        return (
            f"{info['name']} · {info['role'].title()} · {info['level']} star\n"
            f"{info['cost']} gold · HP {status.get('max_hp', 0):g} · "
            f"ATK {status.get('attack', 0):g} · Range {status.get('attackRange', 0):g}"
        )

    def paintEvent(self, event: QPaintEvent | None) -> None:
        """Draw a cost rim, role emblem, unit name, stars and combat HP."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(1, 1, -1, -1)
        color = "#142b38" if self.unit else "#122331"
        accent = get_color(self.unit)[0] if self.unit else "#294052"
        if self.selected:
            accent = "#f1ce83"
        painter.setBrush(QColor("#254653" if self.underMouse() else color))
        painter.setPen(QPen(QColor(accent), 2 if self.selected else 1))
        painter.drawRoundedRect(bounds, 6, 6)
        if not self.unit:
            painter.setPen(QColor("#385365"))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "·")
            return
        self._paint_content(painter)

    def _paint_content(self, painter: QPainter) -> None:
        info = self._info
        width, height = self.width(), self.height()
        if height < 70:
            self._paint_compact(painter)
            return
        painter.setPen(QColor("#e9c77c"))
        painter.setFont(QFont("DejaVu Sans", 8))
        painter.drawText(
            QRect(6, 4, width - 12, 14), Qt.AlignmentFlag.AlignLeft, "★" * info["level"]
        )
        painter.drawText(
            QRect(6, 4, width - 12, 14), Qt.AlignmentFlag.AlignRight, str(info["cost"])
        )
        icon_size = min(30 if self.shop else 25, max(18, height - 50))
        self._icon.paint(painter, (width - icon_size) // 2, 17, icon_size, icon_size)
        painter.setPen(QColor("#e2edf0"))
        painter.setFont(QFont("DejaVu Sans", 8, QFont.Weight.DemiBold))
        name = painter.fontMetrics().elidedText(
            str(info["name"]), Qt.TextElideMode.ElideRight, width - 8
        )
        painter.drawText(
            QRect(4, 19 + icon_size, width - 8, 16), Qt.AlignmentFlag.AlignCenter, name
        )
        painter.setFont(QFont("DejaVu Sans", 7))
        painter.setPen(QColor(ROLE_COLORS[info["role"]]))
        painter.drawText(
            QRect(3, 34 + icon_size, width - 6, 14),
            Qt.AlignmentFlag.AlignCenter,
            info["role"].title(),
        )
        status = info["status"]
        ratio = min(1.0, max(0.0, status.get("hp", 0) / max(1, status.get("max_hp", 1))))
        painter.fillRect(7, height - 7, width - 14, 3, QColor("#0b1720"))
        painter.fillRect(
            7,
            height - 7,
            int((width - 14) * ratio),
            3,
            QColor("#dc8076" if self.unit and self.unit.get("team") == "away" else "#58c7a3"),
        )

    def _paint_compact(self, painter: QPainter) -> None:
        info = self._info
        width, height = self.width(), self.height()
        self._icon.paint(painter, 5, max(4, (height - 25) // 2), 22, 22)
        painter.setPen(QColor("#e2edf0"))
        painter.setFont(QFont("DejaVu Sans", 7, QFont.Weight.DemiBold))
        name = painter.fontMetrics().elidedText(
            str(info["name"]), Qt.TextElideMode.ElideRight, width - 37
        )
        painter.drawText(QRect(31, 5, width - 35, 13), Qt.AlignmentFlag.AlignLeft, name)
        painter.setPen(QColor(ROLE_COLORS[info["role"]]))
        painter.setFont(QFont("DejaVu Sans", 6))
        painter.drawText(
            QRect(31, 18, width - 35, 12),
            Qt.AlignmentFlag.AlignLeft,
            f"{info['role'].title()} {'★' * info['level']}",
        )
        status = info["status"]
        ratio = min(1.0, max(0.0, status.get("hp", 0) / max(1, status.get("max_hp", 1))))
        painter.fillRect(6, height - 5, width - 12, 3, QColor("#0b1720"))
        team = (self.unit or {}).get("team")
        painter.fillRect(
            6,
            height - 5,
            int((width - 12) * ratio),
            3,
            QColor("#dc8076" if team == "away" else "#58c7a3"),
        )

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        """Remember the press position so simple selection does not start a drag."""
        if event is None:
            return
        self._origin = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        """Start a drag only after the desktop's standard movement threshold."""
        if event is None:
            return
        distance = (event.position().toPoint() - self._origin).manhattanLength()
        if event.buttons() != Qt.MouseButton.LeftButton or not self.dragable:
            return
        if distance < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(
            "application/json",
            QByteArray(json.dumps({"source": self.source, "index": self.index}).encode()),
        )
        drag.setMimeData(mime)
        drag.setPixmap(self.create_drag_pixmap())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.DropAction.MoveAction)

    def create_drag_pixmap(self) -> QPixmap:
        """Return the rendered card as a drag preview."""
        return self.grab()

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        """Accept only application-owned unit drag payloads."""
        if event is None:
            return
        mime = event.mimeData()
        if mime and mime.hasFormat("application/json"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent | None) -> None:
        """Validate an incoming payload before sending a move or sale."""
        if event is None:
            return
        mime = event.mimeData()
        if mime is None:
            event.ignore()
            return
        try:
            data = json.loads(mime.data("application/json").data())
        except (ValueError, UnicodeDecodeError):
            event.ignore()
            return
        if not isinstance(data, dict) or data.get("source") not in ("shop", "field", "bench"):
            event.ignore()
            return
        if type(data.get("index")) is not int or not 0 <= data["index"] < 28:
            event.ignore()
            return
        data["target_index"] = self.index
        self.owner.dropped(data)
        event.acceptProposedAction()
