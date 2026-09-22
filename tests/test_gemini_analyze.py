"""tools/gemini_analyze.py の補助関数（履歴・state_text の例）のテスト。API は呼ばない。"""
import importlib.util
import json
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    _spec = importlib.util.spec_from_file_location(
        "gemini_analyze", Path(__file__).parent.parent / "tools" / "gemini_analyze.py"
    )
    ga = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ga)

LOG = """\
--- Episode 0 ---
step=0 Jev -> move_forward | red_mean=40.0 | enemy_visible=no
    state_text: You are playing DOOM. Current state: var0=100, enemy_visible=no, open_left=far
step=8 Jev -> attack | red_mean=50.0 | enemy_visible=yes
    state_text: You are playing DOOM. Current state: var0=90, enemy_visible=yes, enemy_side=left
"""


def _report(tmp: Path, name="r1", criteria="tactical_peeking", scenario="full_map"):
    log = tmp / f"{name}.log"
    log.write_text(LOG)
    report = {
        "criteria": criteria, "scenario": scenario, "log_path": str(log),
        "summary": {"avg_kills": 4.0, "avg_damage_taken": 73.8, "avg_visited_cells": 22.4,
                    "avg_hits": 7.8, "avg_i_exit": 0.0, "full_clears": 0, "seeds": [1000, 1001]},
        "episodes": [{"diag": {"B5_offscreen_hit_rate": 0.6}}, {"diag": {"B5_offscreen_hit_rate": 0.8}}],
    }
    path = tmp / f"{name}.json"
    path.write_text(json.dumps(report))
    return path, report


class TestStateSamples(unittest.TestCase):
    def test_takes_one_with_and_without_enemy(self):
        with tempfile.TemporaryDirectory() as d:
            _, report = _report(Path(d))
            text = ga._state_samples(report)
        self.assertIn("敵なし: `Current state: var0=100, enemy_visible=no, open_left=far`", text)
        self.assertIn("敵あり: `Current state: var0=90, enemy_visible=yes, enemy_side=left`", text)
        self.assertNotIn("You are playing DOOM", text)

    def test_missing_log(self):
        self.assertIn("例なし", ga._state_samples({"log_path": "/nonexistent.log"}))


class TestProposedCriteria(unittest.TestCase):
    def test_both_command_styles(self):
        self.assertEqual(ga.proposed_criteria("python train/jev_agent.py --criteria tactical_x --use-labels"), "tactical_x")
        self.assertEqual(ga.proposed_criteria("./tools/run_and_report.sh tactical_y --scenario full_map"), "tactical_y")
        self.assertIsNone(ga.proposed_criteria("(人間の判断が必要)"))


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._orig = ga.HISTORY_FILE
        ga.HISTORY_FILE = self.dir / "history.jsonl"

    def tearDown(self):
        ga.HISTORY_FILE = self._orig
        self.tmp.cleanup()

    def _result(self, name="tactical_clearing"):
        return {"primary_issue": "画面外からの被弾", "solvable_by_criteria": True,
                "recommended_actions": [{"action_type": "criteria_edit", "description": "索敵を優先"}],
                "next_iteration_command": f"./tools/run_and_report.sh --criteria {name} --seed 1000"}

    def test_entry_summarizes_result_and_proposal(self):
        path, report = _report(self.dir)
        e = ga._history_entry(path, report, self._result())
        self.assertEqual(e["criteria"], "tactical_peeking")
        self.assertEqual(e["proposed_criteria"], "tactical_clearing")
        self.assertEqual(e["result"]["B5_offscreen_hit_rate"], 0.7)
        self.assertEqual(e["result"]["damage_taken"], 73.8)

    def test_save_replaces_same_report_and_filters_scenario(self):
        p1, r1 = _report(self.dir, "r1")
        p2, r2 = _report(self.dir, "r2", scenario="deadly_corridor")
        ga.save_history(ga._history_entry(p1, r1, self._result("a")))
        ga.save_history(ga._history_entry(p1, r1, self._result("b")))  # 再分析は置き換え
        ga.save_history(ga._history_entry(p2, r2, self._result("c")))
        hist = ga.load_history("full_map")
        self.assertEqual([h["proposed_criteria"] for h in hist], ["b"])
        # 分析対象のレポート自身は履歴から除く
        self.assertEqual(ga.load_history("full_map", exclude_report=str(p1.resolve())), [])

    def test_history_is_limited(self):
        for i in range(ga.HISTORY_LIMIT + 3):
            p, r = _report(self.dir, f"r{i}")
            ga.save_history(ga._history_entry(p, r, self._result(f"c{i}")))
        hist = ga.load_history("full_map")
        self.assertEqual(len(hist), ga.HISTORY_LIMIT)
        self.assertEqual(hist[-1]["proposed_criteria"], f"c{ga.HISTORY_LIMIT + 2}")

    def test_prompt_formats(self):
        # プロンプトの {} が壊れていないこと（JSON 例の {{ }} と差し込み位置）
        text = ga.PROMPT_TEMPLATE.format(report_json="{}", criteria_names="x", test_items="t",
                                         state_samples="s", history="h")
        self.assertIn('"solvable_by_criteria": true', text)
        self.assertIn("## これまでの分析と結果の履歴", text)


if __name__ == "__main__":
    unittest.main()
