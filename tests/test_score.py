"""Tests for tools/score_report.py (scenario-aware scoring)."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "score_report", Path(__file__).parent.parent / "tools" / "score_report.py"
)
score_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score_mod)
compute_score = score_mod.compute_score


def _report(scenario="deadly_corridor", n=5, hits=2.0, health=30.0, steps=100.0,
            kills=0.0, visited_cells=0.0, max_distance=0.0):
    return {
        "scenario": scenario,
        "summary": {
            "n_episodes": n,
            "avg_hits": hits,
            "avg_health": health,
            "avg_steps": steps,
            "avg_kills": kills,
            "avg_visited_cells": visited_cells,
            "avg_max_distance": max_distance,
        },
    }


class TestScoreReport(unittest.TestCase):
    def test_corridor_formula_unchanged(self):
        # 既存式：-hits*100 + health - steps*0.1
        self.assertAlmostEqual(compute_score(_report()), -200 + 30 - 10)

    def test_full_map_kills_cells_hits_health(self):
        # full_map：kills*500 + visited_cells*10 - hits*100 + health（max_distance・steps・タイムアウトは使わない）
        self.assertAlmostEqual(
            compute_score(_report(scenario="full_map", kills=2.0, visited_cells=8.0,
                                  max_distance=900.0, steps=2100.0)),
            1000 + 80 - 200 + 30,
        )

    def test_full_map_exit_and_full_clear_are_per_episode(self):
        # D3: EXIT・全滅も他の項と同じくエピソード平均。5回中1回 EXIT・1回全滅なら +2000 +1000
        report = _report(scenario="full_map", kills=2.0, visited_cells=8.0)
        report["summary"].update({"avg_i_exit": 0.2, "exits": 1, "full_clears": 1})
        self.assertAlmostEqual(compute_score(report), 1000 + 80 - 200 + 30 + 2000 + 1000)

    def test_full_map_every_episode_cleared(self):
        # 全エピソードで全滅して EXIT → SSOT §3 の 1エピソード分のボーナス（10000 + 5000）
        report = _report(scenario="full_map", kills=18.0, hits=0.0, health=100.0)
        report["summary"].update({"avg_i_exit": 1.0, "exits": 5, "full_clears": 5})
        self.assertAlmostEqual(compute_score(report), 9000 + 100 + 10000 + 5000)

    def test_invalid_run_fails(self):
        report = _report(scenario="full_map", kills=2.0)
        report["valid"] = False
        self.assertEqual(compute_score(report), -999999.0)

    def test_short_run_fails(self):
        # クラッシュ等でエピソード不足 → -999999
        self.assertEqual(compute_score(_report(n=3)), -999999.0)

    def test_malformed_report_fails(self):
        self.assertEqual(compute_score({}), -999999.0)
        self.assertEqual(compute_score({"summary": {}}), -999999.0)


if __name__ == "__main__":
    unittest.main()
