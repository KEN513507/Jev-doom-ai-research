"""ViZDoom + Jev API integration.

API key is read from TYPESAFE_API_KEY environment variable only.
"""
import math
import os
import statistics
import time
from collections import deque

import requests
from pathlib import Path
from PIL import Image
import numpy as np
import vizdoom as vzd

# --- シナリオ定義のインポート ---
try:
    from train.scenarios import (FULL_MAP_SCENARIOS, SCENARIO_BUTTONS, SCENARIO_CRITERIA,
        ACTION_DEFINITIONS, DEFAULT_CRITERIA, get_action_buttons, build_action_vector)
except ImportError:
    from scenarios import (FULL_MAP_SCENARIOS, SCENARIO_BUTTONS, SCENARIO_CRITERIA,
        ACTION_DEFINITIONS, DEFAULT_CRITERIA, get_action_buttons, build_action_vector)


try:
    from train.world_memory import WorldMemory
    from train.elevation import ElevationTracker, DoorWaiter
except ImportError:
    from world_memory import WorldMemory
    from elevation import ElevationTracker, DoorWaiter

try:
    from train.state_utils import (
        ENEMY_RED_THRESHOLD,
        MIN_ENEMY_WIDTH,
        AreaStagnationDetector,
        ForwardBlockDetector,
        UseFailDetector,
        WALL_NEAR_DEPTH,
        center_depth,
        door_wait_verdict,
        open_directions,
        WallAvoider,
        compute_red_metrics,
        build_state_text,
        detect_enemy_from_labels,
        detect_items_from_labels,
        extract_key_events,
    )
    from train.system3_core import (
        TRIGGER_AREA_STAGNATION,
        TRIGGER_FRONT_BLOCKED,
        TRIGGER_KEY_EVENT,
        StrategicCoreSystem3,
    )
except ImportError:  # python train/jev_agent.py 直接実行時
    from state_utils import (
        ENEMY_RED_THRESHOLD,
        MIN_ENEMY_WIDTH,
        AreaStagnationDetector,
        ForwardBlockDetector,
        UseFailDetector,
        WALL_NEAR_DEPTH,
        center_depth,
        door_wait_verdict,
        open_directions,
        WallAvoider,
        compute_red_metrics,
        build_state_text,
        detect_enemy_from_labels,
        detect_items_from_labels,
        extract_key_events,
    )
    from system3_core import (
        TRIGGER_AREA_STAGNATION,
        TRIGGER_FRONT_BLOCKED,
        TRIGGER_KEY_EVENT,
        StrategicCoreSystem3,
    )


JEV_API_URL = os.environ.get("JEV_API_URL", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = "jev-latest"
JEV_TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "5.0"))

# 接続を使い回す（毎回新規接続だと ~800ms に逆戻りするため最重要）
_SESSION = requests.Session()

# 行動の定義（Jevの criteria と ViZDoom のボタン順を一致させる）
ACTION_BUTTONS = dict(ACTION_DEFINITIONS)


