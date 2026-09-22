#!/bin/bash
cd /home/ken/projects/_Jev/doom-ai-research
VIDEO=$(ls -t experiments/demos/live_*.mp4 | head -1)
BGM="02. At Doom's Gate.mp3"
OUT="${VIDEO%.mp4}_bgm.mp4"
echo "Video:  $VIDEO"
echo "BGM:    $BGM"
echo "Output: $OUT"
ffmpeg -i "$VIDEO" -stream_loop -1 -i "$BGM" -filter_complex "[0:a]volume=1.0[a0];[1:a]volume=0.35[a1];[a0][a1]amix=inputs=2:duration=first[out]" -map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k -shortest -y "$OUT"
echo "Done: $OUT"
ls -la "$OUT"
