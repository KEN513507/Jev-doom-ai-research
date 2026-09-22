"""ViZDoom状態表現の共通ユーティリティ。

calib_red.py と jev_agent.py は必ずこのモジュールを使うこと。
スライス範囲を変更する場合は、ここだけを編集する。
"""
import math
import re
from collections import deque

# 画面解像度（この値に依存してスライスが決まる）
USE_RESOLUTION = "RES_160X120"

# 解像度ごとのスライス範囲（HUD除外 + 中央部）
# NumPy配列 [C, H, W]: H=0 が画面上部（天井）、H=最大 が下部（HUD・床）
SLICE_CONFIG = {
    "RES_320X240": {
        "hud_excluded": (slice(None), slice(0, 200), slice(None)),   # 上部0-199
        "center":       (slice(None), slice(40, 180), slice(None)),  # 中央40-179
    },
    "RES_160X120": {
        "hud_excluded": (slice(None), slice(0, 100), slice(None)),   # 上部0-99
        "center":       (slice(None), slice(20, 90), slice(None)),   # 中央20-89
    },
}

# 使用する領域（"hud_excluded" or "center"）
ACTIVE_REGION = "center"

# 赤強度の閾値（calib_v2: baseline 41.6, enemy 52-65）
ENEMY_RED_THRESHOLD = 48.0


def get_slice():
    """現在の解像度と領域設定に基づくスライスを返す"""
    return SLICE_CONFIG[USE_RESOLUTION][ACTIVE_REGION]


# labels_buffer で敵と判定する種類（deadly_corridor実測：Zombieman, ShotgunGuy, ChaingunGuy）
# freedoom2 map01 実測：Zombieman, ShotgunGuy, DoomImp
ENEMY_NAMES = frozenset({
    "Zombieman",
    "ShotgunGuy",
    "ChaingunGuy",
    "Imp",
    "DoomImp",
    "Demon",
    "Cacodemon",
    "HellKnight",
    "Baron",
    "Revenant",
    "Arachnotron",
    "Mancubus",
    "Archvile",
})

# 画面中央とみなす許容幅（画面幅に対する割合の半分）
CENTER_TOLERANCE_RATIO = 0.1  # 0.2 -> 0.1 (実測: 側面の敵を centered=no と正しく判定)


def _no_enemy():
    return {
        "enemy_visible": False,
        "enemy_count": 0,
        "enemy_names": [],
        "enemy_centered": False,
        "nearest_enemy_x": None,
        "nearest_enemy_width": None,
    }


# 視認とみなす最小ラベル幅（px）。これ未満の極小ラベル（遠方・端の敵）は無視する。
# 実測：Zombieman/ShotgunGuy は幅8以上で出現、ChaingunGuy は幅0で出現。
MIN_ENEMY_WIDTH = 8.0


def detect_enemy_from_labels(state, min_width: float = 0.0) -> dict:
    """labels_buffer から敵情報を抽出する（red_mean より正確）。

    state が labels を持たない場合（無効時など）は全 False を返す。
    min_width を指定すると、それ未満の幅のラベルは視認不可として無視する。
    ただし width==0 のラベルは、x座標が画面内なら有効とする
    （ChaingunGuy など、ViZDoom のラベル幅が0になるケースへの対応）。
    """
    labels = getattr(state, "labels", None) if state is not None else None
    if not labels:
        return _no_enemy()

    try:
        screen_w = float(state.screen_buffer.shape[2])
    except Exception:
        screen_w = float(USE_RESOLUTION.split("X")[0])

    enemies = []
    for lb in labels:
        if getattr(lb, "object_name", None) not in ENEMY_NAMES:
            continue
        if min_width > 0:
            try:
                w = float(lb.width)
            except Exception:
                continue
            if w == 0.0:
                # width==0 でも x が画面内なら有効（ChaingunGuy 等の対応）
                try:
                    x = float(lb.x)
                except Exception:
                    continue
                if not 0.0 <= x < screen_w:
                    continue
            elif w < min_width:
                continue
        enemies.append(lb)
    if not enemies:
        return _no_enemy()

    center_x = screen_w / 2.0

    def _center(lb):
        try:
            return float(lb.x) + float(lb.width) / 2.0
        except Exception:
            return center_x

    nearest = min(enemies, key=lambda lb: abs(_center(lb) - center_x))
    nearest_center = _center(nearest)
    try:
        nearest_width = float(nearest.width)
    except Exception:
        nearest_width = None

    return {
        "enemy_visible": True,
        "enemy_count": len(enemies),
        "enemy_names": [lb.object_name for lb in enemies],
        "enemy_centered": abs(nearest_center - center_x) < screen_w * CENTER_TOLERANCE_RATIO,
        "nearest_enemy_x": nearest_center,
        "nearest_enemy_width": nearest_width,
    }


