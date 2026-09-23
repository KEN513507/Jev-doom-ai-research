"""計測ツール（tools/analyze_log.py・tools/compare_reports.py）のテスト。"""
import importlib.util
import math
import unittest
from pathlib import Path

_TOOLS = Path(__file__).parent.parent / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


analyze = _load("analyze_log")
compare = _load("compare_reports")

LOG = """\
--- Episode 0 ---
step=0 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
    state_text: x, front_blocked=no
step=8 Jev -> turn_left | red_mean=40.0 | enemy_visible=no
    state_text: x
step=16 Jev -> turn_left | red_mean=40.0 | enemy_visible=no
    state_text: x
step=24 Jev -> turn_left | red_mean=40.0 | enemy_visible=no
    state_text: x
!!! HIT #1 at step=28: 100 -> 88
step=32 Jev -> move_right | red_mean=50.0 | enemy_visible=yes
    state_text: x, enemy_centered=no, enemy_side=left, front_blocked=no
step=40 Jev -> attack | red_mean=50.0 | enemy_visible=yes
    state_text: x, enemy_centered=yes, enemy_side=right
!!! HIT #2 at step=44: 88 -> 80
step=48 [System1] FORCED attack (centered, width=22)
step=56 Jev -> strafe_attack_left | red_mean=50.0 | enemy_visible=yes
    state_text: x, enemy_centered=yes, enemy_side=left
step=56 [Reflex] strafe_attack_left -> attack (wall ahead)
step=64 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
    state_text: x
step=64 [Reflex] move_forward -> use (wall ahead)
step=72 Jev -> use | red_mean=40.0 | enemy_visible=no
    state_text: x
step=72 [UseFail] repeated use at same spot -> turn_right
step=80 [DoorWait] no_door (16tic) -> resume
step=80 [Stuck] 30tic 停止 -> move_right
[System 3] triggers=['front_blocked'] -> Turn around.
[skip] timeout
Episode 0 done: hits=2, final_health=80, steps=88
--- Episode 1 ---
step=0 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
"""


class TestAnalyzeLog(unittest.TestCase):
    def setUp(self):
        eps = analyze.split_episodes(LOG.splitlines())
        self.assertEqual(list(eps), [0])  # 未完走の Episode 1 は除外
        self.r = analyze.analyze_episode(eps[0])

    def test_turn_run(self):
        self.assertEqual(self.r["B1_longest_turn_run"], 3)
        self.assertEqual(self.r["B1_longest_turn_dir"], "turn_left")
        self.assertEqual((self.r["B2_turn_left"], self.r["B2_turn_right"]), (3, 0))

    def test_flee_and_engage(self):
        self.assertEqual(self.r["B3_flee_strafe"], 1)  # 敵が左なのに move_right
        # 敵視認の判断 4回（move_right, attack, System1, strafe_attack→attack）中、攻撃 3回
        self.assertEqual(self.r["B4_enemy_decisions"], 4)
        self.assertAlmostEqual(self.r["B4_engage_rate"], 3 / 4)

    def test_offscreen_hits_and_damage(self):
        self.assertEqual(self.r["B5_offscreen_hits"], 1)  # HIT#1 は敵不在中、HIT#2 は敵視認中
        self.assertAlmostEqual(self.r["B5_offscreen_hit_rate"], 0.5)
        self.assertEqual(self.r["A4_damage_taken_log"], 20)
        self.assertEqual(self.r["A4_hits_log"], 2)

    def test_overrides_and_reflexes(self):
        self.assertEqual(self.r["B7_wall_shots"], 1)
        self.assertEqual(self.r["B6_longest_use_run"], 1)  # use → UseFail で turn_right に置換
        self.assertEqual(self.r["B8_use_fail"], 1)
        self.assertEqual(self.r["B8_door_no_door"], 1)
        self.assertEqual(self.r["B8_stuck"], 1)

    def test_system_health(self):
        self.assertEqual(self.r["D2_jev_decisions"], 9)
        self.assertAlmostEqual(self.r["D2_skip_rate"], 1 / 10)
        self.assertEqual(self.r["D3_sys3_calls"], 1)

    def test_no_visual_lines_means_zero(self):
        # LOG フィクスチャに PLACE_* 行がない（Sprint 1 未接続のログ）→ 0 のまま
        self.assertEqual(self.r["V1_place_new"], 0)
        self.assertEqual(self.r["V1_place_revisit"], 0)
        self.assertEqual(self.r["V2_place_transitions"], 0)
        self.assertEqual(self.r["V3_visual_stagnation"], 0)


VISUAL_LOG = """\
--- Episode 0 ---
PLACE_NEW id=0
step=0 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
    state_text: x
PLACE_NEW id=1
PLACE_TRANSITION 0 -> 1 action=move_forward
step=8 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
    state_text: x
PLACE_MATCH id=0 visits=2
PLACE_TRANSITION 1 -> 0 action=turn_left
step=16 Jev -> turn_left | red_mean=40.0 | enemy_visible=no
    state_text: x
STAGNATION=YES route=0,1,0,1,0
Episode 0 done: hits=0, final_health=100, steps=24
"""


