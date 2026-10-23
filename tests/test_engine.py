"""Regression coverage for reproducible research engine behavior."""

import copy

import pytest

from pyautobattle import AutoBattlerGame
from pyautobattle.src.game import GameState
from pyautobattle.src.player import Player
from pyautobattle.src.pool import Pool


def _make_game(seed=0, **kwargs):
    game = AutoBattlerGame("test", seed=seed, **kwargs)
    game.register("human")
    game.start()
    return game


@pytest.mark.parametrize(
    "gold,interest", [(0, 0), (9, 0), (10, 1), (19, 1), (20, 2), (50, 5), (99, 5)]
)
def test_interest_counts_tens(gold, interest):
    player = Player("p", "p", Pool("pyautobattle/data/unit.csv", ""))
    player.gold = gold
    player.get_turn_gold(0)
    assert player.interest_list[-1] == interest


def test_research_profile_and_economy():
    game = _make_game(decision_mode=True)
    player = game.players[0]
    assert (player.hp, player.level, player.gold) == (100, 2, 3)
    assert player.field.max_units == 2
    assert game.state_time == 45
    assert game.to_json()["state"]["ruleset"] == "research"
    for turn, expected in enumerate([2, 2, 3, 4, 5, 5]):
        player.gold = 0
        player.get_turn_gold(turn)
        assert player.gold == expected
    for streak, expected in [(1, 0), (2, 1), (-3, 1), (4, 2), (-5, 3), (20, 3)]:
        player.streak = streak
        assert player.to_json()["economy"]["streak"] == expected


def test_decision_preparation_and_active_fillers():
    game = _make_game(decision_mode=True)
    human = game.players[0]
    assert not any(human.field.units)
    fillers = game.players[1:]
    assert all(any(p.field.units) and p.gold < 3 for p in fillers)
    for _ in range(60):
        game.step(1)
    assert game.state == GameState.READY
    game.advance()
    assert game.state == GameState.BATTLE
    assert game.state_time == 30
    assert game.advance()["message"]


def test_seeds_are_local_and_cover_combat():
    first = _make_game(seed=37)
    other = _make_game(seed=99)
    second = _make_game(seed=37)
    assert first.to_json() == second.to_json()
    assert first.players[0].shop.to_json() != other.players[0].shop.to_json()
    first.advance()
    other.advance()
    second.advance()
    for _ in range(120):
        first.step(60)
        other.step(60)
        second.step(60)
    assert first.to_json() == second.to_json()


def test_pool_samples_are_independent_and_empty_safe():
    pool = Pool("pyautobattle/data/unit.csv", "")
    unit = pool.sample(1)
    template = pool.unit_dict[unit.name]
    assert unit is not template
    unit.status.hp = 1
    assert template.status.hp > 1
    pool.available_units[1] = {key: 0 for key in pool.available_units[1]}
    assert pool.sample(1) is None


def test_copy_preserves_state_and_attack_uses_seconds():
    game = _make_game()
    attacker = game.pool.get_unit("SKATEBOARD", 1)
    target = game.pool.get_unit("SKATEBOARD", 1)
    attacker.cooldown_time = 0.75
    attacker.mana = 33
    target.status.hp = 50
    copied = copy.deepcopy(target)
    assert copied.status.max_hp == target.status.max_hp
    clone = copy.deepcopy(attacker)
    assert clone.cooldown_time == 0.75 and clone.mana == 33
    attacker.cooldown_time = 0
    attacks = 0
    target.status.hp = 100000
    for _ in range(120):
        attacker.update(1 / 60)
        if attacker.cooldowned():
            attacker.hit(target, rng=game.rng)
            attacks += 1
    assert attacks == 2


def test_unit_observations_are_honest_and_complete():
    unit = _make_game().players[0].bench[0]
    observation = unit.to_json()
    assert observation["role"] in {"tank", "fighter", "marksman"}
    assert {"name", "cost", "role_description", "status", "id", "level"} <= observation.keys()
    assert {"attack", "attackRange", "attackSpeed", "defense"} <= observation["status"].keys()


def test_legacy_keeps_original_pacing():
    game = _make_game(ruleset="legacy")
    player = game.players[0]
    assert player.hp == 30 and game.state_time == 10
    player.gold = 19
    player.get_turn_gold(0)
    assert player.gold == 30
    game.advance()
    assert game.state_time == 5


