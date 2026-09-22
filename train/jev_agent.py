"""ViZDoom + Jev API integration.

API key is read from TYPESAFE_API_KEY environment variable only.
"""
import os
import time
from collections import deque

import requests
from pathlib import Path
from PIL import Image
import numpy as np
import vizdoom as vzd

# --- シナリオ定義のインポート ---
try:
    from train.scenarios import SCENARIO_BUTTONS, SCENARIO_CRITERIA
except ImportError:
    from scenarios import SCENARIO_BUTTONS, SCENARIO_CRITERIA


try:
    from train.state_utils import (
        ENEMY_RED_THRESHOLD,
        MIN_ENEMY_WIDTH,
        compute_red_metrics,
        build_state_text,
        detect_enemy_from_labels,
    )
except ImportError:  # python train/jev_agent.py 直接実行時
    from state_utils import (
        ENEMY_RED_THRESHOLD,
        MIN_ENEMY_WIDTH,
        compute_red_metrics,
        build_state_text,
        detect_enemy_from_labels,
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
    # labels_buffer 検出と組み合わせる先制攻撃セット（A方針：Jev純粋評価用）
    "aggressive_p0": {
        "move_forward": "Advance only when enemy_visible=no. Halt and switch to attack the instant an enemy is detected.",
        "move_backward": "Retreat only if health is below 30 and the enemy is very close.",
        "turn_left": "Use only to realign the target when the enemy is slightly off-center.",
        "turn_right": "Use only to realign the target when the enemy is slightly off-center.",
        "attack": "CRITICAL: If enemy_visible=yes, you MUST immediately choose 'attack'. Preemptive fire is mandatory. Do NOT attack if no enemy is visible.",
    },
    "aggressive_p1": {
        "move_forward": "CRITICAL: Advance along the corridor toward the goal. Move forward whenever enemy_centered=no OR enemy_visible=no. Do NOT stand still.",
        "move_backward": "Retreat only if health is below 30.",
        "turn_left": "Rotate left to align with an off-center enemy.",
        "turn_right": "Rotate right to align with an off-center enemy.",
        "attack": "Fire ONLY if enemy_centered=yes. Do NOT attack if the enemy is off-center or not visible.",
    },
    # Sys1 が排除できなかった場合に被弾リスク最小化を優先する基準（B方針：被弾回避重視）
    "tactical_p2": {
        "move_forward": "CRITICAL: Advance toward the goal. If no enemy is visible, always move forward.",
        "move_backward": "Retreat ONLY if health < 30 AND enemy_centered=yes. Do NOT retreat otherwise.",
        "turn_left": "Rotate to aim at off-center enemies.",
        "turn_right": "Rotate to aim at off-center enemies.",
        "attack": "Fire if enemy_centered=yes AND health > 30.",
    },
    "tactical_p1": {
        "move_forward": "Advance only when enemy_visible=no. Do NOT close distance into an enemy's line of fire.",
        "move_backward": "CRITICAL: If enemy_visible=yes, retreat immediately to increase distance and break line of sight, whether or not the enemy is centered. Maintaining a safe distance takes priority over holding ground.",
        "turn_left": "CRITICAL: If enemy_visible=yes, prioritize turning to realign the crosshair onto the enemy from a safer angle before attacking. Prefer this over attacking from a bad angle.",
        "turn_right": "CRITICAL: If enemy_visible=yes, prioritize turning to realign the crosshair onto the enemy from a safer angle before attacking. Prefer this over attacking from a bad angle.",
        "attack": "Fire ONLY if enemy_centered=yes AND health is above 50 AND a safe distance is already maintained. Do NOT attack if it would mean holding position under fire while off-center or at close range.",
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
    extra_keys = set(criteria_dict) - set(ACTION_BUTTONS)
    if extra_keys:
        raise ValueError(
            f"criteria has unknown keys {sorted(extra_keys)}; "
            f"allowed: {sorted(ACTION_BUTTONS)}"
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


def get_jev_decision(
    api_key: str | None,
    state_text: str,
    criteria: str | dict = "baseline",
    timeout: float = 2.0,
) -> dict:
    """Jev API を呼び出して判断を取得する（Session 再利用）"""
    if api_key:
        _SESSION.headers.update({"Authorization": f"Bearer {api_key}"})
    elif "Authorization" in _SESSION.headers:
        del _SESSION.headers["Authorization"]
    response = _SESSION.post(
        JEV_API_URL,
        json=build_payload(state_text, criteria=criteria),
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


def state_to_text(
    state,
    game_vars: list,
    threshold: float = ENEMY_RED_THRESHOLD,
    use_labels: bool = False,
    min_enemy_width: float = 0.0,
) -> tuple[str, float, bool]:
    """ViZDoom の状態を Jev が理解できるテキストに変換する。

    赤平均の定義は train/state_utils.py に集約（calib と共用）。
    注意: game_variables の中身はシナリオ依存のため health と決め打ちしない。
    use_labels=True の場合、enemy_visible は labels_buffer 検出を優先する。
    min_enemy_width で極小ラベル（遠方・端の敵）を視認対象から外せる。
    戻り値の形 (text, red_mean, enemy_visible) は維持する。
    """
    screen = state.screen_buffer if state is not None else None
    red_mean, red_visible = compute_red_metrics(screen, threshold)
    enemy_visible = red_visible
    extra_parts = []
    if use_labels:
        info = detect_enemy_from_labels(state, min_width=min_enemy_width)
        enemy_visible = info["enemy_visible"]
        extra_parts.append(f"enemy_count={info['enemy_count']}")
        if info["enemy_visible"]:
            extra_parts.append(
                f"enemy_centered={'yes' if info['enemy_centered'] else 'no'}"
            )
            extra_parts.append(f"enemy_types={','.join(info['enemy_names'])}")
    text = build_state_text(game_vars, red_mean, enemy_visible)
    if extra_parts:
        text = f"{text} {', '.join(extra_parts)}"
    return text, red_mean, enemy_visible


# System 1（反射層）の発動条件：中央に十分大きな敵がいるとき即攻撃
SYSTEM1_WIDTH_THRESHOLD = 20.0


def should_force_attack(label_info, width_threshold: float = SYSTEM1_WIDTH_THRESHOLD) -> bool:
    """System 1 割込条件。

    発動条件（いずれか）:
      1. ChaingunGuy が視認範囲内（最危険・width=0 のため特別扱い）
      2. enemy_visible AND enemy_centered AND width >= threshold（至近距離）
    """
    if not label_info:
        return False
    if not label_info.get("enemy_visible"):
        return False

    # 条件1: ChaingunGuy は width=0 を返すため、中央判定を無視して常に反射
    enemy_names = label_info.get("enemy_names", [])
    if "ChaingunGuy" in enemy_names:
        return True

    # 条件2: その他の敵は中央かつ至近距離のみ
    if not label_info.get("enemy_centered"):
        return False
    try:
        w = float(label_info.get("nearest_enemy_width"))
        if w == 0.0:
            return True  # 想定外の width=0 への保険
        return w >= width_threshold
    except (TypeError, ValueError):
        return False


def resolve_action(state, game_vars, *, use_labels, min_enemy_width, decide, allow_system1=True):
    """次の行動を決定する。

    decide: state_text -> Jev API応答dict（System2）。
    allow_system1=False の場合、System 1 をスキップして必ず Jev に委ねる
    （立上り限定：前回 System 1 発動時は False を渡す）。
    """
    label_info = (
        detect_enemy_from_labels(state, min_width=min_enemy_width)
        if use_labels
        else None
    )
    if allow_system1 and should_force_attack(label_info):
        return "attack", "system1", label_info
    state_text, red_mean, enemy_visible = state_to_text(
        state, game_vars, use_labels=use_labels, min_enemy_width=min_enemy_width
    )
    choice, probs = extract_choice_and_probs(decide(state_text))
    return choice, "system2", {
        "state_text": state_text,
        "red_mean": red_mean,
        "enemy_visible": enemy_visible,
        "probs": probs,
    }


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



def save_screenshot(state, out_dir, episode, hit_num, tic):
    """被弾時のスクリーンショットを保存する"""
    if state is None or state.screen_buffer is None:
        return
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # screen_buffer: [C, H, W] -> [H, W, C]
    img_array = np.transpose(state.screen_buffer, (1, 2, 0))
    img = Image.fromarray(img_array.astype("uint8"))
    path = out_dir / f"ep{episode}_hit{hit_num}_tic{tic:04d}.png"
    img.save(path)
    return path



def main():
    global ACTION_BUTTONS  # ← この行を追加
    import argparse

    parser = argparse.ArgumentParser(description="ViZDoom + Jev API agent")
    parser.add_argument(
        "--criteria",
        default="baseline",
        choices=sorted(CRITERIA_SETS),
        help="criteriaセット名",
    )
    parser.add_argument(
        "--use-labels",
        action="store_true",
        help="enemy_visible に labels_buffer 検出を使う（要 set_labels_buffer_enabled）",
    )
    parser.add_argument(
        "--scenario",
        default="deadly_corridor",
        choices=sorted(SCENARIO_BUTTONS.keys()),
        help="ViZDoomシナリオ名（デフォルト: deadly_corridor）",
    )
    parser.add_argument(
        "--min-width",
        type=float,
        default=MIN_ENEMY_WIDTH,
        help="視認とみなす最小ラベル幅px（--use-labels時のみ有効）",
    )
    parser.add_argument(
        "--sound",
        action="store_true",
        help="ゲーム音を有効化（観戦時のみ推奨。長時間実験では指定しない）",
    )

    args = parser.parse_args()

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise EnvironmentError("TYPESAFE_API_KEY is not set")
    print(f"scenario={args.scenario} criteria={args.criteria} use_labels={args.use_labels}")

    # --- シナリオに応じて ACTION_BUTTONS を動的に切り替え ---
    scenario_buttons = SCENARIO_BUTTONS[args.scenario]
    ACTION_BUTTONS.clear()
    for btn in scenario_buttons:
        ACTION_BUTTONS[btn.lower()] = btn
    print(f"ACTION_BUTTONS updated: {list(ACTION_BUTTONS.keys())}")

    # --- 初期化: 極限軽量化 ---
    game = vzd.DoomGame()
    game.load_config(f"{vzd.scenarios_path}/{args.scenario}.cfg")
    # 撃破数を取得（cfg書き換え不要。HEALTH の後に KILLCOUNT が追加される）
    game.add_available_game_variable(vzd.GameVariable.KILLCOUNT)
    game.set_window_visible(True)  # ウィンドウ表示（リアルタイム可視化が要件のためTrueを維持）
    game.set_sound_enabled(args.sound)  # --sound 指定時のみ音声オン（initより前）
    game.set_screen_resolution(vzd.ScreenResolution.RES_160X120)
    game.set_depth_buffer_enabled(False)
    game.set_labels_buffer_enabled(args.use_labels)  # labels検出を使う場合のみ有効化
    game.set_automap_buffer_enabled(False)
    game.set_ticrate(35)
    game.init()

    n_buttons = game.get_available_buttons_size()
    button_names = [str(b).split(".")[-1] for b in game.get_available_buttons()]
    print("Available buttons:", button_names)

    # 固定メモリ
    action_vec = [0] * n_buttons
    frame_skip = 4  # A方針：反応速度優先（114ms/step）
    decision_interval_tic = 4  # 何ticごとにJevに聞くか（毎アクションごとに判断）
    
    viz = JevVisualizer()
    episode = 0
    choice = "move_forward"
    last_reward = 0.0

    # シナリオのボタンに存在しない criteria キーを除去（エピソード共通）
    if isinstance(args.criteria, str):
        base_criteria = CRITERIA_SETS.get(
            args.criteria, SCENARIO_CRITERIA[args.scenario]
        )
    else:
        base_criteria = args.criteria
    filtered_criteria = {
        k: v for k, v in base_criteria.items()
        if k in ACTION_BUTTONS
    }

    while episode < 3:  # 3エピソード実行
        game.new_episode()
        print(f"--- Episode {episode} ---")
        tic_counter = 0
        # P1: 被弾監視（合格条件 = health が100から一度も下がらない）
        hit_count = 0
        prev_health = 100
        hit_capture_until = -1  # 被弾後の撮影期限（tic）
        # System 1/2 発動回数
        system1_count = 0
        system2_count = 0
        prev_system1 = False
        last_kills = 0

        while not game.is_episode_finished():
            # 判断フレームのみ get_state() を呼ぶ
            if tic_counter % decision_interval_tic == 0:
                state = game.get_state()
                if state is None:
                    break
                game_vars = list(state.game_variables)
                health = game_vars[0] if game_vars else 0
                if len(game_vars) > 1:
                    last_kills = int(game_vars[1])  # KILLCOUNT（追加変数）
                # P1: 被弾検出（health の減少を数える）
                if game_vars:
                    current_health = int(game_vars[0])
                    if current_health < prev_health:
                        hit_count += 1
                        print(f"!!! HIT #{hit_count} at step={tic_counter}: "
                              f"{prev_health} -> {current_health}")
                        # 被弾後 約1秒間 (35tic) スクリーンショットを保存
                        hit_capture_until = tic_counter + 35
                    prev_health = current_health
                # 被弾後の連続撮影
                if hit_count > 0 and tic_counter <= hit_capture_until:
                    save_screenshot(
                        state,
                        f"experiments/hits/ep{episode}",
                        episode,
                        hit_count,
                        tic_counter,
                    )
                
                try:
                    choice, source, info = resolve_action(
                        state,
                        game_vars,
                        use_labels=args.use_labels,
                        min_enemy_width=args.min_width if args.use_labels else 0.0,
                        decide=lambda text: get_jev_decision(
                            api_key, text, criteria=filtered_criteria, timeout=1.0
                        ),
                        allow_system1=not prev_system1,
                    )
                    prev_system1 = (source == "system1")
                    if source == "system1":
                        system1_count += 1
                        print(f"step={tic_counter} [System1] FORCED attack "
                              f"(centered, width={info['nearest_enemy_width']:.0f})")
                    else:
                        system2_count += 1
                        viz.log(info["probs"], last_reward, health)
                        print(f"step={tic_counter} Jev -> {choice} | "
                              f"red_mean={info['red_mean']:.1f} | "
                              f"enemy_visible={'yes' if info['enemy_visible'] else 'no'}")
                        print(f"    state_text: {info['state_text']}")
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

        # P1: エピソード終了時の被弾サマリー
        print(f"Episode {episode} done: hits={hit_count}, "
              f"final_health={prev_health}, steps={tic_counter}, "
              f"sys1={system1_count}, sys2={system2_count}, "
              f"kills={last_kills}")
        episode += 1

    game.close()
    viz.save("jev_visualization.png")


if __name__ == "__main__":
    main()
