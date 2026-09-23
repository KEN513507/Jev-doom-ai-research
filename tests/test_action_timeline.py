"""行動タイムライン（train/action_timeline.py・tools/analyze_timeline.py）のテスト。"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.action_timeline import ActionTimeline
from train.jev_agent import execute_action

_spec = importlib.util.spec_from_file_location(
    "analyze_timeline", Path(__file__).parent.parent / "tools" / "analyze_timeline.py")
analyze_timeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze_timeline)


class FakeGame:
    """make_action で tic を進め、指定 tic に HP を減らす"""

    def __init__(self, damage_at=None):
        self.tic, self.health, self.calls = 0, 100, []
        self.damage_at = damage_at or {}

    def make_action(self, action, tics):
        self.calls.append((list(action), tics))
        for _ in range(tics):
            self.tic += 1
            self.health -= self.damage_at.get(self.tic, 0)
        return 0.0

    def get_episode_time(self):
        return self.tic

    def is_episode_finished(self):
        return False


class TestActionTimeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t_timeline.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, game, **exec_kw):
        tl = ActionTimeline(game, self.path, run_id="r1", read_health=lambda: game.health)
        tl.begin(episode=0, decision_index=3, decision_source="jev")
        execute_action(tl, [1, 0, 0], 8, **exec_kw)
        tl.close()
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_one_segment_per_make_action_and_calls_unchanged(self):
        game = FakeGame()
        recs = self._run(game)
        self.assertEqual(game.calls, [([1, 0, 0], 8)])  # プロキシ経由でも make_action は同じ
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["tic_before_action"], recs[0]["tic_after_action"], recs[0]["delta_tic"]), (0, 8, 8))
        self.assertEqual((recs[0]["run_id"], recs[0]["decision_index"], recs[0]["segment_index"]), ("r1", 3, 0))

    def test_tap_splits_into_press_and_release(self):
        game = FakeGame(damage_at={5: 20})  # release 側（tic 2〜8）で被弾
        recs = self._run(game, tap=True)
        self.assertEqual(game.calls, [([1, 0, 0], 1), ([0, 0, 0], 7)])
        self.assertEqual([r["delta_tic"] for r in recs], [1, 7])
        self.assertEqual([r["executed_buttons"] for r in recs], [[1, 0, 0], [0, 0, 0]])
        self.assertEqual([r["health_loss"] for r in recs], [0, 20])
        self.assertEqual([r["segment_index"] for r in recs], [0, 1])

    def test_health_loss_ignores_gain(self):
        game = FakeGame(damage_at={2: -25})  # 回復は被ダメージにしない
        recs = self._run(game)
        self.assertEqual(recs[0]["health_loss"], 0)


class TestAnalyzeTimeline(unittest.TestCase):
    def _rec(self, di, seg, src, loss=0, delta=8, tb=None, ta=None, lat=None):
        return {"run_id": "r1", "episode": 0, "decision_index": di, "segment_index": seg,
                "decision_source": src, "tic_before_jev": tb, "tic_after_jev": ta, "jev_latency_ms": lat,
                "delta_tic": delta, "health_loss": loss, "decision_action": "attack",
                "executed_action": "attack", "rewritten_by": [], "enemy_types": []}

    def test_summary(self):
        recs = [
            self._rec(0, 0, "jev", tb=0, ta=0, lat=200.0),
            self._rec(1, 0, "forced_attack", loss=10),
            self._rec(2, 0, "jev", delta=1, tb=16, ta=17, lat=300.0),
            self._rec(2, 1, "jev", delta=7, loss=30, tb=16, ta=17, lat=300.0),
            self._rec(3, 0, "skip", lat=1000.0),
        ]
        s = analyze_timeline.summarize(recs)
        self.assertEqual((s["records"], s["decisions"]), (5, 4))
        self.assertEqual((s["jev_decisions"], s["forced_attack_decisions"], s["skip_decisions"]), (2, 1, 1))
        self.assertEqual(s["jev_wait_tic_advanced_count"], 1)  # 判断単位で1回
        self.assertEqual(s["median_jev_latency_ms"], 300.0)
        self.assertEqual(s["delta_tic_distribution"], {1: 1, 7: 1, 8: 3})
        self.assertEqual(s["health_loss_event_count"], 2)
        self.assertEqual(s["top_damage_windows"][0]["health_loss"], 30)


if __name__ == "__main__":
    unittest.main()
