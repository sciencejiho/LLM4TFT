"""Readable player progression and economy details."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class PlayerWidget(QFrame):
    """Show gold, level, HP and source-backed income projections."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.setObjectName("panel")
        layout = QHBoxLayout(self)
        self.gold_label = QLabel("0 gold")
        self.gold_label.setObjectName("gold")
        self.level_label = QLabel()
        self.level_label.setObjectName("sectionTitle")
        self.exp_label = QLabel()
        self.hp_label = QLabel()
        self.income_label = QLabel()
        self.income_label.setWordWrap(True)
        self.income_label.setObjectName("muted")
        self.unit_rate_label = QLabel()
        self.unit_rate_label.setObjectName("muted")
        self.interest_label = QLabel()
        self.interest_label.setObjectName("muted")
        progression = QVBoxLayout()
        progression.addWidget(self.level_label)
        progression.addWidget(self.exp_label)
        income = QVBoxLayout()
        income.addWidget(self.income_label)
        income.addWidget(self.unit_rate_label)
        income.addWidget(self.interest_label)
        layout.addWidget(self.gold_label)
        layout.addLayout(progression)
        layout.addWidget(self.hp_label)
        layout.addLayout(income, 1)

    def update_state(self, data: dict[str, Any]) -> None:
        """Render authoritative income, falling back without inventing values."""
        self.gold_label.setText(f"{data.get('gold', 0)} gold")
        self.level_label.setText(f"LEVEL {data.get('level', 1)}")
        self.exp_label.setText(f"{data.get('exp', 0)} / {data.get('req_exp', '—')} XP")
        self.hp_label.setText(f"{max(0, data.get('hp', 0)):g} HP")
        economy = data.get("economy")
        if economy:
            self.income_label.setText(
                f"Next income +{economy['total']}   =   Base {economy['base']}"
                f"  +  Interest {economy['interest']}  +  Streak {economy['streak']}"
            )
        else:
            self.income_label.setText("Income breakdown unavailable on this server")
        interest_hint = (
            "Interest capped at +5"
            if economy and economy["interest"] >= 5
            else f"Next interest at {economy.get('next_interest', '—')} gold"
            if economy
            else ""
        )
        self.interest_label.setText(interest_hint)
        rates = data.get("unit_rate", [])[:5]
        odds = "  ·  ".join(f"{index + 1}g {int(rate * 100)}%" for index, rate in enumerate(rates))
        self.unit_rate_label.setText(f"Shop odds  {odds}")
