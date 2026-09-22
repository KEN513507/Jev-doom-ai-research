#!/bin/bash
# 自己修正ループ（無人運転用）: Gemini が criteria を提案 → Claude Code が追加 → 5エピソード実走 → 効果量で採否
# 使い方: ./tools/self_correcting_loop.sh [最大反復=100] [初期criteria] [シナリオ] [seed=1000] [制限時間(分)=300] [連続失敗上限=8]
# 例（5時間）: ./tools/self_correcting_loop.sh 100 tactical_peeking full_map 1000 300
#
# 設計（2026-09-23、5時間無人運転の要件定義 決定2）
# - 停止: 制限時間（残りが1反復の最悪値 ITER_BUDGET_MIN 未満なら新しい反復を始めない）、連続失敗上限、最大反復
# - Gemini が新しい criteria を出せない（criteria では解決できないと判断した等）ときは停止せず、champion を
#   新しい seed で追加実走してデータを増やす（champion の評価が安定し、Gemini にも新しいレポートが渡る）
# - 各実走に timeout。想定外のエラーでループ全体を止めないため set -e は使わない
# - 記録: iterations.jsonl（1反復1行）、summary.md（終了時に必ず生成）
# 環境変数（tools/overnight.sh から使う）:
#   AGENT_EXTRA_ARGS  jev_agent.py への追加引数（既定 "--system3"。例: "--system3 --no-stuck-timeout"）
#   LOOP_LOG_DIR      ログの出力先（既定 experiments/self_correct_<時刻>）
#   INIT_REPORTS      初期 champion のレポート（空白区切り）。指定時は初期実走を省く（Phase 1 の結果を引き継ぐ）
cd "$(dirname "$0")/.."

MAX_ITER="${1:-100}"
CURRENT_CRITERIA="${2:-tactical_peeking}"
SCENARIO="${3:-full_map}"
SEED="${4:-1000}"          # 比較条件をそろえるため seed 固定（エピソード i は seed+i）
DURATION_MIN="${5:-300}"
MAX_CONSECUTIVE_FAIL="${6:-8}"
ITER_BUDGET_MIN=30         # 1反復の最悪値（Gemini 分析 + claude -p 10分 + 実走 5.5分 + 保留時の追加 11分 + 余裕）
RUN_TIMEOUT_SEC=1500       # run_and_report 1回（再試行込み）の上限
CONSECUTIVE_FAIL=0
export EPISODE_END_HOLD_SEC=0   # 目視用の終了時保持を省く（5エピソードで約30秒の短縮）
AGENT_EXTRA_ARGS="${AGENT_EXTRA_ARGS:---system3}"  # 基準線・test_items と同じく System 3 あり

# --- 起動前の確認（前回 python が見つからず空回りした対策）---
for cmd in python claude git; do
    command -v "$cmd" >/dev/null || { echo "🛑 $cmd が見つかりません（conda activate vizdoom を確認）" >&2; exit 1; }
done
for var in TYPESAFE_API_KEY GEMINI_API_KEY; do
    [ -n "${!var}" ] || { echo "🛑 環境変数 $var が未設定です" >&2; exit 1; }
done
# D4 決定（2026-09-23）: 未コミットの追跡変更があれば中止。クリーンなら続行。
# experiments/（latest_report.json など実走のたびに変わる記録）は対象外
if ! git diff --quiet -- . ':(exclude)experiments' || ! git diff --cached --quiet -- . ':(exclude)experiments'; then
    echo "🛑 未コミットの変更があります。コミットしてから起動してください。" >&2
    git status --short >&2
    exit 1
fi

LOG_DIR="${LOOP_LOG_DIR:-experiments/self_correct_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$LOG_DIR"
MASTER="$LOG_DIR/master.log"
START_EPOCH=$(date +%s)
DEADLINE=$((START_EPOCH + DURATION_MIN * 60))

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER"; }
stop_reason() { echo "$*" > "$LOG_DIR/stop_reason.txt"; log "🛑 $*"; }

# 終了時（正常・異常・Ctrl+C とも）に summary.md を必ず生成
trap 'python tools/loop_summary.py "$LOG_DIR" >> "$MASTER" 2>&1' EXIT

