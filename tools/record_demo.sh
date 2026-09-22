#!/bin/bash
# DOOM AI Demo 録画 → 検証 → 再生（完全自動）
# 使い方: ./tools/record_demo.sh [録画秒数=30] [criteria=tactical_peeking]

set -e
cd "$(dirname "$0")/.."

# ─── 設定 ───
DURATION="${1:-30}"
CRITERIA="${2:-tactical_peeking}"
SCENARIO="full_map"
MONITOR=$(pactl get-default-sink 2>/dev/null).monitor
DISPLAY_NUM="${DISPLAY:-:1}"
OUT_DIR="experiments/demos"
TS=$(date +%Y%m%d_%H%M%S)
VIDEO="${OUT_DIR}/demo_${TS}.mp4"
LOG="/tmp/record_demo_${TS}.log"

mkdir -p "$OUT_DIR"

# ─── 色 ───
G="\033[32m"; Y="\033[33m"; R="\033[31m"; N="\033[0m"
log()  { echo -e "${G}[$(date +%H:%M:%S)]${N} $*" | tee -a "$LOG"; }
warn() { echo -e "${Y}[$(date +%H:%M:%S)] WARN${N} $*" | tee -a "$LOG"; }
err()  { echo -e "${R}[$(date +%H:%M:%S)] ERROR${N} $*" | tee -a "$LOG"; }

# ═══════════════════════════════════════════
# Phase 1: 既存プロセス停止
# ═══════════════════════════════════════════
log "Phase 1: 既存プロセスを停止"
pkill -9 -f jev_agent.py 2>/dev/null || true
pkill -9 -f ffmpeg 2>/dev/null || true
tmux kill-server 2>/dev/null || true
sleep 2

REMAIN=$(ps aux | grep -E "jev_agent|ffmpeg|tmux" | grep -v grep | wc -l)
if [ "$REMAIN" -gt 0 ]; then
    warn "残存プロセス: $REMAIN 件"
    ps aux | grep -E "jev_agent|ffmpeg|tmux" | grep -v grep
else
    log "✅ 全停止"
fi

# ═══════════════════════════════════════════
# Phase 2: 環境確認
# ═══════════════════════════════════════════
log "Phase 2: 環境確認"
log "  DISPLAY=$DISPLAY_NUM"
log "  MONITOR=$MONITOR"
log "  DURATION=${DURATION}s"
log "  OUTPUT=$VIDEO"

if ! pactl list sources short | grep -q "${MONITOR}"; then
    err "モニターソースが存在しません: $MONITOR"
    exit 1
fi

# ═══════════════════════════════════════════
# Phase 3: ffmpeg 起動（バックグラウンド）
# ═══════════════════════════════════════════
log "Phase 3: 録画開始（${DURATION}秒）"
DISPLAY="$DISPLAY_NUM" setsid nohup ffmpeg \
  -thread_queue_size 512 -f x11grab -video_size 1024x768 -framerate 30 -i "$DISPLAY_NUM" \
  -thread_queue_size 512 -f pulse -i "$MONITOR" \
  -t "$DURATION" \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k \
  -y "$VIDEO" \
  < /dev/null > /tmp/ffmpeg_${TS}.log 2>&1 &

FFMPEG_PID=$!
sleep 3

if ! ps -p "$FFMPEG_PID" > /dev/null; then
    err "ffmpeg が起動に失敗"
    tail -20 "/tmp/ffmpeg_${TS}.log"
    exit 1
fi
log "  ✅ ffmpeg 稼働中 (PID=$FFMPEG_PID)"

# ═══════════════════════════════════════════
# Phase 4: jev_agent 起動（DOOM ウィンドウ表示）
# ═══════════════════════════════════════════
log "Phase 4: jev_agent 起動（DOOM ウィンドウ表示）"
DISPLAY="$DISPLAY_NUM" setsid nohup python train/jev_agent.py \
  --scenario "$SCENARIO" --criteria "$CRITERIA" \
  --use-labels --sound \
  < /dev/null > /tmp/jev_${TS}.log 2>&1 &

JEV_PID=$!
sleep 3

if ! ps -p "$JEV_PID" > /dev/null; then
    err "jev_agent が起動に失敗"
    tail -20 "/tmp/jev_${TS}.log"
    kill -9 "$FFMPEG_PID" 2>/dev/null
    exit 1
fi
log "  ✅ jev_agent 稼働中 (PID=$JEV_PID)"

# DOOM ウィンドウを前面に
sleep 2
wmctrl -a "VIZDOOM" 2>/dev/null || wmctrl -a "ZDOOM" 2>/dev/null || true

# ═══════════════════════════════════════════
# Phase 5: 録画完了を待機
# ═══════════════════════════════════════════
log "Phase 5: 録画完了待機（最大 ${DURATION}秒）"
REMAIN=$((DURATION + 5))
while ps -p "$FFMPEG_PID" > /dev/null && [ $REMAIN -gt 0 ]; do
    sleep 1
    REMAIN=$((REMAIN - 1))
done

# jev_agent がまだ動いていたら停止
if ps -p "$JEV_PID" > /dev/null; then
    log "  jev_agent を停止"
    kill "$JEV_PID" 2>/dev/null || true
    sleep 1
    pkill -9 -f jev_agent.py 2>/dev/null || true
fi

# ═══════════════════════════════════════════
# Phase 6: 録画ファイル検証
# ═══════════════════════════════════════════
log "Phase 6: 録画ファイル検証"
sleep 2

if [ ! -f "$VIDEO" ]; then
    err "録画ファイルが存在しません: $VIDEO"
    exit 1
fi

SIZE=$(stat -c%s "$VIDEO" 2>/dev/null || echo 0)
DURATION_ACTUAL=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO" 2>/dev/null || echo 0)
HAS_AUDIO=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=noprint_wrappers=1:nokey=1 "$VIDEO" 2>/dev/null || echo "none")

log "  Size:     $((SIZE / 1024)) KB"
log "  Duration: ${DURATION_ACTUAL}s"
log "  Audio:    ${HAS_AUDIO}"

if [ "$SIZE" -lt 10000 ]; then
    err "ファイルサイズが小さすぎます"
    exit 1
fi

if [ "$HAS_AUDIO" = "none" ]; then
    warn "音声トラックがありません"
fi

log "  ✅ 録画成功"

# ═══════════════════════════════════════════
# Phase 7: 自動再生
# ═══════════════════════════════════════════
log "Phase 7: 再生（mpv → vlc → xdg-open の順）"

if command -v mpv > /dev/null; then
    log "  mpv で再生"
    setsid nohup mpv --really-quiet "$VIDEO" < /dev/null > /dev/null 2>&1 &
elif command -v vlc > /dev/null; then
    log "  vlc で再生"
    setsid nohup vlc "$VIDEO" < /dev/null > /dev/null 2>&1 &
else
    log "  xdg-open で再生"
    xdg-open "$VIDEO" 2>/dev/null &
fi

# ═══════════════════════════════════════════
# 完了
# ═══════════════════════════════════════════
log ""
log "═══════════════════════════════════════"
log "✅ 完了"
log "  Video: $VIDEO"
log "  Log:   $LOG"
log "═══════════════════════════════════════"

# 環境復元
pkill -9 ffmpeg 2>/dev/null || true
