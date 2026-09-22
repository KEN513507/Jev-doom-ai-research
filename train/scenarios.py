"""ViZDoomシナリオごとのボタン・criteria定義。

各シナリオの .cfg ファイルに定義された available_buttons と
各アクションの構成ボタンがすべて利用可能である必要がある。
"""

# シナリオ名 → 利用可能なボタン名（ViZDoomの .cfg に合わせる）
SCENARIO_BUTTONS = {
    "basic": ["MOVE_LEFT", "MOVE_RIGHT", "ATTACK"],
    "deadly_corridor": [
        "MOVE_LEFT", "MOVE_RIGHT", "ATTACK",
        "MOVE_FORWARD", "MOVE_BACKWARD",
        "TURN_LEFT", "TURN_RIGHT",
    ],
    "defend_the_center": ["TURN_LEFT", "TURN_RIGHT", "ATTACK"],
    "defend_the_line": ["TURN_LEFT", "TURN_RIGHT", "ATTACK"],
    "my_way_home": [
        "MOVE_FORWARD", "MOVE_BACKWARD",
        "TURN_LEFT", "TURN_RIGHT",
    ],
    "health_gathering": ["MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT"],
    "health_gathering_supreme": ["MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT"],
    "predict_position": ["MOVE_LEFT", "MOVE_RIGHT", "ATTACK"],
    "take_cover": [
        "MOVE_LEFT", "MOVE_RIGHT",
        "MOVE_FORWARD", "MOVE_BACKWARD", "ATTACK",
    ],
    "full_map": [
        "MOVE_LEFT", "MOVE_RIGHT", "ATTACK",
        "MOVE_FORWARD", "MOVE_BACKWARD",
        "TURN_LEFT", "TURN_RIGHT", "USE",
    ],
}

# 単独・複合の唯一の定義源。シナリオ別の辞書はこの定義から生成する。
ACTION_DEFINITIONS = {
    button.lower(): button
    for buttons in SCENARIO_BUTTONS.values()
    for button in buttons
}
ACTION_DEFINITIONS.update({
    "strafe_attack_left": ["MOVE_LEFT", "ATTACK"],
    "strafe_attack_right": ["MOVE_RIGHT", "ATTACK"],
    "advance_attack": ["MOVE_FORWARD", "ATTACK"],
})


def action_components(choice):
    target = ACTION_DEFINITIONS.get(choice, [])
    return (target,) if isinstance(target, str) else tuple(target)


def get_action_buttons(scenario_name):
    available = set(SCENARIO_BUTTONS[scenario_name])
    return {
        name: target.copy() if isinstance(target, list) else target
        for name, target in ACTION_DEFINITIONS.items()
        if set(action_components(name)) <= available
    }


def build_action_vector(choice, button_names, actions):
    """実行時辞書と実機ボタンを検証し、複合を同時押しにする。"""
    target = actions[choice]
    components = [target] if isinstance(target, str) else target
    missing = set(components) - set(button_names)
    if missing:
        raise ValueError(f"Unavailable buttons for {choice}: {sorted(missing)}")
    return [int(button in components) for button in button_names]


# 同梱 .cfg 名とシナリオ名が一致しないフルマップ用の設定
# freedoom2.cfg はゲーム変数なし・19ボタン・126000tic上限のため main 側で上書きする
FULL_MAP_SCENARIOS = {
    # skill 3 の MAP01 の敵は 18体（Zombieman 11, ShotgunGuy 4, Imp 3。WAD の THINGS から実測）= 全滅目標
    "full_map": {"cfg": "freedoom2.cfg", "map": "map01", "episode_timeout": 2100,
                 "skill": 3, "monsters_total": 18},
}


