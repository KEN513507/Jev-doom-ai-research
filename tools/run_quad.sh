#!/bin/bash
# QUAD SYSTEM: Jev + Gemini(System 3) + 反射層 + 視覚 を色分けオーバーレイ付きで実行し、
# DOOM ウィンドウ + オーバーレイの領域だけを録画する
# 使い方: ./tools/run_quad.sh [criteria=tactical_peeking] [録画秒数=60]
set -e
cd "$(dirname "$0")/.."

CRITERIA="${1:-tactical_peeking}"
DURATION="${2:-60}"
DISPLAY_NUM="${DISPLAY:-:1}"
MONITOR=$(pactl get-default-sink).monitor
TS=$(date +%Y%m%d_%H%M%S)
OUT_DIR="experiments/demos"
VIDEO="${OUT_DIR}/quad_${TS}.mp4"
JEV_LOG="/tmp/quad_${TS}_jev.log"
PID_FILE="/tmp/run_quad.pids"
mkdir -p "$OUT_DIR"

# レイアウト: DOOM の右 340px にオーバーレイを置き、両方を 740x300 で録画。
# DOOM は出現位置のまま（固定座標へ動かすと全画面ブラウザの下に隠れ、描画も間引かれる）。
# 録画領域が画面外にはみ出す場合のみ (FALLBACK_X, FALLBACK_Y) へ移動する
FALLBACK_X=100
FALLBACK_Y=100
OVERLAY_DX=340   # DOOM 左端からオーバーレイ左端まで（DOOM 320px + 余白 20px）
CROP_W=740
CROP_H=300

log() { echo "[$(date +%H:%M:%S)] $*"; }

cleanup() {
    [ -f "$PID_FILE" ] || return 0
    while read -r pid; do
        kill -- "-$pid" 2>/dev/null || true
    done < "$PID_FILE"
    rm -f "$PID_FILE"
}

# ─── Phase 1: 前回の run_quad が起動したプロセスだけ停止（他の実験ループは止めない）───
if [ -f "$PID_FILE" ]; then
    cleanup
    sleep 1
fi
trap cleanup EXIT
rm -f /tmp/jev_status.txt

if [ -z "$GEMINI_API_KEY" ]; then
    log "WARN: GEMINI_API_KEY 未設定。System 3 はダミーモード（ローカル規則）で動作"
fi

# ─── Phase 2: jev_agent 起動（--system3 必須: Gemini スレッドはこのフラグでのみ起動）───
DISPLAY="$DISPLAY_NUM" setsid nohup python -u train/jev_agent.py \
    --scenario full_map --criteria "$CRITERIA" --use-labels --sound --system3 \
    < /dev/null > "$JEV_LOG" 2>&1 &
JEV_PID=$!
echo "$JEV_PID" >> "$PID_FILE"
log "Jev PID: $JEV_PID (log: $JEV_LOG)"

# 自分が起動した vizdoom エンジン（jev_agent の子プロセス）の PID でウィンドウを特定する。
# タイトル検索だと並行実行中の別の jev_agent のウィンドウを掴むことがある
WID=""
for i in $(seq 1 15); do
    sleep 1
    DOOM_PID=$(pgrep -P "$JEV_PID" -f vizdoom | head -1)
    [ -n "$DOOM_PID" ] || continue
    WID=$(wmctrl -lp | awk -v p="$DOOM_PID" '$3 == p && tolower($0) ~ /vizdoom/ {print $1; exit}')
    if [ -n "$WID" ] && xwininfo -id "$WID" 2>/dev/null | grep -q "IsViewable"; then
        break
    fi
    WID=""
done
if [ -z "$WID" ]; then
    log "ERROR: DOOM ウィンドウが15秒以内に出現しませんでした"
    tail -10 "$JEV_LOG"
    exit 1
fi

# ─── Phase 3: DOOM の位置を確認し、前面化 ───
read_pos() {
    eval "$(xwininfo -id "$WID" | awk '
        /Absolute upper-left X:/ {print "WIN_X=" $4}
        /Absolute upper-left Y:/ {print "WIN_Y=" $4}
    ')"
}
read_pos
eval "$(xdpyinfo | awk '/dimensions:/ {split($2, d, "x"); print "SCR_W=" d[1] "; SCR_H=" d[2]}')"
if [ $((WIN_X + CROP_W)) -gt "$SCR_W" ] || [ $((WIN_Y + CROP_H)) -gt "$SCR_H" ]; then
    log "録画領域が画面外にはみ出すため DOOM を (${FALLBACK_X},${FALLBACK_Y}) へ移動"
    wmctrl -i -r "$WID" -e "0,${FALLBACK_X},${FALLBACK_Y},-1,-1"
    sleep 1
    read_pos
fi
# 他のウィンドウが重なると録画に映るため、前面化して最前面に固定
wmctrl -i -r "$WID" -b add,above
wmctrl -i -a "$WID"
sleep 1
log "DOOM window $WID at +${WIN_X},${WIN_Y}"

# ─── Phase 4: オーバーレイを DOOM の右に配置 ───
OVERLAY_GEOM="$((CROP_W - OVERLAY_DX))x${CROP_H}+$((WIN_X + OVERLAY_DX))+${WIN_Y}"
setsid nohup python -u tools/overlay.py --geometry "$OVERLAY_GEOM" \
    < /dev/null > /tmp/overlay.log 2>&1 &
echo "$!" >> "$PID_FILE"
log "Overlay PID: $! ($OVERLAY_GEOM)"
sleep 1

# ─── Phase 5: DOOM + オーバーレイの領域を録画 ───
log "録画開始 ${DURATION}s: ${CROP_W}x${CROP_H} at +${WIN_X},${WIN_Y}"
DISPLAY="$DISPLAY_NUM" ffmpeg -loglevel error \
    -thread_queue_size 512 -f x11grab -draw_mouse 0 -video_size "${CROP_W}x${CROP_H}" -framerate 30 \
    -i "${DISPLAY_NUM}+${WIN_X},${WIN_Y}" \
    -thread_queue_size 512 -f pulse -i "$MONITOR" \
    -t "$DURATION" -c:v libx264 -preset fast -crf 20 -c:a aac -b:a 128k \
    -y "$VIDEO" < /dev/null || log "WARN: ffmpeg 異常終了"

# ─── Phase 6: 停止と検証 ───
cleanup

log "Jev 判断:      $(grep -c ' Jev -> ' "$JEV_LOG" || true) 回"
log "System 3 推論: $(grep -c '^\[System 3\] triggers=' "$JEV_LOG" || true) 回（Jev 判断の合間に出れば並行動作）"
log "Reflex:        $(grep -c '\[Reflex\]' "$JEV_LOG" || true) 回"
log "Video: $VIDEO"