# 実験用の criteria セット（キー集合は ACTION_BUTTONS と一致させること）
CRITERIA_SETS = {
    "baseline": {
        "move_forward": "Advance toward the goal. Do this when no enemy is visible, or after defeating one, to make progress.",
        "move_backward": "Retreat only if health is critically low AND the enemy is very close.",
        "turn_left": "Rotate to scan for enemies or align with a corridor.",
        "turn_right": "Rotate to scan for enemies or align with a corridor.",
        "attack": "Fire ONLY if an enemy is clearly visible in the center of view. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use ONLY if an enemy is clearly visible in the center of view, to dodge while firing. Do NOT use if no enemy is visible.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use ONLY if an enemy is clearly visible in the center of view, to dodge while firing. Do NOT use if no enemy is visible.",
        "advance_attack": "Advance AND fire simultaneously. Use ONLY if an enemy is clearly visible in the center of view and closing distance is safe. Do NOT use if no enemy is visible.",
    },
    "aggressive": {
        "move_forward": "Advance toward the enemy to close distance.",
        "move_backward": "Almost never retreat. Holding ground and firing is preferred.",
        "turn_left": "Quickly turn to face the enemy.",
        "turn_right": "Quickly turn to face the enemy.",
        "attack": "Fire whenever an enemy is visible, even if off-center. Attack is the top priority. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use freely whenever an enemy is visible to keep firing while dodging. Do NOT use if no enemy is visible.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use freely whenever an enemy is visible to keep firing while dodging. Do NOT use if no enemy is visible.",
        "advance_attack": "Advance AND fire simultaneously. Preferred way to close distance whenever an enemy is visible. Do NOT use if no enemy is visible.",
    },
    "defensive": {
        "move_forward": "Advance cautiously only when no enemy is visible and health is sufficient.",
        "move_backward": "Retreat to safety when an enemy is visible or health is dropping. Survival comes first.",
        "turn_left": "Rotate to check surroundings before moving.",
        "turn_right": "Rotate to check surroundings before moving.",
        "attack": "Fire ONLY if an enemy is clearly visible in the center of view AND there is no immediate danger. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use ONLY if an enemy is clearly visible in the center of view and you must dodge. Prefer retreating when health is dropping.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use ONLY if an enemy is clearly visible in the center of view and you must dodge. Prefer retreating when health is dropping.",
        "advance_attack": "Advance AND fire simultaneously. Almost never use: advancing into fire contradicts survival first. Only if the enemy is centered, very close, and health is high.",
    },
    "explorer": {
        "move_forward": "Always keep moving forward to expand explored area. This is the top priority, ignore enemies.",
        "move_backward": "Never retreat. Keep pushing forward.",
        "turn_left": "Turn only to unblock the path or follow a corridor.",
        "turn_right": "Turn only to unblock the path or follow a corridor.",
        "attack": "Do not go out of your way to attack. Fire only as a last resort. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Last resort only, when a centered enemy blocks the path. Do NOT use if no enemy is visible.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Last resort only, when a centered enemy blocks the path. Do NOT use if no enemy is visible.",
        "advance_attack": "Advance AND fire simultaneously. Preferred way to handle a centered enemy in your path: keep moving forward while firing. Do NOT use if no enemy is visible.",
    },
    # labels_buffer 検出と組み合わせる先制攻撃セット（A方針：Jev純粋評価用）
    "aggressive_p0": {
        "move_forward": "Advance only when enemy_visible=no. Halt and switch to attack the instant an enemy is detected.",
        "move_backward": "Retreat only if health is below 30 and the enemy is very close.",
        "turn_left": "Use only to realign the target when the enemy is slightly off-center.",
        "turn_right": "Use only to realign the target when the enemy is slightly off-center.",
        "attack": "CRITICAL: If enemy_visible=yes, you MUST immediately choose 'attack'. Preemptive fire is mandatory. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use when enemy_visible=yes AND enemy_centered=yes to fire while dodging. Do NOT use if enemy_visible=no.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use when enemy_visible=yes AND enemy_centered=yes to fire while dodging. Do NOT use if enemy_visible=no.",
        "advance_attack": "Advance AND fire simultaneously. Use when enemy_centered=yes to fire while closing distance. Do NOT use if enemy_visible=no.",
    },
    "aggressive_p1": {
        "move_forward": "CRITICAL: Advance along the corridor toward the goal. Move forward whenever enemy_centered=no OR enemy_visible=no. Do NOT stand still.",
        "move_backward": "Retreat only if health is below 30.",
        "turn_left": "Rotate left to align with an off-center enemy.",
        "turn_right": "Rotate right to align with an off-center enemy.",
        "attack": "Fire ONLY if enemy_centered=yes. Do NOT attack if the enemy is off-center or not visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. ONLY when enemy_centered=yes, to fire while dodging.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. ONLY when enemy_centered=yes, to fire while dodging.",
        "advance_attack": "Advance AND fire simultaneously. ONLY when enemy_centered=yes, to keep advancing along the corridor while firing.",
    },
    # Sys1 が排除できなかった場合に被弾リスク最小化を優先する基準（B方針：被弾回避重視）
    "take_cover_p1": {
        "move_forward": "Advance toward the enemy only when enemy_visible=no or health is high and no immediate threat.",
        "move_backward": "Retreat behind cover when health is below 50 or under heavy fire.",
        "move_left": "Strafe left to dodge incoming fire or peek from cover.",
        "move_right": "Strafe right to dodge incoming fire or peek from cover.",
        "attack": "Fire when enemy_centered=yes AND health > 30. Prioritize cover when reloading or exposed.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. ONLY when enemy_centered=yes AND health > 30, to dodge incoming fire while shooting.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. ONLY when enemy_centered=yes AND health > 30, to dodge incoming fire while shooting.",
        "advance_attack": "Advance AND fire simultaneously. ONLY when enemy_centered=yes AND health >= 50 AND not under heavy fire. Otherwise prefer cover.",
    },
    "tactical_p2": {
        "move_forward": "CRITICAL: Advance toward the goal. If no enemy is visible, always move forward.",
        "move_backward": "Retreat ONLY if health < 30 AND enemy_centered=yes. Do NOT retreat otherwise.",
        "turn_left": "Rotate to aim at off-center enemies.",
        "turn_right": "Rotate to aim at off-center enemies.",
        "attack": "Fire if enemy_centered=yes AND health > 30.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use when enemy_centered=yes AND health > 30.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use when enemy_centered=yes AND health > 30.",
        "advance_attack": "Advance AND fire simultaneously. Use when enemy_centered=yes AND health > 30 to push toward the goal while firing.",
    },
    "tactical_p1": {
        "move_forward": "Advance only when enemy_visible=no. Do NOT close distance into an enemy's line of fire.",
        "move_backward": "CRITICAL: If enemy_visible=yes, retreat immediately to increase distance and break line of sight, whether or not the enemy is centered. Maintaining a safe distance takes priority over holding ground.",
        "turn_left": "CRITICAL: If enemy_visible=yes, prioritize turning to realign the crosshair onto the enemy from a safer angle before attacking. Prefer this over attacking from a bad angle.",
        "turn_right": "CRITICAL: If enemy_visible=yes, prioritize turning to realign the crosshair onto the enemy from a safer angle before attacking. Prefer this over attacking from a bad angle.",
        "attack": "Fire ONLY if enemy_centered=yes AND health is above 50 AND a safe distance is already maintained. Do NOT attack if it would mean holding position under fire while off-center or at close range.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. ONLY when enemy_centered=yes AND health is above 50, to shoot while moving off the line of fire.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. ONLY when enemy_centered=yes AND health is above 50, to shoot while moving off the line of fire.",
        "advance_attack": "Advance AND fire simultaneously. Avoid while enemy_visible=yes: closing distance into fire contradicts keeping a safe distance. Only if health is above 80 and enemy_centered=yes.",
    },
    # tactical_p2 ベースに被弾後の連続被弾対策（strafe/後退で射線を切る）を強化
    # health は state_text 上 var0 として渡る。strafe キーは MOVE_LEFT/RIGHT を持つシナリオのみ有効（main で除去される）
    "tactical_p3": {
        "move_forward": "Advance toward the goal when enemy_visible=no. Do NOT advance into an enemy's line of fire while enemy_visible=yes.",
        "move_backward": "CRITICAL: If enemy_visible=yes AND health (var0) < 50, retreat immediately to break the enemy's line of fire, whether or not the enemy is centered.",
        "move_left": "CRITICAL: If enemy_visible=yes AND (health (var0) < 70 OR enemy_types includes ChaingunGuy), strafe left to dodge incoming fire. Never stand still under fire.",
        "move_right": "CRITICAL: If enemy_visible=yes AND (health (var0) < 70 OR enemy_types includes ChaingunGuy), strafe right to dodge incoming fire. Never stand still under fire.",
        "turn_left": "Rotate to aim at off-center enemies only when health (var0) >= 50. At lower health, strafe or retreat instead of turning under fire.",
        "turn_right": "Rotate to aim at off-center enemies only when health (var0) >= 50. At lower health, strafe or retreat instead of turning under fire.",
        "attack": "Fire if enemy_centered=yes AND health (var0) >= 50. Below 50, prefer strafing or retreating over attacking. Do NOT attack if no enemy is visible.",
        "strafe_attack_left": "Strafe left AND fire simultaneously. ONLY when enemy_centered=yes AND health (var0) >= 50, to dodge while keeping aim. Do NOT use if no enemy is visible.",
        "strafe_attack_right": "Strafe right AND fire simultaneously. ONLY when enemy_centered=yes AND health (var0) >= 50, to dodge while keeping aim. Do NOT use if no enemy is visible.",
        "advance_attack": "Advance AND fire simultaneously. ONLY when enemy_centered=yes AND health (var0) >= 70. Do NOT advance into an enemy's line of fire at lower health.",
    },
    # full_map（遮蔽物・角あり）用：角からの横移動で覗いて撃ち、遮蔽に戻る
    "tactical_peeking": {
        "move_forward": "Advance through the area. Check the Memory summary: if visited cells stopped increasing for several steps, you are looping. In that case, STOP advancing forward. Instead turn_left or turn_right to find a NEW path. If item_visible=yes and no enemy is visible, detour toward the item to pick it up. Advance only when open_center=far or open_center=mid. If open_center=near, do NOT advance: turn toward the side that is far (open_left or open_right).",
        "use": "Select 'use' whenever front_blocked=yes. In DOOM, some walls are switches that open hidden rooms or monster closets. Try 'use' before turning away. If the first attempt does not open the wall, try up to two times in total, the second from a slightly different position.",
        # 修正A: "PRIMARY DODGE ACTION" を削除。敵が中央にいないときは逃げずに中央へ寄せる
        "move_left": "Reposition to center the enemy on screen. If enemy_visible=yes and enemy_side=left, strafe left toward centering. Also use to peek around corners when no enemy is visible.",
        "move_right": "Reposition to center the enemy on screen. If enemy_visible=yes and enemy_side=right, strafe right toward centering. Also use to peek around corners when no enemy is visible.",
        "turn_left": "If enemy_visible=yes and enemy_side=left, turn left toward the enemy to center it. If no enemy is visible, turn left when open_left is the most open direction (far) and open_center is not far.",
        "turn_right": "If enemy_visible=yes and enemy_side=right, turn right toward the enemy to center it. If no enemy is visible, turn right when open_right is the most open direction (far) and open_center is not far.",
        "attack": "Fire whenever enemy_visible=yes. Do not wait for centering. Do NOT attack if no enemy is visible.",
        # ★ 複合アクション: 動きながら撃つ（被弾リスクが高い時だけ）
        "strafe_attack_left": "Strafe left AND fire simultaneously. Use ONLY when enemy_centered=yes AND (health (var0) < 70 OR enemy_types includes ChaingunGuy).",
        "strafe_attack_right": "Strafe right AND fire simultaneously. Use ONLY when enemy_centered=yes AND (health (var0) < 70 OR enemy_types includes ChaingunGuy).",
        "advance_attack": "Advance AND fire simultaneously. Use to close distance on a centered enemy while maintaining pressure.",
    },
    # 修正A を入れる前の tactical_peeking（A/B 切り分け用。B のみの実走で使う）
    "tactical_peeking_v0": {
        "move_forward": "Advance through the area. Check the Memory summary: if visited cells stopped increasing for several steps, you are looping. In that case, STOP advancing forward. Instead turn_left or turn_right to find a NEW path.",
        "use": "Select 'use' ONLY when 'front_blocked=yes' to open doors or operate switches.",
        "move_left": (
            "PRIMARY DODGE ACTION. "
            "Strafe left without firing to dodge or peek when the enemy is not centered. "
            "When enemy_centered=yes, prefer strafe_attack_left or strafe_attack_right to fire while moving. "
            "Circle-strafing: alternate left/right to stay unpredictable. "
            "Only strafe to peek around corners if no enemy is visible."
        ),
        "move_right": (
            "PRIMARY DODGE ACTION. "
            "Strafe right without firing to dodge or peek when the enemy is not centered. "
            "When enemy_centered=yes, prefer strafe_attack_left or strafe_attack_right to fire while moving. "
            "Circle-strafing: alternate left/right to stay unpredictable. "
            "Only strafe to peek around corners if no enemy is visible."
        ),
        "turn_left": "Rotate to check corners and align aim with enemies.",
        "turn_right": "Rotate to check corners and align aim with enemies.",
        "attack": "Fire ONLY when enemy_centered=yes AND no dodge needed. If health (var0) < 70 OR enemy_types includes ChaingunGuy, prefer strafe_attack_left or strafe_attack_right to dodge WHILE firing. Only use plain 'attack' when health is high and enemy is slow.",
        "strafe_attack_left": "PRIMARY COMBAT ACTION. Strafe left AND fire simultaneously. Use when enemy_centered=yes to dodge incoming fire while keeping damage output.",
        "strafe_attack_right": "PRIMARY COMBAT ACTION. Strafe right AND fire simultaneously. Use when enemy_centered=yes to dodge incoming fire while keeping damage output.",
        "advance_attack": "Advance AND fire simultaneously. Use to close distance on a centered enemy while maintaining pressure.",
    },
    # 隠し部屋・モンスタークローゼット（壁スイッチ）を探しながら探索する汎用戦略。マップ固有の情報は書かない
    "tactical_secret_hunt": {
        "attack": "Fire whenever enemy_visible=yes. Prefer enemy_centered=yes when possible.",
        "move_forward": "Advance only when open_center=far or open_center=mid. If open_center=near, do NOT advance. If visited cells stop increasing, try turn_left and turn_right alternately to find a new direction.",
        "turn_left": "Turn left when open_left=far. If front_blocked=yes, try 'use' before turning.",
        "turn_right": "Turn right when open_right=far. If front_blocked=yes, try 'use' before turning.",
        "use": "Select 'use' whenever front_blocked=yes. DOOM has hidden rooms and monster closets opened by wall switches. Try 'use' up to two times in total, the second from a slightly different position, before giving up and turning away.",
        "move_backward": "Retreat only if health is below 20 AND enemy is visible AND very close.",
        "strafe_attack_left": "Use when enemy_visible=yes AND enemy_side=left.",
        "strafe_attack_right": "Use when enemy_visible=yes AND enemy_side=right.",
        "advance_attack": "Use when enemy_visible=yes AND enemy_centered=yes.",
    },
}

