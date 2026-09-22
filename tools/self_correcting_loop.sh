#!/bin/bash
# 自己修正ループ: 改善したら採用、悪化したら自動ロールバック
set -e
cd "$(dirname "$0")/.."

MAX_ITER="${1:-10}"
CURRENT_CRITERIA="${2:-aggressive_p1}"
SCENARIO="${3:-deadly_corridor}"
# 比較条件をそろえるため seed 固定（第4引数、既定は基準線と同じ 1000）
SEED="${4:-1000}"
CONSECUTIVE_FAIL=0
MAX_CONSECUTIVE_FAIL=3

# D4 決定（2026-09-23）: 未コミットの追跡変更があれば中止。クリーンなら続行
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "🛑 未コミットの変更があります。コミットしてから起動してください。" >&2
    git status --short >&2
    exit 1
fi

LOG_DIR="experiments/self_correct_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"
MASTER="$LOG_DIR/master.log"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER"; }

# --- 初期チャンピオンを確立 ---
log "===== Self-Correcting Loop Start ====="
log "Max iterations: $MAX_ITER"
log "Initial criteria: $CURRENT_CRITERIA"
log "Scenario: $SCENARIO"

# 初期実行
log "[Init] Establishing champion baseline..."
SKIP_GEMINI_ANALYZE=1 ./tools/run_and_report.sh "$CURRENT_CRITERIA" --scenario "$SCENARIO" --seed "$SEED" > "$LOG_DIR/init.log" 2>&1 || true
cp experiments/auto_logs/latest_report.json "$LOG_DIR/champion.json"

# スコア式は tools/score_report.py に一元化（シナリオ対応）
CHAMPION_SCORE=$(python tools/score_report.py "$LOG_DIR/champion.json")
if [ "$CHAMPION_SCORE" = "-999999.00" ]; then
    log "🛑 初期実行が無効（再試行後もクラッシュ・エピソード不足・Jev API 障害）。無人ループを中止"
    exit 1
fi
CHAMPION_CRITERIA="$CURRENT_CRITERIA"
# 改善2: 採否は compare_reports.py の効果量で判定する。champion のレポート（保留時は seed+5 の追加分も）を保持
CHAMPION_REPORTS=("$LOG_DIR/champion.json")
EXTEND_SEED=$((SEED + 5))  # 保留時の追加5エピソードの seed（エピソード i は EXTEND_SEED+i）

# 効果量で判定し、判定語（改善候補/保留（追加実走）/効果なし/悪化候補/判定不可）を返す。比較表は $1 に保存
judge() {
    local out="$1"; shift
    python tools/compare_reports.py --decide score "$@" > "$out" 2>&1
    sed -n 's/^VERDICT=//p' "$out" | tail -n 1
}
log "Champion: criteria=$CHAMPION_CRITERIA, score=$CHAMPION_SCORE"

# チャンピオンのコードをタグ付け
git tag -f "champion" HEAD >/dev/null
git add train/jev_agent.py 2>/dev/null || true
git commit -m "champion: $CHAMPION_CRITERIA score=$CHAMPION_SCORE" 2>/dev/null || true
git tag -f "champion" HEAD >/dev/null

