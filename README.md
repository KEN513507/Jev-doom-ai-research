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

## Active development: CLEAR Controller V2

現在の最優先目標は `freedoom2 MAP01 / skill 3` の
`CLEAR = kills >= 18 AND actual exit`。

現行のlegacy agentは比較・再利用元として保持し、新しい制御系は
`train/controller_v2/` に隔離して構築する。

設計原則:

- JevをゲームAIそのものではなく teacher / fallback policy として使う
- 最終 `executed_action` は ActionArbitrator だけが決定する
- System1 / Memory / Vision / recovery系は proposal / veto / preference を返す
- Modeは candidate set / fallback / execution profile を所有する
- Memoryは攻略状態として保持し、将来のExperience Datasetとは分離する
- ControllerでCLEAR可能になった後にDistillation、必要な部分だけRLを検討する

参照:

- `docs/controller_v2/ARCHITECTURE_CONTRACT.md`
- `docs/controller_v2/SPRINT_PLAN.md`
- `train/controller_v2/README.md`

> 旧ドキュメントには初期研究目的の記述が残っている。
> CLEAR_TRACKの現行設計を進める際は、上記V2文書とSSOTを優先して確認する。
