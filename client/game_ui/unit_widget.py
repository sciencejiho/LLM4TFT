"""Selected-unit inspector exposing only mechanics implemented by the engine."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from .role_icon import role_icon
from .util import ROLE_COLORS, get_price, unit_details


class UnitWidget(QFrame):
    """Explain a unit's role, placement, scaled stats and available action."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.setObjectName("panel")
        self.setMinimumWidth(244)
        self.setMaximumWidth(290)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        title = QLabel("UNIT INSPECTOR")
        title.setObjectName("eyebrow")
        self.portrait = QLabel()
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label = QLabel()
        self.name_label.setObjectName("sectionTitle")
        self.name_label.setWordWrap(True)
        self.gold_label = QLabel()
        self.gold_label.setObjectName("muted")
        self.role_label = QLabel()
        self.role_label.setObjectName("heroRole")
        self.placement_label = QLabel()
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("muted")
        self.health_bar = QProgressBar()
        self.health_bar.setFixedHeight(18)
        self.health_bar.setFormat("%v / %m HP")
        self._build_stats()
        self.action_button = QPushButton("Select a unit")
        self.action_button.clicked.connect(self._action)
        for widget in (
            title,
            self.portrait,
            self.name_label,
            self.gold_label,
            self.role_label,
            self.placement_label,
            self.description_label,
            self.health_bar,
        ):
            layout.addWidget(widget)
        layout.addLayout(self.stats)
        layout.addStretch()
        layout.addWidget(self.action_button)
        self.update_state(None)

    def _build_stats(self) -> None:
        self.hp_label = QLabel()
        self.attack_label = QLabel()
        self.defense_label = QLabel()
        self.attack_speed_label = QLabel()
        self.attack_range_label = QLabel()
        self.critical_label = QLabel()
        self.stats = QGridLayout()
        labels = (
            self.hp_label,
            self.attack_label,
            self.defense_label,
            self.attack_speed_label,
            self.attack_range_label,
            self.critical_label,
        )
        for index in range(6):
            labels[index].setWordWrap(True)
            labels[index].setMinimumHeight(42)
            self.stats.addWidget(labels[index], index // 2, index % 2)

    def update_state(self, unit: dict[str, Any] | None) -> None:
        """Display a selected unit's actual current stats or a useful empty state."""
        self.unit = unit
        info = unit_details(unit)
        self.name_label.setText(info["name"] if unit else "Select a unit")
        self.gold_label.setText(
            f"{'★' * info['level']}   ·   {info['cost']} gold"
            if unit
            else "Click a board, bench or shop card"
        )
        role = info["role"]
        self.portrait.setPixmap(role_icon(role, 82).pixmap(82, 82))
        self.role_label.setText(role.title() if unit else "Understand your army")
        self.role_label.setStyleSheet(f"color: {ROLE_COLORS[role]};")
        placement = {
            "tank": "Front line",
            "fighter": "Front / middle line",
            "marksman": "Back line",
        }[role]
        self.placement_label.setText(
            f"Recommended placement · {placement}" if unit else "Roles guide your positioning"
        )
        self.placement_label.setWordWrap(True)
        self.description_label.setText(
            info.get(
                "role_description", "Select a unit to inspect its role, range and combat stats."
            )
        )
        self._update_stats(info["status"])
        self.refresh_action()

    def _update_stats(self, status: dict[str, Any]) -> None:
        maximum = max(1, int(status.get("max_hp", 0)))
        self.health_bar.setRange(0, maximum)
        self.health_bar.setValue(max(0, int(status.get("hp", 0))))
        self.health_bar.setVisible(self.unit is not None)
        self.hp_label.setText(f"HEALTH\n{status.get('max_hp', 0):g}")
        self.attack_label.setText(f"ATTACK\n{status.get('attack', 0):g}")
        self.defense_label.setText(f"ARMOR\n{status.get('defense', 0):g}")
        self.attack_speed_label.setText(f"ATTACK SPEED\n{status.get('attackSpeed', 0):.2f}")
        self.attack_range_label.setText(f"RANGE\n{status.get('attackRange', 0):g} cells")
        self.critical_label.setText(
            f"CRITICAL\n{status.get('criticalRate', 0):g}% · {status.get('criticalDamage', 1):g}×"
        )

    def refresh_action(self) -> None:
        """Recheck selection ownership and affordability after each state change."""
        selection = self.controller.selection
        enabled = self.unit is not None and selection is not None and self.controller.can_edit()
        if selection and selection[0] == "battle":
            self.action_button.setText("Combat unit · inspect only")
            self.action_button.setEnabled(False)
            return
        if not selection or not self.unit:
            self.action_button.setText("Select a unit")
        elif selection[0] == "shop":
            cost = unit_details(self.unit)["cost"]
            self.action_button.setText(f"Buy unit · {cost} gold")
            enabled = enabled and self.controller.can_buy(selection[1])
        else:
            self.action_button.setText(f"Sell unit · {get_price(self.unit)} gold")
        self.action_button.setEnabled(enabled)

    def _action(self) -> None:
        if not self.controller.selection:
            return
        source, index = self.controller.selection
        if source == "shop":
            self.controller.send_command("buy_unit", index)
        else:
            self.controller.send_command("sell_unit", source, index)
