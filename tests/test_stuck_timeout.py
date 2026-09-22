"""stuck_timeout（半径128単位・80tic・中心固定・円を出たら数え直し・留まれば80ticごとに加算）のテスト。"""
import sys
import types
import unittest

sys.modules.setdefault("vizdoom", types.ModuleType("vizdoom"))

from train.jev_agent import state_to_text  # noqa: E402
from train.state_utils import STAGNATION_RADIUS, STUCK_TIMEOUT_TICS, StuckTimeoutDetector  # noqa: E402


def _feed(det, positions, step=8):
    """8tic ごと（frame_skip=8）に位置を与え、発火した tic のリストを返す"""
    fired = []
    for k, pos in enumerate(positions):
        if det.update(pos, k * step):
            fired.append(k * step)
    return fired


class TestStuckTimeout(unittest.TestCase):
    def test_constants_follow_spec(self):
        self.assertEqual(STAGNATION_RADIUS, 128.0)  # AreaStagnationDetector と共有
        self.assertEqual(STUCK_TIMEOUT_TICS, 80)

    def test_fires_after_80_tics_and_counts_up(self):
        det = StuckTimeoutDetector()
        fired = _feed(det, [(0.0, 0.0)] * 25)  # 0〜192tic 同じ場所
        self.assertEqual(fired, [80, 160])  # 80tic ごとに再発火（発火後も続行）
        self.assertEqual(det.count, 2)
        self.assertTrue(det.active)

    def test_center_is_fixed_at_start(self):
        # 少しずつ動いても、開始位置から 128 以内ならカウントは続く
        det = StuckTimeoutDetector()
        fired = _feed(det, [(10.0 * k, 0.0) for k in range(12)])  # 最大 110 単位
        self.assertEqual(fired, [80])

    def test_leaving_radius_resets_with_new_center(self):
        det = StuckTimeoutDetector()
        positions = [(0.0, 0.0)] * 9 + [(200.0, 0.0)] * 11  # 64tic で円を出る → そこから数え直し
        fired = _feed(det, positions)
        self.assertEqual(fired, [72 + 80])  # 新しい円に入った 72tic から 80tic 後
        self.assertEqual(det.center, (200.0, 0.0))

    def test_not_active_after_leaving(self):
        det = StuckTimeoutDetector()
        _feed(det, [(0.0, 0.0)] * 12)
        self.assertTrue(det.active)
        det.update((500.0, 0.0), 200)
        self.assertFalse(det.active)
        self.assertEqual(det.count, 1)  # 回数は残る


class TestStateTextField(unittest.TestCase):
    def test_field(self):
        self.assertIn("stuck_timeout=yes", state_to_text(None, [100], stuck_timeout=True)[0])
        self.assertIn("stuck_timeout=no", state_to_text(None, [100], stuck_timeout=False)[0])
        self.assertNotIn("stuck_timeout", state_to_text(None, [100])[0])


if __name__ == "__main__":
    unittest.main()
