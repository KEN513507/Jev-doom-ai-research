"""行動タイムライン（experiments/auto_logs/<run_id>_timeline.jsonl）の集計。

使い方:
    python tools/analyze_timeline.py <run_id>_timeline.jsonl [--top 10]

H1: Jev 待ちの間に game tic が進んだ判断の数（同期 PLAYER モードなら 0 のはず）
H2: segment ごとの delta_tic の分布（通常の行動は 8 のはず）
H3/H4: health_loss > 0 の segment と、そのとき実際に送っていた行動の対応
被弾と enemy_types の対応は関連（damage_source_association）であり、原因の証明ではない。
"""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def load(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def summarize(records: list[dict], top: int = 10) -> dict:
    # 判断単位（run_id, episode, decision_index）で1回だけ数える（1判断 = 1〜2 segment）
    decisions = {}
    for r in records:
        decisions.setdefault((r["run_id"], r["episode"], r["decision_index"]), r)
    sources = Counter(d["decision_source"] for d in decisions.values())
    jev_waits = [d for d in decisions.values() if d["tic_before_jev"] is not None]
    latencies = [d["jev_latency_ms"] for d in decisions.values() if d["jev_latency_ms"] is not None]
    damage = [r for r in records if (r["health_loss"] or 0) > 0]
    damage.sort(key=lambda r: -r["health_loss"])
    return {
        "records": len(records),
        "decisions": len(decisions),
        "jev_decisions": sources.get("jev", 0),
        "forced_attack_decisions": sources.get("forced_attack", 0),
        "skip_decisions": sources.get("skip", 0),
        "jev_wait_measured": len(jev_waits),
        "jev_wait_tic_advanced_count": sum(1 for d in jev_waits if d["tic_after_jev"] != d["tic_before_jev"]),
        "median_jev_latency_ms": statistics.median(latencies) if latencies else None,
        "delta_tic_distribution": dict(sorted(Counter(r["delta_tic"] for r in records).items())),
        "health_loss_event_count": len(damage),
        "health_loss_total": sum(r["health_loss"] for r in damage),
        "top_damage_windows": [
            {k: r.get(k) for k in ("episode", "decision_index", "segment_index", "tic_before_action",
                                   "decision_source", "decision_action", "executed_action",
                                   "executed_buttons", "rewritten_by", "action_press_tics", "delta_tic",
                                   "health_loss", "enemy_visible", "enemy_types")}
            for r in damage[:top]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(summarize(load(args.timeline), args.top), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
