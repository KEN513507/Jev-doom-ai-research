#!/bin/bash
# 実行ログの監査スクリプト
# 使い方: ./tools/audit.sh [log_file]

LATEST="${1:-$(ls -t /tmp/quad_*_jev.log 2>/dev/null | head -1)}"

if [ -z "$LATEST" ] || [ ! -f "$LATEST" ]; then
    echo "ERROR: log not found"
    exit 1
fi

echo "═══════════════════════════════════════════"
echo "  LOG: $LATEST"
echo "  SIZE: $(wc -l < "$LATEST") lines"
echo "═══════════════════════════════════════════"
echo ""

# ─── 1. Jev選択の分布 ───
echo "═══ 1. Jev選択の分布 ═══"
grep -oP 'Jev -> \K\w+' "$LATEST" | sort | uniq -c | sort -rn
echo ""

# ─── 2. 最長 turn 連続 ───
echo "═══ 2. 最長 turn 連続 ═══"
grep -oP 'Jev -> \K\w+' "$LATEST" | awk '
/^turn_(left|right)$/ {c = (prev ~ /^turn/)? c+1 : 1; if (c > m) {m = c; mc = $0}}
!/^turn_(left|right)$/ {c = 0}
{prev = $0}
END {print "  longest:", mc, m}
'
echo ""

# ─── 3. 最長 move_forward 連続 ───
echo "═══ 3. 最長 move_forward 連続 ═══"
grep -oP 'Jev -> \K\w+' "$LATEST" | awk '
/^move_forward$/ {c++; if (c > m) m = c}
!/^move_forward$/ {c = 0}
END {print "  longest:", m}
'
echo ""

# ─── 4. 新機能の発火回数 ───
echo "═══ 4. 新機能の発火回数 ═══"
echo "  TurnMove:      $(grep -c '\[TurnMove\]' "$LATEST")"
echo "  Stuck:         $(grep -c '\[Stuck\]' "$LATEST")"
echo "  Reflex:        $(grep -c '\[Reflex\]' "$LATEST")"
echo "  System1:       $(grep -c '\[System1\]' "$LATEST")"
echo ""

# ─── 5. Gemini 司令 ───
echo "═══ 5. Gemini 司令回数 ═══"
echo "  [System 3] 発火:   $(grep -c '\[System 3\]' "$LATEST")"
echo ""
echo "  --- 司令ごとの残存判断数 ---"
grep 'order(System3):' "$LATEST" | sort | uniq -c | sort -rn | head -10
echo ""

# ─── 6. HIT 発生時の前後 ───
echo "═══ 6. HIT 発生時の前後 ═══"
grep -B1 -A1 '!!! HIT' "$LATEST" | grep -E 'Jev ->|HIT' | head -30
echo ""

# ─── 7. 敵視認中の Jev 判断（決定打）───
echo "═══ 7. enemy_visible=yes 直後の Jev 判断 ═══"
grep -A1 'enemy_visible=yes' "$LATEST" | grep 'Jev ->' | \
  sed 's/.*Jev -> //' | awk '{print $1}' | sort | uniq -c | sort -rn
echo ""

# ─── 8. 戦闘行動の全発生時刻 ───
echo "═══ 8. attack系の発生（全件）═══"
grep -nE 'Jev -> (attack|strafe_attack)' "$LATEST" | head -20
echo ""

# ─── 9. Episode サマリー ───
echo "═══ 9. Episode サマリー ═══"
grep 'Episode.*done' "$LATEST" | tail -3
echo ""

echo "═══════════════════════════════════════════"
echo "  AUDIT COMPLETE"
echo "═══════════════════════════════════════════"
