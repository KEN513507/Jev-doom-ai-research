#!/bin/bash
# 3回限定の半自動ループ
# 各イテレーション: 実行 → Gemini分析 → Claude Code実装 → 検証
set -e
cd "$(dirname "$0")/.."

MAX_ITER=3
CURRENT_CRITERIA="${1:-aggressive_p1}"

LOG_DIR="experiments/semi_auto_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"
MASTER_LOG="$LOG_DIR/master.log"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER_LOG"; }

log "===== Semi-Auto Loop Start ====="
log "Max iterations: $MAX_ITER"
log "Initial criteria: $CURRENT_CRITERIA"
log "Log dir: $LOG_DIR"

# 初期スナップショット
git tag -f "semi_auto_start" HEAD >/dev/null
log "Git tag: semi_auto_start"

for i in $(seq 1 "$MAX_ITER"); do
    log ""
    log "═══════════ Iteration $i / $MAX_ITER ═══════════"
    
    # --- Step 1: 実行 ---
    log "[1/5] Running experiment..."
    ./tools/run_and_report.sh "$CURRENT_CRITERIA" > "$LOG_DIR/iter${i}_run.log" 2>&1 || true
    
    cp experiments/auto_logs/latest_report.json "$LOG_DIR/iter${i}_report.json"
    PREV_METRIC=$(python -c "
import json
d = json.load(open('$LOG_DIR/iter${i}_report.json'))
s = d['summary']
print(f\"{s['avg_hits']:.2f} {s['avg_health']:.1f} {s['avg_steps']:.1f}\")
")
    log "    Result: $PREV_METRIC"
    
    # --- Step 2: Gemini分析 ---
    log "[2/5] Gemini analyzing..."
    python tools/gemini_analyze.py > "$LOG_DIR/iter${i}_gemini.log" 2>&1 || true
    cp experiments/auto_logs/next_action.md "$LOG_DIR/iter${i}_next_action.md"
    
    # --- Step 3: Claude Code に実装依頼 ---
    log "[3/5] Claude Code implementing..."
    PROMPT=$(cat << PROMPTEOF
以下の分析に基づき、train/jev_agent.py を修正してください。

$(cat "$LOG_DIR/iter${i}_next_action.md")

【絶対制約】
- Git操作禁止（commit/pushしない）
- 変更は最小限（1つのcriteria追加 or 1つのパラメータ変更のみ）
- 修正後、必ず `python -m py_compile train/jev_agent.py` を実行
- 完了したら「DONE」とだけ出力

【重要】
- CRITERIA_SETSに新しいcriteriaを追加する場合、既存の構造に従うこと
- 既存のcriteriaは削除しないこと
PROMPTEOF
)
    
    # Claude Code 呼び出し（print モード）
    timeout 600 claude -p "$PROMPT" > "$LOG_DIR/iter${i}_claude.log" 2>&1 || {
        log "    ⚠ Claude Code timeout/error. Check log."
    }
    
    # --- Step 4: 検証 ---
    log "[4/5] Verifying..."
    if python -m py_compile train/jev_agent.py 2>&1; then
        log "    ✅ Compile OK"
        
        # 差分を保存
        git diff > "$LOG_DIR/iter${i}_diff.patch"
        
        # 次のcriteria名を抽出（next_action から）
        NEXT_CRITERIA=$(grep -oP 'criteria \K[a-z_]+' "$LOG_DIR/iter${i}_next_action.md" | head -1)
        if [ -z "$NEXT_CRITERIA" ]; then
            NEXT_CRITERIA="$CURRENT_CRITERIA"
        fi
        
        # CRITERIA_SETS に存在するか確認
        if ! grep -q "\"$NEXT_CRITERIA\"" train/jev_agent.py; then
            log "    ⚠ $NEXT_CRITERIA が存在しません。次回は $CURRENT_CRITERIA のまま"
            NEXT_CRITERIA="$CURRENT_CRITERIA"
        fi
    else
        log "    ❌ Compile FAILED. Rolling back..."
        git checkout train/jev_agent.py
        NEXT_CRITERIA="$CURRENT_CRITERIA"
    fi
    
    # --- Step 5: 次へ ---
    log "[5/5] Next criteria: $NEXT_CRITERIA"
    CURRENT_CRITERIA="$NEXT_CRITERIA"
done

log ""
log "═══════════ Final Summary ═══════════"
python - << 'PYEOF' 2>&1 | tee -a "$MASTER_LOG"
import json
from pathlib import Path
import glob

rows = []
for f in sorted(glob.glob("experiments/semi_auto_*/iter*_report.json")):
    d = json.load(open(f))
    it = Path(f).stem.replace("_report", "")
    s = d["summary"]
    rows.append({
        "iter": it,
        "criteria": d["criteria"],
        "hits": s["avg_hits"],
        "health": s["avg_health"],
        "steps": s["avg_steps"],
        "sys2_ratio": s.get("sys2_ratio", 0),
    })

print(f"{'iter':<10}{'criteria':<18}{'hits':<8}{'health':<8}{'steps':<8}{'sys2%':<8}")
print("-" * 60)
for r in rows:
    print(f"{r['iter']:<10}{r['criteria']:<18}{r['hits']:<8.2f}{r['health']:<8.1f}"
          f"{r['steps']:<8.1f}{r['sys2_ratio']*100:<8.1f}")
PYEOF

log ""
log "===== Semi-Auto Loop Complete ====="
log "Results: $LOG_DIR"
log "Rollback: git reset --hard semi_auto_start"
