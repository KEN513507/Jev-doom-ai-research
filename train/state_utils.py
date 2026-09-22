"""ViZDoom状態表現の共通ユーティリティ。

calib_red.py と jev_agent.py は必ずこのモジュールを使うこと。
スライス範囲を変更する場合は、ここだけを編集する。
"""

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