# criteria キーは小文字化したボタン名（例: MOVE_FORWARD → move_forward）
SCENARIO_CRITERIA = {
    "basic": {
        "move_left": "Strafe left to align with the enemy.",
        "move_right": "Strafe right to align with the enemy.",
        "attack": "Fire at the visible enemy.",
    },
    "deadly_corridor": {
        "move_left": "Strafe left to dodge incoming fire.",
        "move_right": "Strafe right to dodge incoming fire.",
        "attack": "Fire IMMEDIATELY at any visible enemy.",
        "move_forward": "Advance only when no enemy is visible.",
        "move_backward": "Retreat only if health is critically low.",
        "turn_left": "Rotate left to scan or aim.",
        "turn_right": "Rotate right to scan or aim.",
    },
    "defend_the_center": {
        "turn_left": "Rotate left to face the enemy.",
        "turn_right": "Rotate right to face the enemy.",
        "attack": "Fire immediately when an enemy is visible.",
    },
    "defend_the_line": {
        "turn_left": "Rotate left to track the incoming enemy.",
        "turn_right": "Rotate right to track the incoming enemy.",
        "attack": "Fire at the visible enemy.",
    },
    "my_way_home": {
        "move_forward": "Advance toward the goal.",
        "move_backward": "Retreat if blocked or cornered.",
        "turn_left": "Rotate left to navigate around obstacles.",
        "turn_right": "Rotate right to navigate around obstacles.",
    },
    "health_gathering": {
        "move_forward": "Advance toward the nearest health pack.",
        "turn_left": "Rotate left to locate a health pack.",
        "turn_right": "Rotate right to locate a health pack.",
    },
    "health_gathering_supreme": {
        "move_forward": "Advance toward the nearest health pack.",
        "turn_left": "Rotate left to locate a health pack.",
        "turn_right": "Rotate right to locate a health pack.",
    },
    "predict_position": {
        "move_left": "Strafe left to track the moving enemy.",
        "move_right": "Strafe right to track the moving enemy.",
        "attack": "Fire at the predicted enemy position.",
    },
    "take_cover": {
        "move_left": "Move left to take cover.",
        "move_right": "Move right to take cover.",
        "move_forward": "Advance cautiously.",
        "move_backward": "Retreat to cover.",
        "attack": "Fire at the visible enemy.",
    },
    "full_map": {
        "move_left": "Strafe left to peek around corners or dodge fire.",
        "move_right": "Strafe right to peek around corners or dodge fire.",
        "attack": "Fire at any visible enemy.",
        "move_forward": "Advance to explore the map.",
        "move_backward": "Retreat behind cover if under heavy fire.",
        "turn_left": "Rotate left to scan or aim.",
        "turn_right": "Rotate right to scan or aim.",
        "use": "Press USE to open a door or activate a switch directly in front.",
    },
}


DEFAULT_CRITERIA = {
    **SCENARIO_CRITERIA["full_map"],
    "strafe_attack_left": "Strafe left AND fire simultaneously only when enemy_centered=yes and dodging is needed.",
    "strafe_attack_right": "Strafe right AND fire simultaneously only when enemy_centered=yes and dodging is needed.",
    "advance_attack": "Advance AND fire simultaneously only when enemy_centered=yes and the path ahead is clear.",
}

for _scenario, _criteria in SCENARIO_CRITERIA.items():
    SCENARIO_CRITERIA[_scenario] = {
        name: _criteria.get(name, DEFAULT_CRITERIA[name])
        for name in get_action_buttons(_scenario)
    }


def get_scenario_config(scenario_name: str) -> tuple[list[str], dict[str, str]]:
    """シナリオ名から (buttons, criteria) を取得する。
    
    Returns:
        (button_names, criteria_dict)
    
    Raises:
        ValueError: 未知のシナリオ名の場合
    """
    if scenario_name not in SCENARIO_BUTTONS:
        raise ValueError(
            f"Unknown scenario: {scenario_name!r}. "
            f"Available: {sorted(SCENARIO_BUTTONS.keys())}"
        )
    return SCENARIO_BUTTONS[scenario_name], dict(SCENARIO_CRITERIA[scenario_name])
