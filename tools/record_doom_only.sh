#!/bin/bash
# DOOM ウィンドウだけを録画（xdotool で常時最前面強制）
set -e
cd "$(dirname "$0")/.."

DURATION="${1:-30}"
CRITERIA="${2:-tactical_peeking}"
SCENARIO="full_map"
MONITOR=$(pactl get-default-sink).monitor
DISPLAY_NUM="${DISPLAY:-:1}"
OUT_DIR="experiments/demos"
TS=$(date +%Y%m%d_%H%M%S)
VIDEO="${OUT_DIR}/doom_${TS}.mp4"
LOG="/tmp/record_doom_${TS}.log"
mkdir -p "$OUT_DIR"

G="\033[32m"; Y="\033[33m"; R="\033[31m"; N="\033[0m"
log()  { echo -e "${G}[$(date +%H:%M:%S)]${N} $*" | tee -a "$LOG"; }
err()  { echo -e "${R}[$(date +%H:%M:%S)] ERROR${N} $*" | tee -a "$LOG"; }

# ─── 安全な停止 ───
log "Phase 1: 既存プロセスを安全に停止"
JEV_PIDS=$(pgrep -f "python train/jev_agent.py" 2>/dev/null || true)
[ -n "$JEV_PIDS" ] && echo "$JEV_PIDS" | xargs -r kill -9 2>/dev/null || true
FFMPEG_PIDS=$(pgrep -af ffmpeg 2>/dev/null | grep "x11grab" | awk '{print $1}' || true)
[ -n "$FFMPEG_PIDS" ] && echo "$FFMPEG_PIDS" | xargs -r kill -9 2>/dev/null || true
sleep 2

# ─── jev_agent 起動 ───
log "Phase 2: jev_agent 起動"
DISPLAY="$DISPLAY_NUM" setsid nohup python train/jev_agent.py \
  --scenario "$SCENARIO" --criteria "$CRITERIA" \
  --use-labels --sound \
  < /dev/null > /tmp/jev_${TS}.log 2>&1 &
JEV_PID=$!

WID=""
for i in $(seq 1 15); do
    sleep 1
    WID=$(wmctrl -l | grep -iE "vizdoom|zdoom" | head -1 | awk '{print $1}')
    [ -n "$WID" ] && { log "  ✅ DOOM ウィンドウ検出: $WID"; break; }
done
[ -z "$WID" ] && { err "DOOM ウィンドウ出現せず"; kill -9 "$JEV_PID" 2>/dev/null; exit 1; }

# ─── ウィンドウ座標 ───
log "Phase 3: ウィンドウ座標取得"
eval $(xwininfo -id "$WID" | awk '
    /Absolute upper-left X:/ {print "WIN_X=" $4}
    /Absolute upper-left Y:/ {print "WIN_Y=" $4}
    /Width:/ {print "WIN_W=" $2}
    /Height:/ {print "WIN_H=" $2}
')
[ -z "$WIN_W" ] && { err "座標取得失敗"; kill -9 "$JEV_PID" 2>/dev/null; exit 1; }
log "  ✅ ${WIN_W}x${WIN_H} at +${WIN_X},${WIN_Y}"

WIN_W=$((WIN_W / 2 * 2))
WIN_H=$((WIN_H / 2 * 2))

# ─── ★ 最前面を強制（xdotool ループ）───
log "Phase 4: DOOM を最前面に強制固定"
wmctrl -i -r "$WID" -b add,above 2>/dev/null || true
wmctrl -i -a "$WID" 2>/dev/null || true
xdotool windowraise "$WID" 2>/dev/null || true

# バックグラウンドで 0.3 秒ごとに raise（録画中ずっと）
(
  while true; do
    xdotool windowraise "$WID" 2>/dev/null || true
    sleep 0.3
  done
) &
KEEPER_PID=$!
log "  ✅ keeper 起動 (PID=$KEEPER_PID)"

sleep 2

# ─── 録画 ───
log "Phase 5: クロップ録画開始（${DURATION}秒）"
DISPLAY="$DISPLAY_NUM" setsid nohup ffmpeg \
  -thread_queue_size 512 -f x11grab \
  -video_size "${WIN_W}x${WIN_H}" -framerate 30 \
  -draw_mouse 0 \
  -i "${DISPLAY_NUM}+${WIN_X},${WIN_Y}" \
  -thread_queue_size 512 -f pulse -i "$MONITOR" \
  -t "$DURATION" \
  -vf "scale=960:720:flags=neighbor" \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k \
  -y "$VIDEO" \
  < /dev/null > /tmp/ffmpeg_${TS}.log 2>&1 &
FFMPEG_PID=$!
sleep 3

if ! ps -p "$FFMPEG_PID" > /dev/null; then
    err "ffmpeg 起動失敗"; tail -10 /tmp/ffmpeg_${TS}.log
    kill -9 "$KEEPER_PID" "$JEV_PID" 2>/dev/null || true
    exit 1
fi
log "  ✅ ffmpeg 稼働中"

# ─── 完了待機 ───
log "Phase 6: 録画完了待機"
REMAIN=$((DURATION + 5))
while ps -p "$FFMPEG_PID" > /dev/null && [ $REMAIN -gt 0 ]; do
    sleep 1; REMAIN=$((REMAIN - 1))
done

# keeper 停止
kill -9 "$KEEPER_PID" 2>/dev/null || true
wmctrl -i -r "$WID" -b remove,above 2>/dev/null || true
ps -p "$JEV_PID" > /dev/null && kill "$JEV_PID" 2>/dev/null || true
sleep 1

# ─── 検証 ───
log "Phase 7: 検証"
sleep 2
[ ! -f "$VIDEO" ] && { err "ファイルなし"; exit 1; }

SIZE=$(stat -c%s "$VIDEO")
DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO" 2>/dev/null)
log "  Size: $((SIZE / 1024)) KB"
log "  Duration: ${DUR}s"
log "  ✅ 録画成功"

# ─── 再生 ───
log "Phase 8: 再生"
command -v mpv > /dev/null && setsid nohup mpv --really-quiet "$VIDEO" < /dev/null > /dev/null 2>&1 &
log "✅ 完了: $VIDEO"
