"""Offscreen interaction regressions for the desktop research client."""

import copy
import os
from collections.abc import Iterator
from types import SimpleNamespace

# quality: ignore[PY001] - select offscreen Qt before importing Qt in GUI tests
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

from client.game import GameScreen
from client.game_ui.util import unit_details


@pytest.fixture(scope="module")
def application() -> QApplication:
    """Keep the offscreen Qt application alive across UI examples."""
    return QApplication.instance() or QApplication([])


def _sample_unit(name="IRON GUARD", role="tank"):
    return {
        "id": "unit_1",
        "name": name,
        "level": 2,
        "cost": 2,
        "role": role,
        "role_description": "Absorbs damage on the front line.",
        "status": {
            "hp": 950,
            "max_hp": 950,
            "attack": 80,
            "defense": 45,
            "attackSpeed": 0.8,
            "attackRange": 1,
            "criticalRate": 25,
            "criticalDamage": 1.5,
        },
    }


def _sample_state():
    own = {
        "id": 0,
        "name": "Researcher",
        "hp": 100,
        "level": 4,
        "gold": 23,
        "exp": 2,
        "req_exp": 10,
        "streak": 2,
        "unit_rate": [0.55, 0.30, 0.15, 0, 0],
        "economy": {"base": 5, "interest": 2, "streak": 1, "total": 8, "next_interest": 30},
        "field": {"max_units": 4, "units": [_sample_unit()] + [None] * 27},
        "bench": {"units": [_sample_unit("BRAWLER", "fighter")] + [None] * 8},
        "shop": {"units": [_sample_unit("RANGER", "marksman")] + [None] * 4},
    }
    other = copy.deepcopy(own)
    other.update(id=1, name="Baseline", hp=87)
    other["field"]["units"][0] = _sample_unit("SCOUTED RANGER", "marksman")
    return {
        "player": own,
        "game": {
            "id": "game-a",
            "players": [own, other],
            "rank": [own, other],
            "battle": [None, None],
            "state": {
                "current_state": "READY",
                "round": 2,
                "time": 0,
                "state_time": 30,
                "decision_mode": True,
                "ruleset": "research",
            },
        },
    }


@pytest.fixture
def screen(application: QApplication) -> Iterator[GameScreen]:
    """Provide a populated, isolated game screen and release it afterward."""
    sent = []
    socket = SimpleNamespace(send_command=lambda action, args: (action, args), state={"game": {}})
    parent = SimpleNamespace(socket_thread=socket, run_async=sent.append)
    widget = GameScreen(parent)
    widget._test_sent = sent
    widget.update_state(_sample_state())
    yield widget
    widget.close()


def test_roles_and_scaled_inspector(screen):
    screen.view_unit("field", 0)
    assert "Tank" in screen.unit_widget.role_label.text()
    assert "950" in screen.unit_widget.hp_label.text()
    assert "45" in screen.unit_widget.defense_label.text()
    assert "Front" in screen.unit_widget.placement_label.text()
    assert unit_details({"id": "missing", "level": 1})["name"] == "Unknown unit"


def test_scout_selection_and_immediate_return(screen):
    screen.set_view_player(1)
    screen.view_unit("field", 0)
    assert "SCOUTED RANGER" in screen.unit_widget.name_label.text()
    assert not screen.btn_reroll.isEnabled()
    screen.set_view_player(0)
    assert screen.btn_reroll.isEnabled()


def test_phase_control_and_affordability(screen):
    assert screen.btn_combat.isEnabled()
    screen.btn_combat.click()
    assert screen._test_sent[-1] == ("advance_round", ())
    state = _sample_state()
    state["game"]["state"]["current_state"] = "BATTLE"
    screen.update_state(state)
    assert not screen.btn_combat.isEnabled()
    assert not screen.btn_reroll.isEnabled()
    assert screen.field_layout.stacked_widget.currentWidget() is screen.field_layout.battle_page
    state["game"]["state"]["current_state"] = "READY"
    state["player"]["gold"] = 0
    screen.update_state(state)
    assert not screen.btn_exp.isEnabled()
    assert not screen.shop_layout.buy_buttons[0].isEnabled()
    assert screen.field_layout.stacked_widget.currentWidget() is screen.field_layout.field_page


def test_battle_reuses_widgets_and_empty_state(screen):
    battle = screen.field_layout.battle_page
    before = tuple(battle.unit_buttons)
    state = _sample_state()
    state["game"]["state"]["current_state"] = "BATTLE"
    state["game"]["battle"][0] = {
        "team": "home",
        "arena": [{"unit": _sample_unit(), "pos": [0, 0]}],
    }
    screen.update_state(state)
    screen.update_state(copy.deepcopy(state))
    assert tuple(battle.unit_buttons) == before
    assert len(before) == 56
    assert len(battle.findChildren(QPushButton)) == 56
    state["game"]["battle"][0] = None
    screen.update_state(state)
    assert all(card.unit is None for card in before)


def test_new_game_and_elimination_clear_stale_selection(screen):
    screen.set_view_player(1)
    screen.view_unit("field", 0)
    state = _sample_state()
    state["game"]["id"] = "game-b"
    state["player"]["id"] = 7
    state["game"]["players"][0]["id"] = 7
    screen.update_state(state)
    assert screen.player_id == 7
    assert screen.view_player == 7
    state["player"]["hp"] = 0
    screen.update_state(state)
    assert not screen.btn_combat.isEnabled()
    assert "Eliminated" in screen.context_label.text()


