"""シナリオ対応のスコア計算。ループ内3箇所の式を一元化する。

使い方: python tools/score_report.py <report.json> [expected_episodes]
出力: スコアを1行で表示（常に exit 0）。エピソード不足・形式不正は -999999。

式:
- deadly_corridor（既定、後方互換）: -hits*100 + health - steps*0.1
  steps減点は停滞・後退スパム防止用。
- full_map: kills*500 + visited_cells*10 - hits*100 + health
            + i_exit*10000 + full_clear*5000（係数は FULL_MAP_* 定数。全項目エピソード平均）
  steps項・タイムアウト減点なし。full_mapでは生存=2100tic固定のため、
  steps減点は「早く死ぬほど高得点」の逆インセンティブになる。
"""

import json
import sys

FAIL_SCORE = -999999.0

# full_map の係数（撃破・前進・被弾・体力）
FULL_MAP_KILL_WEIGHT = 500.0
FULL_MAP_VISITED_CELL_WEIGHT = 10.0  # visited_cells（訪れた 128×128 単位のマス数）
FULL_MAP_HIT_PENALTY = 100.0
FULL_MAP_HEALTH_WEIGHT = 1.0
# D3 決定（2026-09-23）: EXIT と全滅をスコアに入れる。SSOT §3 の Clear Score（1エピソード単位）と整合させるため、
# 他の項と同じくエピソード平均（EXIT 率・全滅率）に掛ける
FULL_MAP_EXIT_BONUS = 10000.0
FULL_MAP_FULL_CLEAR_BONUS = 5000.0


def compute_score(report: dict, expected_episodes: int = 5) -> float:
    try:
        if report.get("valid") is False:  # 再試行後もクラッシュ・API障害（run_and_report.sh が記録）
            return FAIL_SCORE
        s = report["summary"]
        if s.get("n_episodes", 0) < expected_episodes:
            return FAIL_SCORE
        hits = s["avg_hits"]
        health = s["avg_health"]
        if report.get("scenario", "deadly_corridor") == "full_map":
            return (
                s.get("avg_kills", 0.0) * FULL_MAP_KILL_WEIGHT
                + s.get("avg_visited_cells", 0.0) * FULL_MAP_VISITED_CELL_WEIGHT
                - hits * FULL_MAP_HIT_PENALTY
                + health * FULL_MAP_HEALTH_WEIGHT
                + s.get("avg_i_exit", 0.0) * FULL_MAP_EXIT_BONUS
                + s.get("full_clears", 0) / s["n_episodes"] * FULL_MAP_FULL_CLEAR_BONUS
            )
        return -hits * 100 + health - s["avg_steps"] * 0.1
    except (KeyError, TypeError):
        return FAIL_SCORE


def main() -> None:
    path = sys.argv[1]
    expected = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    try:
        report = json.load(open(path))
    except (OSError, ValueError):
        report = {}
    print(f"{compute_score(report, expected):.2f}")


if __name__ == "__main__":
    main()
