#!/bin/bash
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
LOGDIR="$PROJECT_DIR/experiments/auto_logs"
mkdir -p "$LOGDIR"

CRITERIA="${1:-aggressive_p1}"
shift || true
EXTRA_ARGS="$@"

TS=$(date +%Y%m%d_%H%M%S)
LOG="$LOGDIR/run_${CRITERIA}_${TS}.log"
JSON="$LOGDIR/report_${CRITERIA}_${TS}.json"

python train/jev_agent.py --criteria "$CRITERIA" --use-labels $EXTRA_ARGS > "$LOG" 2>&1 || true

python - "$LOG" "$JSON" "$CRITERIA" << 'PYEOF'
import sys, re, json
from pathlib import Path

log_path, json_path, criteria = sys.argv[1], sys.argv[2], sys.argv[3]
lines = Path(log_path).read_text().splitlines()

episodes = []
hits_events = []

for line in lines:
    m = re.search(
        r'Episode (\d+) done: hits=(\d+), final_health=(-?\d+), steps=(\d+), sys1=(\d+), sys2=(\d+)',
        line
    )
    if m:
        episodes.append({
            "episode": int(m.group(1)),
            "hits": int(m.group(2)),
            "final_health": int(m.group(3)),
            "steps": int(m.group(4)),
            "sys1": int(m.group(5)),
            "sys2": int(m.group(6)),
        })
    elif "!!! HIT" in line:
        hm = re.search(r'HIT #(\d+) at step=(\d+): (\d+) -> (\d+)', line)
        if hm:
            hits_events.append({
                "num": int(hm.group(1)),
                "step": int(hm.group(2)),
                "before": int(hm.group(3)),
                "after": int(hm.group(4)),
                "damage": int(hm.group(3)) - int(hm.group(4)),
            })

summary = {}
if episodes:
    n = len(episodes)
    summary = {
        "n_episodes": n,
        "avg_hits": sum(e["hits"] for e in episodes) / n,
        "avg_health": sum(e["final_health"] for e in episodes) / n,
        "avg_steps": sum(e["steps"] for e in episodes) / n,
        "avg_sys1": sum(e["sys1"] for e in episodes) / n,
        "avg_sys2": sum(e["sys2"] for e in episodes) / n,
        "total_hits": sum(e["hits"] for e in episodes),
    }
    if summary["avg_sys1"] + summary["avg_sys2"] > 0:
        summary["sys2_ratio"] = summary["avg_sys2"] / (summary["avg_sys1"] + summary["avg_sys2"])
    else:
        summary["sys2_ratio"] = 0.0

result = {
    "criteria": criteria,
    "log_path": str(log_path),
    "episodes": episodes,
    "hits_events": hits_events,
    "summary": summary,
}

Path(json_path).write_text(json.dumps(result, indent=2, ensure_ascii=False))
print(json.dumps(result, indent=2, ensure_ascii=False))
print(f"\n✅ JSON: {json_path}")
PYEOF

# 最新レポートへのシンボリックリンク
ln -sf "$JSON" "$LOGDIR/latest_report.json"
