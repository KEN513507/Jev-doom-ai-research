"""ViZDoom状態表現の共通ユーティリティ。

calib_red.py と jev_agent.py は必ずこのモジュールを使うこと。
スライス範囲を変更する場合は、ここだけを編集する。
"""
import math
import re
from collections import deque

import numpy as np

try:
    from train.scenarios import action_components
except ImportError:
    from scenarios import action_components

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


# 拾える物（体力・アーマー・弾薬・武器・パワーアップ・鍵）。装飾（木・柱・樽・死体）は含めない。
# freedoom2 map01 実測: ArmorBonus, HealthBonus, Stimpack, Medikit, Clip, Shell, Shotgun,
# Chainsaw, GreenArmor, BlueArmor, Soulsphere。残りは Doom 標準の取得物クラス名。
ITEM_NAMES = frozenset({
    "HealthBonus", "Stimpack", "Medikit", "Soulsphere", "Megasphere", "Berserk",
    "ArmorBonus", "GreenArmor", "BlueArmor",
    "Clip", "ClipBox", "Shell", "ShellBox", "RocketAmmo", "RocketBox", "Cell", "CellPack", "Backpack",
    "Chainsaw", "Shotgun", "SuperShotgun", "Chaingun", "RocketLauncher", "PlasmaRifle", "BFG9000",
    "InvulnerabilitySphere", "BlurSphere", "RadSuit", "Infrared", "Allmap",
    "BlueCard", "RedCard", "YellowCard", "BlueSkull", "RedSkull", "YellowSkull",
})


