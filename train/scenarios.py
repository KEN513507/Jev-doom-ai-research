"""ViZDoomシナリオごとのボタン・criteria定義。

各シナリオの .cfg ファイルに定義された available_buttons と
criteria のキーを一致させる必要がある。
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
