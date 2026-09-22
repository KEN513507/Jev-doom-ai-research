"""Regression tests for train/state_utils.py + train/jev_agent.py.

Run:  python3 -m unittest discover -s tests -v
vizdoom is stubbed: these tests cover only the pure decision-shaping logic.
"""
import sys
import types
import unittest

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.state_utils import (
    ACTIVE_REGION,
    ENEMY_RED_THRESHOLD,
    ForwardBlockDetector,
    SLICE_CONFIG,
    USE_RESOLUTION,
    build_state_text,
    compute_red_metrics,
    detect_enemy_from_labels,
    get_slice,
)
from train.jev_agent import (
    ACTION_BUTTONS,
    CRITERIA_SETS,
    SYSTEM1_WIDTH_THRESHOLD,
    build_payload,
    execute_action,
    extract_choice_and_probs,
    resolve_action,
    should_force_attack,
    state_to_text,
)


def _fake_buffer(red, h=120, w=160):
    import numpy as np

    buf = np.zeros((3, h, w), dtype=np.uint8)
    buf[0] = red
    return buf


class TestSliceConfig(unittest.TestCase):
    def test_active_region_fits_resolution(self):
        # スライスが解像度内に収まること（はみ出しは敵検出の意味を壊す）
        h = int(USE_RESOLUTION.split("X")[1])
        sl = get_slice()
        self.assertEqual(sl[0], slice(None))
        self.assertLessEqual(sl[1].stop, h)
        self.assertIn(ACTIVE_REGION, SLICE_CONFIG[USE_RESOLUTION])

    def test_compute_red_metrics_baseline(self):
        # 壁ベースライン相当の均一赤は閾値未満のはず
        red_mean, visible = compute_red_metrics(_fake_buffer(42))
        self.assertAlmostEqual(red_mean, 42.0)
        self.assertFalse(visible)

    def test_compute_red_metrics_enemy(self):
        red_mean, visible = compute_red_metrics(_fake_buffer(200))
        self.assertTrue(visible)

    def test_compute_red_metrics_none(self):
        self.assertEqual(compute_red_metrics(None), (0.0, False))


class TestStateText(unittest.TestCase):
    def test_returns_tuple(self):
        state = types.SimpleNamespace(screen_buffer=_fake_buffer(42))
        text, red_mean, visible = state_to_text(state, [100])
        self.assertIn("red_mean=42.0", text)
        self.assertIn("enemy_visible=no", text)
        self.assertFalse(visible)

    def test_no_health_hardcode(self):
        text, _, _ = state_to_text(None, [50])
        self.assertIn("var0=50", text)
        self.assertNotIn("health=", text)

    def test_build_state_text_balanced_context(self):
        text = build_state_text([100], 42.0, False)
        self.assertIn("Do not attack blindly", text)


class TestCriteriaBalance(unittest.TestCase):
    def test_attack_requires_visible_enemy(self):
        crit = build_payload("x")["questions"]["next_action"]["criteria"]
        self.assertIn("Do NOT attack if no enemy is visible", crit["attack"])

    def test_criteria_keys_match_buttons(self):
        crit = build_payload("x")["questions"]["next_action"]["criteria"]
        self.assertEqual(set(crit), set(ACTION_BUTTONS))

    def test_extract_tolerates_missing_probabilities(self):
        c, p = extract_choice_and_probs({"answers": {"next_action": {"choice": "attack"}}})
        self.assertEqual((c, p), ("attack", {}))

    def test_extract_rejects_garbage(self):
        with self.assertRaises(ValueError):
            extract_choice_and_probs({"answers": {}})


def _fake_label(name, x=80, width=20):
    return types.SimpleNamespace(object_name=name, x=x, width=width)


def _fake_state_with_labels(labels, w=160, h=120):
    import numpy as np

    return types.SimpleNamespace(
        screen_buffer=np.zeros((3, h, w), dtype=np.uint8),
        labels=labels,
    )


