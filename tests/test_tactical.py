"""Tests for train/tactical_movement.py の Jev への委譲。"""
import unittest

from train.tactical_movement import TacticalController, TacticalState


class TestJevDelegation(unittest.TestCase):
    def test_advance_delegates_two_of_eight_steps_to_jev(self):
        ctl = TacticalController()
        ctl.state, ctl.state_ticks = TacticalState.ADVANCE, -1  # 次の update で ADVANCE の0ステップ目
        actions = [
            ctl.update(enemy_visible=False, front_blocked=False, position=(30.0 * i, 0.0))["action"]
            for i in range(8)
        ]
        self.assertEqual(actions.count(None), 2)
        self.assertEqual(actions.count("move_forward"), 6)

    def test_combat_is_decided_by_jev(self):
        # D2 決定（2026-09-23）: COMBAT 時は attack 強制が正。Jev 委譲の旧期待を更新
        ctl = TacticalController()
        order = ctl.update(enemy_visible=True, front_blocked=False, position=(0.0, 0.0))
        self.assertEqual(ctl.state, TacticalState.COMBAT)
        self.assertEqual(order["action"], "attack")


if __name__ == "__main__":
    unittest.main()