# 1実走（run_and_report、timeout 付き）。$1=criteria $2=seed $3=ログ $4=レポートの保存先。成功なら 0
run_eval() {
    # shellcheck disable=SC2086  # AGENT_EXTRA_ARGS は意図的に単語分割する
    SKIP_GEMINI_ANALYZE=1 timeout "$RUN_TIMEOUT_SEC" ./tools/run_and_report.sh "$1" --scenario "$SCENARIO" --seed "$2" $AGENT_EXTRA_ARGS > "$3" 2>&1
    local rc=$?
    [ "$rc" -eq 124 ] && log "  ⚠ 実走タイムアウト (${RUN_TIMEOUT_SEC}s): $1"
    # 今回の実走のレポートだけを採る（古い latest_report を取り違えない）
    local rep
    rep=$(grep -o "experiments/auto_logs/report_[^ ]*\.json" "$3" | tail -n 1)
    [ -n "$rep" ] && [ -f "$rep" ] && cp "$rep" "$4" && return 0
    return 1
}

# 効果量で判定し判定語を返す。比較表は $1、数値は $1.json
judge() {
    local out="$1"; shift
    python tools/compare_reports.py --decide score --json "$out.json" "$@" > "$out" 2>&1
    sed -n 's/^VERDICT=//p' "$out" | tail -n 1
}

# iterations.jsonl に1行追記。引数は key=value（d_* は比較 JSON から）
record() {
    python - "$LOG_DIR/iterations.jsonl" "$@" <<'PYEOF'
import json, sys
path, *kvs = sys.argv[1:]
row = {}
for kv in kvs:
    k, _, v = kv.partition("=")
    if k == "compare_json":
        try:
            for r in json.load(open(v)):
                if r["metric"] in ("score", "kills", "damage_taken") and r["d"] is not None:
                    row[f"d_{r['metric']}"] = float(r["d"])
        except (OSError, ValueError):
            pass
        continue
    row[k] = int(v) if v.lstrip("-").isdigit() else (v or None)
with open(path, "a") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
PYEOF
}

# --- 初期チャンピオン ---
log "===== Self-Correcting Loop Start ====="
log "制限時間 ${DURATION_MIN}分（〜$(date -d @$DEADLINE +%H:%M)）、最大 $MAX_ITER 反復、連続失敗上限 $MAX_CONSECUTIVE_FAIL"
log "Initial criteria: $CURRENT_CRITERIA / Scenario: $SCENARIO / seed: $SEED / agent args: $AGENT_EXTRA_ARGS"
if [ -n "$INIT_REPORTS" ]; then
    # Phase 1 の結果を初期 champion として引き継ぐ（同じ criteria・コード・フラグ・seed の実走なので再測定は不要）
    read -r -a CHAMPION_REPORTS_IN <<< "$INIT_REPORTS"
    log "[Init] 初期 champion を引き継ぐ: ${CHAMPION_REPORTS_IN[*]}"
    cp "${CHAMPION_REPORTS_IN[0]}" "$LOG_DIR/champion.json"
else
    log "[Init] Establishing champion baseline..."
    if ! run_eval "$CURRENT_CRITERIA" "$SEED" "$LOG_DIR/init.log" "$LOG_DIR/champion.json"; then
        stop_reason "初期実行のレポートが得られない（ログ: $LOG_DIR/init.log）。無人ループを中止"
        exit 1
    fi
    CHAMPION_REPORTS_IN=("$LOG_DIR/champion.json")
fi
CHAMPION_SCORE=$(python tools/score_report.py "$LOG_DIR/champion.json")
if [ "$CHAMPION_SCORE" = "-999999.00" ]; then
    stop_reason "初期実行が無効（クラッシュ・エピソード不足・Jev API 障害）。無人ループを中止"
    exit 1
fi
CHAMPION_CRITERIA="$CURRENT_CRITERIA"
CHAMPION_REPORTS=("$LOG_DIR/champion.json" "${CHAMPION_REPORTS_IN[@]:1}")  # 引き継いだ n=10 分も含める
EXTEND_SEED=$((SEED + 5))  # 保留時の追加5エピソードの seed
EXTRA_SEED=$((SEED + 100)) # 提案なしのときの champion 追加実走の seed（反復ごとに +5）
log "Champion: criteria=$CHAMPION_CRITERIA, score=$CHAMPION_SCORE"

git tag -f "champion" HEAD >/dev/null
git add train/jev_agent.py 2>/dev/null || true
git commit -m "champion: $CHAMPION_CRITERIA score=$CHAMPION_SCORE" 2>/dev/null || true
git tag -f "champion" HEAD >/dev/null