# 全方針は同じキー集合を持ち、実行時にシナリオの利用可能ボタンで絞る。
for _name, _criteria in CRITERIA_SETS.items():
    CRITERIA_SETS[_name] = {
        action: _criteria.get(action, DEFAULT_CRITERIA[action])
        for action in ACTION_DEFINITIONS
    }


def configure_actions(scenario, criteria):
    """単独・複合を再登録し、実行可能な全候補に方針を適用する。"""
    actions = get_action_buttons(scenario)
    if isinstance(criteria, str):
        base = CRITERIA_SETS.get(criteria, SCENARIO_CRITERIA[scenario])
    else:
        base = criteria
    unknown = set(base) - set(ACTION_DEFINITIONS)
    if unknown:
        raise ValueError(f"Unknown actions: {sorted(unknown)}")
    ACTION_BUTTONS.clear()
    ACTION_BUTTONS.update(actions)
    return {name: base.get(name, DEFAULT_CRITERIA[name]) for name in actions}


# criteria ごとの敵検出閾値（red_mean > threshold で enemy_visible=yes）
THRESHOLDS = {
    "baseline": 48.0,
    "aggressive": 40.0,
    "defensive": 60.0,
    "explorer": 70.0,
}


BASE_INSTRUCTIONS = "Choose the single best next action for the DOOM agent."