class TestVisualDiagnostics(unittest.TestCase):
    def test_counts_place_lines(self):
        eps = analyze.split_episodes(VISUAL_LOG.splitlines())
        r = analyze.analyze_episode(eps[0])
        self.assertEqual(r["V1_place_new"], 2)
        self.assertEqual(r["V1_place_revisit"], 1)
        self.assertEqual(r["V2_place_transitions"], 2)
        self.assertEqual(r["V3_visual_stagnation"], 1)


class TestParseEpisodeEnd(unittest.TestCase):
    """level_clear は fail closed。exit_candidate は根拠にしない"""

    def test_level_clear(self):
        r = analyze.parse_episode_end(
            "Episode 0 done: hits=0, exit_candidate=1, died=0, level_clear=1, end_reason=level_clear, timeout_reached=0")
        self.assertEqual((r["end_reason"], r["level_clear"], r["timeout_reached"]), ("level_clear", 1, 0))

    def test_death_and_timeout(self):
        for reason in ("death", "timeout", "aborted", "unknown"):
            r = analyze.parse_episode_end(f"Episode 0 done: level_clear=0, end_reason={reason}")
            self.assertEqual((r["end_reason"], r["level_clear"]), (reason, 0))

    def test_legacy_log_without_fields_is_unknown(self):
        # 旧ログ: exit_candidate=1 でも level_clear にしない
        r = analyze.parse_episode_end("Episode 0 done: hits=0, i_exit=0, exit_candidate=1, died=0")
        self.assertEqual((r["end_reason"], r["level_clear"], r["timeout_reached"]), ("unknown", 0, None))

    def test_inconsistent_fields_fail_closed(self):
        for line in ("level_clear=1, end_reason=timeout", "level_clear=0, end_reason=level_clear",
                     "level_clear=1", "level_clear=1, end_reason=exit_candidate"):
            r = analyze.parse_episode_end(f"Episode 0 done: {line}")
            self.assertEqual((r["end_reason"], r["level_clear"]), ("unknown", 0), line)


class TestCompare(unittest.TestCase):
    def test_effect_size(self):
        self.assertAlmostEqual(compare.effect_size([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]), 5 / math.sqrt(2.5))
        self.assertEqual(compare.effect_size([2, 2], [2, 2]), 0.0)
        self.assertEqual(compare.effect_size([2, 2], [3, 3]), math.inf)
        self.assertIsNone(compare.effect_size([1], [2, 3]))

    def test_welch_p_known_value(self):
        # t = -5, df = 8 の両側 p ≈ 0.00105
        self.assertAlmostEqual(compare.welch_p([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]), 0.001053, places=5)
        self.assertAlmostEqual(compare.welch_p([1, 2, 3], [1, 2, 3]), 1.0, places=6)

    def test_verdict_uses_direction(self):
        self.assertEqual(compare.verdict(2.0, +1), "改善候補")
        self.assertEqual(compare.verdict(2.0, -1), "悪化候補")  # 被ダメージが増えた
        self.assertEqual(compare.verdict(-0.3, +1), "効果なし")
        self.assertEqual(compare.verdict(1.0, +1), "保留（追加実走）")
        self.assertEqual(compare.verdict(5.0, 0), "記録のみ")

    def test_compare_pools_episodes(self):
        def ep(kills, dmg):
            return {"kills": kills, "damage_taken": dmg, "hits": 1, "final_health": 50, "steps": 2100,
                    "i_exit": 0, "kills_total": 18, "visited_cells": 10, "ammo_used": 10, "dmg_hits": 3}
        rows = {r["metric"]: r for r in compare.compare(
            [ep(1, 60), ep(2, 50), ep(1, 55)], [ep(5, 20), ep(6, 25), ep(5, 30)])}
        self.assertEqual(rows["kills"]["verdict"], "改善候補")
        self.assertEqual(rows["damage_taken"]["verdict"], "改善候補")
        self.assertEqual(rows["kills"]["new"], [5.0, 6.0, 5.0])


class TestDecide(unittest.TestCase):
    def _rows(self, **verdicts):
        return [{"metric": m, "verdict": v} for m, v in verdicts.items()]

    def test_primary_verdict_is_used(self):
        self.assertEqual(compare.decide(self._rows(score="改善候補", kills="効果なし", damage_taken="効果なし")),
                         "改善候補")
        self.assertEqual(compare.decide(self._rows(score="保留（追加実走）")), "保留（追加実走）")

    def test_guard_overrides_primary(self):
        # スコアが上がっても被ダメージが悪化候補なら採用しない
        self.assertEqual(compare.decide(self._rows(score="改善候補", damage_taken="悪化候補")), "悪化候補")
        self.assertEqual(compare.decide(self._rows(score="改善候補", kills="悪化候補")), "悪化候補")

    def test_missing_primary(self):
        self.assertEqual(compare.decide([]), "判定不可")


if __name__ == "__main__":
    unittest.main()
