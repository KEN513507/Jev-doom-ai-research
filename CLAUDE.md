ご指摘の通り、先ほどの引き継ぎ書は**Claude Codeの最新ベストプラクティスからは外れています**。特に「CLAUDE.md」の活用と「プロンプト設計」の原則に反しています。以下、最新の公式・コミュニティ知見に基づき、修正点を整理します。

---

## 🔍 先ほどの引き継ぎ書の問題点

| 問題点 | 理由 |
|--------|------|
| **CLAUDE.md を無視** | プロジェクトの永続コンテキストは `CLAUDE.md` に書くのが原則。引き継ぎ書をそのまま渡すのは非効率 |
| **長すぎる** | `CLAUDE.md` は**150行以下**（推奨60行）が理想。先ほどの引き継ぎ書は200行超 |
| **「手順」を書いている** | Claude Codeは「結果」を記述する方が効果的。手順（ステップ）を細かく書くと、かえって柔軟性を損なう |
| **コンテキスト管理への言及なし** | `/clear`、サブエージェント、`/cost` などの機能活用が前提 |
| **検証（テスト）の指示は良い** | ただし「自分でテストを実行して確認せよ」と明示すべき |

---

## ✅ Claude Code 最新ベストプラクティス（2025-2026）

### 1. CLAUDE.md をプロジェクトの「憲法」として使う

Claude Codeは**セッション開始時に必ず `CLAUDE.md` を読み込みます**。ここに以下を書くのが推奨です：

- よく使うbashコマンド
- コアファイルとユーティリティ関数
- コードスタイルガイドライン
- テスト手順
- リポジトリの慣習（ブランチ命名、マージ vs リベース）
- 開発環境のセットアップ

**推奨行数：150行以下（理想は60行程度）**。それ以上は `.claude/rules/` に分割します。

### 2. プロンプトは「結果」を書く（手順は書かない）

Anthropic公式の推奨：

> **Describe the outcome, not the steps.** Say what you want and let Claude find the files.

また、タスクは**最初のターンで完全に指定**するのが最も効率的です：

> Well-specified task descriptions that incorporate intent, constraints, acceptance criteria, and relevant file locations give Opus 4.7 the context it needs to deliver stronger outputs.

### 3. コンテキスト管理を徹底する

- **`/clear` を5〜7プロンプトごとに実行**（トークン効率化）
- **サブエージェント（Haiku）** を探索に使う
- **`/cost` で予算監視**

### 4. Plan Mode を活用する

大きなタスクは**Plan Mode**で計画を立ててから実装します：

> Delimita i compiti grandi con Plan Mode prima...

### 5. 検証をプロンプトに含める

> Give it a way to check its own work. Ask for run, test, compare, or verify in the same prompt so Claude iterates instead of stopping after one attempt.

---

## 🛠 修正版：Claude Codeへの正しい指示方法

### ① まず `CLAUDE.md` を作成（プロジェクトルート）

```markdown
# DOOM AI Research - Jev × ViZDoom

## プロジェクト概要
TypeSafe AIのJev（クラウドAPI）にDOOMをプレイさせ、判断プロセスを可視化する研究。
ゲームクリアは目的ではない。**リアルタイム可視化**と**判断の記録**が本質。

## 環境
- OS: Ubuntu 24.04 LTS
- GPU: GTX 970 (Maxwell, sm_52, 4GB VRAM)
- Python: 3.10 (conda env: `vizdoom`)
- ViZDoom: 1.3.1
- Jev API: `https://api.typesafe.ai/v1/systemone` (model=`jev-latest`)
- APIレイテンシ: median 249ms

## 制約（厳守）
- AIは一切Git操作を行わない（commit/push禁止）
- APIキーは環境変数 `TYPESAFE_API_KEY` から読み込む
- `game.set_window_visible(True)` をデフォルト維持
- ユーザーのPCスペックを言い訳にしない

## ディレクトリ構造
- `train/jev_agent.py` - メインエージェント
- `train/state_utils.py` - 状態検出（labels_buffer, red_mean）
- `train/scenarios.py` - シナリオ別ボタン・criteria定義
- `experiments/` - 実験結果

## よく使うコマンド
```bash
cd ~/projects/_Jev/doom-ai-research
conda activate vizdoom
python train/jev_agent.py --criteria aggressive_p0 --use-labels
```

## 現在の課題
- `--min-width` argparse定義が欠落（344行目で参照 → AttributeError）
- System 1/2分離（反射層）が未実装
- 被弾ゼロがcriteria調整では達成不可能（実測済み）

## テスト
- `python -m py_compile train/jev_agent.py`
- `pytest tests/ -v`（存在する場合）
```

### ② Claude Codeへのプロンプト（結果ベース）

```
`train/jev_agent.py` の `--min-width` argparse定義を追加し、
System 1/2分離を実装してください。

【意図】
- クラウドAPI 250msの遅延を反射層で吸収し、被弾を減らす
- System 1: 敵が中央・近距離（width>=20）の時、Jevを待たずに attack を強制
- System 2: それ以外は Jev API に判断を委ねる

【受け入れ基準】
- `python -m py_compile train/jev_agent.py` が通ること
- `python train/jev_agent.py --criteria aggressive_p0 --use-labels` がエラーなく起動
- 3エピソード完走し、各エピソード終了時に `sys1` と `sys2` が出力される
- 既存テストがすべて通過

【関連ファイル】
- `train/jev_agent.py`（mainループ、argparse）
- `train/state_utils.py`（detect_enemy_from_labels）
- `tests/test_jev_agent.py`

【検証】
実装後、自分でテストを実行し、結果を報告してください。
```

### ③ 大きなタスクは Plan Mode で開始

```
/plan
System 1/2分離を実装したい。まず計画を立てて。
```

これでClaudeが**計画を提示**し、承認後に実装します。

---

## 📋 まとめ：先ほどの引き継ぎ書との違い

| 項目 | 先ほどの引き継ぎ書 | 正しい方法 |
|------|-------------------|-----------|
| コンテキスト | 長文をそのまま渡す | `CLAUDE.md` に分割（150行以下） |
| プロンプト | 手順を細かく指定 | **結果と受け入れ基準**を指定 |
| タスク開始 | 直接依頼 | **Plan Mode** で計画→承認→実装 |
| 検証 | 言及なし | **自分でテスト実行**を明示 |
| コンテキスト管理 | 言及なし | `/clear`、サブエージェント活用 |
