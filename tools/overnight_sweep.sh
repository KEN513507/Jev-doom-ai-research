#!/bin/bash
# 夜間スイープ: 複数のcriteriaを順番に実行し、結果を集計
set -e
cd "$(dirname "$0")/.."

CRITERIA_LIST=(
    "baseline"
    "aggressive"
    "aggressive_p0"
    "aggressive_p1"
    "defensive"
    "explorer"
)

REPORT_DIR="experiments/overnight_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "=== Overnight Sweep Start: $(date) ==="
echo "Report dir: $REPORT_DIR"

for crit in "${CRITERIA_LIST[@]}"; do
    echo ""
    echo "▶ Running: $crit ($(date +%H:%M:%S))"
    
    LOG="$REPORT_DIR/run_${crit}.log"
    python train/jev_agent.py --criteria "$crit" --use-labels > "$LOG" 2>&1 || true
    
    # 1回だけ集計用にJSON化
    python - "$LOG" "$REPORT_DIR/${crit}.json" "$crit" << 'PYEOF'
import sys, re, json
from pathlib import Path
log_path, json_path, criteria = sys.argv[1], sys.argv[2], sys.argv[3]
lines = Path(log_path).read_text().splitlines()
episodes = []
for line in lines:
    m = re.search(r'Episode (\d+) done: hits=(\d+), final_health=(-?\d+), steps=(\d+), sys1=(\d+), sys2=(\d+)', line)
    if m:
        episodes.append({"hits": int(m.group(2)), "health": int(m.group(3)),
                        "steps": int(m.group(4)), "sys1": int(m.group(5)), "sys2": int(m.group(6))})
summary = {}
if episodes:
    n = len(episodes)
    summary = {
        "criteria": criteria,
        "avg_hits": sum(e["hits"] for e in episodes) / n,
        "avg_health": sum(e["health"] for e in episodes) / n,
        "avg_steps": sum(e["steps"] for e in episodes) / n,
        "avg_sys1": sum(e["sys1"] for e in episodes) / n,
        "avg_sys2": sum(e["sys2"] for e in episodes) / n,
        "episodes": episodes,
    }
Path(json_path).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
PYEOF
done

# 集計
python - "$REPORT_DIR" << 'PYEOF'
import sys, json
from pathlib import Path
report_dir = Path(sys.argv[1])
rows = []
for f in sorted(report_dir.glob("*.json")):
    d = json.loads(f.read_text())
    rows.append(d)

print()
print("=" * 70)
print(f"{'criteria':<16}{'hits':<8}{'health':<8}{'steps':<8}{'sys1':<8}{'sys2':<8}")
print("-" * 70)
for r in rows:
    print(f"{r['criteria']:<16}{r['avg_hits']:<8.2f}{r['avg_health']:<8.1f}"
          f"{r['avg_steps']:<8.1f}{r['avg_sys1']:<8.1f}{r['avg_sys2']:<8.1f}")
print("=" * 70)
print()
best = min(rows, key=lambda r: (r["avg_hits"], -r["avg_health"]))
print(f"🏆 ベスト criteria: {best['criteria']} (hits={best['avg_hits']:.2f}, health={best['avg_health']:.1f})")
PYEOF

echo ""
echo "=== Sweep Complete: $(date) ==="
