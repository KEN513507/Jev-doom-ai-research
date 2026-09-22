#!/bin/bash
# 5時間テストの邪魔をしない低負荷録画（nice/ionice、10fps、360x640）
# 使い方: ./tools/record_lowload.sh [seconds=18000] [criteria=tactical_peeking]
cd "$(dirname "$0")/.."

export SDL_AUDIODRIVER=alsa

DURATION="${1:-18000}"
CRITERIA="${2:-tactical_peeking}"
DISPLAY_NUM="${DISPLAY:-:1}"
SEGMENT_SEC=1800

OUT_W=360; OUT_H=640; DOOM_H=270; LOG_H=370

AVAIL_GB=$(df --output=avail -BG . | tail -1 | tr -d 'G ')
NEED_GB=$(( DURATION / 3600 + 2 ))
if [ "$AVAIL_GB" -lt "$NEED_GB" ]; then
    echo "🛑 ディスク不足: 空き ${AVAIL_GB}GB < 必要 ${NEED_GB}GB"
    exit 1
fi
echo "ディスク: 空き ${AVAIL_GB}GB, 必要 ${NEED_GB}GB"

pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
pkill -9 -f "python.*overlay" 2>/dev/null || true
pkill -9 -f "ffmpeg.*x11grab" 2>/dev/null || true
sleep 3

setsid nohup python -u train/jev_agent.py \
  --scenario full_map --criteria "$CRITERIA" \
  --use-labels --sound --system3 \
  < /dev/null > /tmp/qv_jev.log 2>&1 &
JEV_PID=$!
echo "[$(date +%H:%M:%S)] Jev PID: $JEV_PID"

WID=""
for i in $(seq 1 20); do
    sleep 1
    WID=$(wmctrl -l 2>/dev/null | grep -iE "vizdoom|zdoom" | head -1 | awk '{print $1}')
    [ -n "$WID" ] && break
done
[ -z "$WID" ] && { echo "❌ DOOM window 未出現"; exit 1; }

eval $(xwininfo -id "$WID" | awk '
    /Absolute upper-left X:/ {print "DX=" $4}
    /Absolute upper-left Y:/ {print "DY=" $4}
    /Width:/ {print "DW=" $2}
    /Height:/ {print "DH=" $2}
')
echo "[$(date +%H:%M:%S)] DOOM: ${DW}x${DH} at +${DX},${DY}"

OVL_X=$DX; OVL_Y=$((DY + DH)); OVL_W=320; OVL_H=240

setsid nohup nice -n 19 python -u tools/overlay.py \
  --geometry ${OVL_W}x${OVL_H}+${OVL_X}+${OVL_Y} \
  < /dev/null > /tmp/qv_overlay.log 2>&1 &

sleep 3

MONITOR=$(pactl get-default-sink).monitor
TS=$(date +%Y%m%d_%H%M%S)
OUTDIR="experiments/demos/overnight_${TS}"
mkdir -p "$OUTDIR"

echo "低負荷録画開始: ${DURATION}s (10fps, ${OUT_W}x${OUT_H}, nice/ionice)"
echo "出力: $OUTDIR/"

DISPLAY="$DISPLAY_NUM" setsid nohup nice -n 19 ionice -c3 ffmpeg \
  -loglevel error \
  -thread_queue_size 256 -f x11grab -draw_mouse 0 \
    -video_size "${DW}x${DH}" -framerate 10 \
    -i "${DISPLAY_NUM}+${DX},${DY}" \
  -thread_queue_size 256 -f x11grab -draw_mouse 0 \
    -video_size "${OVL_W}x${OVL_H}" -framerate 10 \
    -i "${DISPLAY_NUM}+${OVL_X},${OVL_Y}" \
  -thread_queue_size 256 -f pulse -i "$MONITOR" \
  -filter_complex "\
    [0:v]scale=${OUT_W}:${DOOM_H}:flags=neighbor[top];\
    [1:v]scale=${OUT_W}:${LOG_H}:flags=neighbor[bottom];\
    [top][bottom]vstack=inputs=2[out]" \
  -map "[out]" -map 2:a \
  -t "$DURATION" \
  -c:v libx264 -preset ultrafast -crf 28 -threads 1 \
  -c:a aac -b:a 64k \
  -f segment -segment_time "$SEGMENT_SEC" -reset_timestamps 1 \
  -y "${OUTDIR}/part_%03d.mp4" \
  < /dev/null > /tmp/qv_ffmpeg.log 2>&1 &
FFMPEG_PID=$!

echo "ffmpeg PID: $FFMPEG_PID (nice 19, ionice idle, 1 thread)"

REMAIN=$((DURATION + 10))
while ps -p "$FFMPEG_PID" > /dev/null && [ $REMAIN -gt 0 ]; do
    sleep 30
    REMAIN=$((REMAIN - 30))
    if ! ps -p "$JEV_PID" > /dev/null 2>&1; then
        echo "⚠ jev_agent (PID $JEV_PID) が死亡。録画を停止"
        kill "$FFMPEG_PID" 2>/dev/null
        break
    fi
    if [ $((REMAIN % 600)) -eq 0 ]; then
        JEV_COUNT=$(grep -c "Jev ->" /tmp/qv_jev.log 2>/dev/null || echo 0)
        LATEST_LAT=$(grep "\[Jev\] latency=" /tmp/qv_jev.log | tail -1 | grep -oE "[0-9]+ms")
        SEG_COUNT=$(ls "$OUTDIR"/part_*.mp4 2>/dev/null | wc -l)
        echo "  [$(date +%H:%M:%S)] 残${REMAIN}秒, Jev: $JEV_COUNT, 最新latency: $LATEST_LAT, seg: $SEG_COUNT"
    fi
done

echo ""
echo "═══════════════════════════════"
echo "✅ 完了: $OUTDIR"
ls -la "$OUTDIR"/part_*.mp4 2>/dev/null | tail -3
echo "Jev 判断: $(grep -c 'Jev ->' /tmp/qv_jev.log)"
echo "Jev latency 中央値: $(grep -oE '\[Jev\] latency=[0-9]+' /tmp/qv_jev.log | grep -oE '[0-9]+$' | sort -n | awk '{a[NR]=$1} END{print a[int(NR/2)+1]}')ms"
echo "═══════════════════════════════"
