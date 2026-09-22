"""特殊部隊CQBドクトリンに基づく戦術的機動（System 3 の上位司令）"""
from enum import Enum
from collections import Counter


class TacticalState(Enum):
    SCAN = "scan"
    ADVANCE = "advance"
    STACK_UP = "stack"
    SLICE = "slice"
    COMBAT = "combat"


class TacticalController:
    """毎判断フレームで tactical_order を返す"""

    def __init__(self, scan_interval=4, advance_interval=8, reflex_lock_steps=3, jev_delegate_every=4):
        # ADVANCE 中は jev_delegate_every ステップに1回 Jev に委ねる（既定: 8ステップ中2回）
        self.jev_delegate_every = jev_delegate_every
        self.state = TacticalState.SCAN
        self.state_ticks = 0
        self.scan_direction = "left"
        self.last_position = None
        self.stuck_counter = 0
        self.scan_interval = scan_interval
        self.advance_interval = advance_interval
        # 修正1: Reflex ヒステリシス
        self.reflex_lock_steps = reflex_lock_steps
        self.reflex_lock_counter = 0
        self.reflex_locked_action = None
        self.last_reflex_direction = None
        self.last_reflex_tic = -999

    def update(self, enemy_visible, front_blocked, position, current_tic=0):
        """次の姿勢指示を返す。"""
        self.state_ticks += 1
        x, y = position if position else (None, None)

        # 修正1: Reflex ロック中は同じ action を強制継続
        if self.reflex_lock_counter > 0:
            self.reflex_lock_counter -= 1
            return {
                "action": self.reflex_locked_action,
                "reason": f"Reflex lock ({self.reflex_lock_counter} steps left)",
                "priority": "high",
                "locked": True,
            }

        # スタック検出（position が None の場合はスキップ）
        if x is not None and y is not None:
            if self.last_position and (x, y) == self.last_position:
                self.stuck_counter += 1
            else:
                self.stuck_counter = 0
            self.last_position = (x, y)

        # 状態遷移
        if enemy_visible:
            self._transition(TacticalState.COMBAT)
        elif self.stuck_counter >= 12:  # 12step同じセルなら真の停滞
            self._transition(TacticalState.SCAN)
        elif self.state == TacticalState.SCAN:
            if self.state_ticks >= self.scan_interval:
                self._transition(TacticalState.ADVANCE)
        elif self.state == TacticalState.ADVANCE:
            if front_blocked:
                self._transition(TacticalState.STACK_UP)
            elif self.state_ticks >= self.advance_interval:
                self._transition(TacticalState.SCAN)
        elif self.state == TacticalState.STACK_UP:
            if self.state_ticks >= 6:
                self._transition(TacticalState.SLICE)
        elif self.state == TacticalState.SLICE:
            if self.state_ticks >= 4:
                self._transition(TacticalState.ADVANCE)
        elif self.state == TacticalState.COMBAT:
            if not enemy_visible:
                self._transition(TacticalState.SCAN)

        return self._get_instruction(current_tic)

    def _transition(self, new_state):
        if self.state != new_state:
            self.state = new_state
            self.state_ticks = 0

    def _get_instruction(self, current_tic):
        if self.state == TacticalState.SCAN:
            direction = self.scan_direction
            self.scan_direction = "right" if direction == "left" else "left"
            # 修正1: ロック設定
            self.reflex_lock_counter = self.reflex_lock_steps
            self.reflex_locked_action = f"turn_{direction}"
            self.last_reflex_direction = direction
            self.last_reflex_tic = current_tic
            return {
                "action": f"turn_{direction}",
                "reason": f"Sector scan (locked {self.reflex_lock_steps} steps)",
                "priority": "high",
                "locked": False,
            }
        elif self.state == TacticalState.ADVANCE:
            # criteria の判断を記録するため、一部のステップは Jev に委ねる
            if self.state_ticks % self.jev_delegate_every == self.jev_delegate_every - 1:
                return {
                    "action": None,
                    "reason": "Bounding: Jev decides",
                    "priority": None,
                    "locked": False,
                }
            # ADVANCE中は強制前進（Jevの逆旋回を防止）
            return {
                "action": "move_forward",
                "reason": "Bounding: forced advance",
                "priority": "high",
                "locked": False,
            }
        elif self.state == TacticalState.STACK_UP:
            return {
                "action": "use",
                "reason": "Stack up at door",
                "priority": "high",
                "locked": False,
            }
        elif self.state == TacticalState.SLICE:
            # SLICEは慎重な前進（強制）
            return {
                "action": "move_forward",
                "reason": "Slicing: careful peek",
                "priority": "high",
                "locked": False,
            }
        elif self.state == TacticalState.COMBAT:
            # 戦闘中は攻撃を最優先（Jevに委ねない）
            return {
                "action": "attack",
                "reason": "Combat: force attack",
                "priority": "critical",
                "locked": False,
            }
        return {"action": None, "reason": "default", "priority": None, "locked": False}


# ═══════════════════════════════════════════════════════════
# 修正3: 滞留検出 → System 3（Gemini）への介入要求
# ═══════════════════════════════════════════════════════════

STAGNATION_WINDOW = 40
STAGNATION_THRESHOLD = 8


class StagnationDetector:
    """同一エリアに留まっているかを検出し、Gemini介入をトリガーする"""

    def __init__(self, window=STAGNATION_WINDOW, threshold=STAGNATION_THRESHOLD):
        self.window = window
        self.threshold = threshold
        self.position_history = []
        self.stagnation_tic = -999
        self.intervention_pending = False
        self.GRID_SIZE = 128

    def _to_grid(self, pos):
        if pos is None or pos[0] is None:
            return None
        return (int(pos[0]) // self.GRID_SIZE, int(pos[1]) // self.GRID_SIZE)

    def update(self, position, current_tic):
        grid = self._to_grid(position)
        if grid is None:
            return False

        self.position_history.append(grid)
        if len(self.position_history) > self.window:
            self.position_history.pop(0)

        if len(self.position_history) < self.window:
            return False

        most_common = Counter(self.position_history).most_common(1)[0]
        if most_common[1] >= self.threshold:
            if not self.intervention_pending:
                self.stagnation_tic = current_tic
                self.intervention_pending = True
                self.position_history.clear()
                return True
        else:
            if self.intervention_pending and most_common[1] < self.threshold // 2:
                self.intervention_pending = False

        return False

    def get_gemini_prompt(self) -> str:
        return (
            "CRITICAL: The agent has been stuck in the same area for over "
            f"{self.window} steps. It is likely in a decision loop. "
            "Issue a DECISIVE instruction: move_forward for many steps ignoring walls, "
            "OR turn_left or turn_right in one direction and keep going. Do NOT oscillate."
        )

    def get_forced_action(self) -> str:
        return "turn_left"
