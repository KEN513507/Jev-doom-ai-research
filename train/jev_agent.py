"""ViZDoom + Jev API integration.

API key is read from TYPESAFE_API_KEY environment variable only.
"""
import os
import time
from collections import deque

import requests
import vizdoom as vzd


JEV_API_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

# screen_buffer 赤チャネル平均がこの値を超えたら「敵が見える」とみなす。
# 要調整（実機ログの red 値を見てキャリブレーションすること）。
ENEMY_RED_THRESHOLD = 100.0

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


def build_payload(state_text: str) -> dict:
    """Jev API に送る payload を組み立てる"""
    return {
        "model": JEV_MODEL,
        "state": state_text,
        "questions": {
            "next_action": {
                "type": "choice",
                "instructions": "Choose the single best next action for the DOOM agent.",
                "criteria": {
                    "move_forward": "Advance toward the goal. Do this when no enemy is visible, or after defeating one, to make progress.",
                    "move_backward": "Retreat only if health is critically low AND the enemy is very close.",
                    "turn_left": "Rotate to scan for enemies or align with a corridor.",
                    "turn_right": "Rotate to scan for enemies or align with a corridor.",
                    "attack": "Fire ONLY if an enemy is clearly visible in the center of view. Do NOT attack if no enemy is visible.",
                },
            }
        },
    }


def get_jev_decision(api_key: str, state_text: str, timeout: float = 2.0) -> dict:
    """Jev API を呼び出して判断を取得する（Session 再利用）"""
    _SESSION.headers.update({"Authorization": f"Bearer {api_key}"})
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


def state_to_text(state, game_vars: list) -> str:
    """ViZDoom の状態を Jev が理解できる豊富なテキストに変換する。

    注意: game_variables の中身はシナリオ依存（basic.cfg は AMMO2 のみ、
    deadly_corridor.cfg は HEALTH のみ）。health と決め打ちせず、
    汎用名で渡し、文脈文でゲーム目的を明示する。
    """
    parts = []
    for i, v in enumerate(game_vars):
        try:
            parts.append(f"var{i}={float(v):.0f}")
        except (TypeError, ValueError):
            parts.append(f"var{i}={v}")

    if state is not None:
        screen = getattr(state, "screen_buffer", None)
        if screen is not None:
            try:
                import numpy as np

                red_mean = float(np.asarray(screen)[0].mean())
                enemy_visible = red_mean > ENEMY_RED_THRESHOLD
                parts.append(f"enemy_visible={'yes' if enemy_visible else 'no'}")
            except Exception:
                pass

    context = (
        "You are playing DOOM. "
        "Your goal is to progress through the level and survive. "
        "Balance offense and movement."
    )
    return f"{context} Current state: {', '.join(parts) if parts else 'unknown'}"


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

    game = vzd.DoomGame()
    game.load_config(f"{vzd.scenarios_path}/deadly_corridor.cfg")
    game.set_window_visible(True)
    game.set_mode(vzd.Mode.PLAYER)
    game.set_ticrate(4)  # 250ms/tic = median 249ms と一致
    game.init()

    n_buttons = game.get_available_buttons_size()
    button_names = [str(b).split(".")[-1] for b in game.get_available_buttons()]
    print("Available buttons:", button_names)

    viz = JevVisualizer()
    episode = 0

    while episode < 3:  # 3エピソード実行
        game.new_episode()
        print(f"--- Episode {episode} ---")
        while not game.is_episode_finished():
            state = game.get_state()
            game_vars = list(state.game_variables) if state else []
            health = game_vars[0] if game_vars else 0

            state_text = state_to_text(state, game_vars)

            try:
                jev_resp = get_jev_decision(api_key, state_text)
                choice, probs = extract_choice_and_probs(jev_resp)
                print(f"Jev -> {choice} | probs={probs}")
            except Exception as e:
                print(f"Jev API error: {e}. Falling back to random.")
                choice = "move_forward"
                probs = {}

            # ボタンベクトルに変換
            action_vec = [0] * n_buttons
            target = ACTION_BUTTONS.get(choice, "MOVE_FORWARD")
            if target in button_names:
                action_vec[button_names.index(target)] = 1

            reward = game.make_action(action_vec)
            viz.log(probs, reward, health)

        episode += 1

    game.close()
    viz.save("jev_visualization.png")


if __name__ == "__main__":
    main()
