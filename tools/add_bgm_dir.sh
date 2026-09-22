#!/bin/bash
cd "$(dirname "$0")/.."
DIR="$1"
BGM="02. At Doom's Gate.mp3"

[ -z "$DIR" ] && { echo "使い方: $0 <ディレクトリ>"; exit 1; }
[ ! -f "$BGM" ] && { echo "❌ BGM なし: $BGM"; exit 1; }

for f in "$DIR"/part_*.mp4; do
    case "$f" in *_bgm.mp4) continue ;; esac
    OUT="${f%.mp4}_bgm.mp4"
    echo "処理: $f → $OUT"
    ffmpeg -v error -i "$f" -stream_loop -1 -i "$BGM" \
      -filter_complex "[0:a]volume=1.0[a0];[1:a]volume=0.35[a1];[a0][a1]amix=inputs=2:duration=first[out]" \
      -map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k -shortest -y "$OUT"
done
echo "✅ 完了: $DIR"
