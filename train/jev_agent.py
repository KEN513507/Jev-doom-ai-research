"""ViZDoom + Jev API integration.

API key is read from TYPESAFE_API_KEY environment variable only.
"""
import os
import time
from collections import deque

import requests
import vizdoom as vzd


try:
    from train.state_utils import (
        ENEMY_RED_THRESHOLD,
        compute_red_metrics,
        build_state_text,
    )
except ImportError:  # python train/jev_agent.py 直接実行時
    from state_utils import (
        ENEMY_RED_THRESHOLD,
        compute_red_metrics,
        build_state_text,
    )


JEV_API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = "jev-latest"
JEV_TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "5.0"))

# 接続を使い回す（毎回新規接続だと ~800ms に逆戻りするため最重要）
_SESSION = requests.Session()

# 行動の定義（Jevの criteria と ViZDoom のボタン順を一致させる）
ACTION_BUTTONS = {
    "move_forward": "MOVE_FORWARD",
    "move_backward": "MOVE_BACKWARD",
    "turn_left": "TURN_LEFT",
    "turn_right": "TURN_RIGHT",
    "attack": "ATTACK",
}


# 実験用の criteria セット（キー集合は ACTION_BUTTONS と一致させること）
CRITERIA_SETS = {
    "baseline": {
        "move_forward": "Advance toward the goal. Do this when no enemy is visible, or after defeating one, to make progress.",
        "move_backward": "Retreat only if health is critically low AND the enemy is very close.",
        "turn_left": "Rotate to scan for enemies or align with a corridor.",
        "turn_right": "Rotate to scan for enemies or align with a corridor.",
        "attack": "Fire ONLY if an enemy is clearly visible in the center of view. Do NOT attack if no enemy is visible.",
    },
    "aggressive": {
        "move_forward": "Advance toward the enemy to close distance.",
        "move_backward": "Almost never retreat. Holding ground and firing is preferred.",
        "turn_left": "Quickly turn to face the enemy.",
        "turn_right": "Quickly turn to face the enemy.",
        "attack": "Fire whenever an enemy is visible, even if off-center. Attack is the top priority. Do NOT attack if no enemy is visible.",
    },
    "defensive": {
        "move_forward": "Advance cautiously only when no enemy is visible and health is sufficient.",
        "move_backward": "Retreat to safety when an enemy is visible or health is dropping. Survival comes first.",
        "turn_left": "Rotate to check surroundings before moving.",
        "turn_right": "Rotate to check surroundings before moving.",
        "attack": "Fire ONLY if an enemy is clearly visible in the center of view AND there is no immediate danger. Do NOT attack if no enemy is visible.",
    },
    "explorer": {
        "move_forward": "Always keep moving forward to expand explored area. This is the top priority, ignore enemies.",
        "move_backward": "Never retreat. Keep pushing forward.",
        "turn_left": "Turn only to unblock the path or follow a corridor.",
        "turn_right": "Turn only to unblock the path or follow a corridor.",
        "attack": "Do not go out of your way to attack. Fire only as a last resort. Do NOT attack if no enemy is visible.",
    },
}

# criteria ごとの敵検出閾値（red_mean > threshold で enemy_visible=yes）
THRESHOLDS = {
    "baseline": 48.0,
    "aggressive": 40.0,
    "defensive": 60.0,
    "explorer": 70.0,
}


def build_payload(state_text: str, criteria: str | dict = "baseline") -> dict:
    """Jev API に送る payload を組み立てる"""
    if isinstance(criteria, str):
        try:
            criteria_dict = CRITERIA_SETS[criteria]
        except KeyError:
            raise ValueError(
                f"Unknown criteria: {criteria!r} (choose from {sorted(CRITERIA_SETS)})"
            )
    else:
        criteria_dict = criteria
    if set(criteria_dict) != set(ACTION_BUTTONS):
        raise ValueError(
            f"criteria keys must match actions {sorted(ACTION_BUTTONS)}, "
            f"got {sorted(criteria_dict)}"
        )
    return {
        "model": JEV_MODEL,
        "state": state_text,
        "questions": {
            "next_action": {
                "type": "choice",
                "instructions": "Choose the single best next action for the DOOM agent.",
                "criteria": dict(criteria_dict),
            }
        },
    }


