"""行動タイムライン（JSONL）: 実際に game.make_action() がゲームを進めた単位（segment）ごとに1行。

診断専用。行動・tic 数・make_action 回数は変えない（make_action をそのまま1回ずつ委譲する）。
用語（2026-09-23 固定）:
    decision_source: forced_attack（Jev を呼ぶ前の強制攻撃）/ jev（Jev が選択）/ skip（API 失敗等で判断なし）
    rewritten_by:    Jev・強制攻撃の後で行動を変えた後処理（Stuck, WallAvoider, UseFail, TurnMove,
                     CautiousForward, DoorWait）。decision_source ではない
enemy_visible / enemy_types は判断時（行動ウィンドウ開始時）の観測。被弾の原因の証明ではなく関連付け
（damage_source_association）にだけ使う。
"""
import json
from pathlib import Path


class ActionTimeline:
    """game のプロキシ。make_action だけ横取りして記録し、それ以外は game に委譲する。

    使い方: begin(**判断単位の項目) → execute_action(timeline, ...) などで make_action → 各 segment を1行記録
    """

    def __init__(self, game, path, *, run_id: str, read_health):
        self._game = game
        self._read_health = read_health  # () -> int。vizdoom に依存しないよう注入（テスト用）
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("w")
        self.run_id = run_id
        self._ctx = {}
        self._segment_index = 0

    def begin(self, **decision_fields) -> None:
        """判断1回分の項目（episode, decision_index, decision_source, ...）を設定し segment 番号を戻す"""
        self._ctx = decision_fields
        self._segment_index = 0

    def _health(self) -> int | None:
        try:
            return int(self._read_health())
        except Exception:
            return None

    def make_action(self, action, tics=1):
        tic_before = self._game.get_episode_time()
        health_before = self._health()
        reward = self._game.make_action(action, tics)
        tic_after = self._game.get_episode_time()
        health_after = self._health()
        loss = (max(0, health_before - health_after)
                if health_before is not None and health_after is not None else None)
        record = {
            "run_id": self.run_id,
            **self._ctx,
            "segment_index": self._segment_index,
            "tic_before_action": tic_before,
            "tic_after_action": tic_after,
            "delta_tic": tic_after - tic_before,
            "segment_tics_requested": tics,
            "executed_buttons": [int(b) for b in action],
            "health_before": health_before,
            "health_after": health_after,
            "health_loss": loss,
            "episode_finished_after": bool(self._game.is_episode_finished()),
        }
        self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._segment_index += 1
        return reward

    def flush(self) -> None:
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    def __getattr__(self, name):
        return getattr(self._game, name)
