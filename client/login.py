"""Player identification before entering the local research workbench."""

import re
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .baseWidget import BaseWidget


class LoginScreen(BaseWidget):
    """A clear entry point that reports connection and username requirements."""

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card = QFrame()
        card.setObjectName("panel")
        card.setFixedWidth(460)
        form = QVBoxLayout(card)
        form.setContentsMargins(36, 36, 36, 36)
        form.setSpacing(18)
        eyebrow = QLabel("AUTOBATTLER RESEARCH WORKBENCH")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("LLM4TFT")
        title.setObjectName("title")
        description = QLabel(
            "Build an army. Study each decision.\nPosition units and watch your strategy unfold."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Player name, e.g. Research_User")
        self.username_input.setMaxLength(64)
        self.username_input.returnPressed.connect(self.login)
        self.login_button = QPushButton("Enter workbench  →")
        self.login_button.setObjectName("primary")
        self.login_button.clicked.connect(self.login)
        self.message_label = QLabel("Choose a name to enter the local lobby.")
        self.message_label.setObjectName("muted")
        self.message_label.setWordWrap(True)
        for widget in (
            eyebrow,
            title,
            description,
            self.username_input,
            self.login_button,
            self.message_label,
        ):
            form.addWidget(widget)
        layout.addWidget(card)

    def login(self) -> None:
        """Submit a non-empty name once the application's socket is connected."""
        username = self.username_input.text().strip()
        if not username:
            self.message_label.setText("Enter a player name to continue.")
            return
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username) or username in (".", ".."):
            self.message_label.setText(
                "Use 1–64 letters, digits, underscores, dots or hyphens. Spaces and the names '.' and '..' are unavailable."
            )
            return
        if not self.controller.socket_thread.sio.connected:
            self.message_label.setText(
                "Waiting for the server connection. Try again when connected."
            )
            return
        self.controller.run_async(self.controller.socket_thread.send_command("login", username))
        self.message_label.setText("Signing in… Waiting for the server to confirm your name.")
