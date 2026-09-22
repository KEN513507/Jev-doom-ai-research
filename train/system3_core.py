import os
import time
import json
import threading
from typing import Dict, Any, Optional

# google-genai SDK または google.generativeai を使用
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# フレーム問題を排除するための厳格なシステムプロンプト
SYSTEM_INSTRUCTION = """
You are a deterministic, zero-hallucination spatial navigation state machine for DOOM.
Your SOLE PURPOSE is to analyze the game state vector and issue macro goals.

CRITICAL RULES:
1. Ignore all general knowledge unassociated with standard DOOM mechanics.
2. If 'front_blocked' is True, your HIGHEST priority is instructing the agent to 'use' (interact) or 'turn'.
3. OUTPUT ONLY VALID JSON. No prose, no markdown code blocks, no conversational explanations.
"""

class StrategicCoreSystem3(threading.Thread):
    """
    System 3: Gemini Flash を用いた非同期・戦略司令塔クラス
    ゲームのメインループ（35 tics/s）を一切止めることなく、バックグラウンドで高次の目標を更新します。
    """
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        super().__init__(daemon=True)
        self.model_name = model_name
        self.api_key = os.environ.get("GEMINI_API_KEY")
        
        # 共有ステート（System 1 / 2 と非同期でデータ授受）
        self.latest_state: Dict[str, Any] = {}
        self.current_instruction: str = "Explore area and proceed forward."
        self.should_trigger: bool = False
        self.lock = threading.Lock()
        self.running = True

        if HAS_GENAI and self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
            if not self.api_key:
                print("[System 3 Warning] GEMINI_API_KEY is not set. Running in dummy mode.")

    def update_state(self, state_vector: Dict[str, Any]):
        """System 1 / 2 からゲームの最新状況を受け取る (軽量・ロック処理)"""
        with self.lock:
            self.latest_state = state_vector
            # front_blocked=True などの緊急イベント発生時に推論フラグを立てる
            if state_vector.get("front_blocked", False):
                self.should_trigger = True

    def get_current_instruction(self) -> str:
        """System 2 (Jev) が参照する最新のプロンプト（CRITERIA）指示を取得"""
        with self.lock:
            return self.current_instruction

    def run(self):
        """バックグラウンドで Gemini Flash API を必要時のみ呼び出す非同期ループ"""
        last_call_time = 0
        min_call_interval = 2.0  # API消費と連打を防ぐ安全間隔（秒）

        while self.running:
            time.sleep(0.1)
            now = time.time()

            # 発動条件: イベント発生時 (front_blocked=True) または一定時間経過時
            with self.lock:
                trigger = self.should_trigger or (now - last_call_time > 10.0)
                current_state = dict(self.latest_state)

            if trigger and (now - last_call_time >= min_call_interval):
                self.should_trigger = False
                last_call_time = now
                self._query_gemini(current_state)

    def _query_gemini(self, state: Dict[str, Any]):
        """Context Isolation（極小化データ）のみを Gemini に渡して JSON 推論を実行"""
        if not self.client:
            # APIキーがない場合のフォールバック（ローカルルール判断）
            if state.get("front_blocked"):
                with self.lock:
                    self.current_instruction = "Front is blocked. Use 'use' button immediately to open the door."
            return

        # Gemini に渡す極小化された入力テキスト（フレーム問題対策）
        minimal_input = {
            "front_blocked": state.get("front_blocked", False),
            "health": state.get("health", 100),
            "enemy_visible": state.get("enemy_visible", False),
            "enemy_count": state.get("enemy_count", 0),
            "position": state.get("position", (0, 0))
        }

        prompt = f"Current DOOM State Vector: {json.dumps(minimal_input)}\nProvide JSON decision."

        try:
            # Gemini 2.0 / 2.5 Flash の高速 JSON 推論呼び出し
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.1,  # 決定論的な出力を保証
                    response_mime_type="application/json",  # 強制 JSON フォーマット
                )
            )

            res_json = json.loads(response.text)
            macro_goal = res_json.get("macro_goal", "Explore forward.")

            with self.lock:
                self.current_instruction = macro_goal
                print(f"\n[System 3 Gemini Flash Output] {macro_goal}")

        except Exception as e:
            # 通信エラーやフォーマット異常時のガードレール（ゲームを止めない）
            print(f"\n[System 3 Error] {e} -> Fallback to default instruction.")
            if state.get("front_blocked"):
                with self.lock:
                    self.current_instruction = "Front is blocked. Use 'use' to open door."

    def stop(self):
        self.running = False