def test_legacy_metadata_scales_only_hp_and_attack():
    one = unit_details({"id": "unit_1", "level": 1})
    two = unit_details({"id": "unit_1", "level": 2})
    assert two["status"]["hp"] == int(one["status"]["hp"] * 1.8)
    assert two["status"]["attack"] == int(one["status"]["attack"] * 1.8)
    assert two["status"]["defense"] == one["status"]["defense"]
    assert two["role"] == "tank"
    assert unit_details({"id": "unit_2", "level": 1})["role"] == "marksman"


def test_real_json_mapping_ids_and_late_actions(screen):
    state = _sample_state()
    own = state["player"]
    own["id"] = "researcher"
    other = state["game"]["players"][1]
    other["id"] = "baseline"
    state["game"]["players"] = {"researcher": own, "baseline": other}
    state["game"]["battle"] = {"researcher": None, "baseline": None}
    screen.update_state(state)
    screen.set_view_player(1)
    screen.send_command("reroll")
    screen.send_command("buy_unit", 0)
    assert not screen._test_sent
    screen.view_unit("field", 0)
    assert "SCOUTED RANGER" in screen.unit_widget.name_label.text()
    screen.set_view_player(0)
    state["game"]["state"]["decision_mode"] = False
    screen.update_state(state)
    assert not screen.btn_combat.isEnabled()


def test_combat_inspection_is_current_and_never_sellable(screen):
    screen.view_unit("bench", 0)
    state = _sample_state()
    state["game"]["state"]["current_state"] = "BATTLE"
    unit = _sample_unit("COMBAT GUARD")
    state["game"]["battle"][0] = {"team": "home", "arena": [{"unit": unit, "pos": [0, 0]}]}
    screen.update_state(state)
    screen.field_layout.battle_page.unit_buttons[49].click()
    assert screen.selection == ("battle", 49)
    assert "COMBAT GUARD" in screen.unit_widget.name_label.text()
    assert not screen.unit_widget.action_button.isEnabled()
    state = copy.deepcopy(state)
    state["game"]["battle"][0]["arena"][0]["unit"]["status"]["hp"] = 400
    screen.update_state(state)
    assert screen.unit_widget.health_bar.value() == 400


def test_preparation_widgets_reused_and_shop_selection_cleared(screen):
    cards = tuple(screen.field_layout.unit_buttons)
    screen.view_unit("shop", 0)
    assert screen.unit_widget.action_button.isEnabled()
    state = _sample_state()
    state["player"]["shop"]["units"][0] = None
    screen.update_state(state)
    assert not screen.unit_widget.action_button.isEnabled()
    assert tuple(screen.field_layout.unit_buttons) == cards


def test_full_bench_purchase_requires_room_or_matching_merge(screen):
    state = _sample_state()
    own = state["player"]
    own["bench"]["units"] = [dict(_sample_unit(), id="other")] * 9
    own["shop"]["units"][0] = dict(_sample_unit(), id="new")
    screen.update_state(state)
    assert not screen.shop_layout.buy_buttons[0].isEnabled()
    own["bench"]["units"][0] = dict(_sample_unit(), id="new")
    own["bench"]["units"][1] = dict(_sample_unit(), id="new")
    screen.update_state(state)
    assert screen.shop_layout.buy_buttons[0].isEnabled()


@pytest.fixture
def navigation(application: QApplication) -> Iterator[tuple[SimpleNamespace, list[tuple]]]:
    """Provide real screens with an isolated outbound command collector."""
    from PyQt6.QtWidgets import QStackedWidget

    from client.home import HomeScreen
    from client.lobby import LobbyScreen
    from client.login import LoginScreen

    sent = []
    socket = SimpleNamespace(
        sio=SimpleNamespace(connected=True),
        send_command=lambda action, params=None: (action, params),
        state={"game": {}},
    )
    parent = SimpleNamespace(
        socket_thread=socket, run_async=sent.append, stacked_widget=QStackedWidget()
    )
    parent.login_screen = LoginScreen(parent)
    parent.home_screen = HomeScreen(parent)
    parent.lobby_screen = LobbyScreen(parent)
    parent.game_screen = QPushButton("Game")
    parent.stacked_widget.addWidget(parent.login_screen)
    parent.stacked_widget.addWidget(parent.home_screen)
    parent.stacked_widget.addWidget(parent.lobby_screen)
    parent.stacked_widget.addWidget(parent.game_screen)
    yield parent, sent
    parent.stacked_widget.close()


def test_login_submission_waits_for_server_ack(navigation):
    parent, sent = navigation
    parent.login_screen.username_input.setText("Research_User")
    parent.login_screen.login()
    assert sent == [("login", "Research_User")]
    assert parent.stacked_widget.currentWidget() is parent.login_screen


@pytest.mark.parametrize("username", ["Research User", ".", "..", "연구자", "", "../escape"])
def test_login_invalid_username_remains_editable_without_sending(navigation, username):
    parent, sent = navigation
    parent.login_screen.username_input.setText(username)
    parent.login_screen.login()
    assert sent == []
    assert parent.stacked_widget.currentWidget() is parent.login_screen
    assert parent.login_screen.message_label.text()


def test_username_supports_server_64_character_limit(navigation):
    parent, sent = navigation
    assert parent.login_screen.username_input.maxLength() == 64
    parent.login_screen.username_input.setText("x" * 64)
    parent.login_screen.login()
    assert sent == [("login", "x" * 64)]


def test_register_and_start_wait_for_server_ack(navigation):
    parent, sent = navigation
    parent.stacked_widget.setCurrentWidget(parent.home_screen)
    parent.home_screen.register_game()
    assert sent[-1][0] == "register_game"
    assert parent.stacked_widget.currentWidget() is parent.home_screen
    parent.stacked_widget.setCurrentWidget(parent.lobby_screen)
    parent.lobby_screen.start_game()
    assert sent[-1] == ("start_game", None)
    assert parent.stacked_widget.currentWidget() is parent.lobby_screen