class TestLabelsDetection(unittest.TestCase):
    def test_no_state(self):
        info = detect_enemy_from_labels(None)
        self.assertFalse(info["enemy_visible"])
        self.assertEqual(info["enemy_count"], 0)

    def test_no_labels_attr(self):
        state = types.SimpleNamespace(screen_buffer=_fake_buffer(42))
        info = detect_enemy_from_labels(state)
        self.assertFalse(info["enemy_visible"])

    def test_non_enemy_labels_ignored(self):
        # GreenArmor / DoomPlayer は敵ではない
        state = _fake_state_with_labels([_fake_label("GreenArmor"), _fake_label("DoomPlayer")])
        info = detect_enemy_from_labels(state)
        self.assertFalse(info["enemy_visible"])
        self.assertEqual(info["enemy_count"], 0)

    def test_enemy_detected_with_names(self):
        state = _fake_state_with_labels(
            [_fake_label("Zombieman", x=10), _fake_label("ShotgunGuy", x=120)]
        )
        info = detect_enemy_from_labels(state)
        self.assertTrue(info["enemy_visible"])
        self.assertEqual(info["enemy_count"], 2)
        self.assertEqual(set(info["enemy_names"]), {"Zombieman", "ShotgunGuy"})

    def test_centered_judgement(self):
        # 画面幅160 → 中央80。中央付近の敵は centered
        state = _fake_state_with_labels([_fake_label("Zombieman", x=75, width=10)])
        self.assertTrue(detect_enemy_from_labels(state)["enemy_centered"])
        # 端の敵は centered ではない
        state = _fake_state_with_labels([_fake_label("Zombieman", x=5, width=10)])
        self.assertFalse(detect_enemy_from_labels(state)["enemy_centered"])

    def test_state_to_text_prefers_labels(self):
        # red_mean は閾値未満でも labels に敵がいれば visible
        state = _fake_state_with_labels([_fake_label("Zombieman", x=75, width=10)])
        text, _, visible = state_to_text(state, [100], use_labels=True)
        self.assertTrue(visible)
        self.assertIn("enemy_visible=yes", text)
        self.assertIn("enemy_count=1", text)
        self.assertIn("enemy_types=Zombieman", text)

    def test_state_to_text_labels_override_red(self):
        # red が高くても labels に敵がいなければ not visible
        state = _fake_state_with_labels(
            [_fake_label("GreenArmor")], w=160, h=120
        )
        import numpy as np

        state.screen_buffer = np.full((3, 120, 160), 200, dtype=np.uint8)
        text, _, visible = state_to_text(state, [100], use_labels=True)
        self.assertFalse(visible)
        self.assertIn("enemy_visible=no", text)

    def test_min_width_filters_distant_enemies(self):
        # 幅5の遠方ラベルは無視、幅30の近傍ラベルのみ検出
        state = _fake_state_with_labels(
            [_fake_label("Zombieman", x=10, width=5), _fake_label("ShotgunGuy", x=100, width=30)]
        )
        info = detect_enemy_from_labels(state, min_width=20.0)
        self.assertTrue(info["enemy_visible"])
        self.assertEqual(info["enemy_count"], 1)
        self.assertEqual(info["enemy_names"], ["ShotgunGuy"])

    def test_min_width_all_filtered(self):
        state = _fake_state_with_labels([_fake_label("Zombieman", x=10, width=5)])
        info = detect_enemy_from_labels(state, min_width=20.0)
        self.assertFalse(info["enemy_visible"])
        self.assertEqual(info["enemy_count"], 0)

    def test_min_width_default_zero_keeps_behavior(self):
        # デフォルトではフィルタなし（既存の振る舞いを維持）
        state = _fake_state_with_labels([_fake_label("Zombieman", x=10, width=5)])
        self.assertTrue(detect_enemy_from_labels(state)["enemy_visible"])

    def test_zero_width_label_with_valid_x_detected(self):
        # ChaingunGuy のように width=0 でも x が画面内なら検出
        state = _fake_state_with_labels([_fake_label("ChaingunGuy", x=80, width=0)])
        info = detect_enemy_from_labels(state, min_width=8.0)
        self.assertTrue(info["enemy_visible"])
        self.assertEqual(info["enemy_names"], ["ChaingunGuy"])

    def test_zero_width_label_offscreen_ignored(self):
        state = _fake_state_with_labels([_fake_label("ChaingunGuy", x=200, width=0)])
        info = detect_enemy_from_labels(state, min_width=8.0)
        self.assertFalse(info["enemy_visible"])

    def test_system1_trigger_boundary(self):
        # 閾値ちょうど20 → 発動、19.9 → 不発、0（ChaingunGuy）→ 不発（System2に委ねる）
        base = {"enemy_visible": True, "enemy_centered": True}
        self.assertTrue(
            should_force_attack({**base, "nearest_enemy_width": 20.0})
        )
        self.assertFalse(
            should_force_attack({**base, "nearest_enemy_width": 19.9})
        )
        self.assertFalse(
            should_force_attack({**base, "nearest_enemy_width": 0.0})
        )

    def test_system1_does_not_fire_below_threshold(self):
        # 実測幅（Zombieman 10〜18、中央）はSystem1閾値20未満のため発動しない
        state = _fake_state_with_labels([_fake_label("Zombieman", x=74, width=12)])
        info = detect_enemy_from_labels(state, min_width=8.0)
        self.assertTrue(info["enemy_visible"])
        self.assertTrue(info["enemy_centered"])
        self.assertFalse(should_force_attack(info))

    def test_system1_requires_visible_and_centered(self):
        self.assertFalse(should_force_attack(None))
        self.assertFalse(should_force_attack({}))
        base = {"enemy_visible": True, "enemy_centered": True,
                "nearest_enemy_width": 25.0}
        self.assertTrue(should_force_attack(base))
        off = dict(base, enemy_centered=False)
        self.assertFalse(should_force_attack(off))
        novis = dict(base, enemy_visible=False)
        self.assertFalse(should_force_attack(novis))
        nowidth = dict(base, nearest_enemy_width=None)
        self.assertFalse(should_force_attack(nowidth))

    def test_system1_skips_api(self):
        calls = []

        def decide(text):
            calls.append(text)
            raise AssertionError("API must not be called on System1")

        state = _fake_state_with_labels([_fake_label("Zombieman", x=70, width=25)])
        choice, source, info = resolve_action(
            state, [100], use_labels=True, min_enemy_width=8.0, decide=decide
        )
        self.assertEqual((choice, source), ("attack", "system1"))
        self.assertEqual(calls, [])
        self.assertIn("Zombieman", info["enemy_names"])

    def test_system1_defers_zero_width_enemy_to_api(self):
        # ChaingunGuy（width=0、中央）はSystem1閾値未満のためSystem2（Jev）に委ねる
        calls = []

        def decide(text):
            calls.append(text)
            return {"answers": {"next_action": {"choice": "attack"}}}

        state = _fake_state_with_labels([_fake_label("ChaingunGuy", x=80, width=0)])
        choice, source, _ = resolve_action(
            state, [100], use_labels=True, min_enemy_width=8.0, decide=decide
        )
        self.assertEqual((choice, source), ("attack", "system2"))
        self.assertEqual(len(calls), 1)

    def test_system2_calls_api(self):
        calls = []

        def decide(text):
            calls.append(text)
            return {"answers": {"next_action": {"choice": "move_forward"}}}

        state = _fake_state_with_labels([_fake_label("GreenArmor")])
        choice, source, info = resolve_action(
            state, [100], use_labels=True, min_enemy_width=8.0, decide=decide
        )
        self.assertEqual((choice, source), ("move_forward", "system2"))
        self.assertEqual(len(calls), 1)
        self.assertIn("enemy_visible=no", calls[0])

    def test_system1_inactive_without_labels(self):
        # --use-labels なしでは System1 は発動しない（後方互換）
        calls = []

        def decide(text):
            calls.append(text)
            return {"answers": {"next_action": {"choice": "attack"}}}

        state = _fake_state_with_labels([_fake_label("Zombieman", x=70, width=25)])
        choice, source, _ = resolve_action(
            state, [100], use_labels=False, min_enemy_width=0.0, decide=decide
        )
        self.assertEqual(source, "system2")
        self.assertEqual(len(calls), 1)

    def test_state_to_text_min_width_passthrough(self):
        state = _fake_state_with_labels([_fake_label("Zombieman", x=10, width=5)])
        _, _, visible = state_to_text(
            state, [100], use_labels=True, min_enemy_width=20.0
        )
        self.assertFalse(visible)

    def test_build_payload_accepts_subset(self):
        # シナリオのボタンに対するサブセットは許容（修正5）
        payload = build_payload("x", criteria={"attack": "Fire."})
        crit = payload["questions"]["next_action"]["criteria"]
        self.assertEqual(crit, {"attack": "Fire."})

    def test_build_payload_rejects_unknown_keys(self):
        with self.assertRaises(ValueError):
            build_payload("x", criteria={"attack": "Fire.", "fly": "Nope."})

    def test_aggressive_p0_criteria_keys(self):
        self.assertEqual(set(CRITERIA_SETS["aggressive_p0"]), set(ACTION_BUTTONS))
        payload = build_payload("x", criteria="aggressive_p0")
        crit = payload["questions"]["next_action"]["criteria"]
        self.assertIn("MUST immediately", crit["attack"])


