#!/bin/bash
# QUAD SYSTEM 縦型レイアウト（スマホ向け 9:16）
# 上: DOOM プレイ、下: QUAD SYSTEM ログ
set -e
cd "$(dirname "$0")/.."

CRITERIA="${1:-tactical_peeking}"
DURATION="${2:-120}"
DISPLAY_NUM="${DISPLAY:-:1}"

# 出力サイズ（9:16）
OUT_W=720
OUT_H=1280
DOOM_H=540   # DOOM 表示部分
LOG_H=740    # ログ表示部分

# ─── 既存停止 ───
pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
pkill -9 -f "python.*overlay" 2>/dev/null || true
pkill -9 -f "ffmpeg.*x11grab" 2>/dev/null || true
sleep 3

# 古い VIZDOOM ウィンドウ閉じ
for w in $(wmctrl -l 2>/dev/null | grep -iE "vizdoom|zdoom" | awk '{print $1}'); do
    pid=$(xprop -id "$w" _NET_WM_PID 2>/dev/null | awk '{print $3}')
    [ -n "$pid" ] && ! ps -p "$pid" >/dev/null 2>&1 && wmctrl -ic "$w" 2>/dev/null
done

# ─── Jev 起動（--system3）───
setsid nohup python -u train/jev_agent.py \
  --scenario full_map --criteria "$CRITERIA" \
  --use-labels --sound --system3 \
  < /dev/null > /tmp/qv_jev.log 2>&1 &
JEV_PID=$!
echo "[$(date +%H:%M:%S)] Jev PID: $JEV_PID"

# DOOM ウィンドウ出現待ち
WID=""
for i in $(seq 1 15); do
    sleep 1
    WID=$(wmctrl -l | grep -iE "vizdoom|zdoom" | head -1 | awk '{print $1}')
    [ -n "$WID" ] && break
done
[ -z "$WID" ] && { echo "❌ DOOM window 未出現"; exit 1; }

eval $(xwininfo -id "$WID" | awk '
    /Absolute upper-left X:/ {print "DX=" $4}
    /Absolute upper-left Y:/ {print "DY=" $4}
    /Width:/ {print "DW=" $2}
    /Height:/ {print "DH=" $2}
')
echo "[$(date +%H:%M:%S)] DOOM window: ${DW}x${DH} at +${DX},${DY}"

# ─── Overlay を DOOM の「真下」に配置 ───
# Overlay の位置 = DX, DY + DH
OVL_X=$DX
OVL_Y=$((DY + DH))
OVL_W=320        # DOOM と同じ幅
OVL_H=240        # 縦型用に高さ確保

setsid nohup python -u tools/overlay.py \
  --geometry ${OVL_W}x${OVL_H}+${OVL_X}+${OVL_Y} \
  < /dev/null > /tmp/qv_overlay.log 2>&1 &
OVL_PID=$!
echo "[$(date +%H:%M:%S)] Overlay: ${OVL_W}x${OVL_H} at +${OVL_X},${OVL_Y}"

sleep 3

# ─── 縦型録画 ───
# 合成領域: DOOM (320x240) + Overlay (320x240) = 320x480
# ffmpeg の vstack フィルタで縦に結合し、720x1280 に拡大
MONITOR=$(pactl get-default-sink).monitor
TS=$(date +%Y%m%d_%H%M%S)
VIDEO="experiments/demos/vertical_${TS}.mp4"

DISPLAY="$DISPLAY_NUM" setsid nohup ffmpeg \
  -loglevel error \
  -thread_queue_size 512 -f x11grab -draw_mouse 0 \
    -video_size "${DW}x${DH}" -framerate 30 \
    -i "${DISPLAY_NUM}+${DX},${DY}" \
  -thread_queue_size 512 -f x11grab -draw_mouse 0 \
    -video_size "${OVL_W}x${OVL_H}" -framerate 30 \
    -i "${DISPLAY_NUM}+${OVL_X},${OVL_Y}" \
  -thread_queue_size 512 -f pulse -i "$MONITOR" \
  -filter_complex "\
    [0:v]scale=${OUT_W}:${DOOM_H}:flags=neighbor[top];\
    [1:v]scale=${OUT_W}:${LOG_H}:flags=neighbor[bottom];\
    [top][bottom]vstack=inputs=2[out]" \
  -map "[out]" -map 2:a \
  -t "$DURATION" \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k \
  -y "$VIDEO" \
  < /dev/null > /tmp/qv_ffmpeg.log 2>&1 &
FFMPEG_PID=$!
echo "[$(date +%H:%M:%S)] 縦型録画開始 ${DURATION}s: ${OUT_W}x${OUT_H} (DOOM上/Log下)"
echo "  → $VIDEO"

# ─── 待機 ───
REMAIN=$((DURATION + 5))
while ps -p "$FFMPEG_PID" > /dev/null && [ $REMAIN -gt 0 ]; do
    sleep 5
    REMAIN=$((REMAIN - 5))
    if [ $((REMAIN % 30)) -eq 0 ]; then
        JEV_COUNT=$(grep -c "Jev ->" /tmp/qv_jev.log 2>/dev/null || echo 0)
        echo "  [${REMAIN}秒残] Jev decisions: $JEV_COUNT"
    fi
done

# ─── 停止 ───
pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
pkill -9 -f "python.*overlay" 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════"
echo "✅ 完了"
echo "  Video:    $VIDEO"
echo "  Duration: ${DURATION}s"
echo "  Layout:   縦型 ${OUT_W}x${OUT_H} (DOOM上/ログ下)"
echo ""
echo "  ログ統計:"
echo "    Jev 判断:     $(grep -c 'Jev ->' /tmp/qv_jev.log)"
echo "    System 3 推論: $(grep -c '\[System 3\]' /tmp/qv_jev.log)"
echo "    Reflex:       $(grep -c '\[System1\]' /tmp/qv_jev.log)"
echo "    複合アクション: $(grep -cE 'strafe_attack|advance_attack' /tmp/qv_jev.log)"
echo "═══════════════════════════════════════"

# 再生
mpv --really-quiet "$VIDEO" &
