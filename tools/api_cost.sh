#!/bin/bash
# API利用コスト確認（Jev + Gemini）
cd "$(dirname "$0")/.."

PERIOD="${1:-today}"

# 日付フィルタ（find の -newermt 用に YYYY-MM-DD 形式）
case "$PERIOD" in
  today) SINCE=$(date '+%Y-%m-%d') ;;
  week)  SINCE=$(date -d '7 days ago' '+%Y-%m-%d') ;;
  all)   SINCE="2000-01-01" ;;
  *)     SINCE="$PERIOD" ;;
esac

echo "═══════════════════════════════════════════════════════════════"
echo " API Cost Report — Period: $PERIOD (since $SINCE)"
echo " Generated: $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────
# 1. Jev API
# ─────────────────────────────────────────────
echo "【1】Jev API (TypeSafe AI)"
echo "─────────────────────────────────────────────────────────────"

JEV_TOTAL=0
JEV_FILES=0

# experiments/ 配下の run_*.log
while IFS= read -r f; do
    [ -z "$f" ] && continue
    count=$(grep -c "Jev ->" "$f" 2>/dev/null | head -1)
    count=${count:-0}
    JEV_TOTAL=$((JEV_TOTAL + count))
    JEV_FILES=$((JEV_FILES + 1))
done < <(find experiments/ -name "run_*.log" -newermt "$SINCE" 2>/dev/null)

# ルート直下の run_*.log（過去分、既にruns/へ移動済みならゼロ）
for f in run_*.log; do
    [ -f "$f" ] || continue
    count=$(grep -c "Jev ->" "$f" 2>/dev/null | head -1)
    count=${count:-0}
    JEV_TOTAL=$((JEV_TOTAL + count))
    JEV_FILES=$((JEV_FILES + 1))
done

echo "  リクエスト数: $JEV_TOTAL 回（$JEV_FILES ファイル）"
echo "  単価:         \$0.042 / 1M input tokens"
TOKENS=$((JEV_TOTAL * 350))
JEV_COST=$(awk "BEGIN {printf \"%.4f\", $TOKENS / 1000000 * 0.042}")
echo "  推定トークン: ~$TOKENS tokens（平均350tok/req）"
echo "  推定コスト:  \$$JEV_COST"
echo ""

# ─────────────────────────────────────────────
# 2. Gemini API
# ─────────────────────────────────────────────
echo "【2】Gemini API"
echo "─────────────────────────────────────────────────────────────"

GEMINI_CALLS=$(find experiments/ -name "iter*_next.md" -newermt "$SINCE" 2>/dev/null | wc -l)
GEMINI_TOKENS=$((GEMINI_CALLS * 2000))
GEMINI_COST=$(awk "BEGIN {printf \"%.4f\", $GEMINI_TOKENS / 1000000 * 0.075}")

echo "  分析回数:    $GEMINI_CALLS 回"
echo "  推定トークン: $GEMINI_TOKENS tokens"
echo "  単価（Flash）: \$0.075 / 1M input tokens（推定）"
echo "  推定コスト:  \$$GEMINI_COST"
echo ""

# ─────────────────────────────────────────────
# 3. 合計
# ─────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo "【合計】"
echo "─────────────────────────────────────────────────────────────"

TOTAL_COST=$(awk "BEGIN {printf \"%.4f\", $JEV_COST + $GEMINI_COST}")
TOTAL_JPY=$(awk "BEGIN {printf \"%.1f\", $TOTAL_COST * 150}")

echo "  Jev API:    \$$JEV_COST  ($JEV_TOTAL req)"
echo "  Gemini API: \$$GEMINI_COST  ($GEMINI_CALLS calls)"
echo "  ─────────────────────"
echo "  合計:       \$$TOTAL_COST"
echo ""
echo "  円換算:     ¥$TOTAL_JPY  (@¥150/\$)"
echo "═══════════════════════════════════════════════════════════════"