class TestFullMap(unittest.TestCase):
    def test_full_map_has_strafe_buttons(self):
        from train.scenarios import FULL_MAP_SCENARIOS, SCENARIO_BUTTONS, SCENARIO_CRITERIA

        buttons = SCENARIO_BUTTONS["full_map"]
        self.assertIn("MOVE_LEFT", buttons)
        self.assertIn("MOVE_RIGHT", buttons)
        self.assertEqual(set(SCENARIO_CRITERIA["full_map"]), {b.lower() for b in buttons})
        self.assertIn("full_map", FULL_MAP_SCENARIOS)

    def test_tactical_peeking_keys_fit_full_map(self):
        from train.scenarios import SCENARIO_BUTTONS

        keys = set(CRITERIA_SETS["tactical_peeking"])
        self.assertLessEqual(keys, {b.lower() for b in SCENARIO_BUTTONS["full_map"]})
        self.assertIn("move_left", keys)
        self.assertIn("move_right", keys)
        self.assertIn("use", keys)
        self.assertIn("USE", SCENARIO_BUTTONS["full_map"])

    def test_doom_imp_detected(self):
        # freedoom2 map01 のインプは object_name="DoomImp"
        state = _fake_state_with_labels([_fake_label("DoomImp", x=70, width=12)])
        info = detect_enemy_from_labels(state)
        self.assertTrue(info["enemy_visible"])
        self.assertEqual(info["enemy_names"], ["DoomImp"])

    def test_tactical_peeking_use_gated_by_front_blocked(self):
        crit = CRITERIA_SETS["tactical_peeking"]
        self.assertIn("front_blocked=yes", crit["use"])
        self.assertIn("front_blocked=yes", crit["move_forward"])


