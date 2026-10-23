"""LLM4TFT desktop board, inspection, scouting and preparation controls."""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .baseWidget import BaseWidget
from .game_ui.bench_widget import BenchWidget
from .game_ui.field_widget import FieldWidget
from .game_ui.game_state_widget import GameStateWidget
from .game_ui.map_widget import MapWidget
from .game_ui.player_widget import PlayerWidget
from .game_ui.shop_widget import ShopWidget
from .game_ui.unit_widget import UnitWidget
from .game_ui.util import get_cost


class GameScreen(BaseWidget):
    """A persistent, role-oriented research and human-play interface.

    Parameters
    ----------
    parent : object
        Application controller exposing ``run_async`` and ``socket_thread``.
    """

    def __init__(self, parent: Any) -> None:
        super().__init__()
        self.controller = parent
        self.state: dict[str, Any] | None = None
        self.player_id: Any = None
        self.view_player: Any = None
        self.selection: tuple[str, int] | None = None
        self.current_player: dict[str, Any] = {}
        self._game_key: Any = None
        self._build_layout()

    def _build_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        header = QHBoxLayout()
        brand = QLabel("LLM4TFT")
        brand.setObjectName("title")
        subtitle = QLabel("RESEARCH WORKBENCH")
        subtitle.setObjectName("eyebrow")
        self.btn_quit = QPushButton("Leave match")
        self.btn_quit.setObjectName("quiet")
        self.btn_quit.clicked.connect(self.quit)
        header.addWidget(brand)
        header.addWidget(subtitle)
        header.addStretch()
        header.addWidget(self.btn_quit)
        outer.addLayout(header)
        content = QHBoxLayout()
        content.setSpacing(14)
        self.map_widget = MapWidget(self)
        content.addWidget(self.map_widget)
        center = QVBoxLayout()
        center.setSpacing(10)
        self.game_state_widget = GameStateWidget(self)
        center.addWidget(self.game_state_widget)
        board = QFrame()
        board.setObjectName("panel")
        board_layout = QVBoxLayout(board)
        self.context_label = QLabel("YOUR BOARD")
        self.context_label.setObjectName("sectionTitle")
        self.board_hint = QLabel("Front line  ·  Tanks & fighters")
        self.board_hint.setObjectName("muted")
        self.field_layout = FieldWidget(self)
        self.placement_hint = QLabel("Back line  ·  Keep marksmen behind your front line")
        self.placement_hint.setObjectName("muted")
        board_layout.addWidget(self.context_label)
        board_layout.addWidget(self.board_hint)
        board_layout.addWidget(self.field_layout, 1)
        board_layout.addWidget(self.placement_hint)
        center.addWidget(board, 1)
        center.addLayout(self._bench_section())
        self.player_layout = PlayerWidget(self)
        center.addWidget(self.player_layout)
        center.addLayout(self._shop_section())
        content.addLayout(center, 1)
        self.unit_widget = UnitWidget(self)
        content.addWidget(self.unit_widget)
        outer.addLayout(content, 1)
        footer = QLabel(
            "Click a unit to inspect  ·  Drag bench ↔ board to position  ·  Drag a unit to the shop to sell  ·  Three copies combine into a stronger unit"
        )
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        outer.addWidget(footer)
        self.refresh_style()

    def _bench_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        heading = QHBoxLayout()
        title = QLabel("BENCH")
        title.setObjectName("eyebrow")
        hint = QLabel("Reserves · drag onto the board")
        hint.setObjectName("muted")
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(hint)
        self.bench_layout = BenchWidget(self)
        self.bench_layout.setFixedHeight(82)
        layout.addLayout(heading)
        layout.addWidget(self.bench_layout)
        return layout

    def _shop_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        controls = QHBoxLayout()
        title = QLabel("RECRUIT UNITS")
        title.setObjectName("eyebrow")
        self.btn_exp = QPushButton("Buy 4 XP · 4 gold")
        self.btn_reroll = QPushButton("Reroll · 2 gold")
        self.btn_combat = QPushButton("Start combat  →")
        self.btn_combat.setObjectName("primary")
        self.btn_exp.clicked.connect(lambda: self.send_command("buy_exp"))
        self.btn_reroll.clicked.connect(lambda: self.send_command("reroll"))
        self.btn_combat.clicked.connect(lambda: self.send_command("advance_round"))
        controls.addWidget(title)
        controls.addStretch()
        controls.addWidget(self.btn_exp)
        controls.addWidget(self.btn_reroll)
        controls.addWidget(self.btn_combat)
        self.shop_layout = ShopWidget(self)
        self.shop_layout.setFixedHeight(144)
        layout.addLayout(controls)
        layout.addWidget(self.shop_layout)
        return layout

    def update_state(self, data: dict[str, Any]) -> None:
        """Apply a game snapshot, resetting stale scouting when a match changes."""
        if not data or not data.get("player") or not data.get("game"):
            return
        own = data["player"]
        game_key = data["game"].get("id", data.get("game_id"))
        new_match = self.player_id != own["id"] or game_key != self._game_key
        if self.state:
            previous_round = self.state["game"]["state"].get("round", 0)
            new_match = new_match or data["game"]["state"].get("round", 0) < previous_round
        if new_match or self.view_player is None:
            self.view_player = own["id"]
            self.selection = None
        self.player_id = own["id"]
        self._game_key = game_key
        self.state = data
        if not self.player_by_id(self.view_player):
            self.view_player = self.player_id
            self.selection = None
        self._render_state()

    def player_by_id(self, player_id: Any) -> dict[str, Any]:
        """Resolve IDs consistently across JSON string keys and list snapshots."""
        if not self.state:
            return {}
        if str(player_id) == str(self.state["player"]["id"]):
            return dict(self.state["player"])
        players = self.state["game"].get("players", {})
        if isinstance(players, dict):
            return dict(players.get(player_id, players.get(str(player_id), {})) or {})
        return next(
            (dict(player) for player in players[:8] if str(player["id"]) == str(player_id)), {}
        )

    def can_edit(self) -> bool:
        """Return whether this is the local living player's preparation board."""
        if not self.state:
            return False
        own = self.state["player"]
        return (
            str(self.view_player) == str(self.player_id)
            and own.get("hp", 0) > 0
            and own.get("active", True)
            and self.state["game"]["state"].get("current_state") == "READY"
        )

    def _render_state(self) -> None:
        if not self.state:
            return
        game = self.state["game"]
        player = self.player_by_id(self.view_player)
        self.current_player = player
        phase = game["state"].get("current_state", "READY")
        self.game_state_widget.update_state(game["state"])
        self.field_layout.set_game_state(phase)
        self.field_layout.update_state(player.get("field", {}))
        self.field_layout.update_battle(self._battle_for_player())
        self.bench_layout.update_state(player.get("bench", {}))
        self.shop_layout.update_state(player.get("shop", {}))
        self.player_layout.update_state(player)
        self.map_widget.update_state(game.get("rank", []))
        field = player.get("field", {})
        count = sum(unit is not None for unit in field.get("units", [])[:28])
        label = (
            "YOUR BOARD"
            if str(self.view_player) == str(self.player_id)
            else f"SCOUTING · {player.get('name', self.view_player)}"
        )
        if self.state["player"].get("hp", 0) <= 0:
            label = "Eliminated · scout the remaining players"
        self.context_label.setText(f"{label}     {count} / {field.get('max_units', 0)} units")
        self.board_hint.setText(
            "COMBAT ARENA · enemy above / your army below"
            if phase == "BATTLE"
            else "Front line  ·  Tanks & fighters"
        )
        self.placement_hint.setVisible(phase != "BATTLE")
        editable = self.can_edit()
        gold = player.get("gold", 0)
        self.btn_reroll.setEnabled(editable and gold >= 2)
        self.btn_exp.setEnabled(editable and gold >= 4 and player.get("level", 1) < 10)
        legal = player.get("legal_actions", {})
        self.btn_reroll.setEnabled(self.btn_reroll.isEnabled() and legal.get("reroll", True))
        self.btn_exp.setEnabled(self.btn_exp.isEnabled() and legal.get("buy_exp", True))
        self.btn_combat.setEnabled(editable and game["state"].get("decision_mode", False))
        self.btn_combat.setText(
            {"READY": "Start combat  →", "BATTLE": "Combat in progress"}.get(phase, "Match ended")
        )
        self.btn_combat.setToolTip(
            "Finish preparation and start the next combat"
            if game["state"].get("decision_mode")
            else "Timed matches advance automatically"
        )
        self._render_selection()

    def _battle_for_player(self) -> dict[str, Any] | None:
        if not self.state:
            return None
        battles = self.state["game"].get("battle", {})
        if isinstance(battles, dict):
            return battles.get(self.view_player, battles.get(str(self.view_player)))
        players = self.state["game"].get("players", [])
        if isinstance(players, list):
            index = next(
                (
                    i
                    for i, player in enumerate(players[:8])
                    if str(player["id"]) == str(self.view_player)
                ),
                -1,
            )
            return battles[index] if 0 <= index < len(battles) else None
        return None

    def set_view_player(self, index: int) -> None:
        """Immediately scout the player at a roster rank, preserving the snapshot."""
        if not self.state or not 0 <= index < len(self.state["game"].get("rank", [])):
            return
        self.view_player = self.state["game"]["rank"][index]["id"]
        self.selection = None
        self._render_state()

    def view_unit(self, where: str, index: int) -> None:
        """Select a unit from the displayed player's board, bench or shop."""
        if where not in ("field", "bench", "shop", "battle"):
            return
        self.selection = (where, index)
        self._render_selection()

    def _render_selection(self) -> None:
        unit = None
        if self.selection:
            source, index = self.selection
            units = self.current_player.get(source, {}).get("units", [])
            unit = units[index] if 0 <= index < len(units) else None
            if source == "battle" and 0 <= index < 56:
                unit = self.field_layout.battle_page.unit_buttons[index].unit
        for zone in (self.field_layout.field_page, self.bench_layout, self.shop_layout):
            for index in range(28):
                if index >= len(zone.buttons):
                    break
                button = zone.buttons[index]
                button.selected = self.selection == (button.source, index)
                button.update()
        for index in range(56):
            button = self.field_layout.battle_page.unit_buttons[index]
            button.selected = self.selection == ("battle", index)
            button.update()
        self.unit_widget.update_state(unit)

    def send_command(self, action: str, *args: Any) -> Any:
        """Send an allowed command through the application's existing async bridge."""
        if action != "quit_game" and not self.can_edit():
            return None
        if action == "advance_round" and not self.btn_combat.isEnabled():
            return None
        if action in ("reroll", "buy_exp"):
            cost = 2 if action == "reroll" else 4
            if self.current_player.get("gold", 0) < cost:
                return None
            if not self.current_player.get("legal_actions", {}).get(action, True):
                return None
            if action == "buy_exp" and self.current_player.get("level", 1) >= 10:
                return None
        if action == "buy_unit" and not self._can_buy(args):
            return None
        return self.controller.run_async(self.controller.socket_thread.send_command(action, args))

    def _can_buy(self, args: tuple[Any, ...]) -> bool:
        return bool(args) and type(args[0]) is int and self.can_buy(args[0])

    def can_buy(self, index: int) -> bool:
        """Check affordability and bench room, retaining purchases that merge copies."""
        units = self.current_player.get("shop", {}).get("units", [])
        if not self.can_edit() or not 0 <= index < len(units):
            return False
        unit = units[index]
        if unit is None or self.current_player.get("gold", 0) < get_cost(unit):
            return False
        legal = self.current_player.get("legal_actions", {})
        if "buy_unit" in legal:
            return index in legal["buy_unit"]
        bench = self.current_player.get("bench", {}).get("units", [])[:9]
        if len(bench) < 9 or None in bench:
            return True
        owned = bench + self.current_player.get("field", {}).get("units", [])[:28]
        copies = sum(
            candidate is not None
            and candidate.get("id") == unit.get("id")
            and candidate.get("level", 1) == unit.get("level", 1)
            for candidate in owned
        )
        return copies >= 2

    def refresh_style(self) -> None:
        """Preserve the public drag-refresh hook with the shared persistent theme."""
        self.update()

    def quit(self) -> None:
        """Leave the current game, clear selection and return to the home screen."""
        self.send_command("quit_game")
        self.state = None
        self.selection = None
        self.view_player = None
        self.unit_widget.update_state(None)
        self.controller.socket_thread.state["game"] = {}
        self.controller.stacked_widget.setCurrentWidget(self.controller.home_screen)