rollback() {
    git stash push -m "loop-rollback: $LOG_DIR iter $1" -- train/jev_agent.py >/dev/null 2>&1 || git checkout train/jev_agent.py
}

# --- ループ ---
i=0
while :; do
    i=$((i + 1))
    NOW=$(date +%s)
    if [ "$i" -gt "$MAX_ITER" ]; then stop_reason "最大反復 $MAX_ITER に到達"; break; fi
    if [ $((DEADLINE - NOW)) -lt $((ITER_BUDGET_MIN * 60)) ]; then
        stop_reason "制限時間（残り $(( (DEADLINE - NOW) / 60 ))分 < 1反復の最悪値 ${ITER_BUDGET_MIN}分）"; break
    fi
    if [ "$CONSECUTIVE_FAIL" -ge "$MAX_CONSECUTIVE_FAIL" ]; then
        stop_reason "$MAX_CONSECUTIVE_FAIL 回連続で不採用・失敗"; break
    fi
    ITER_START=$NOW

    log ""
    log "═══════ Iteration $i （経過 $(( (NOW - START_EPOCH) / 60 ))分 / ${DURATION_MIN}分、champion=$CHAMPION_CRITERIA）═══════"
    git tag -f "iter_${i}_before" HEAD >/dev/null

    # --- Step 1: Gemini の提案（直前の実走のレポートを分析。履歴は analysis_history.jsonl）---
    log "[1/4] Gemini proposing next..."
    timeout 300 python tools/gemini_analyze.py > "$LOG_DIR/iter${i}_gemini.log" 2>&1 || true
    cp experiments/auto_logs/next_action.md "$LOG_DIR/iter${i}_next.md" 2>/dev/null || true
    NEXT_CRITERIA=$(grep -oP '(--criteria |run_and_report\.sh )\K[a-z0-9_]+' "$LOG_DIR/iter${i}_next.md" 2>/dev/null | head -1)

    if [ -z "$NEXT_CRITERIA" ] || [ "$NEXT_CRITERIA" = "$CHAMPION_CRITERIA" ] \
            || grep -q "\"$NEXT_CRITERIA\": {" train/jev_agent.py; then
        # 新しい提案なし（criteria では解決できない判断、または既存 criteria の再提案）→ champion を新しい seed で追加実走
        grep -q "criteria では解決できない" "$LOG_DIR/iter${i}_next.md" 2>/dev/null \
            && log "  → Gemini: criteria では解決できない（人間の判断事項として summary.md に記録）"
        log "  → 新しい提案なし（${NEXT_CRITERIA:-なし}）。champion を seed $EXTRA_SEED で追加実走してデータを増やす"
        if run_eval "$CHAMPION_CRITERIA" "$EXTRA_SEED" "$LOG_DIR/iter${i}_extra_run.log" "$LOG_DIR/iter${i}_champion_extra.json"; then
            ln -sf "$(readlink -f "$LOG_DIR/iter${i}_champion_extra.json")" experiments/auto_logs/latest_report.json
        fi
        EXTRA_SEED=$((EXTRA_SEED + 5))
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        record iter=$i proposed="$NEXT_CRITERIA" status=no_proposal duration_s=$(( $(date +%s) - ITER_START ))
        continue
    fi

    # --- Step 2: Claude Code で criteria を追加 ---
    log "[2/4] Claude Code implementing: $NEXT_CRITERIA"
    PROMPT="train/jev_agent.py の CRITERIA_SETS に新しい criteria '$NEXT_CRITERIA' を追加してください。

$(cat "$LOG_DIR/iter${i}_next.md")

