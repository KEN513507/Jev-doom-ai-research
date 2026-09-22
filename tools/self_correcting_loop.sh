#!/bin/bash
# 自己修正ループ: 改善したら採用、悪化したら自動ロールバック
set -e
cd "$(dirname "$0")/.."

MAX_ITER="${1:-10}"
CURRENT_CRITERIA="${2:-aggressive_p1}"
CONSECUTIVE_FAIL=0
MAX_CONSECUTIVE_FAIL=3

LOG_DIR="experiments/self_correct_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"
MASTER="$LOG_DIR/master.log"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER"; }

# --- 初期チャンピオンを確立 ---
log "===== Self-Correcting Loop Start ====="
log "Max iterations: $MAX_ITER"
log "Initial criteria: $CURRENT_CRITERIA"

# 初期実行
log "[Init] Establishing champion baseline..."
./tools/run_and_report.sh "$CURRENT_CRITERIA" > "$LOG_DIR/init.log" 2>&1 || true
cp experiments/auto_logs/latest_report.json "$LOG_DIR/champion.json"

CHAMPION_SCORE=$(python -c "
import json
d = json.load(open('$LOG_DIR/champion.json'))
s = d['summary']
# スコア = hits が少ないほど良い、health が高いほど良い、steps が長いほど良い
score = -s['avg_hits'] * 100 + s['avg_health'] - s['avg_steps'] * 0.1
print(f'{score:.2f}')
")
CHAMPION_CRITERIA="$CURRENT_CRITERIA"
log "Champion: criteria=$CHAMPION_CRITERIA, score=$CHAMPION_SCORE"

# チャンピオンのコードをタグ付け
git tag -f "champion" HEAD >/dev/null
git add train/jev_agent.py 2>/dev/null || true
git commit -m "champion: $CHAMPION_CRITERIA score=$CHAMPION_SCORE" 2>/dev/null || true
git tag -f "champion" HEAD >/dev/null

# --- ループ ---
for i in $(seq 1 "$MAX_ITER"); do
    log ""
    log "═══════ Iteration $i / $MAX_ITER ═══════"
    
    # 直前の状態を記録
    git tag -f "iter_${i}_before" HEAD >/dev/null
    cp experiments/auto_logs/latest_report.json "$LOG_DIR/iter${i}_before.json" 2>/dev/null || true
    
    # --- Step 1: 実行（現状維持 or 新criteria で） ---
    # Gemini に提案させる
    log "[1/4] Gemini proposing next..."
    python tools/gemini_analyze.py > "$LOG_DIR/iter${i}_gemini.log" 2>&1 || true
    cp experiments/auto_logs/next_action.md "$LOG_DIR/iter${i}_next.md" 2>/dev/null || true
    
    # 提案された criteria を抽出
    NEXT_CRITERIA=$(grep -oP 'criteria \K[a-z0-9_]+' "$LOG_DIR/iter${i}_next.md" 2>/dev/null | head -1)
    if [ -z "$NEXT_CRITERIA" ] || [ "$NEXT_CRITERIA" = "$CHAMPION_CRITERIA" ]; then
        log "  → 同じ criteria のため、スキップ"
        log "  → 停止条件: Gemini が新しい提案を出せず"
        break
    fi
    
    # --- Step 2: Claude Code で実装 ---
    log "[2/4] Claude Code implementing: $NEXT_CRITERIA"
    PROMPT="train/jev_agent.py に新しい criteria '$NEXT_CRITERIA' を追加してください。

$(cat "$LOG_DIR/iter${i}_next.md")

【絶対制約】
- Git操作禁止
- 既存criteriaは削除しない
- should_force_attack() の中身は変更しない（ChaingunGuy特例を保持）
- 新しい criteria の追加のみ
- 完了したら「DONE」と出力"

    timeout 600 claude -p "$PROMPT" \
        --allowed-tools "Read,Edit,Write,Bash(python*),Bash(pytest*),Bash(ls*),Bash(cat*),Bash(grep*)" \
        > "$LOG_DIR/iter${i}_claude.log" 2>&1 || true
    
    # 実装確認
    if ! grep -q "\"$NEXT_CRITERIA\"" train/jev_agent.py; then
        log "  ❌ $NEXT_CRITERIA が追加されていない。スキップ"
        git checkout train/jev_agent.py
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        continue
    fi
    
    if ! python -m py_compile train/jev_agent.py 2>/dev/null; then
        log "  ❌ コンパイル失敗。ロールバック"
        git checkout train/jev_agent.py
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        continue
    fi
    
    # --- Step 3: 実行 ---
    log "[3/4] Running $NEXT_CRITERIA..."
    ./tools/run_and_report.sh "$NEXT_CRITERIA" > "$LOG_DIR/iter${i}_run.log" 2>&1 || true
    cp experiments/auto_logs/latest_report.json "$LOG_DIR/iter${i}_result.json" 2>/dev/null || true
    
    NEW_SCORE=$(python -c "
import json
try:
    d = json.load(open('$LOG_DIR/iter${i}_result.json'))
    s = d['summary']
    score = -s['avg_hits'] * 100 + s['avg_health'] - s['avg_steps'] * 0.1
    print(f'{score:.2f}')
except Exception:
    print('-999999')
")
    
    log "  New score: $NEW_SCORE (Champion: $CHAMPION_SCORE)"
    
    # --- Step 4: 比較 & 判定 ---
    log "[4/4] Comparing..."
    BETTER=$(python -c "print('yes' if float('$NEW_SCORE') > float('$CHAMPION_SCORE') else 'no')")
    
    if [ "$BETTER" = "yes" ]; then
        log "  ✅ 改善！新チャンピオン: $NEXT_CRITERIA"
        CHAMPION_SCORE="$NEW_SCORE"
        CHAMPION_CRITERIA="$NEXT_CRITERIA"
        git add train/jev_agent.py
        git commit -m "champion: $NEXT_CRITERIA score=$NEW_SCORE" 2>/dev/null || true
        git tag -f "champion" HEAD >/dev/null
        CONSECUTIVE_FAIL=0
    else
        log "  ❌ 悪化。ロールバック"
        git checkout train/jev_agent.py
        git reset --hard "iter_${i}_before" >/dev/null 2>&1 || true
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
    fi
    
    # 停止条件
    if [ "$CONSECUTIVE_FAIL" -ge "$MAX_CONSECUTIVE_FAIL" ]; then
        log ""
        log "🛑 $MAX_CONSECUTIVE_FAIL 回連続で失敗。停止"
        break
    fi
done

# --- 最終レポート ---
log ""
log "═══════ 最終結果 ═══════"
log "チャンピオン: $CHAMPION_CRITERIA (score=$CHAMPION_SCORE)"
log "全履歴:"
for f in "$LOG_DIR"/iter*_result.json; do
    [ -f "$f" ] || continue
    python -c "
import json, sys
d = json.load(open('$f'))
s = d['summary']
print(f'  {d[\"criteria\"]:<20} hits={s[\"avg_hits\"]:.2f} health={s[\"avg_health\"]:.1f} steps={s[\"avg_steps\"]:.1f}')
" 2>/dev/null || true
done
log ""
log "Results: $LOG_DIR"
log "ロールバック: git reset --hard champion"
