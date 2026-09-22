```
# DOOM AI Research — Jev × ViZDoom

## Purpose

TypeSafe AIのJev（クラウドAPI）にDOOM（ViZDoom）をプレイさせ、判断プロセスの可視化と評価関数（criteria）の影響を研究する。ゲームクリアは目的ではない。**リアルタイム可視化**と**判断の記録**が本質。

## Environment

- OS: Ubuntu 24.04 LTS
- GPU: GTX 970 (Maxwell, sm_52, 4GB VRAM)
- CPU: Intel i5-4570
- Python: 3.10 (conda env: `vizdoom`)
- ViZDoom: 1.3.1 (ZDOOM 2.8.1+)
- Jev API: `https://api.typesafe.ai/v1/systemone` (model=`jev-latest`, 実体: jev-1.13.0)
- API latency: median 249ms (Session reuse + NO_PROXY 設定済み)
- Project path: `/home/ken/projects/_Jev/doom-ai-research`
- Git remote: `https://github.com/KEN513507/Jev-doom-ai-research`

## Constraints (MUST)

1. **AIは一切Git操作を行わない**（commit/push禁止）。すべて人間が実行。
2. **APIキーは環境変数 `TYPESAFE_API_KEY` から読み込む**。ハードコード禁止。
3. **`game.set_window_visible(True)` をデフォルト維持**。リアルタイム可視化が最優先。
4. **ヘッドレス化は明示的な例外のみ**（ユーザー確認後）。
5. **ユーザーのPCスペックを言い訳にしない**（GTX 970で721fps実測済み）。

## Directory Structure

```
train/
  jev_agent.py        # メインエージェント（実行対象）
  state_utils.py      # 状態検出（labels_buffer, red_mean, front_blocked）
  calib_red.py        # 赤強度キャリブレーション
  scenarios.py        # シナリオ別ボタン・criteria定義
tests/                # pytest
experiments/          # 実験結果
docs/                 # objective.md, findings.md
tools/                # 自動化スクリプト（self_correcting_loop.sh等）
```

## Common Commands

```bash
cd ~/projects/_Jev/doom-ai-research
conda activate vizdoom

# deadly_corridor 実行
python train/jev_agent.py --criteria tactical_p3 --use-labels

# full_map 実行
python train/jev_agent.py --scenario full_map --criteria tactical_peeking --use-labels

# 自動ループ
./tools/self_correcting_loop.sh 10 tactical_p2

# 検証
python -m py_compile train/jev_agent.py && echo COMPILE_OK
pytest tests/ -v
```

## Key API

### train/jev_agent.py
- `CRITERIA_SETS`: criteria定義（baseline, aggressive_p0/p1, tactical_p1〜p6, take_cover_p1, tactical_peeking等）
- `ACTION_BUTTONS`: criteriaキー → ViZDoomボタン名（シナリオ応じて動的）
- `resolve_action(state, game_vars, *, use_labels, min_enemy_width, decide, allow_system1=True)`: System1/2ディスパッチャ
- `should_force_attack(label_info)`: System1条件（ChaingunGuy特例あり）
- `get_jev_decision(api_key, state_text, criteria, timeout)`: API呼び出し（Session再利用）

### train/state_utils.py
- `MIN_ENEMY_WIDTH = 8.0`: 視認判定の最小幅
- `SYSTEM1_WIDTH_THRESHOLD = 20.0`: System1発動の至近距離判定
- `ENEMY_RED_THRESHOLD = 48.0`: red_mean閾値
- `detect_enemy_from_labels(state, min_width)`: labels_bufferから敵検出
- `front_blocked`: 壁検出（full_map用）

### train/scenarios.py
- `SCENARIO_BUTTONS`: 10シナリオのボタン定義
- `SCENARIO_CRITERIA`: シナリオ別標準criteria

## Current State (as of 2026-09-22 夜)

- Champion: **tactical_p3**（hits 2.8, health 28.0, steps 164.8, sys2 90.8%）
- 次点: tactical_p2（hits 2.33, kills=2 確認済み）
- System 1閾値方針が未決（20 vs 8.0）。立上り限定の呼び出し側が欠落中
- full_map 対応実装済み、`front_blocked` 検出が機能していない
- 詳細は `docs/objective.md` と `docs/findings.md`

## Enemy Detection Reference（実測）

| 敵 | width | 備考 |
|----|-------|------|
| Zombieman | 10〜18 | 右寄り (x=100-104) |
| ShotgunGuy | 10〜15 | 左側面 (x=40-50) |
| ChaingunGuy | **0** | width=0例外で検出、最危険 |

解像度: RES_160X120（画面幅160px）

## Code Style

- Python 3.10, 型ヒント使用
- インデント: スペース4個（タブ禁止）
- docstring: 日本語OK
- ログ出力は `print()`（logging未使用）

## Notes

- 変更は1つずつ。複数同時変更は因果不明。
- ユーザーはウィンドウで目視評価する。
- 研究の成果は「被弾ゼロ」だけでなく「Jevの判断プロセスの可視化」も含む。
- 被弾ゼロはクラウドJevでは物理的に不可能（ChaingunGuy初弾57ms vs API遅延250ms）。
```