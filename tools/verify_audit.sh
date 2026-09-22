#!/usr/bin/env bash
# 監査結果の技術的検証スクリプト

echo "=================================================="
echo "1. WallAvoider 呼出位置の検証 (Jev API呼出の後か)"
echo "=================================================="
grep -n -C 5 "WallAvoider\|call_jev\|execute_action" train/jev_agent.py || echo "該当箇所が見つかりません"

echo ""
echo "=================================================="
echo "2. ViZDoomUnexpectedExitException の存在検証"
echo "=================================================="
EX_COUNT=$(grep -rn "ViZDoomUnexpectedExitException" . | wc -l)
if [ "$EX_COUNT" -eq 0 ]; then
    echo "✔ 検出数: 0件 (コードベース内に存在しない架空の例外クラスであることが確定)"
else
    grep -rn "ViZDoomUnexpectedExitException" .
fi

echo ""
echo "=================================================="
echo "3. 滞留検知の二重定義・重複呼び出し検証"
echo "=================================================="
echo "[L580-590 の状態]"
sed -n '580,590p' train/jev_agent.py 2>/dev/null || echo "範囲外"
echo "[L665-675 の状態]"
sed -n '665,675p' train/jev_agent.py 2>/dev/null || echo "範囲外"

echo ""
echo "=================================================="
echo "4. バックグラウンド稼働中プロセスの検出"
echo "=================================================="
RUNNING_PROCS=$(ps aux | grep -E "run_and_report|self_correcting|jev_agent" | grep -v grep)
if [ -z "$RUNNING_PROCS" ]; then
    echo "稼働中の関連プロセスはありません"
else
    echo "$RUNNING_PROCS"
fi

echo ""
echo "=================================================="
echo "5. train/jev_agent.py の動的変更・未コミット差分"
echo "=================================================="
git status --short train/jev_agent.py
git diff train/jev_agent.py