def detect_items_from_labels(state) -> dict:
    """labels_buffer から取得可能アイテムを抽出する（中央判定は敵と同じ基準）"""
    labels = getattr(state, "labels", None) if state is not None else None
    items = [lb for lb in (labels or []) if getattr(lb, "object_name", None) in ITEM_NAMES]
    if not items:
        return {"item_visible": False, "item_centered": False, "item_names": []}
    screen_w = float(state.screen_buffer.shape[2])
    center_x = screen_w / 2.0
    offset = min(abs(float(lb.x) + float(lb.width) / 2.0 - center_x) for lb in items)
    return {
        "item_visible": True,
        "item_centered": offset < screen_w * CENTER_TOLERANCE_RATIO,
        "item_names": sorted({lb.object_name for lb in items}),
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
        if "MOVE_FORWARD" not in action_components(last_action):
            self.positions.clear()
        self.positions.append(position)
        if len(self.positions) <= self.window:
            return False
        (x0, y0), (x1, y1) = self.positions[0], self.positions[-1]
        return math.hypot(x1 - x0, y1 - y0) < self.max_distance


# 壁回避（ゲームAI定番の「前方レイの距離で操舵」を depth_buffer の目線の高さの帯で行う）。
# 実測（160x120, freedoom2 map01）: 深度値 ≈ 壁までの距離/7、接触で1、遠方は63で飽和。
# 7 ≈ 壁の手前44単位 = use が届く距離（USERANGE 64 − 体の半径 16）。
WALL_NEAR_DEPTH = 7
DOOR_WAIT_STEPS = 6  # use 後にドアが目線の高さまで開くのを待つ判断ステップ数（24tic）
USE_SPOT_RADIUS = 32.0


class WallAvoider:
    """前進はドア操作・旋回、複合横移動は移動側の近い壁で射撃のみへ切替。"""

    def __init__(self):
        self.use_pos = None
        self.wait = 0
        self.turn = None

    def filter(self, choice, depth, position, front_blocked=False) -> str:
        components = action_components(choice)
        h, w = depth.shape
        band = depth[h // 2 - 3:h // 2 + 3]
        # 前方カメラの左右端による保守的な検出。真横の空間を保証するものではない。
        # 前方のドア待機中でも横移動側の壁をチェックする。
        if "ATTACK" in components and ("MOVE_LEFT" in components or "MOVE_RIGHT" in components):
            side = band[:, :w // 3] if "MOVE_LEFT" in components else band[:, w * 2 // 3:]
            if np.median(side) <= WALL_NEAR_DEPTH:
                return "attack"
            return choice
        if self.wait > 0:
            self.wait -= 1
            return choice
        if not front_blocked and np.median(band[:, w * 2 // 5:w * 3 // 5]) > WALL_NEAR_DEPTH:
            self.turn = None
            return choice
        if "MOVE_FORWARD" not in components:
            return choice
        if self.use_pos is None or math.dist(position, self.use_pos) >= USE_SPOT_RADIUS:
            self.use_pos = position
            self.wait = DOOR_WAIT_STEPS
            return "use"
        if self.turn is None:  # 角で左右に迷わないよう、開けるまで同じ向きに回る
            self.turn = "turn_left" if band[:, :w // 3].mean() > band[:, w * 2 // 3:].mean() else "turn_right"
        return self.turn


# 修正B: 同じ地点での use 失敗検出。USE_FAIL_LIMIT 回目の use（それまでの use で動けていない）を旋回に置き換える
USE_FAIL_LIMIT = 2


class UseFailDetector:
    def __init__(self, limit: int = USE_FAIL_LIMIT, radius: float = USE_SPOT_RADIUS):
        self.limit = limit
        self.radius = radius
        self.pos = None
        self.fails = 0

    def filter(self, choice: str, position) -> str:
        """同じ地点で use が limit 回失敗していれば "turn_right" を返す。それ以外は choice のまま"""
        if self.pos is not None and math.dist(position, self.pos) >= self.radius:
            self.pos, self.fails = None, 0  # 動けた = 前回の use は成功
        if choice != "use":
            return choice
        if self.pos is None:
            self.pos = position
            return choice
        if self.fails + 1 >= self.limit:
            self.pos, self.fails = None, 0
            return "turn_right"
        self.fails += 1
        return choice


# 修正B: ドア待機の早期解除。前方中央の深度が DOOR_OPEN_DEPTH_GAIN 増えたら開いた、
# DOOR_NO_CHANGE_TICS 待っても増えなければドアではない
DOOR_OPEN_DEPTH_GAIN = 3.0
DOOR_NO_CHANGE_TICS = 12


def center_depth(depth) -> float:
    """深度バッファの目線の高さ・中央帯の中央値（WallAvoider と同じ領域）"""
    h, w = depth.shape
    return float(np.median(depth[h // 2 - 3:h // 2 + 3, w * 2 // 5:w * 3 // 5]))


def door_wait_verdict(start_depth: float, current_depth: float, waited_tics: int) -> str | None:
    """"opened" / "no_door" なら待機を解除、None なら待機継続"""
    gain = current_depth - start_depth
    if gain >= DOOR_OPEN_DEPTH_GAIN:
        return "opened"
    if waited_tics >= DOOR_NO_CHANGE_TICS and gain < 1.0:
        return "no_door"
    return None


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


# 鍵に関する通知。Freedoom 実測: "Blue passcard secured!"
KEY_EVENT_PATTERN = re.compile(r"passcard|keycard|skull ?key|\bkeys?\b", re.IGNORECASE)
# 取得動詞ガード: 鍵付きドアの "You need a blue key ..." を取得と誤判定しないため
# （freedoom2 MAP01 は鍵0個だが keys=1 が記録されていた）。"secured" は Freedoom の取得文言
KEY_ACQUIRE_PATTERN = re.compile(r"picked up|you got|secured", re.IGNORECASE)
KEY_REQUIRED_PATTERN = re.compile(r"you need", re.IGNORECASE)


def coerce_notifications(buf) -> str:
    """notifications_buffer（str/bytes/None）を str に正規化する。

    ViZDoom の notifications_buffer は str で返る場合があり、
    bytes 決め打ちの .decode() は AttributeError で空文字化する。
    """
    if buf is None:
        return ""
    if isinstance(buf, bytes):
        try:
            return buf.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    try:
        return str(buf)
    except Exception:
        return ""


def extract_key_events(notifications: str | None) -> list[str]:
    """notifications_buffer から鍵取得の行だけを返す（体力ボーナス等・鍵要求メッセージは除外）"""
    if not notifications:
        return []
    return [
        line.strip() for line in notifications.splitlines()
        if KEY_EVENT_PATTERN.search(line)
        and KEY_ACQUIRE_PATTERN.search(line)
        and not KEY_REQUIRED_PATTERN.search(line)
    ]
