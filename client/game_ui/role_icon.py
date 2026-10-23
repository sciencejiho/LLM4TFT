"""Original vector role emblems, drawn without external artwork."""

from functools import lru_cache

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from .util import ROLE_COLORS


@lru_cache(maxsize=12)
def role_icon(role: str, size: int = 40) -> QIcon:
    """Draw a shield, crossed blades, or a ranged targeting emblem."""
    if not 12 <= size <= 256:
        raise ValueError("Role emblem size must be between 12 and 256 pixels")
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 40, size / 40)
    color = QColor(ROLE_COLORS.get(role, "#ac9fea"))
    painter.setPen(QPen(color, 2))
    painter.setBrush(QColor(color.red(), color.green(), color.blue(), 25))
    if role == "tank":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(8, 7),
                    QPointF(20, 3),
                    QPointF(32, 7),
                    QPointF(30, 25),
                    QPointF(20, 36),
                    QPointF(10, 25),
                ]
            )
        )
        painter.drawLine(20, 11, 20, 27)
        painter.drawLine(14, 18, 26, 18)
    elif role == "fighter":
        painter.drawLine(9, 33, 31, 7)
        painter.drawLine(7, 7, 31, 33)
        painter.drawLine(7, 25, 16, 33)
        painter.drawLine(24, 33, 33, 25)
        painter.drawLine(25, 7, 31, 7)
        painter.drawLine(31, 7, 31, 14)
    else:
        painter.drawEllipse(9, 9, 22, 22)
        painter.drawLine(20, 3, 20, 14)
        painter.drawLine(20, 26, 20, 37)
        painter.drawLine(3, 20, 14, 20)
        painter.drawLine(26, 20, 37, 20)
        painter.drawEllipse(18, 18, 4, 4)
    painter.end()
    return QIcon(pixmap)
