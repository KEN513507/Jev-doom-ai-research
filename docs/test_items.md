# テスト項目と判定ルール（2026-09-23 確定）

基準線（Phase 1）と以後のすべての変更（Phase 3）は、この項目とルールで比較する。
目標の定義は `docs/ssot_clear_definition.md`（全滅18体 + EXIT）に従う。

## 実行条件

- シナリオ: `full_map`（freedoom2 MAP01、難易度3、敵18体）
- 1条件 = 5エピソード。**seed を固定**し、全条件で同じ seed を使う（エピソード i は seed+i）
- 実行: `./tools/run_and_report.sh <criteria> --scenario full_map --system3 --seed <seed>`
  - レポート JSON に A・C 項目、`episodes[i].diag` に B・D 項目（`tools/analyze_log.py` が自動で追記）
- 比較: `python tools/compare_reports.py --base <基準.json> --new <変更後.json>`
- 固定 seed への過適合を避けるため、節目で別の seed でも確認する

## A. 目標（SSOT）

| ID | 項目 | 定義 | 取得元 |
|---|---|---|---|
| A1 | Clear | 全滅（kills >= 18）かつ EXIT | JSON `kills`, `kills_total`, `i_exit` |
| A2 | kills | 倒した数（/18） | JSON `kills` |
| A3 | EXIT | **人間が確定する**（決定3）。コードは「終了・生存（`is_player_dead()` が偽）・timeout 前」を EXIT 候補として記録するだけ | JSON `exit_candidate`（候補）、`i_exit`（人間の確定後）、ログ `[Episode End] reason=exit_candidate` |
| A4 | **被ダメージ合計（主指標）** | HP 減少の合計。回復アイテムの影響を受けない | JSON `damage_taken` |
| A4' | 副指標 | 被弾回数、最終HP、死亡（`is_player_dead()`） | JSON `hits`, `final_health`, `died` |
| A5 | 探索 | 訪問セル数（128単位） | JSON `visited_cells` |
| A6 | スコア | `tools/score_report.py` の式を1エピソードに適用 | 計算 |

## B. 行動の診断（ログから集計）

| ID | 項目 | 定義 | 目安 |
|---|---|---|---|
| B1 | 旋回し続け | Jev の同じ向きの旋回の最長連続 | 8 未満 |
| B2 | 旋回の偏り | turn_left : turn_right | 片方が 0 にならない |
| B3 | 敵から逃げる横移動 | 敵視認中、敵と逆向きへの move_left/right | 0 に近い |
| B4 | 戦闘に入る | 敵視認中の判断のうち、最終行動が攻撃系（attack / strafe_attack / advance_attack）の割合 | 上がる |
| B5 | 画面外からの被弾 | 被弾直前の Jev 判断で `enemy_visible=no` だった割合 | 3a で下げる |
| B6 | use の連打 | 最終行動が use の最長連続 | 3 以下 |
| B7 | 壁への誤射 | `[Reflex] strafe_attack_* -> attack` の回数 | 3b で 0 |
| B8 | 反射層の発動 | Stuck / TurnMove / UseFail / DoorWait（opened・no_door）の回数 | 記録のみ |
| B9 | stuck_timeout | 半径128単位の円から80tic出られなかった回数（中心はカウント開始時に固定、円を出たら数え直し、留まれば80ticごとに加算）。位置は判断ごと（8tic 単位）に見る | 0 に近い |

## C. 資源

| ID | 項目 | 定義 | 取得元 |
|---|---|---|---|
| C1 | 弾消費 | 同じ武器のまま減った弾の合計 | JSON `ammo_used` |
| C2 | 命中率 | `dmg_hits / ammo_used`（HITCOUNT / 弾消費） | 計算 |
| C3 | 弾切れ | 銃の弾の最小値（0 なら弾切れ）。スロット1（拳・チェーンソー）は除く | JSON `ammo_min`, `melee_steps` |

## D. 実験の健全性

| ID | 項目 | 基準 |
|---|---|---|
| D1 | 有効な実行 | `valid=true`（API 失敗 20% 以下、5エピソード完走）。無効な実行は比較から除外 |
| D2 | Jev の判断回数・skip 率 | 記録のみ。条件間で大きく変わっていないか |
| D3 | Gemini の呼び出し回数・エラー数 | 記録のみ |
| D4 | Jev レイテンシ中央値 | 記録のみ。エピソード内の全呼び出し（[skip] 含む）の中央値。JSON `jev_latency_median`、ログ `[Jev] latency=Xms` |

## 判定ルール

- 条件ごとに全エピソードの値を並べ、平均・標準偏差を出す
- **効果量 d = (変更後の平均 − 基準の平均) / プール標準偏差**。良い方向を正にそろえて判定する

| 良い方向にそろえた d | 判定 | 次の行動 |
|---|---|---|
| 1.5 以上 | 改善候補 | 採用を検討 |
| 0.5〜1.5 | 保留 | 両条件に 5エピソード追加し、n=10 で再計算 |
| 0.5 未満 | 効果なし | 採用しない（または別の案へ） |
| −1.5 以下 | 悪化候補 | 採用しない |

- Welch の t 検定の p 値は参考として表示するが、判定には使わない（n=5 同士では検出力が低い）
- **悪化の確認**: すべての変更で A2（kills）と A4（被ダメージ合計）が「悪化候補」になっていないこと
- 1回の比較で変える要素は1つだけ（CLAUDE.md の原則）