def test_upgrade_and_sales_conserve_pool_supply_with_full_bench():
    game = _make_game()
    player = game.players[0]
    player.release_holdings()
    name = "SKATEBOARD"
    for index in range(player.bench.num_slots):
        unit = game.pool.get_unit(name if index < 2 else "YO-YO", 1)
        game.pool.remove_unit(unit)
        player.bench.units[index] = unit
    offered = game.pool.get_unit(name, 1)
    game.pool.remove_unit(offered)
    player.shop.units[0] = offered
    player.gold = 10
    before = game.pool.available_units[1][name]
    result = player.purchase_unit(0)
    assert result["message"]
    owned = [unit for unit in player.bench if unit and unit.name == name]
    assert len(owned) == 1 and owned[0].level == 2
    assert game.pool.available_units[1][name] == before
    player.release_holdings()
    assert game.pool.available_units[1][name] == before + 3
    player.release_holdings()
    assert game.pool.available_units[1][name] == before + 3


def test_invalid_moves_are_atomic_and_append_keeps_last_slot():
    player = _make_game().players[0]
    before = player.to_json()
    player.move_unit("bench", "field", player.bench.num_slots, -1)
    assert player.to_json() == before
    player.bench.units[-1] = player.pool.get_unit("YO-YO", 1)
    last = player.bench.units[-1]
    player.move_unit("bench", "field", 0, -1)
    assert player.bench.units[-1] is last
    assert player.field.units[0] is not None


def test_odd_survivors_settle_once_and_round_ceiling_stops():
    game = _make_game()
    for player in game.players[3:]:
        player.hp = 0
        player.release_holdings()
    game.advance()
    assert len(game.matchup) == 2
    game.end_battle()
    assert [len(player.combat_result_list) for player in game.players[:3]] == [1, 1, 1]
    game.round = 200
    game.step(60)
    assert not game.running
    assert not any(player.active for player in game.players)


def test_top_level_observations_remain_strict_json():
    import json

    player = _make_game().players[0]
    player.give_exp(10000)
    assert player.level == 10
    json.dumps(player.observe(), allow_nan=False)
    assert player.observe()["req_exp"] is None


def test_scripted_fillers_deploy_stronger_owned_units():
    game = _make_game()
    bot = game.players[1]
    bot.release_holdings()
    bot.field.max_units = 1
    weak = game.pool.get_unit("SKATEBOARD", 1)
    strong = game.pool.get_unit("SKATEBOARD", 3)
    bot.field.units[0] = weak
    bot.bench.units[0] = strong
    bot.play_randomly()
    assert any(unit is strong for unit in bot.field)


def test_action_mask_tracks_phase_and_affordability():
    game = _make_game()
    player = game.players[0]
    player.gold = 0
    actions = player.observe()["legal_actions"]
    assert not actions["reroll"] and not actions["buy_exp"] and actions["buy_unit"] == []
    player.gold = 20
    assert player.observe()["legal_actions"]["buy_unit"] == [0, 1, 2, 3, 4]
    assert game.to_json()["state"]["ruleset_version"] == 1
    game.advance()
    assert player.observe()["legal_actions"]["buy_unit"] == []


def test_decision_mode_continues_after_registered_human_elimination():
    game = _make_game(decision_mode=True)
    human = game.get_player_by_user_id("human")
    human.hp = 0
    human.release_holdings()
    for _ in range(game.rules.preparation_seconds):
        game.step(1)
    assert game.state == GameState.BATTLE


def test_all_bot_decision_mode_finishes_without_manual_advance():
    game = AutoBattlerGame("bots", seed=17, decision_mode=True)
    game.start()
    max_ticks = game.rules.max_rounds * (game.rules.preparation_seconds + game.rules.combat_seconds)
    for _ in range(max_ticks):
        if not game.running:
            break
        game.step(1)
    assert not game.running
    assert game.winner is not None


def test_fillers_put_tanks_nearer_enemy_than_marksmen():
    game = _make_game()
    bot = game.players[1]
    bot.release_holdings()
    bot.field.max_units = 2
    bot.gold = 0
    tank = game.pool.get_unit("SKATEBOARD", 1)
    marksman = game.pool.get_unit("YO-YO", 1)
    game.pool.remove_unit(tank)
    game.pool.remove_unit(marksman)
    bot.bench.units[:2] = [tank, marksman]
    bot.play_randomly()
    assert bot.field.units.index(tank) // 7 == 3
    assert bot.field.units.index(marksman) // 7 == 0


def test_bot_identifiers_cannot_collide_with_registered_users():
    game = AutoBattlerGame("g")
    game.register("g-2")
    game.register("g-2-bot")
    game.start()
    identifiers = [player.player_id for player in game.players]
    assert len(set(identifiers)) == 8
    assert len(game.to_json()["players"]) == 8
