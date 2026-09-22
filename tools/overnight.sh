#!/bin/bash
# 夜間の無人運転（5時間）: criteria 探索ループ（self_correcting_loop.sh）を直接起動する
# 使い方: ./tools/overnight.sh [制限時間(分)=300] [基準 criteria=tactical_peeking] [seed=1000]
#
# - 初期 champion はループの初回実走で測る（Phase 1 の A/B 検証は行わない）
# - stuck_timeout は有効（--no-stuck-timeout を付けない）、System 3 あり
# 出力: experiments/overnight_<時刻>/（overnight.log、loop/、SUMMARY.md）
cd "$(dirname "$0")/.."

DURATION_MIN="${1:-300}"
CRITERIA="${2:-tactical_peeking}"
SEED="${3:-1000}"
SCENARIO=full_map
FLAGS="--system3"

# --- 起動前の確認（ループ側でも確認するが、起動直後に止まる理由をここで表示する）---
for cmd in python claude git; do
    command -v "$cmd" >/dev/null || { echo "🛑 $cmd が見つかりません（conda activate vizdoom を確認）" >&2; exit 1; }
done
for var in TYPESAFE_API_KEY GEMINI_API_KEY; do
    [ -n "${!var}" ] || { echo "🛑 環境変数 $var が未設定です" >&2; exit 1; }
done
if ! git diff --quiet -- . ':(exclude)experiments' || ! git diff --cached --quiet -- . ':(exclude)experiments'; then
    echo "🛑 未コミットの変更があります（experiments/ 以外）。コミットしてから起動してください。" >&2
    git status --short -- . ':(exclude)experiments' >&2
    exit 1
fi

OUT="experiments/overnight_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
LOG="$OUT/overnight.log"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

log "═══════ criteria 探索ループ（${DURATION_MIN}分、$CRITERIA、seed $SEED、$FLAGS、stuck_timeout 有効）═══════"
LOOP_LOG_DIR="$OUT/loop" AGENT_EXTRA_ARGS="$FLAGS" \
    ./tools/self_correcting_loop.sh 100 "$CRITERIA" "$SCENARIO" "$SEED" "$DURATION_MIN" >> "$LOG" 2>&1
log "ループ終了（終了コード $?）"

# ═══════ まとめ ═══════
{
    echo "# 夜間運転の結果（$OUT）"
    echo
    echo "- 設定: ${DURATION_MIN}分、初期 criteria \`$CRITERIA\`、seed $SEED、\`$FLAGS\`、stuck_timeout 有効"
    echo "- 初期 champion: ループの初回実走で測定"
    echo
    if [ -f "$OUT/loop/summary.md" ]; then sed 's/^# /## /' "$OUT/loop/summary.md"; else echo "（loop/summary.md なし。overnight.log を確認）"; fi
} > "$OUT/SUMMARY.md"
log "✅ まとめ: $OUT/SUMMARY.md"
