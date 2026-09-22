# 研究ノート: ViZDoom × Jev

## Finding 1: Jev の判断は入力に極めて忠実
- `basic.cfg` の game_variable は AMMO2 のみ。これを `health` と決め打ちしたため、
  弾薬数 (50) を「体力 50」と誤認 → `move_backward` 0.6 前後に偏向。
- 文脈文（DOOM・敵・目的の明示）を追加 → `attack` 0.99 に反転。
- 結論: Jev は「おかしい判断」をするのではなく、入力の誤りに忠実。
  対策として `state_to_text()` の変数名を汎用化（`var0=...`）。

## Finding 2: criteria の強度が判断を支配する
- 「attack は得点の主要手段」と書く → `attack` 0.97 が 30 ステップ連続。
- 「後退は危険時のみ」と書く → `move_backward` 0.0。
- 状況依存に書き換え（attack は「敵が中央に clairement 見える場合のみ」、
  前進は「敵が見えない時」）＋ `enemy_visible` の二値化 →
  敵あり: `attack`、敵なし: `move_forward` 1.0 と切り替わることを確認。
- 結論: criteria の表現が確率分布を大きく左右する。バランス設計が必須。

## Finding 3: レイテンシは「動かせる速度」を決めるが「判断の質」は決めない
- 毎回新規接続: median 794ms → `requests.Session` 再利用で median 249ms。
  初回のみ 825ms（TLS＋接続確立）。プロキシ経由あり。
- 判断の質は state と criteria に依存（Finding 1・2）。
- `set_ticrate(4)`（250ms/tic）で同期実行可能。実効レート約 4 decisions/s。

## 目標3（判断可視化）の達成
- `jev_visualization.png`: 行動確率ヒートマップ＋報酬＋体力の時系列を確認。
- 報酬の死亡スパイク（-100）と体力低下が記録され、可視化として成立。
## Finding 5: 解像度・領域の標準化
- state_utils.py に定数を集約し、calib と agent で完全に同じスライス・閾値を使用
- 160×120, center領域 (slice[:, 20:90, :]) で安定した分離を確認
- baseline 41.6, enemy 52-65 → 閾値48.0で偽陽性・偽陰性を最小化
## Finding 6: red_mean 閾値による完全な状況依存判断

- state_utils.py に定数を集約（解像度・スライス・閾値を一元管理）
- calib_v2: baseline median=41.6, enemy max=52-65
- ENEMY_RED_THRESHOLD=48.0 で判定
- 実機ログ: 
  - red_mean 41-47 → enemy_visible=no → move_forward (100%)
  - red_mean 48-61 → enemy_visible=yes → attack (100%)
- 境界 48.0 ケースも正しく判定
- 結論: Jevは criteria + 数値コンテキストに完全に忠実