【絶対制約】
- Git操作禁止
- 変更してよいのは train/jev_agent.py の CRITERIA_SETS への新しいエントリの追加だけ（既存 criteria の削除・変更、Python ロジックの追加は禁止）
- criteria の文面は state_text に実在する項目だけを参照する（一覧は tools/gemini_analyze.py の「Jev の入力」節）
- マップ固有の情報（マップ名・座標・敵配置）を書かない。DOOM 全般に通用する戦略だけを書く
- System 1（should_force_attack）の条件・閾値は変更しない
- 完了したら「DONE」と出力"
    CLAUDE_RC=0
    timeout 600 claude -p "$PROMPT" \
        --allowed-tools "Read,Edit,Write,Bash(python*),Bash(pytest*),Bash(ls*),Bash(cat*),Bash(grep*)" \
        > "$LOG_DIR/iter${i}_claude.log" 2>&1 || CLAUDE_RC=$?
    git diff -- train/ tests/ > "$LOG_DIR/iter${i}_diff.patch" 2>/dev/null || true
    [ "$CLAUDE_RC" -eq 124 ] && log "  ⚠ Claude Code タイムアウト (600s)"
    [ "$CLAUDE_RC" -ne 0 ] && [ "$CLAUDE_RC" -ne 124 ] && log "  ⚠ Claude Code 終了コード=$CLAUDE_RC"

    if ! grep -q "\"$NEXT_CRITERIA\"" train/jev_agent.py; then
        log "  ❌ $NEXT_CRITERIA が追加されていない。ロールバック"
        rollback "$i"; CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        record iter=$i proposed="$NEXT_CRITERIA" status=impl_failed duration_s=$(( $(date +%s) - ITER_START ))
        continue
    fi
    if ! python -m py_compile train/jev_agent.py 2>/dev/null; then
        log "  ❌ コンパイル失敗。ロールバック"
        rollback "$i"; CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        record iter=$i proposed="$NEXT_CRITERIA" status=compile_failed duration_s=$(( $(date +%s) - ITER_START ))
        continue
    fi

    # --- Step 3: 実走 ---
    log "[3/4] Running $NEXT_CRITERIA..."
    if ! run_eval "$NEXT_CRITERIA" "$SEED" "$LOG_DIR/iter${i}_run.log" "$LOG_DIR/iter${i}_result.json"; then
        log "  ❌ 実走のレポートが得られない。ロールバック"
        rollback "$i"; CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        record iter=$i proposed="$NEXT_CRITERIA" status=invalid duration_s=$(( $(date +%s) - ITER_START ))
        continue
    fi
    NEW_SCORE=$(python tools/score_report.py "$LOG_DIR/iter${i}_result.json")
    log "  New score: $NEW_SCORE (Champion: $CHAMPION_SCORE、参考値。採否は効果量で判定)"

    # --- Step 4: 効果量で判定（docs/test_items.md の判定ルール）---
    log "[4/4] Comparing (effect size)..."
    NEW_REPORTS=("$LOG_DIR/iter${i}_result.json")
    CMP="$LOG_DIR/iter${i}_compare.txt"
    if [ "$NEW_SCORE" = "-999999.00" ]; then
        VERDICT="判定不可"
    else
        VERDICT=$(judge "$CMP" --base "${CHAMPION_REPORTS[@]}" --new "${NEW_REPORTS[@]}")
    fi
    N=5
    log "  判定 (n=5): $VERDICT"

    if [ "$VERDICT" = "保留（追加実走）" ]; then
        if [ "${#CHAMPION_REPORTS[@]}" -lt 2 ]; then
            log "  保留 → champion ($CHAMPION_CRITERIA) を seed $EXTEND_SEED で5エピソード追加"
            run_eval "$CHAMPION_CRITERIA" "$EXTEND_SEED" "$LOG_DIR/champion_ext_run.log" "$LOG_DIR/champion_ext.json" \
                && CHAMPION_REPORTS+=("$LOG_DIR/champion_ext.json")
        fi
        log "  保留 → $NEXT_CRITERIA を seed $EXTEND_SEED で5エピソード追加"
        run_eval "$NEXT_CRITERIA" "$EXTEND_SEED" "$LOG_DIR/iter${i}_run_ext.log" "$LOG_DIR/iter${i}_result_ext.json" \
            && NEW_REPORTS+=("$LOG_DIR/iter${i}_result_ext.json")
        CMP="$LOG_DIR/iter${i}_compare_n10.txt"
        VERDICT=$(judge "$CMP" --base "${CHAMPION_REPORTS[@]}" --new "${NEW_REPORTS[@]}")
        N=10
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
        STATUS=adopted
    else
        log "  ❌ $VERDICT。ロールバック"
        rollback "$i"
        CONSECUTIVE_FAIL=$((CONSECUTIVE_FAIL + 1))
        STATUS=rejected
    fi
    record iter=$i proposed="$NEXT_CRITERIA" status=$STATUS verdict="$VERDICT" n=$N \
        compare_json="$CMP.json" duration_s=$(( $(date +%s) - ITER_START ))
done

log ""
log "═══════ 最終結果 ═══════"
log "チャンピオン: $CHAMPION_CRITERIA (score=$CHAMPION_SCORE)"
log "要約: $LOG_DIR/summary.md"
log "ロールバック: git checkout champion -- train/jev_agent.py"
