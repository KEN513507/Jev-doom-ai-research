#!/bin/bash
# Phase 2 のみ: criteria 探索ループ（5時間無人運転）
# 使い方: ./tools/overnight_phase2.sh [分=300] [criteria=tactical_peeking] [seed=1000]
set -e
cd "$(dirname "$0")/.."

DURATION_MIN="${1:-300}"
CRITERIA="${2:-tactical_peeking}"
SEED="${3:-1000}"
SCENARIO="${4:-full_map}"

OUT="experiments/overnight_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
LOG="$OUT/overnight.log"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

export EPISODE_END_HOLD_SEC=0

if ! git diff --quiet -- . ':(exclude)experiments' || ! git diff --cached --quiet -- . ':(exclude)experiments'; then
    echo "🛑 未コミットの変更があります（experiments/ 以外）" >&2
    exit 1
fi

log "═══════ Phase 2 only: criteria 探索（$DURATION_MIN分, $CRITERIA, seed $SEED）═══════"
LOOP_LOG_DIR="$OUT/loop" AGENT_EXTRA_ARGS="--system3" \
    ./tools/self_correcting_loop.sh 100 "$CRITERIA" "$SCENARIO" "$SEED" "$DURATION_MIN" >> "$LOG" 2>&1
RC=$?
log "Phase 2 終了（終了コード $RC）"

if [ -f "$OUT/loop/summary.md" ]; then
    cp "$OUT/loop/summary.md" "$OUT/SUMMARY.md"
    log "✅ 結果: $OUT/SUMMARY.md"
else
    log "⚠ loop/summary.md なし。$OUT/overnight.log を確認"
fi
