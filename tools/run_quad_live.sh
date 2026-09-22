#!/bin/bash
# QUAD SYSTEM LIVE: リアルタイム監視 + 手動録画停止
# ユーザーが見て、ENTER で保存、ESC で破棄
set -e
cd "$(dirname "$0")/.."

# conda 環境
source /home/ken/miniconda3/etc/profile.d/conda.sh 2>/dev/null || true
conda activate vizdoom 2>/dev/null || true

CRITERIA="${1:-tactical_peeking}"
DISPLAY_NUM="${DISPLAY:-:1}"

# 画面サイズ取得
SCREEN_W=$(xdpyinfo | awk '/dimensions/{print $2}' | cut -dx -f1)
SCREEN_H=$(xdpyinfo | awk '/dimensions/{print $2}' | cut -dx -f2)
echo "Screen: ${SCREEN_W}x${SCREEN_H}"

# DOOM 位置（画面左上、余裕を持って）
DOOM_X=50
DOOM_Y=50

# ─── 完全クリーンアップ ───
echo "=== クリーンアップ ==="
pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
pkill -9 -f "python.*overlay" 2>/dev/null || true
pkill -9 -f "ffmpeg.*x11grab" 2>/dev/null || true
pkill -9 -f "vizdoom" 2>/dev/null || true
sleep 3

for w in $(wmctrl -l 2>/dev/null | grep -iE "vizdoom|zdoom" | awk '{print $1}'); do
    wmctrl -ic "$w" 2>/dev/null || true
done

# ─── Jev 起動 ───
echo "=== Jev 起動 ==="
setsid nohup python -u train/jev_agent.py \
  --scenario full_map --criteria "$CRITERIA" \
  --use-labels --sound --system3 --recording \
  < /dev/null > /tmp/ql_jev.log 2>&1 &
JEV_PID=$!
echo "Jev PID: $JEV_PID"

# DOOM ウィンドウ待ち
WID=""
for i in $(seq 1 20); do
    sleep 1
    WID=$(wmctrl -l | grep -iE "vizdoom|zdoom" | head -1 | awk '{print $1}')
    [ -n "$WID" ] && break
done

if [ -z "$WID" ]; then
    echo "❌ DOOM window 未出現"
    tail -20 /tmp/ql_jev.log
    exit 1
fi

# ─── DOOM ウィンドウを「見える位置」へ移動 ───
echo "=== DOOM ウィンドウを ${DOOM_X},${DOOM_Y} へ移動 ==="
wmctrl -i -r "$WID" -e 0,${DOOM_X},${DOOM_Y},320,240
sleep 1

# 実際の座標を再取得
eval $(xwininfo -id "$WID" | awk '
    /Absolute upper-left X:/ {print "DX=" $4}
    /Absolute upper-left Y:/ {print "DY=" $4}
    /Width:/ {print "DW=" $2}
    /Height:/ {print "DH=" $2}
')
echo "DOOM: ${DW}x${DH} at +${DX},${DY}"

# ─── Overlay を DOOM の右隣に配置 ───
OVL_X=$((DX + DW + 10))
OVL_Y=$DY
OVL_W=400
OVL_H=400

echo "=== Overlay 起動: ${OVL_W}x${OVL_H} at +${OVL_X},${OVL_Y} ==="
setsid nohup python -u tools/overlay.py \
  --geometry ${OVL_W}x${OVL_H}+${OVL_X}+${OVL_Y} \
  < /dev/null > /tmp/ql_overlay.log 2>&1 &
OVL_PID=$!

sleep 3

# ─── 準備完了確認 ───
echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║  READY - 画面を確認してください                     ║"
echo "║                                                    ║"
echo "║  DOOM:    ${DW}x${DH} at +${DX},${DY}                       ║"
echo "║  Overlay: ${OVL_W}x${OVL_H} at +${OVL_X},${OVL_Y}                  ║"
echo "║                                                    ║"
echo "║  画面で DOOM とログが見えていますか？               ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
read -p "ENTER で録画開始、Q で中止: " CONFIRM
if [ "$CONFIRM" = "q" ] || [ "$CONFIRM" = "Q" ]; then
    echo "中止します"
    pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
    pkill -9 -f "python.*overlay" 2>/dev/null || true
    exit 0
fi

# ─── 録画開始（手動停止まで）───
MONITOR=$(pactl get-default-sink).monitor
TS=$(date +%Y%m%d_%H%M%S)
VIDEO="experiments/demos/live_${TS}.mp4"

# DOOM + Overlay の合成領域
CROP_X=$DX
CROP_Y=$DY
CROP_W=$((DW + OVL_W + 10))
CROP_H=$DH
[ $OVL_H -gt $CROP_H ] && CROP_H=$OVL_H

echo ""
echo "=== 録画開始（手動停止まで、ESC で破棄）==="
echo "  領域: ${CROP_W}x${CROP_H} at +${CROP_X},${CROP_Y}"
echo "  出力: $VIDEO"
echo ""
echo "  ⏵ 画面を監視してください"
echo "  ⏵ ENTER を押すと【保存】して停止"
echo "  ⏵ ESC + ENTER で【破棄】"
echo ""

DISPLAY="$DISPLAY_NUM" setsid nohup ffmpeg \
  -loglevel error \
  -thread_queue_size 512 -f x11grab -draw_mouse 0 \
    -video_size "${CROP_W}x${CROP_H}" -framerate 30 \
    -i "${DISPLAY_NUM}+${CROP_X},${CROP_Y}" \
  -thread_queue_size 512 -f pulse -i "$MONITOR" \
  -c:v libx264 -preset fast -crf 20 \
  -c:a aac -b:a 128k \
  -y "$VIDEO" \
  < /dev/null > /tmp/ql_ffmpeg.log 2>&1 &
FFMPEG_PID=$!

# ─── 待機（ユーザー入力）───
read -p "監視中... ENTER で停止（保存）: " STOP_KEY

# ─── 停止 ───
echo ""
echo "=== 停止処理中 ==="
kill -INT $FFMPEG_PID 2>/dev/null || true
sleep 3
kill -9 $FFMPEG_PID 2>/dev/null || true

pkill -9 -f "python.*jev_agent.py" 2>/dev/null || true
pkill -9 -f "python.*overlay" 2>/dev/null || true
sleep 1

# ─── 検証 ───
echo ""
echo "=== 録画検証 ==="
if [ ! -f "$VIDEO" ]; then
    echo "❌ ファイルなし"
    exit 1
fi

ls -la "$VIDEO"
DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VIDEO" 2>/dev/null)
SIZE=$(stat -c%s "$VIDEO")

echo "  Size:     $((SIZE / 1024)) KB"
echo "  Duration: ${DUR}s"

# 再生
echo ""
read -p "再生しますか？ (y/n): " PLAY
if [ "$PLAY" = "y" ]; then
    mpv --really-quiet "$VIDEO" &
fi

echo ""
echo "✅ 完了: $VIDEO"
