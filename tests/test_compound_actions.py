"""Runtime registration -> Jev payload -> simultaneous button execution."""
import sys
import types
from unittest.mock import patch

import numpy as np
import pytest

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.jev_agent import (
    ACTION_BUTTONS, CRITERIA_SETS, build_payload, configure_actions,
    execute_action, extract_choice_and_probs,
)
from train.scenarios import (
    ACTION_DEFINITIONS, SCENARIO_BUTTONS, SCENARIO_CRITERIA,
    build_action_vector, get_action_buttons,
)
from train.state_utils import ForwardBlockDetector, WallAvoider


def test_all_policies_have_same_keys():
    for criteria in CRITERIA_SETS.values():
        assert set(criteria) == set(ACTION_DEFINITIONS)


@pytest.mark.parametrize("scenario", SCENARIO_BUTTONS)
def test_runtime_candidates_match_supported_actions_for_every_policy(scenario):
    expected = set(get_action_buttons(scenario))
    assert set(SCENARIO_CRITERIA[scenario]) == expected
    with patch.dict(ACTION_BUTTONS):
        for policy in CRITERIA_SETS:
            criteria = configure_actions(scenario, policy)
            payload = build_payload("enemy_centered=yes", criteria)
            assert set(payload["questions"]["next_action"]["criteria"]) == expected
            assert set(ACTION_BUTTONS) == expected


@pytest.mark.parametrize("choice,pressed", [
    ("strafe_attack_left", {"MOVE_LEFT", "ATTACK"}),
    ("strafe_attack_right", {"MOVE_RIGHT", "ATTACK"}),
    ("advance_attack", {"MOVE_FORWARD", "ATTACK"}),
])
def test_runtime_compound_candidate_becomes_simultaneous_buttons(choice, pressed):
    # Reconfigure twice to catch clear()/re-registration regressions.
    with patch.dict(ACTION_BUTTONS):
        configure_actions("health_gathering", "baseline")
        assert choice not in ACTION_BUTTONS
        criteria = configure_actions("full_map", "tactical_peeking")
        assert choice in build_payload("enemy_centered=yes", criteria)["questions"]["next_action"]["criteria"]
        selected, _ = extract_choice_and_probs({"answers": {"next_action": {"choice": choice}}})
        buttons = list(reversed(SCENARIO_BUTTONS["full_map"]))
        vector = build_action_vector(selected, buttons, ACTION_BUTTONS)

        class Game:
            def make_action(self, actual, tics):
                assert {button for button, down in zip(buttons, actual) if down} == pressed
                assert tics == 4
                return 1

        assert execute_action(Game(), vector, 4) == 1


def test_missing_component_is_excluded_and_cannot_partially_execute():
    assert "advance_attack" not in get_action_buttons("basic")
    assert "strafe_attack_left" not in get_action_buttons("defend_the_center")
    with pytest.raises(ValueError):
        build_action_vector("strafe_attack_left", ["ATTACK"], ACTION_DEFINITIONS)
    with pytest.raises(KeyError):
        build_action_vector("invalid", ["ATTACK"], ACTION_DEFINITIONS)


def depth(center=63, left=63, right=63):
    buffer = np.full((120, 160), 63, dtype=np.uint8)
    buffer[:, :53] = left
    buffer[:, 106:] = right
    buffer[:, 64:96] = center
    return buffer


def test_advance_attack_opens_door_then_turns_and_tracks_stagnation():
    avoider = WallAvoider()
    assert avoider.filter("advance_attack", depth(center=3), (0, 0)) == "use"
    avoider.wait = 0
    assert avoider.filter("advance_attack", depth(center=3, right=10), (0, 0)) == "turn_left"
    assert WallAvoider().filter("advance_attack", depth(), (0, 0), front_blocked=True) == "use"
    detector = ForwardBlockDetector(window=3)
    assert not detector.update((0, 0), None)
    assert not detector.update((0, 0), "advance_attack")
    assert not detector.update((0, 0), "move_forward")
    assert detector.update((0, 0), "advance_attack")


@pytest.mark.parametrize("choice,side", [
    ("strafe_attack_left", "left"), ("strafe_attack_right", "right"),
])
def test_strafe_checks_movement_side_and_preserves_fire(choice, side):
    avoider = WallAvoider()
    avoider.wait = 3
    assert avoider.filter(choice, depth(**{side: 3}), (0, 0)) == "attack"
    opposite = "right" if side == "left" else "left"
    assert avoider.filter(choice, depth(center=3, **{opposite: 3}), (0, 0)) == choice


@pytest.mark.parametrize("choice", ["advance_attack", "strafe_attack_left", "strafe_attack_right"])
def test_clear_space_preserves_compound_action(choice):
    assert WallAvoider().filter(choice, depth(), (0, 0)) == choice
