#!/bin/bash
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
LOGDIR="$PROJECT_DIR/experiments/auto_logs"
mkdir -p "$LOGDIR"

CRITERIA="${1:-aggressive_p1}"
shift || true
EXTRA_ARGS="$@"

# 本体クラッシュ時の再試行とエピソード数検証（full_map無人運用の前提）
EXPECTED_EPISODES="${EXPECTED_EPISODES:-5}"
MAX_RUN_RETRIES="${MAX_RUN_RETRIES:-3}"
MAX_SKIP_PCT="${MAX_SKIP_PCT:-20}"  # Jev 呼び出し失敗（[skip]）がこの割合を超えた実行は API 障害とみなす
RETRY_BASE_SEC="${RETRY_BASE_SEC:-30}"  # 再試行の待ち時間は 30s, 60s, ... と倍増

# EXTRA_ARGS から --scenario を拾う（JSON記録用。既定は deadly_corridor）
SCENARIO="deadly_corridor"
_prev=""
for _a in $EXTRA_ARGS; do
    if [ "$_prev" = "--scenario" ]; then SCENARIO="$_a"; fi
    _prev="$_a"
done

TS=$(date +%Y%m%d_%H%M%S)
LOG="$LOGDIR/run_${CRITERIA}_${TS}.log"
JSON="$LOGDIR/report_${CRITERIA}_${TS}.json"

VALID=0
_attempt=1
while :; do
    python train/jev_agent.py --criteria "$CRITERIA" --use-labels $EXTRA_ARGS > "$LOG" 2>&1 || true
    _done=$(grep -c "^Episode [0-9][0-9]* done:" "$LOG" || true)
    _skips=$(grep -c "^\[skip\]" "$LOG" || true)
    _jev=$(grep -c " Jev -> " "$LOG" || true)
    if [ "$_done" -ge "$EXPECTED_EPISODES" ] && [ $((_skips * 100)) -le $(((_jev + _skips) * MAX_SKIP_PCT)) ]; then
        VALID=1
        break
    fi
    echo "⚠ Attempt $_attempt/$MAX_RUN_RETRIES: episodes $_done/$EXPECTED_EPISODES, jev_skips $_skips/$((_jev + _skips))" >&2
    # 最終回のログは残したまま集計し、valid=false として記録する（古いレポートを流用させない）
    [ "$_attempt" -ge "$MAX_RUN_RETRIES" ] && break
    cp "$LOG" "${LOG%.log}_failed${_attempt}.log"
    _wait=$((RETRY_BASE_SEC * 2 ** (_attempt - 1)))
    echo "  Retrying in ${_wait}s..." >&2
    sleep "$_wait"
    _attempt=$((_attempt + 1))
done

python - "$LOG" "$JSON" "$CRITERIA" "$SCENARIO" "$VALID" << 'PYEOF'
import sys, re, json
from pathlib import Path

log_path, json_path, criteria, scenario = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
valid = sys.argv[5] == "1"
lines = Path(log_path).read_text().splitlines()

episodes = []
hits_events = []

for line in lines:
    m = re.search(r'Episode (\d+) done: (.*)', line)
    if m:
        # key=value を個別に読む（連結した任意グループだと1項目のずれで後続が全て0になる）
        kv = {k: int(float(v)) for k, v in re.findall(r'(\w+)=(-?\d+(?:\.\d+)?)', m.group(2))}
        if "max_distance" not in kv and "max_dist" in kv:  # WorldMemory.get_summary 形式の別名
            kv["max_distance"] = kv["max_dist"]
        if not all(k in kv for k in ("hits", "final_health", "steps", "sys1", "sys2")):
            continue
        episodes.append({
            "episode": int(m.group(1)),
            "hits": kv["hits"],
            "final_health": kv["final_health"],
            "steps": kv["steps"],
            "sys1": kv["sys1"],
            "sys2": kv["sys2"],
            "kills": kv.get("kills", 0),
            "visited_cells": kv.get("visited_cells", 0),
            "max_distance": kv.get("max_distance", 0),
            "keys": kv.get("keys", 0),
            "dead_ends": kv.get("dead_ends", 0),
            "i_exit": kv.get("i_exit", 0),
            "kills_total": kv.get("kills_total", 0),
            "ammo_used": kv.get("ammo_used", 0),
            "attack_steps": kv.get("attack_steps", 0),
            "dmg_hits": kv.get("dmg_hits", 0),
            "damage_taken": kv.get("damage_taken"),
            "ammo_min": kv.get("ammo_min", -1),
            "melee_steps": kv.get("melee_steps", 0),
            "seed": kv.get("seed", -1),
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
        "avg_kills": sum(e["kills"] for e in episodes) / n,
        "avg_visited_cells": sum(e["visited_cells"] for e in episodes) / n,
        "avg_max_distance": sum(e["max_distance"] for e in episodes) / n,
        "avg_keys": sum(e["keys"] for e in episodes) / n,
        "avg_dead_ends": sum(e["dead_ends"] for e in episodes) / n,
        "avg_i_exit": sum(e["i_exit"] for e in episodes) / n,
        "exits": sum(e["i_exit"] for e in episodes),
        "kills_total": max(e["kills_total"] for e in episodes),
        "full_clears": sum(1 for e in episodes if e["kills_total"] and e["kills"] >= e["kills_total"]),
        "avg_ammo_used": sum(e["ammo_used"] for e in episodes) / n,
        "avg_attack_steps": sum(e["attack_steps"] for e in episodes) / n,
        "avg_dmg_hits": sum(e["dmg_hits"] for e in episodes) / n,
        "avg_damage_taken": (sum(e["damage_taken"] for e in episodes) / n
                             if all(e["damage_taken"] is not None for e in episodes) else None),
        "deaths": sum(1 for e in episodes if e["final_health"] <= 0),
        "ammo_outs": sum(1 for e in episodes if e["ammo_min"] == 0),
        "seeds": [e["seed"] for e in episodes],
    }
    if summary["avg_sys1"] + summary["avg_sys2"] > 0:
        summary["sys2_ratio"] = summary["avg_sys2"] / (summary["avg_sys1"] + summary["avg_sys2"])
    else:
        summary["sys2_ratio"] = 0.0

result = {
    "criteria": criteria,
    "scenario": scenario,
    "valid": valid,
    "log_path": str(log_path),
    "episodes": episodes,
    "hits_events": hits_events,
    "summary": summary,
}

Path(json_path).write_text(json.dumps(result, indent=2, ensure_ascii=False))
print(json.dumps(result, indent=2, ensure_ascii=False))
print(f"\n✅ JSON: {json_path}")
PYEOF

# ログをエピソードごとに集計して episodes[i].diag に追記（B1〜B8・D2〜D3、docs/test_items.md）
python tools/analyze_log.py "$LOG" --merge "$JSON" || echo "⚠ analyze_log 失敗（レポート本体は有効）" >&2

# 最新レポートへのシンボリックリンク
ln -sf "$JSON" "$LOGDIR/latest_report.json"
