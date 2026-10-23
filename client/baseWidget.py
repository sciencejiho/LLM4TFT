"""Shared desktop theme loading independent of the caller's working directory."""
# ruff: noqa: N999 -- preserve the existing client.baseWidget import interface.

from pathlib import Path

from PyQt6.QtWidgets import QWidget


class BaseWidget(QWidget):
    """Base presentation widget with the LLM4TFT desktop theme."""

    def __init__(self, stylesheet_path: str = "client/styles.qss") -> None:
        super().__init__()
        self.load_stylesheet(stylesheet_path)

    def load_stylesheet(self, file_path: str) -> None:
        """Load a repository-relative stylesheet and propagate real read failures."""
        path = Path(__file__).resolve().parent.parent / file_path
        self.setStyleSheet(path.read_text(encoding="utf-8"))