def build_payload(state_text: str, criteria: str | dict = "baseline", order: str | None = None) -> dict:
    """Jev API に送る payload を組み立てる。order は System 3 の指示（criteria は変えない）"""
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
                "instructions": (
                    f"{BASE_INSTRUCTIONS} Strategic order from the commander: {order}"
                    if order else BASE_INSTRUCTIONS
                ),
                "criteria": dict(criteria_dict),
            }
        },
    }


# 直近の Jev API 呼び出しのレイテンシ（ms）。main がログに出す（行動には使わない）
LAST_JEV_LATENCY_MS = [None]


def get_jev_decision(
    api_key: str | None,
    state_text: str,
    criteria: str | dict = "baseline",
    timeout: float = 2.0,
    order: str | None = None,
) -> dict:
    """Jev API を呼び出して判断を取得する（Session 再利用）"""
    if api_key:
        _SESSION.headers.update({"Authorization": f"Bearer {api_key}"})
    elif "Authorization" in _SESSION.headers:
        del _SESSION.headers["Authorization"]
    t0 = time.perf_counter()
    try:
        response = _SESSION.post(
            JEV_API_URL,
            json=build_payload(state_text, criteria=criteria, order=order),
            timeout=timeout,
        )
    finally:  # タイムアウト（[skip]）でも記録する
        LAST_JEV_LATENCY_MS[0] = (time.perf_counter() - t0) * 1000
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
    front_blocked: bool | None = None,
    took_damage: bool | None = None,
    report_items: bool = False,
    report_open: bool = False,
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
            # ★ enemy_side: 動的中心（解像度対応）
            ne_x = info.get("nearest_enemy_x")
            if ne_x is not None:
                # screen_buffer の幅から動的に取得
                if state is not None and state.screen_buffer is not None:
                    _w = state.screen_buffer.shape[2]
                else:
                    _w = 160  # フォールバック
                _center = _w / 2
                side = "left" if ne_x < _center else "right"
                extra_parts.append(f"enemy_side={side}")
    if front_blocked is not None:
        extra_parts.append(f"front_blocked={'yes' if front_blocked else 'no'}")
    if took_damage is not None:
        # Phase 3a（2026-09-23）: 前回判断以降の被弾有無。画面外からの被弾への反応用
        extra_parts.append(f"took_damage={'yes' if took_damage else 'no'}")
    if report_open and state is not None and getattr(state, "depth_buffer", None) is not None:
        # 3方向の開け具合（far / mid / near）。どちらへ進めば歩けるかを Jev に渡す
        extra_parts.extend(f"{k}={v}" for k, v in open_directions(state.depth_buffer).items())
    if report_items:
        # アイテム報告（要求時のみ）。敵がいないときの回収判断用
        item_info = detect_items_from_labels(state)
        extra_parts.append(f"item_visible={'yes' if item_info['item_visible'] else 'no'}")
        if item_info["item_visible"]:
            extra_parts.append(
                f"item_centered={'yes' if item_info['item_centered'] else 'no'}"
            )
            extra_parts.append(f"item_types={','.join(item_info['item_names'])}")
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


def resolve_action(state, game_vars, *, use_labels, min_enemy_width, decide, allow_system1=True,
                   front_blocked=None, memory_summary="", took_damage=None,
                   report_items=False, report_open=False):
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
        state, game_vars, use_labels=use_labels, min_enemy_width=min_enemy_width,
        front_blocked=front_blocked, took_damage=took_damage,
        report_items=report_items, report_open=report_open,
    )
    if memory_summary:
        state_text = state_text + f" [Memory: {memory_summary}]"
    choice, probs = extract_choice_and_probs(decide(state_text))
    return choice, "system2", {
        "state_text": state_text,
        "red_mean": red_mean,
        "enemy_visible": enemy_visible,
        "probs": probs,
    }


def execute_action(game, action_vec, frame_skip, *, tap=False, press_tics=None):
    """tap=True なら 1tic だけ押して残りは離す（USE は押した瞬間しか作動せず、押しっぱなしでは再作動しない）。
    press_tics を指定すると、その tic 数だけ押して残りは離す（慎重な前進用）"""
    press = 1 if tap else (press_tics or frame_skip)
    if press >= frame_skip:
        return game.make_action(action_vec, frame_skip)
    reward = game.make_action(action_vec, press)
    if not game.is_episode_finished():
        reward += game.make_action([0] * len(action_vec), frame_skip - press)
    return reward


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


