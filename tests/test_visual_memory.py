"""座標なし視覚記憶（Sprint 1: VisualMemory / TopologicalMap / PlaceStagnationDetector）のテスト。"""
import unittest

import numpy as np

from train.visual_memory import (
    EMBEDDING_DIM,
    GRID_H,
    GRID_W,
    PlaceStagnationDetector,
    TopologicalMap,
    VisualMemory,
    compute_embedding,
    cosine_distance,
)


def _screen(value, h=120, w=160, c=3):
    return np.full((c, h, w), value, dtype=np.uint8)


class TestComputeEmbedding(unittest.TestCase):
    def test_shape_and_range(self):
        emb = compute_embedding(_screen(128))
        self.assertEqual(len(emb), EMBEDDING_DIM)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in emb))

    def test_uniform_screen_is_uniform_embedding(self):
        emb = compute_embedding(_screen(64))
        self.assertTrue(all(abs(v - 64 / 255.0) < 1e-6 for v in emb))

    def test_none_screen(self):
        self.assertIsNone(compute_embedding(None))

    def test_different_screens_differ(self):
        # 左半分だけ明るい画面は、真っ暗な画面と異なる embedding になる
        arr = np.zeros((3, 120, 160), dtype=np.uint8)
        arr[:, :, :80] = 200
        a = compute_embedding(arr)
        b = compute_embedding(_screen(0))
        self.assertGreater(cosine_distance(a, b), 0.1)


class TestVisualMemory(unittest.TestCase):
    def test_first_frame_is_new_place(self):
        mem = VisualMemory()
        node, is_new = mem.update(compute_embedding(_screen(100)), step=0)
        self.assertTrue(is_new)
        self.assertEqual(node.id, 0)
        self.assertEqual(mem.current_place_id, 0)

    def test_same_screen_matches_existing_place(self):
        mem = VisualMemory()
        emb = compute_embedding(_screen(100))
        mem.update(emb, step=0)
        node, is_new = mem.update(emb, step=8)
        self.assertFalse(is_new)
        self.assertEqual(node.id, 0)
        self.assertEqual(node.visit_count, 2)

    def test_different_screen_registers_new_place(self):
        mem = VisualMemory()
        mem.update(compute_embedding(_screen(0)), step=0)
        node, is_new = mem.update(compute_embedding(_screen(255)), step=8)
        self.assertTrue(is_new)
        self.assertEqual(node.id, 1)
        self.assertEqual(len(mem.nodes), 2)

    def test_threshold_boundary(self):
        # 閾値ぎりぎりの微差は同一場所、それを超えると別場所（cosine_distance で確認済みの値を使う）
        mem = VisualMemory(match_threshold=0.05)
        base = compute_embedding(_screen(100))
        mem.update(base, step=0)
        near = [v + 0.001 for v in base]
        self.assertLess(cosine_distance(base, near), 0.05)
        _, is_new_near = mem.update(near, step=8)
        self.assertFalse(is_new_near)
        far = compute_embedding(_screen(0))
        self.assertGreater(cosine_distance(base, far), 0.05)
        _, is_new_far = mem.update(far, step=16)
        self.assertTrue(is_new_far)


class TestTopologicalMap(unittest.TestCase):
    def test_records_transition_with_action(self):
        topo = TopologicalMap()
        topo.record_transition(previous_place=1, current_place=2, action="move_forward")
        edge = topo.edges[(1, 2, "move_forward")]
        self.assertEqual((edge.source, edge.target, edge.count), (1, 2, 1))

    def test_repeated_transition_counts_up(self):
        topo = TopologicalMap()
        for _ in range(3):
            topo.record_transition(1, 2, "move_forward")
        self.assertEqual(topo.edges[(1, 2, "move_forward")].count, 3)

    def test_self_transition_and_missing_action_ignored(self):
        topo = TopologicalMap()
        topo.record_transition(1, 1, "move_forward")
        topo.record_transition(None, 2, "move_forward")
        topo.record_transition(1, 2, None)
        self.assertEqual(topo.edges, {})


class TestPlaceStagnationDetector(unittest.TestCase):
    def test_needs_full_window_before_firing(self):
        det = PlaceStagnationDetector(window=10, max_unique=2, min_transitions=5)
        for i in range(9):
            self.assertFalse(det.update(i % 2))

    def test_fires_on_two_place_ping_pong(self):
        det = PlaceStagnationDetector(window=10, max_unique=2, min_transitions=5)
        result = [det.update(i % 2) for i in range(10)]
        self.assertTrue(result[-1])
        self.assertEqual(det.recent_route(), [i % 2 for i in range(10)])

    def test_no_fire_when_exploring_new_places(self):
        det = PlaceStagnationDetector(window=10, max_unique=2, min_transitions=5)
        result = [det.update(i) for i in range(10)]  # 毎回新しい場所
        self.assertFalse(result[-1])

    def test_no_fire_when_staying_in_one_place(self):
        # unique=1 は「往復」ではなく「同じ場所に留まっている」。transitions=0 なので条件を満たさない
        det = PlaceStagnationDetector(window=10, max_unique=2, min_transitions=5)
        result = [det.update(0) for _ in range(10)]
        self.assertFalse(result[-1])


if __name__ == "__main__":
    unittest.main()
