"""座標を使わない視覚的な場所記憶（Sprint 1: ログのみ、行動は変えない）。

目的: 「visited_cells（座標グリッド）が少ないのは、実際には同じ場所を視覚的に往復しているからか」
を、座標を一切使わずに検証する。VisualMemory は screen_buffer の埋め込みだけで場所の同一性を判定する。

embedding の定義（2026-09-23 決定、要調整）:
  screen_buffer を GRID_H x GRID_W のブロックにグレースケール平均プーリングし、[0,1] に正規化して
  フラット化したベクトル（次元 = GRID_H*GRID_W）。CNN 等の学習済みモデルは使わない（GPU 不要・決定論的）。
  match_threshold はプレースホルダー値。実走ログで距離の分布を見てから調整する。
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

GRID_H = 12
GRID_W = 16
EMBEDDING_DIM = GRID_H * GRID_W
DEFAULT_MATCH_THRESHOLD = 0.05  # 要調整。実走の距離分布から見直す

STAGNATION_WINDOW = 40
STAGNATION_MAX_UNIQUE = 3
STAGNATION_MIN_TRANSITIONS = 10


def compute_embedding(screen_buffer) -> list[float] | None:
    """screen_buffer（[C,H,W]、0-255）から GRID_H×GRID_W のグレースケール平均プーリング embedding を作る"""
    if screen_buffer is None:
        return None
    arr = np.asarray(screen_buffer, dtype=np.float32)
    gray = arr.mean(axis=0)  # [C,H,W] -> [H,W]（チャンネル平均）
    h, w = gray.shape
    bh, bw = h // GRID_H, w // GRID_W
    if bh == 0 or bw == 0:
        return None
    cropped = gray[: bh * GRID_H, : bw * GRID_W]
    pooled = cropped.reshape(GRID_H, bh, GRID_W, bw).mean(axis=(1, 3))
    return (pooled.flatten() / 255.0).tolist()


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


@dataclass
class PlaceNode:
    id: int
    embedding: list[float]
    visit_count: int = 0
    last_seen_step: int = 0


@dataclass
class Edge:
    source: int
    target: int
    action: str
    count: int = 1


class VisualMemory:
    """embedding の類似度だけで「既知の場所か」を判定する（座標不使用）"""

    def __init__(self, match_threshold: float = DEFAULT_MATCH_THRESHOLD):
        self.nodes: list[PlaceNode] = []
        self.current_place_id: int | None = None
        self.match_threshold = match_threshold

    def find_place(self, embedding: list[float]) -> PlaceNode | None:
        best_node, best_distance = None, float("inf")
        for node in self.nodes:
            d = cosine_distance(embedding, node.embedding)
            if d < best_distance:
                best_distance, best_node = d, node
        if best_distance <= self.match_threshold:
            return best_node
        return None

    def update(self, embedding: list[float], step: int) -> tuple[PlaceNode, bool]:
        """(node, is_new) を返す"""
        node = self.find_place(embedding)
        is_new = node is None
        if is_new:
            node = PlaceNode(id=len(self.nodes), embedding=embedding)
            self.nodes.append(node)
        node.visit_count += 1
        node.last_seen_step = step
        self.current_place_id = node.id
        return node, is_new


class TopologicalMap:
    """場所間の遷移（座標なし）を記録する"""

    def __init__(self):
        self.edges: dict[tuple[int, int, str], Edge] = {}

    def record_transition(self, previous_place: int | None, current_place: int, action: str | None) -> None:
        if previous_place is None or previous_place == current_place or action is None:
            return
        key = (previous_place, current_place, action)
        if key not in self.edges:
            self.edges[key] = Edge(source=previous_place, target=current_place, action=action)
        else:
            self.edges[key].count += 1


class PlaceStagnationDetector:
    """直近 window 回の場所IDを見て、少数の場所を往復しているかを判定する（AreaStagnationDetector の座標なし版）"""

    def __init__(self, window: int = STAGNATION_WINDOW, max_unique: int = STAGNATION_MAX_UNIQUE,
                 min_transitions: int = STAGNATION_MIN_TRANSITIONS):
        self.max_unique = max_unique
        self.min_transitions = min_transitions
        self.history: deque[int] = deque(maxlen=window)

    def update(self, place_id: int) -> bool:
        self.history.append(place_id)
        if len(self.history) < self.history.maxlen:
            return False
        unique_places = len(set(self.history))
        transitions = sum(a != b for a, b in zip(self.history, list(self.history)[1:]))
        return unique_places <= self.max_unique and transitions >= self.min_transitions

    def recent_route(self) -> list[int]:
        return list(self.history)