# オーバーレイ（tools/overlay.py）が読むステータスファイル。1行 = "TAG|本文"
# TAG: SYS1=反射層（WallAvoider/ForwardBlockDetector/AreaStagnationDetector/should_force_attack）,
#      SYS2=Jev, SYS3=Gemini, GAME=視覚・ゲーム状態
STATUS_FILE = "/tmp/jev_status.txt"


def _state_field(state_text: str, key: str) -> str:
    """state_text から key=value の値を取り出す（Jev に渡した内容をそのまま表示するため）"""
    marker = f"{key}="
    if marker not in state_text:
        return "-"
    return state_text.split(marker, 1)[1].split(",")[0].split()[0]


def format_status(*, jev_line: str, reason: str, sys1_events: list[str],
                  order: str | None, health, info: dict | None, tic: int) -> list[str]:
    """1判断ステップ分のオーバーレイ表示行を組み立てる"""
    lines = [f"SYS2|{jev_line}"]
    if reason:
        lines.append(f"SYS2|Reason: {reason}")
    if sys1_events:
        lines.extend(f"SYS1|{e}" for e in sys1_events)
    else:
        lines.append("SYS1|(no reflex)")
    lines.append(f"SYS3|Commander: {order[:100]}" if order else "SYS3|(no active order)")
    st = (info or {}).get("state_text", "")
    enemy = "yes" if (info or {}).get("enemy_visible") else "no"
    lines.append(f"GAME|HP={int(health)} Enemy={enemy} Centered={_state_field(st, 'enemy_centered')} "
                 f"Side={_state_field(st, 'enemy_side')} Blocked={_state_field(st, 'front_blocked')}")
    red = (info or {}).get("red_mean")
    lines.append(f"GAME|red_mean={red:.1f} tic={tic}" if red is not None else f"GAME|tic={tic}")
    return lines


def write_status(lines: list[str], path: str = STATUS_FILE) -> None:
    """一時ファイルに書いてから os.replace（オーバーレイが書きかけを読まないよう原子的に置換）"""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except OSError:
        pass  # 表示用なのでゲームは止めない



