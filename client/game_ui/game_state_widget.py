"""Round and phase presentation for timed and decision-based matches."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget


class GameStateWidget(QWidget):
    """Present readable stage, phase and remaining planning time."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.round_label = QLabel("ROUND 01")
        self.round_label.setObjectName("sectionTitle")
        self.state_label = QLabel("Preparation")
        self.state_label.setObjectName("eyebrow")
        self.state_timer = QProgressBar()
        self.state_timer.setFixedWidth(170)
        self.state_timer.setFixedHeight(18)
        layout.addWidget(self.round_label)
        layout.addWidget(self.state_label)
        layout.addStretch()
        layout.addWidget(self.state_timer)

    def update_state(self, data: dict[str, Any]) -> None:
        """Update round and timer without implying a timer in decision mode."""
        phase = data.get("current_state", "READY")
        profile = str(data.get("ruleset", "legacy")).upper()
        self.round_label.setText(f"ROUND {int(data.get('round', 0)) + 1:02d} · {profile}")
        self.state_label.setText(
            {"READY": "PREPARATION", "BATTLE": "COMBAT"}.get(phase, phase.title())
        )
        decision = data.get("decision_mode", False) and phase == "READY"
        duration = max(1, int(data.get("state_time", 1)))
        remaining = max(0, duration - int(data.get("time", 0)))
        self.state_timer.setRange(0, duration)
        self.state_timer.setValue(duration if decision else remaining)
        self.state_timer.setFormat("Plan at your pace" if decision else f"{remaining}s remaining")
