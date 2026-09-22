"""System 3（戦略司令塔）: Gemini をトリガー発生時のみ非同期で呼び、Jev への高次指示を更新する。

通常時は休眠（API 呼び出しなし）。ボタン選択は常に Jev（System 2）が行い、
System 3 は Jev への問いかけ文（payload の instructions）に添える指示を1文更新するだけ。
指示は ORDER_TTL_SEC で失効し、Jev は既定の問いかけに戻る。
"""
import json
import os
import threading
import time

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

DEFAULT_MODEL = "gemini-flash-latest"  # tools/gemini_analyze.py と同じ
MIN_CALL_INTERVAL_SEC = 2.0
ORDER_TTL_SEC = 10.0

TRIGGER_FRONT_BLOCKED = "front_blocked"
TRIGGER_AREA_STAGNATION = "area_stagnation"
TRIGGER_KEY_EVENT = "key_event"

SYSTEM_INSTRUCTION = """You are the strategic commander (System 3) of a DOOM-playing agent.
A separate tactical model (Jev) chooses every button press. You only issue one short order that Jev will read.
You are called only when a trigger fires:
- front_blocked: moving forward made no progress (a wall or a closed door is directly ahead).
- area_stagnation: the agent has stayed within a small area for about 5 seconds.
- key_event: an in-game message about a key (picked up, or a locked door needs one).
Jev's available actions: move_forward, move_left, move_right, turn_left, turn_right, attack, use.
A reflex already stops the agent before walls, presses 'use' once at each blocked spot, and turns away.
So order where to go next (e.g. turn around, take another passage), not 'use'.
Base the order only on the given state. Reply with JSON only."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "macro_goal": {
            "type": "string",
            "description": "One imperative sentence (max 20 words) for Jev.",
        }
    },
    "required": ["macro_goal"],
}


def local_order(triggers, state) -> str:
    """API キーなし・SDK なし・Gemini エラー時のローカル規則"""
    if TRIGGER_KEY_EVENT in triggers:
        events = "; ".join(state.get("key_events") or []) or "key message"
        return f"Key event ({events}): find the door of the matching color and go through it."
    if TRIGGER_FRONT_BLOCKED in triggers:
        return "The way ahead is blocked: turn toward an open direction and explore another passage."
    return "You have stayed in the same small area too long: turn around and head for an unexplored passage."


class StrategicCoreSystem3(threading.Thread):
    def __init__(self, model_name: str = DEFAULT_MODEL, *, clock=time.monotonic):
        super().__init__(daemon=True)
        self.model_name = model_name
        self._clock = clock
        self._lock = threading.Lock()
        self._running = True
        self._latest_state = {}
        self._pending_triggers = set()
        self._order = None
        self._order_expires = 0.0
        self._last_call = float("-inf")

        api_key = os.environ.get("GEMINI_API_KEY")
        self.client = None
        if not api_key:
            print("[System 3] GEMINI_API_KEY 未設定: ダミーモード（ローカル規則）で動作")
        elif not HAS_GENAI:
            print("[System 3] google-genai 未導入: ダミーモード（ローカル規則）で動作")
        else:
            self.client = genai.Client(api_key=api_key)

    def update_state(self, state: dict, triggers=()):
        """毎判断ステップ呼ぶ。triggers が空なら状態を保持するだけ（推論しない）"""
        with self._lock:
            self._latest_state = dict(state)
            self._pending_triggers.update(triggers)

    def get_current_instruction(self):
        """有効な指示があれば返す。失効・未発行なら None"""
        with self._lock:
            if self._order is not None and self._clock() < self._order_expires:
                return self._order
            return None

    def run(self):
        while self._running:
            time.sleep(0.1)
            self.step()

    def step(self) -> bool:
        """保留中のトリガーがあり最小間隔を過ぎていれば1回推論する。推論したら True"""
        with self._lock:
            if not self._pending_triggers:
                return False
            if self._clock() - self._last_call < MIN_CALL_INTERVAL_SEC:
                return False
            triggers = sorted(self._pending_triggers)
            self._pending_triggers.clear()
            state = dict(self._latest_state)
            self._last_call = self._clock()

        order = self._decide(triggers, state)
        with self._lock:
            self._order = order
            self._order_expires = self._clock() + ORDER_TTL_SEC
        print(f"[System 3] triggers={triggers} -> {order}")
        return True

    def _decide(self, triggers, state) -> str:
        if self.client is None:
            return local_order(triggers, state)
        try:
            return self._query_gemini(triggers, state)
        except Exception as e:
            print(f"[System 3] Gemini error: {e} -> ローカル規則で代替")
            return local_order(triggers, state)

    def _query_gemini(self, triggers, state) -> str:
        payload = {"triggers": triggers, **state}
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=f"Current DOOM state: {json.dumps(payload)}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.1,
                response_mime_type="application/json",
                response_json_schema=RESPONSE_SCHEMA,
            ),
        )
        goal = json.loads(response.text)["macro_goal"].strip()
        if not goal:
            raise ValueError("empty macro_goal")
        return goal

    def stop(self):
        self._running = False