# 付け焼き刃: スタック判定（STUCK_TICS の間に STUCK_MOVE_EPS 単位以上動かなければ脱出）
STUCK_TICS = 30
STUCK_MOVE_EPS = 8.0
ESCAPE_STEPS = 4  # 脱出行動を続ける判断ステップ数（frame_skip=4 で 16tic）
ESCAPE_ORDER = ("move_right", "move_left", "move_backward")
# 敵が見えない間の move_forward は frame_skip のうちこの tic 数だけ押す（周囲を確認しながら小刻みに進む）
CAUTIOUS_FORWARD_TICS = 3


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
        "--seed",
        type=int,
        default=None,
        help="乱数の種。エピソード i は seed+i を使う（条件間で同じ敵の動きにそろえる比較用）",
    )
    parser.add_argument(
        "--no-open-dirs",
        action="store_true",
        help="3方向の開け具合（open_left/center/right）を Jev に渡さない（効果の切り分け用）",
    )
    parser.add_argument(
        "--no-door-fix",
        action="store_true",
        help="修正B（use 失敗検出・ドア待機の早期解除）を無効化（A/B 切り分け用）",
    )
    parser.add_argument(
        "--sound",
        action="store_true",
        help="ゲーム音を有効化（観戦時のみ推奨。長時間実験では指定しない）",
    )
    parser.add_argument(
        "--recording",
        action="store_true",
        help="録画モード: ticrate=35, frame_skip=1、audio_buffer=False（--soundでスピーカー出力）",
    )
    parser.add_argument(
        "--system3",
        action="store_true",
        help="System 3（Gemini）をトリガー時のみ非同期で呼び、Jev への instructions に指示を添える",
    )

    args = parser.parse_args()

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise EnvironmentError("TYPESAFE_API_KEY is not set")
    print(f"scenario={args.scenario} criteria={args.criteria} use_labels={args.use_labels}")

    # --- シナリオに応じて ACTION_BUTTONS を動的に切り替え ---
    scenario_buttons = SCENARIO_BUTTONS[args.scenario]
    filtered_criteria = configure_actions(args.scenario, args.criteria)
    print(f"ACTION_BUTTONS updated: {list(ACTION_BUTTONS.keys())}")

    # API 優先モード: frame_skip 大 + ticrate 低 = API待ちを吸収、カクカク抑制
    # recording モードでも API 優先（BGM は ffmpeg 後付）
    frame_skip = 8     # 8tic = 228ms ≒ API 250ms
    ticrate = 15       # 15 tic/s = 66ms/tic、ゲーム進行を遅く
    print(f"[MODE] frame_skip={frame_skip} ticrate={ticrate} (API-priority)")

    # --- 初期化: 極限軽量化 ---
    game = vzd.DoomGame()
    full_map = FULL_MAP_SCENARIOS.get(args.scenario)
    if full_map:
        game.load_config(f"{vzd.scenarios_path}/{full_map['cfg']}")
        game.set_doom_map(full_map["map"])
        game.set_doom_skill(full_map["skill"])  # 全滅目標（monsters_total）はこの難易度の敵数
        # deadly_corridor.cfg 相当に揃える（game_vars[0]=HEALTH 前提、HUD/フラッシュは red_mean を乱す）
        game.set_available_buttons([getattr(vzd.Button, b) for b in scenario_buttons])
        game.set_available_game_variables([vzd.GameVariable.HEALTH])
        game.set_episode_timeout(full_map["episode_timeout"])
        game.set_render_hud(True)
        game.set_render_messages(True)
        game.set_render_screen_flashes(False)
    else:
        game.load_config(f"{vzd.scenarios_path}/{args.scenario}.cfg")
    # 撃破数を取得（cfg書き換え不要。HEALTH の後に KILLCOUNT が追加される）
    game.add_available_game_variable(vzd.GameVariable.KILLCOUNT)
    # 弾消費メトリクス用（SELECTED_WEAPON_AMMO）。登録に失敗しても本編は動く
    try:
        game.add_available_game_variable(vzd.GameVariable.SELECTED_WEAPON_AMMO)
    except Exception:
        pass
    try:
        game.add_available_game_variable(vzd.GameVariable.POSITION_Z)
    except Exception:
        pass
    game.set_window_visible(True)  # ウィンドウ表示（リアルタイム可視化が要件のためTrueを維持）
    game.set_sound_enabled(args.sound)
    # スピーカー出力を維持し、PulseAudioで録音できるようにする。
    # 録画時はticrate=35、frame_skip=1を使用する。
    game.set_audio_buffer_enabled(False)
    # BGM は ffmpeg 後付のため、ゲーム内 BGM は無効
    # if args.sound:
    #     game.add_game_args("+snd_musicvolume 0.5")
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.set_depth_buffer_enabled("use" in ACTION_BUTTONS)  # 壁回避（WallAvoider）用
    game.set_labels_buffer_enabled(args.use_labels)  # labels検出を使う場合のみ有効化
    game.set_automap_buffer_enabled(False)
    # 鍵イベント検出用（WorldMemory・System 3）。バッファは直近N tic分なので frame_skip に合わせると取りこぼし・重複がない
    game.set_notifications_buffer_enabled(True)
    game.set_notifications_buffer_size(frame_skip)
    game.set_ticrate(ticrate)
    game.init()
    if args.sound:
        # このViZDoomのFluidSynthはlibfluidsynth.so.1を要求する。
        # 内蔵OPLなら追加ライブラリ不要。負値は起動引数でなく実行時に設定する。
        game.send_game_command("snd_mididevice -3")
        # BGM は ffmpeg 後付のため、ゲーム内 BGM は無効
        # game.send_game_command("snd_musicvolume 0.5")
        # print("[BGM] enabled: built-in OPL, volume=0.5")

    n_buttons = game.get_available_buttons_size()
    button_names = [str(b).split(".")[-1] for b in game.get_available_buttons()]
    print("Available buttons:", button_names)

    # 固定メモリ
    action_vec = [0] * n_buttons
    decision_interval_tic = 4  # 何ticごとにJevに聞くか（毎アクションごとに判断）

    sys3 = StrategicCoreSystem3() if args.system3 else None
    if sys3 is not None:
        sys3.start()

    viz = JevVisualizer()
    episode = 0
    choice = "move_forward"
    last_reward = 0.0

    print(f"Jev candidates: {list(filtered_criteria)}")

    while episode < 5:  # 5エピソード実行
        episode_seed = None if args.seed is None else args.seed + episode
        if episode_seed is not None:
            game.set_seed(episode_seed)
        game.new_episode()
        print(f"--- Episode {episode} ---")
        tic_counter = 0
        # P1: 被弾監視（合格条件 = health が100から一度も下がらない）
        hit_count = 0
        prev_health = 100
        prev_decision_health = 100  # Phase 3a: 前回判断時の HP（took_damage 判定用）
        hit_capture_until = -1  # 被弾後の撮影期限（tic）
        # System 1/2 発動回数
        system1_count = 0
        system2_count = 0
        prev_system1 = False
        last_kills = 0
        # USE を持つシナリオのみ front_blocked を state_text に載せる（他シナリオの入力は不変）
        block_detector = ForwardBlockDetector() if "use" in ACTION_BUTTONS else None
        front_blocked = None
        world_memory = WorldMemory()
        elevation = ElevationTracker()
        door_waiter = DoorWaiter(wait_tic=30)
        wall_avoider = WallAvoider() if block_detector is not None else None
        visited_cells = set()  # ★ 探索セル
        GRID_SIZE = 128
        stagnation_detector = AreaStagnationDetector() if sys3 is not None else None
        order = None
        # 付け焼き刃: スタック脱出の状態
        _last_pos = None
        _stuck_since = 0
        _escape_dir = None
        _escape_left = 0
        # 修正B: use の失敗検出とドア待機開始時の前方深度（--no-door-fix で無効）
        use_fail = None if args.no_door_fix else UseFailDetector()
        _door_depth = None
        # 弾消費の計測（武器が変わったステップの増減は数えない）
        ammo_used = 0
        damage_taken = 0  # 被ダメージの合計（回復アイテムの影響を受けない主指標）
        jev_latencies = []  # Jev API のレイテンシ（ms）。[skip] も含む
        ammo_min = None  # 銃（スロット1=拳・チェーンソー以外）の弾の最小値。0 なら弾切れ
        melee_steps = 0  # スロット1（拳・チェーンソー）を持っていたステップ数
        attack_steps = 0
        _prev_ammo = None
        _prev_weapon = None

        while not game.is_episode_finished():
            # 判断フレームのみ get_state() を呼ぶ
            if tic_counter % decision_interval_tic == 0:
                state = game.get_state()
                if state is None:
                    break
                sys1_events = []  # オーバーレイ用: このステップで反射層が動いた記録
                turn_move = False  # 付け焼き刃: 旋回に前進を同時押しするか
                cautious = False  # 敵不在の前進を小刻みにするか
                game_vars = list(state.game_variables)
                health = game_vars[0] if game_vars else 0
                if len(game_vars) > 1:
                    last_kills = int(game_vars[1])  # KILLCOUNT（追加変数）
                # P1: 被弾検出（health の減少を数える）
                if game_vars:
                    current_health = int(game_vars[0])
                    if current_health < prev_health:
                        hit_count += 1
                        damage_taken += prev_health - current_health
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
                position = (game.get_game_variable(vzd.GameVariable.POSITION_X),
                            game.get_game_variable(vzd.GameVariable.POSITION_Y))
                try:
                    position_z = game.get_game_variable(vzd.GameVariable.POSITION_Z)
                except Exception:
                    position_z = 0.0
                # ─── WorldMemory + Elevation 更新 ───
                world_memory.update(position, tic_counter,
                                    notifications=state.notifications_buffer or "",  # str（bytes ではない）
                                    front_blocked=bool(front_blocked))
                elevation.update(position_z)
                # ★ 探索セル記録
                visited_cells.add((int(position[0]) // 128, int(position[1]) // 128))
                # この時点の choice は前回の判断で実行済みの行動
                if block_detector is not None:
                    front_blocked = block_detector.update(position, choice)
                    if front_blocked:
                        sys1_events.append("ForwardBlock: front_blocked=yes")

                # System 3: トリガー発生時のみ非同期推論を依頼し、有効な指示を受け取る
                if sys3 is not None:
                    key_events = extract_key_events(state.notifications_buffer)
                    triggers = []
                    if front_blocked:
                        triggers.append(TRIGGER_FRONT_BLOCKED)
                    if stagnation_detector.update(position):
                        triggers.append(TRIGGER_AREA_STAGNATION)
                        sys1_events.append("AreaStagnation: stuck in area")
                    if key_events:
                        triggers.append(TRIGGER_KEY_EVENT)
                    sys3_state = {
                        "health": int(health),
                        "kills": last_kills,
                        "front_blocked": bool(front_blocked),
                        "position": [round(position[0]), round(position[1])],
                        "angle": round(game.get_game_variable(vzd.GameVariable.ANGLE)),
                        "key_events": key_events,
                    }
                    if args.use_labels:
                        label_info = detect_enemy_from_labels(state, min_width=args.min_width)
                        sys3_state["enemy_visible"] = label_info["enemy_visible"]
                        sys3_state["enemy_count"] = label_info["enemy_count"]
                    sys3.update_state(sys3_state, triggers)
                    order = sys3.get_current_instruction()

                # ─── WorldMemory 要約を state_text に追加（resolve_action 内で）───
                memory_summary = world_memory.get_summary()

                info = None
                jev_line, reason = "(no decision)", ""
                LAST_JEV_LATENCY_MS[0] = None  # System 1 で Jev を呼ばなかった判断と区別する
                # Phase 3a: 前回判断以降に HP が減っていれば被弾あり
                took_damage = int(health) < prev_decision_health
                prev_decision_health = int(health)
                try:
                    choice, source, info = resolve_action(
                        state,
                        game_vars,
                        use_labels=args.use_labels,
                        min_enemy_width=args.min_width if args.use_labels else 0.0,
                        decide=lambda text: get_jev_decision(
                            api_key, text, criteria=filtered_criteria, timeout=1.0,
                            order=order,
                        ),
                        allow_system1=not prev_system1,
                        front_blocked=front_blocked,
                        memory_summary=memory_summary,
                        took_damage=took_damage,
                        report_items=True,
                        report_open=not args.no_open_dirs,
                    )
                    prev_system1 = (source == "system1")
                    if source == "system1":
                        system1_count += 1
                        print(f"step={tic_counter} [System1] FORCED attack "
                              f"(centered, width={info['nearest_enemy_width']:.0f})")
                        jev_line = "(bypassed by System 1)"
                        sys1_events.append(
                            f"force_attack (width={info['nearest_enemy_width']:.0f})")
                    else:
                        system2_count += 1
                        viz.log(info["probs"], last_reward, health)
                        print(f"step={tic_counter} Jev -> {choice} | "
                              f"red_mean={info['red_mean']:.1f} | "
                              f"enemy_visible={'yes' if info['enemy_visible'] else 'no'}")
                        print(f"    state_text: {info['state_text']}")
                        if order:
                            print(f"    order(System3): {order}")
                        jev_line = f"Jev -> {choice}"
                        reason = filtered_criteria.get(choice, "")[:80]
                except Exception as e:
                    print(f"[skip] {e}")
                    jev_line = f"[skip] {str(e)[:60]}"
                if LAST_JEV_LATENCY_MS[0] is not None:  # 成功・[skip] とも（System 1 のみの判断は除く）
                    jev_latencies.append(LAST_JEV_LATENCY_MS[0])
                    print(f"step={tic_counter} [Jev] latency={LAST_JEV_LATENCY_MS[0]:.0f}ms")

                # 付け焼き刃: STUCK_TICS の間ほぼ動かなければ 右→左→後退 の順に脱出を試す。
                # ドア待機中（意図的な停止）と敵視認中（立ち止まって撃つのが正常）は数えない
                enemy_now = info is not None and info.get("enemy_visible")
                if (enemy_now or door_waiter.is_waiting() or _last_pos is None
                        or math.dist(position, _last_pos) > STUCK_MOVE_EPS):
                    _last_pos, _stuck_since = position, tic_counter
                elif _escape_left == 0 and tic_counter - _stuck_since >= STUCK_TICS:
                    dirs = [d for d in ESCAPE_ORDER if d in ACTION_BUTTONS]
                    if dirs:
                        _escape_dir = dirs[(dirs.index(_escape_dir) + 1) % len(dirs)] if _escape_dir in dirs else dirs[0]
                        _escape_left = ESCAPE_STEPS
                        _stuck_since = tic_counter
                        print(f"step={tic_counter} [Stuck] {STUCK_TICS}tic 停止 -> {_escape_dir}")
                if _escape_left > 0:
                    _escape_left -= 1
                    sys1_events.append(f"Stuck: {choice} -> {_escape_dir}")
                    choice = _escape_dir

                # 反射層（Jev の判断の後）：壁に向かう前進を止める。地点ごとに use 1回、以後は開けた側へ旋回
                if wall_avoider is not None:
                    steered = wall_avoider.filter(choice, state.depth_buffer, position, front_blocked)
                    if steered != choice:
                        print(f"step={tic_counter} [Reflex] {choice} -> {steered} (wall ahead)")
                        sys1_events.append(f"WallAvoider: {choice} -> {steered}")
                        choice = steered

                # 修正B: ドア待機の早期解除（開いたら即再開、変化がなければドアではない）
                if (not args.no_door_fix and door_waiter.is_waiting() and _door_depth is not None
                        and state.depth_buffer is not None):
                    waited = door_waiter.total_wait - door_waiter.wait_remaining
                    verdict = door_wait_verdict(_door_depth, center_depth(state.depth_buffer), waited)
                    if verdict is not None:
                        door_waiter.reset()
                        print(f"step={tic_counter} [DoorWait] {verdict} ({waited}tic) -> resume")

                # 修正B: 同じ地点で use が続けて失敗（その場に留まっている）したら turn_right で離れる
                if use_fail is not None:
                    steered = use_fail.filter(choice, position)
                    if steered != choice:
                        print(f"step={tic_counter} [UseFail] repeated use at same spot -> {steered}")
                        sys1_events.append(f"UseFail: {choice} -> {steered}")
                        choice = steered

                # 弾消費: 同じ武器のまま弾が減った分を数える（拾った分・持ち替えは除外）
                weapon = game.get_game_variable(vzd.GameVariable.SELECTED_WEAPON)
                ammo = game.get_game_variable(vzd.GameVariable.SELECTED_WEAPON_AMMO)
                if _prev_ammo is not None and weapon == _prev_weapon and ammo < _prev_ammo:
                    ammo_used += int(_prev_ammo - ammo)
                _prev_ammo, _prev_weapon = ammo, weapon
                if int(weapon) == 1:
                    melee_steps += 1
                else:
                    ammo_min = ammo if ammo_min is None else min(ammo_min, ammo)

                # 付け焼き刃: 敵不在の旋回は前進も同時押しし、その場で回り続けず弧を描いて進む。
                # 敵視認中（照準合わせ）・脱出中・前方が壁（WallAvoider の旋回を含む）は変更しない
                if (choice in ("turn_left", "turn_right") and not enemy_now and _escape_left == 0
                        and not front_blocked and state.depth_buffer is not None):
                    d = state.depth_buffer
                    h, w = d.shape
                    if np.median(d[h // 2 - 3:h // 2 + 3, w * 2 // 5:w * 3 // 5]) > WALL_NEAR_DEPTH:
                        turn_move = True
                        print(f"step={tic_counter} [TurnMove] {choice} + MOVE_FORWARD")
                        sys1_events.append(f"TurnMove: {choice} + MOVE_FORWARD")

                # 敵が見えないまま前進し続けないよう、敵不在の move_forward は小刻みにする
                if choice == "move_forward" and not enemy_now:
                    cautious = True

                write_status(format_status(
                    jev_line=jev_line, reason=reason, sys1_events=sys1_events,
                    order=order, health=health, info=info, tic=tic_counter,
                ))

            # 候補登録と同じ辞書を使い、複合の全ボタンを同時押しする。
            action_vec[:] = build_action_vector(choice, button_names, ACTION_BUTTONS)
            if "ATTACK" in button_names and action_vec[button_names.index("ATTACK")] and not door_waiter.is_waiting():
                attack_steps += 1
            if turn_move and "MOVE_FORWARD" in button_names:
                action_vec[button_names.index("MOVE_FORWARD")] = 1
            target = ACTION_BUTTONS[choice]

            # ドア待機中は前進・旋回を抑制
            if door_waiter.is_waiting():
                if not door_waiter.tick(frame_skip):
                    print(f"step={tic_counter} [DoorWait] done")
                # 待機中は行動せず、その場で待つ
                last_reward = game.make_action([0] * n_buttons, frame_skip)
            else:
                # フレームスキップで進める（USE はタップ）
                last_reward = execute_action(
                    game, action_vec, frame_skip, tap=(target == "USE"),
                    press_tics=CAUTIOUS_FORWARD_TICS if cautious else None,
                )
                # ─── use 実行後にドア待機開始（実行前に start すると同ステップで待機に入り USE が消える）───
                if target == "USE":
                    door_waiter.start()
                    _door_depth = (center_depth(state.depth_buffer)
                                   if state is not None and state.depth_buffer is not None else None)
            tic_counter += frame_skip

        # P1: エピソード終了時の被弾サマリー
        # SSOT: I_EXIT = 1 は「timeout前 + 生存」
        # ★ 死亡判定: エピソードが早期終了（timeout=2100未満）したら死亡扱い
        # （現在、EXIT到達判定は未実装のため、早期終了 = 死亡と見なす）
        episode_ended_early = (tic_counter < 2100)
        
        # より正確な health 取得を試みる
        final_health = prev_health
        try:
            if game.is_episode_finished():
                # 最後の state を取得できる場合がある
                _fs = game.get_state()
                if _fs is not None and len(_fs.game_variables) > 0:
                    final_health = int(_fs.game_variables[0])
        except Exception:
            pass
        
        is_dead = episode_ended_early or (final_health <= 0)
        
        # ★ ゲームオーバー画面を保持（人間が目視できるように）
        if is_dead and episode_ended_early:
            print(f"[GAME OVER] Episode {episode} - 死亡（early end at tic={tic_counter}）。10秒保持")
            import time as _time
            for _i in range(10):
                _time.sleep(1)
                print(f"  ...{_i+1}/10")
            print("[GAME OVER] 次のエピソードへ")
        elif tic_counter >= 2100:
            print(f"[TIMEOUT] Episode {episode} - タイムアウト（生存）。5秒待機")
            import time as _time
            for _i in range(5):
                _time.sleep(1)
                print(f"  ...{_i+1}/5")
        
        i_exit = 1 if (not is_dead and tic_counter < 2100) else 0
        print(f"Episode {episode} done: hits={hit_count}, "
              f"final_health={prev_health}, steps={tic_counter}, "
              f"sys1={system1_count}, sys2={system2_count}, "
              f"kills={last_kills}, visited_cells={len(world_memory.visited_cells)}, "
              f"max_distance={world_memory.max_distance:.0f}, "
              f"keys={len(world_memory.keys_obtained)}, "
              f"dead_ends={len(world_memory.dead_ends)}, "
              f"i_exit={i_exit}, "
              f"kills_total={full_map['monsters_total'] if full_map else 0}, "
              f"ammo_used={ammo_used}, attack_steps={attack_steps}, "
              f"dmg_hits={int(game.get_game_variable(vzd.GameVariable.HITCOUNT))}, "
              f"damage_taken={damage_taken}, "
              f"ammo_min={int(ammo_min) if ammo_min is not None else -1}, melee_steps={melee_steps}, "
              f"seed={episode_seed if episode_seed is not None else -1}, "
              f"jev_latency_median={statistics.median(jev_latencies) if jev_latencies else -1:.0f}")
        episode += 1

    if sys3 is not None:
        sys3.stop()
    game.close()
    viz.save("jev_visualization.png")


if __name__ == "__main__":
    main()
