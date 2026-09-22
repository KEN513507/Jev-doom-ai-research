"""修正B（use 失敗検出・ドア待機の早期解除）の再現テスト。

実走では同じ場所で use を繰り返す状況が起きなかったため、ここで人工的に作る。
"""
import unittest

import numpy as np

from train.state_utils import (
    DOOR_NO_CHANGE_TICS,
    USE_SPOT_RADIUS,
    UseFailDetector,
    center_depth,
    door_wait_verdict,
)


class TestUseFailDetector(unittest.TestCase):
    def test_repeated_use_at_same_spot_turns(self):
        det = UseFailDetector(limit=2)
        pos = (100.0, 200.0)
        self.assertEqual(det.filter("use", pos), "use")          # 1回目: 試す
        self.assertEqual(det.filter("use", pos), "use")          # 2回目: 1回目が失敗（動けていない）
        self.assertEqual(det.filter("use", pos), "turn_right")   # 3回目: 2回失敗したので離れる

    def test_small_jitter_still_counts_as_same_spot(self):
        det = UseFailDetector(limit=2)
        det.filter("use", (100.0, 200.0))
        det.filter("use", (105.0, 203.0))
        self.assertEqual(det.filter("use", (98.0, 199.0)), "turn_right")

    def test_moving_away_resets(self):
        # use の後に通れた（地点から離れた）なら失敗ではない
        det = UseFailDetector(limit=2)
        det.filter("use", (0.0, 0.0))
        det.filter("use", (0.0, 0.0))
        far = (USE_SPOT_RADIUS + 1.0, 0.0)
        det.filter("move_forward", far)
        self.assertEqual(det.filter("use", far), "use")
        self.assertEqual(det.filter("use", far), "use")

    def test_counter_resets_after_turning(self):
        det = UseFailDetector(limit=2)
        pos = (0.0, 0.0)
        for _ in range(2):
            det.filter("use", pos)
        self.assertEqual(det.filter("use", pos), "turn_right")
        self.assertEqual(det.filter("use", pos), "use")  # 旋回後は数え直し

    def test_other_actions_pass_through(self):
        det = UseFailDetector()
        self.assertEqual(det.filter("attack", (0.0, 0.0)), "attack")


class TestDoorWaitVerdict(unittest.TestCase):
    def test_depth_gain_means_opened(self):
        self.assertEqual(door_wait_verdict(5.0, 60.0, 4), "opened")

    def test_no_change_after_wait_means_no_door(self):
        self.assertEqual(door_wait_verdict(5.0, 5.0, DOOR_NO_CHANGE_TICS), "no_door")

    def test_keep_waiting_before_deadline(self):
        self.assertIsNone(door_wait_verdict(5.0, 5.0, DOOR_NO_CHANGE_TICS - 4))

    def test_slow_opening_keeps_waiting(self):
        # 開き始め（+1〜+2）は判定を保留して待ち続ける
        self.assertIsNone(door_wait_verdict(5.0, 7.0, DOOR_NO_CHANGE_TICS))

    def test_center_depth_uses_center_band(self):
        d = np.full((120, 160), 63, dtype=np.uint8)
        d[57:63, 64:96] = 3  # 目線の高さ・中央だけ壁が近い
        self.assertEqual(center_depth(d), 3.0)


if __name__ == "__main__":
    unittest.main()