class TestFrontBlocked(unittest.TestCase):
    def _run(self, steps):
        det = ForwardBlockDetector(window=3, max_distance=8.0)
        return [det.update(pos, action) for pos, action in steps]

    def test_blocked_when_forward_without_progress(self):
        # 最初の観測 + move_forward 3回で位置が変わらない → 3回目で blocked
        steps = [((0, 0), None)] + [((0, 0), "move_forward")] * 3
        self.assertEqual(self._run(steps), [False, False, False, True])

    def test_not_blocked_while_moving(self):
        steps = [((0, 0), None)] + [((29 * i, 0), "move_forward") for i in range(1, 5)]
        self.assertFalse(any(self._run(steps)))

    def test_other_action_resets_window(self):
        steps = (
            [((0, 0), None)]
            + [((0, 0), "move_forward")] * 2
            + [((0, 0), "turn_left")]
            + [((0, 0), "move_forward")] * 2
        )
        self.assertFalse(any(self._run(steps)))

    def test_state_text_includes_front_blocked_only_when_given(self):
        state = _fake_state_with_labels([])
        text_yes, _, _ = state_to_text(state, [100], use_labels=True, front_blocked=True)
        text_none, _, _ = state_to_text(state, [100], use_labels=True)
        self.assertIn("front_blocked=yes", text_yes)
        self.assertNotIn("front_blocked", text_none)

    def test_resolve_action_passes_front_blocked_to_jev(self):
        seen = []

        def decide(text):
            seen.append(text)
            return {"answers": {"next_action": {"choice": "use"}}}

        choice, source, _ = resolve_action(
            _fake_state_with_labels([]), [100], use_labels=True,
            min_enemy_width=8.0, decide=decide, front_blocked=True,
        )
        self.assertEqual((choice, source), ("use", "system2"))
        self.assertIn("front_blocked=yes", seen[0])


class _FakeGame:
    def __init__(self):
        self.calls = []

    def make_action(self, vec, tics):
        self.calls.append((list(vec), tics))
        return 1.0

    def is_episode_finished(self):
        return False


class TestExecuteAction(unittest.TestCase):
    def test_tap_presses_one_tic_then_releases(self):
        game = _FakeGame()
        reward = execute_action(game, [0, 1, 0], 4, tap=True)
        self.assertEqual(game.calls, [([0, 1, 0], 1), ([0, 0, 0], 3)])
        self.assertEqual(reward, 2.0)

    def test_hold_uses_full_frame_skip(self):
        game = _FakeGame()
        execute_action(game, [1, 0, 0], 4)
        self.assertEqual(game.calls, [([1, 0, 0], 4)])


if __name__ == "__main__":
    unittest.main()
