"""open_directions（3方向の開け具合）のテスト。境界・閾値は WallAvoider と共通。"""
import unittest

import numpy as np

from train.state_utils import OPEN_FAR_DEPTH, WALL_NEAR_DEPTH, open_directions


def _depth(left, center, right, h=120, w=160):
    d = np.full((h, w), 63, dtype=np.uint8)
    d[:, : w * 2 // 5] = left
    d[:, w * 2 // 5: w * 3 // 5] = center
    d[:, w * 3 // 5:] = right
    return d


class TestOpenDirections(unittest.TestCase):
    def test_categories(self):
        r = open_directions(_depth(left=40, center=3, right=12))
        self.assertEqual(r, {"open_left": "far", "open_center": "near", "open_right": "mid"})

    def test_thresholds_are_inclusive_for_near(self):
        r = open_directions(_depth(left=WALL_NEAR_DEPTH, center=OPEN_FAR_DEPTH, right=OPEN_FAR_DEPTH + 1))
        self.assertEqual(r, {"open_left": "near", "open_center": "mid", "open_right": "far"})

    def test_only_eye_level_band_counts(self):
        # 床・天井が近くても目線の高さが遠ければ far
        d = np.full((120, 160), 2, dtype=np.uint8)
        d[57:63, :] = 50
        self.assertEqual(set(open_directions(d).values()), {"far"})


if __name__ == "__main__":
    unittest.main()
