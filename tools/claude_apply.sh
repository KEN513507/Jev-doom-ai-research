#!/bin/bash
# Gemini の next_action.md を読み、Claude Code に実装させる。
# 実行前に必ず Git の状態をクリーンにする。
set -e
cd "$(dirname "$0")/.."
LOGDIR="experiments/auto_logs"

if [ ! -f "$LOGDIR/next_action.md" ]; then
    echo "ERROR: $LOGDIR/next_action.md が見つかりません"
    exit 1
fi

# Git状態チェック
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  未コミットの変更があります。先にcommit/stashしてください。"
    git status --short
    exit 1
fi

# 直前の状態をタグ付け
git tag -f "auto_before_$(date +%s)" HEAD >/dev/null

PROMPT=$(cat << PROMPTEOF
以下の分析結果に基づき、コードを修正してください。

$(cat "$LOGDIR/next_action.md")

【制約】
- Git操作は禁止（commit/pushしない）
- 変更は最小限に
- 修正後、自分で python -m py_compile train/jev_agent.py を実行
- 修正内容の diff を最後に表示
PROMPTEOF
)

echo "=== Claude Code 実行 ==="
echo "$PROMPT"
echo "========================="
echo

# Claude Code 呼び出し（print mode）
claude -p "$PROMPT"

echo
echo "=== 変更内容 ==="
git diff