# --- ループ ---
for i in $(seq 1 "$MAX_ITER"); do
    # 停止条件（continue 経由の失敗も拾うためループ先頭で判定）
    if [ "$CONSECUTIVE_FAIL" -ge "$MAX_CONSECUTIVE_FAIL" ]; then
        break
    fi

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
    # 次のコマンドの criteria 名（--criteria X と run_and_report.sh X の両方の書き方に対応）
    NEXT_CRITERIA=$(grep -oP '(--criteria |run_and_report\.sh )\K[a-z0-9_]+' "$LOG_DIR/iter${i}_next.md" 2>/dev/null | head -1)
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
- 新しい criteria の追加のみ
- System 1（should_force_attack）の条件・閾値は変更しない
- 完了したら「DONE」と出力"

    CLAUDE_RC=0
    timeout 600 claude -p "$PROMPT" \
        --allowed-tools "Read,Edit,Write,Bash(python*),Bash(pytest*),Bash(ls*),Bash(cat*),Bash(grep*)" \
        > "$LOG_DIR/iter${i}_claude.log" 2>&1 || CLAUDE_RC=$?

    # 判定より前に保存（失敗時は直後の checkout で変更が消えるため）
    git diff -- train/ tests/ > "$LOG_DIR/iter${i}_diff.patch" 2>/dev/null || true

    if [ "$CLAUDE_RC" -eq 124 ]; then
        log "  ⚠ Claude Code タイムアウト (600s)。ログ: $LOG_DIR/iter${i}_claude.log"
    elif [ "$CLAUDE_RC" -ne 0 ]; then
        log "  ⚠ Claude Code 終了コード=$CLAUDE_RC。ログ: $LOG_DIR/iter${i}_claude.log"
        log "    最終行: $(tail -n 1 "$LOG_DIR/iter${i}_claude.log" 2>/dev/null)"
    fi

    # 実装確認
    if ! grep -q "\"$NEXT_CRITERIA\"" train/jev_agent.py; then
        log "  ❌ $NEXT_CRITERIA が追加されていない。スキップ"
        git stash push -m "loop-rollback: $LOG_DIR iter ${i:-?}" -- train/jev_agent.py >/dev/null || git checkout train/jev_agent.py
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        continue
    fi
    
    if ! python -m py_compile train/jev_agent.py 2>/dev/null; then
        log "  ❌ コンパイル失敗。ロールバック"
        git stash push -m "loop-rollback: $LOG_DIR iter ${i:-?}" -- train/jev_agent.py >/dev/null || git checkout train/jev_agent.py
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        continue
    fi
    
    # --- Step 3: 実行 ---
    log "[3/4] Running $NEXT_CRITERIA..."
    SKIP_GEMINI_ANALYZE=1 ./tools/run_and_report.sh "$NEXT_CRITERIA" --scenario "$SCENARIO" --seed "$SEED" > "$LOG_DIR/iter${i}_run.log" 2>&1 || true
    cp experiments/auto_logs/latest_report.json "$LOG_DIR/iter${i}_result.json" 2>/dev/null || true

    NEW_SCORE=$(python tools/score_report.py "$LOG_DIR/iter${i}_result.json")
    log "  New score: $NEW_SCORE (Champion: $CHAMPION_SCORE、参考値。採否は効果量で判定)"

    # --- Step 4: 効果量で判定（docs/test_items.md の判定ルール）---
    log "[4/4] Comparing (effect size)..."
    NEW_REPORTS=("$LOG_DIR/iter${i}_result.json")
    if [ "$NEW_SCORE" = "-999999.00" ]; then
        VERDICT="判定不可"
    else
        VERDICT=$(judge "$LOG_DIR/iter${i}_compare.txt" --base "${CHAMPION_REPORTS[@]}" --new "${NEW_REPORTS[@]}")
    fi
    log "  判定 (n=5): $VERDICT  （比較表: $LOG_DIR/iter${i}_compare.txt）"

    if [ "$VERDICT" = "保留（追加実走）" ]; then
        # 両条件に seed+5 の5エピソードを追加し n=10 で再判定。champion の追加分は一度走らせたら使い回す
        if [ "${#CHAMPION_REPORTS[@]}" -lt 2 ]; then
            log "  保留 → champion ($CHAMPION_CRITERIA) を seed $EXTEND_SEED で5エピソード追加"
            SKIP_GEMINI_ANALYZE=1 ./tools/run_and_report.sh "$CHAMPION_CRITERIA" --scenario "$SCENARIO" --seed "$EXTEND_SEED" > "$LOG_DIR/champion_ext_run.log" 2>&1 || true
            cp experiments/auto_logs/latest_report.json "$LOG_DIR/champion_ext.json"
            CHAMPION_REPORTS+=("$LOG_DIR/champion_ext.json")
        fi
        log "  保留 → $NEXT_CRITERIA を seed $EXTEND_SEED で5エピソード追加"
        SKIP_GEMINI_ANALYZE=1 ./tools/run_and_report.sh "$NEXT_CRITERIA" --scenario "$SCENARIO" --seed "$EXTEND_SEED" > "$LOG_DIR/iter${i}_run_ext.log" 2>&1 || true
        cp experiments/auto_logs/latest_report.json "$LOG_DIR/iter${i}_result_ext.json"
        NEW_REPORTS+=("$LOG_DIR/iter${i}_result_ext.json")
        VERDICT=$(judge "$LOG_DIR/iter${i}_compare_n10.txt" --base "${CHAMPION_REPORTS[@]}" --new "${NEW_REPORTS[@]}")
        log "  判定 (n=10): $VERDICT"
        [ "$VERDICT" = "保留（追加実走）" ] && VERDICT="効果なし" && log "  n=10 でも保留 → 効果なしとして扱う"
    fi

    if [ "$VERDICT" = "改善候補" ]; then
        log "  ✅ 改善候補。新チャンピオン: $NEXT_CRITERIA"
        CHAMPION_SCORE="$NEW_SCORE"
        CHAMPION_CRITERIA="$NEXT_CRITERIA"
        CHAMPION_REPORTS=("${NEW_REPORTS[@]}")
        cp "$LOG_DIR/iter${i}_result.json" "$LOG_DIR/champion.json"
        git add train/jev_agent.py
        git commit -m "champion: $NEXT_CRITERIA (effect size: 改善候補, score=$NEW_SCORE)" 2>/dev/null || true
        git tag -f "champion" HEAD >/dev/null
        CONSECUTIVE_FAIL=0
    else
        log "  ❌ $VERDICT。ロールバック"
        git stash push -m "loop-rollback: $LOG_DIR iter ${i:-?}" -- train/jev_agent.py >/dev/null || git checkout train/jev_agent.py
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
    fi
done

if [ "$CONSECUTIVE_FAIL" -ge "$MAX_CONSECUTIVE_FAIL" ]; then
    log ""
    log "🛑 $MAX_CONSECUTIVE_FAIL 回連続で失敗。停止"
fi

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
log "ロールバック: git checkout champion -- train/jev_agent.py"
