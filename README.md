# DOOM AI Research

ViZDoom + Jev による自動プレイAIの研究リポジトリ。

## 目標
1. DOOM（ViZDoom）のインストール
2. 自動プレイの実現
3. Jev の判断可視化
4. 評価関数の変更によるスコア改善
5. 研究結果のGit管理

## 環境
- OS: Ubuntu 24.04 LTS
- RAM: 16GB
- GPU: GTX 970 (Maxwell / VRAM 4GB / sm_52)
- Python: 3.10 (conda env: vizdoom)
- Project path: /home/ken/projects/_Jev/doom-ai-research

## 制約
- Gitコミット・プッシュは人間が実行（AIエージェントは一切行わない）
- APIキーは必ず環境変数から読み込む

## ディレクトリ構成
- env/          : カスタム報酬ラッパーなど環境定義
- train/        : 学習スクリプト・設定
- eval/         : 評価・可視化スクリプト
- experiments/  : 実験結果（baseline / aggressive / defensive）
- docs/         : 研究メモ・結果まとめ
- assets/       : 画像・図

## セットアップ
（後で追記）