def get_jev_decision(api_key: str | None, state_text: str, timeout: float = 2.0) -> dict:
    """Jev API を呼び出して判断を取得する（Session 再利用）"""
    if api_key:
        _SESSION.headers.update({"Authorization": f"Bearer {api_key}"})
    elif "Authorization" in _SESSION.headers:
        del _SESSION.headers["Authorization"]
    response = _SESSION.post(
        JEV_API_URL,
        json=build_payload(state_text),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def extract_choice_and_probs(jev_response: dict) -> tuple[str, dict]:
    """Jev 応答から選択された行動と確率分布を取り出す。

    Jev の応答形式は以下のいずれかを想定：
      {"answers": {"next_action": {"choice": "attack", "probabilities": {...}}}}
      {"answers": {"next_action": {"choice": "attack"}}}
    """
    answers = jev_response.get("answers", {})
    next_action = answers.get("next_action", {})

    choice = next_action.get("choice") or next_action.get("value")
    probs = next_action.get("probabilities") or next_action.get("scores") or {}

    if choice is None:
        raise ValueError(f"Unexpected Jev response: {jev_response}")

    return choice, probs


def state_to_text(state, game_vars: list) -> tuple[str, float, bool]:
    """ViZDoom の状態を Jev が理解できるテキストに変換する。

    赤平均の定義は train/state_utils.py に集約（calib と共用）。
    注意: game_variables の中身はシナリオ依存のため health と決め打ちしない。
    """
    red_mean, enemy_visible = compute_red_metrics(
        state.screen_buffer if state is not None else None
    )
    return build_state_text(game_vars, red_mean, enemy_visible), red_mean, enemy_visible


class JevVisualizer:
    """Jev の判断確率を時系列で記録する"""

    def __init__(self, window_size: int = 200):
        self.action_probs = deque(maxlen=window_size)
        self.rewards = deque(maxlen=window_size)
        self.health = deque(maxlen=window_size)
        self.action_names = list(ACTION_BUTTONS.keys())

    def log(self, probs: dict, reward: float, health: float):
        vec = [probs.get(name, 0.0) for name in self.action_names]
        self.action_probs.append(vec)
        self.rewards.append(reward)
        self.health.append(health)

    def save(self, save_path: str = "jev_visualization.png"):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

        if self.action_probs:
            prob_matrix = np.array(self.action_probs).T
            im = axes[0].imshow(prob_matrix, aspect="auto", cmap="viridis", interpolation="nearest")
            axes[0].set_yticks(range(len(self.action_names)))
            axes[0].set_yticklabels(self.action_names)
            axes[0].set_ylabel("Action")
            axes[0].set_title("Jev Action Probability Distribution")
            fig.colorbar(im, ax=axes[0], label="Probability")

        axes[1].plot(self.rewards, color="green", linewidth=1)
        axes[1].set_ylabel("Reward")
        axes[1].set_title("Reward Over Time")
        axes[1].grid(True, alpha=0.3)

        axes[2].plot(self.health, color="red", linewidth=1)
        axes[2].set_ylabel("Health")
        axes[2].set_xlabel("Time Step")
        axes[2].set_title("Health Over Time")
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(save_path, dpi=150)
        print(f"Saved: {save_path}")


def main():
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise EnvironmentError("TYPESAFE_API_KEY is not set")

    # --- 初期化: 極限軽量化 ---
    game = vzd.DoomGame()
    game.load_config(f"{vzd.scenarios_path}/deadly_corridor.cfg")
    game.set_window_visible(True)  # ウィンドウ表示（リアルタイム可視化が要件のためTrueを維持）
    game.set_screen_resolution(vzd.ScreenResolution.RES_160X120)
    game.set_depth_buffer_enabled(False)
    game.set_labels_buffer_enabled(False)
    game.set_automap_buffer_enabled(False)
    game.set_ticrate(35)
    game.init()

    n_buttons = game.get_available_buttons_size()
    button_names = [str(b).split(".")[-1] for b in game.get_available_buttons()]
    print("Available buttons:", button_names)

    # 固定メモリ
    action_vec = [0] * n_buttons
    frame_skip = 4  # 1回の make_action で4tic進める（約114ms）
    decision_interval_tic = 4  # 何ticごとにJevに聞くか

    viz = JevVisualizer()
    episode = 0
    choice = "move_forward"
    last_reward = 0.0

    while episode < 3:  # 3エピソード実行
        game.new_episode()
        print(f"--- Episode {episode} ---")
        tic_counter = 0

        while not game.is_episode_finished():
            # 判断フレームのみ get_state() を呼ぶ
            if tic_counter % decision_interval_tic == 0:
                state = game.get_state()
                if state is None:
                    break
                game_vars = list(state.game_variables)
                health = game_vars[0] if game_vars else 0
                state_text, red_mean, enemy_visible = state_to_text(state, game_vars)
                try:
                    jev_resp = get_jev_decision(api_key, state_text, timeout=1.0)
                    choice, probs = extract_choice_and_probs(jev_resp)
                    viz.log(probs, last_reward, health)
                    print(f"step={tic_counter} Jev -> {choice} | "
                          f"red_mean={red_mean:.1f} | "
                          f"enemy_visible={'yes' if enemy_visible else 'no'}")
                except Exception as e:
                    print(f"[skip] {e}")

            # ボタンベクトルを再利用
            for i in range(n_buttons):
                action_vec[i] = 0
            target = ACTION_BUTTONS.get(choice, "MOVE_FORWARD")
            if target in button_names:
                action_vec[button_names.index(target)] = 1

            # フレームスキップで進める
            last_reward = game.make_action(action_vec, frame_skip)
            tic_counter += frame_skip

        episode += 1

    game.close()
    viz.save("jev_visualization.png")


if __name__ == "__main__":
    main()