def compute_red_metrics(screen_buffer, threshold: float = ENEMY_RED_THRESHOLD):
    """画面バッファから red_mean と enemy_visible を計算する"""
    if screen_buffer is None:
        return 0.0, False
    try:
        import numpy as np

        region = np.asarray(screen_buffer)[get_slice()]
        red_mean = float(region[0].mean())
    except Exception:
        return 0.0, False
    enemy_visible = red_mean > threshold
    return red_mean, enemy_visible


def build_state_text(game_vars, red_mean, enemy_visible):
    """Jevへ渡す state_text を組み立てる"""
    parts = []
    for i, v in enumerate(game_vars):
        try:
            parts.append(f"var{i}={float(v):.0f}")
        except (TypeError, ValueError):
            parts.append(f"var{i}={v}")
    parts.append(f"red_mean={red_mean:.1f}")
    parts.append(f"enemy_visible={'yes' if enemy_visible else 'no'}")
    context = (
        "You are playing DOOM. Your goal is to progress through the level and survive. "
        "Balance offense and movement. Do not attack blindly when no enemy is visible."
    )
    return f"{context} Current state: {', '.join(parts) if parts else 'unknown'}"


# front_blocked 判定：move_forward を BLOCKED_WINDOW 判断ステップ続けても
# 合計移動量が BLOCKED_MAX_DISTANCE 未満なら前方が塞がれている（壁・閉じたドア）とみなす。
# 実測（freedoom2 map01, frame_skip=4）：自由移動 約29単位/ステップ、ドア前 0。
# 静止からの歩き出しは 0→1→9 単位と遅く、3ステップ窓では合計≈10で誤検知の余地が小さいため 4。
BLOCKED_WINDOW = 4
BLOCKED_MAX_DISTANCE = 8.0


class ForwardBlockDetector:
    def __init__(self, window: int = BLOCKED_WINDOW, max_distance: float = BLOCKED_MAX_DISTANCE):
        self.window = window
        self.max_distance = max_distance
        self.positions = deque(maxlen=window + 1)

    def update(self, position, last_action) -> bool:
        """position: 現在の (x, y)。last_action: 前回の観測から今回までに実行した行動。"""
        if last_action != "move_forward":
            self.positions.clear()
        self.positions.append(position)
        if len(self.positions) <= self.window:
            return False
        (x0, y0), (x1, y1) = self.positions[0], self.positions[-1]
        return math.hypot(x1 - x0, y1 - y0) < self.max_distance


# area_stagnation 判定：直近 STAGNATION_WINDOW 判断ステップ（frame_skip=4 で 176tic ≈ ゲーム内5秒）の
# 位置がすべて重心から STAGNATION_RADIUS 単位以内なら、同じ狭い範囲に留まっているとみなす
STAGNATION_WINDOW = 44
STAGNATION_RADIUS = 128.0


class AreaStagnationDetector:
    def __init__(self, window: int = STAGNATION_WINDOW, radius: float = STAGNATION_RADIUS):
        self.radius = radius
        self.positions = deque(maxlen=window)

    def update(self, position) -> bool:
        self.positions.append(position)
        if len(self.positions) < self.positions.maxlen:
            return False
        n = len(self.positions)
        cx = sum(x for x, _ in self.positions) / n
        cy = sum(y for _, y in self.positions) / n
        if all(math.hypot(x - cx, y - cy) < self.radius for x, y in self.positions):
            self.positions.clear()  # 発火後は窓を貯め直し、毎ステップの連続発火を防ぐ
            return True
        return False


# 鍵に関する通知（取得・鍵付きドア）。Freedoom 実測: "Blue passcard secured!"
KEY_EVENT_PATTERN = re.compile(r"passcard|keycard|skull ?key|\bkeys?\b", re.IGNORECASE)


def extract_key_events(notifications: str | None) -> list[str]:
    """notifications_buffer から鍵関連の行だけを返す（体力ボーナス等の取得通知は除外）"""
    if not notifications:
        return []
    return [line.strip() for line in notifications.splitlines() if KEY_EVENT_PATTERN.search(line)]
