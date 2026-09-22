#!/bin/bash
# 統合ループ: エピソードを繰り返し、クリア（または上限）まで継続
set -e
cd "$(dirname "$0")/.."

MAX_EPISODES="${1:-100}"
SCENARIO="${2:-full_map}"
CRITERIA="${3:-tactical_peeking}"

LOG_DIR="experiments/integration_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"
MASTER="$LOG_DIR/master.log"
PROGRESS="$LOG_DIR/progress.json"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MASTER"; }

log "═══ Integration Loop Start ═══"
log "  Scenario: $SCENARIO"
log "  Criteria: $CRITERIA"
log "  Max episodes: $MAX_EPISODES"
log ""

BEST_KILLS=0
BEST_HEALTH=0
TOTAL_EPISODES=0
CLEARED=0

for i in $(seq 1 "$MAX_EPISODES"); do
    log "─── Episode $i / $MAX_EPISODES ───"
    
    LOG="$LOG_DIR/ep${i}.log"
    
    # 1エピソード実行
    if ! python train/jev_agent.py --scenario "$SCENARIO" --criteria "$CRITERIA" \
         --use-labels --tactical --sound > "$LOG" 2>&1; then
        log "  ⚠ 実行失敗（クラッシュ？）。ログ: $LOG"
        log "  最後の10行:"
        tail -10 "$LOG" | sed 's/^/    /' | tee -a "$MASTER"
        break
    fi
    
    # 結果抽出
    RESULT=$(grep -E "Episode 0 done:" "$LOG" | tail -1)
    if [ -z "$RESULT" ]; then
        log "  ⚠ 結果未検出。ログ: $LOG"
        break
    fi
    
    KILLS=$(echo "$RESULT" | grep -oP 'kills=\K\d+' || echo 0)
    HEALTH=$(echo "$RESULT" | grep -oP 'final_health=\K\d+' || echo 0)
    STEPS=$(echo "$RESULT" | grep -oP 'steps=\K\d+' || echo 0)
    HITS=$(echo "$RESULT" | grep -oP 'hits=\K\d+' || echo 0)
    
    log "  Kills=$KILLS  Health=$HEALTH  Steps=$STEPS  Hits=$HITS"
    
    # 進捗記録
    TOTAL_EPISODES=$((TOTAL_EPISODES + 1))
    cat > "$PROGRESS" << EOJSON
{
  "episodes": $TOTAL_EPISODES,
  "last": {"kills": $KILLS, "health": $HEALTH, "steps": $STEPS, "hits": $HITS},
  "best_kills": $BEST_KILLS,
  "cleared": $CLEARED
}
EOJSON
    
    # クリア判定（暫定: KILLS > 0 かつ HEALTH > 50 でクリア兆候）
    if [ "$KILLS" -gt "$BEST_KILLS" ]; then
        BEST_KILLS="$KILLS"
        log "  🎯 新記録: Kills=$KILLS"
    fi
    if [ "$HEALTH" -gt "$BEST_HEALTH" ]; then
        BEST_HEALTH="$HEALTH"
    fi
    
    # ゴール到達検出（state_text 内の "goal" を除外、DOOM固有メッセージのみ）
    # ViZDoom の FINISHED 画面は game_state でのみ検出可能
    # ここでは「timeout 前に完走」を代理指標とする
    if [ "$STEPS" -lt 2100 ]; then
        log "  ⚠ 途中終了（ゴール or 死亡）: steps=$STEPS"
        # 死亡判定（health==0 なら死亡）
        if [ "$HEALTH" -eq 0 ]; then
            log "  💀 死亡"
        else
            log "  🏆 ゴール候補（要目視確認）"
            CLEARED=1
            break
        fi
    fi
done

log ""
log "═══ Integration Loop Complete ═══"
log "  実行エピソード数: $TOTAL_EPISODES"
log "  Best Kills: $BEST_KILLS"
log "  Best Health: $BEST_HEALTH"
log "  Cleared: $CLEARED"
log ""
log "  Log dir: $LOG_DIR"
