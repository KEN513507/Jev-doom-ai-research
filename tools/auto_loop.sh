#!/bin/bash
# 自動イテレーションループ
# 使い方: ./tools/auto_loop.sh aggressive_p1 5
set -e
cd "$(dirname "$0")/.."

CRITERIA="${1:-aggressive_p1}"
MAX_ITER="${2:-3}"

for i in $(seq 1 "$MAX_ITER"); do
    echo ""
    echo "╔════════════════════════════════════════════╗"
    echo "║  Iteration $i / $MAX_ITER  (criteria=$CRITERIA)"
    echo "╚════════════════════════════════════════════╝"
    echo ""

    # [1] 実行 & レポート生成
    echo "[1/3] 実行中..."
    ./tools/run_and_report.sh "$CRITERIA" > /dev/null

    # [2] Gemini 分析
    echo "[2/3] Gemini 分析中..."
    python tools/gemini_analyze.py > /dev/null

    # 停止推奨チェック
    SHOULD_STOP=$(python -c "
import json
from pathlib import Path
p = sorted(Path('experiments/auto_logs').glob('analysis_*.json'))[-1]
d = json.loads(p.read_text())
print('yes' if d.get('should_stop') else 'no')
")
    if [ "$SHOULD_STOP" = "yes" ]; then
        echo "🛑 Gemini が停止を推奨。next_action.md を確認してください。"
        cat experiments/auto_logs/next_action.md
        exit 0
    fi

    # [3] 人間のチェックポイント
    echo ""
    echo "────── 次のアクション ──────"
    cat experiments/auto_logs/next_action.md
    echo "───────────────────────────"
    echo ""
    read -p "▶ このアクションを Claude Code で適用しますか？ [y/N/h(uman check)/q(uit)] " ans
    case "$ans" in
        y|Y)
            ./tools/claude_apply.sh
            echo ""
            echo "▶ 変更を確認してください。続行しますか？ [y/N/q]"
            read -p "" ans2
            [ "$ans2" != "y" ] && [ "$ans2" != "Y" ] && break
            ;;
        q|Q)
            echo "終了します。"
            exit 0
            ;;
        *)
            echo "スキップ。手動で次を決めてください。"
            exit 0
            ;;
    esac
done

echo ""
echo "✅ ループ完了（$MAX_ITER iterations）"
