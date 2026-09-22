# MAP01 完全クリア計画書

**目標**: freedoom2 map01 の EXIT スイッチを、AIエージェントが生存状態で押す。

**保証ではなく、達成可能な根拠を示す**。各Phaseが完了すれば、
次のPhaseの前提が満たされ、最終的にクリアに到達する。

---

## Phase 0: baseline 確立（今夜）

**目的**: 「動く」「記録される」ことを確認
**完了条件**:
- 1エピソード完走し、`Episode 0 done:` 行に `i_exit=0` が出力される
- `visited_cells > 20`, `max_distance > 800`
- クラッシュなし

**根拠**: 既に19:16の実測で `kills=2, visited_cells=30, max_distance=1681` を確認済み。

---

## Phase 1: DoorStateMachine（ドア前反転バグの根絶）

**目的**: ドア開口アニメーション中に「壁」と誤認して反転するのを防ぐ
**実装**:
- 状態: IDLE / ACTION_USE / WAITING_OPEN / LOCKED_CHECK
- `use` 後 35 tic 待機 → 深度バッファで開口確認 → IDLE復帰
- 開かなければ LOCKED_CHECK → WorldMemory に記録

**完了条件**: `[DoorWait] done` が発火、ドア通過を1回以上確認
**根拠**: DOOMのドアは `use` 後 35〜70 tic で開く（エンジン仕様）
**所要**: 1〜2時間

---

## Phase 2: ItemPriorityQueue（回復アイテム取得）

**目的**: HP < 30 の時、視界内のHealthPackへ自動接近
**実装**:
- `labels_buffer` からアイテム座標抽出
- Priority = W_type / distance
- System 1 が Jev をバイパスして接近制御

**完了条件**: `item_visible=yes` → `HealthPack` 取得で HP 回復
**根拠**: ViZDoomの labels_buffer は物体名を返す（実測で Zombieman 等確認済み）
**所要**: 2〜3時間

---

## Phase 3: POSITION_Z + 段差/リフト判定

**目的**: 高低差を壁と誤認するのを防ぐ
**実装**:
- `POSITION_Z` を毎フレーム取得（既に var2 で取得済み）
- `front_blocked=True` かつ ΔZ > 0 → 階段と判定、前進維持
- アクションなしで ΔZ ≠ 0 → リフト、待機

**完了条件**: 段差を登る、リフトで昇降
**根拠**: 19:16 の実測で `var2=-5 → -128` の変化を確認済み（既に動作）
**所要**: 3〜4時間（一部完了）

---

## Phase 4: WorldMemory トポロジーグラフ + A*

**目的**: 鍵→鍵ドアのバックトラック
**実装**:
- 256単位グリッドでノード化
- 移動成功時に有向エッジ追加
- 鍵取得 → DOOR_RED を目的地に A* 探索
- `state_text` に `[Navigation: turn 180, advance]` 注入

**完了条件**: 鍵取得後、元の場所に戻ってドアを開ける
**根拠**: DOOM MAP01 は「鍵→戻る」構造（既知のマップ設計）
**所要**: 1〜2日

---

## 最終条件: EXIT到達

**必要条件**:
- Phase 1-4 全て完了
- 実行ループ: `self_correcting_loop.sh` で criteria 自動探索

**根拠**:
- 各Phase完了時点で「クリアに必要な物理条件」が1つずつ揃う
- Phase 4 完了で「鍵→ドア→EXIT」の全経路が A* で復元可能
- 25% の運（敵配置、鍵位置）が、5時間×N回の試行で1回は揃う

**現実的到達**: 2〜4日後

---

## 判断基準

| 段階 | クリア確率 |
|------|-----------|
| 今夜（Phase 0のみ） | **< 1%** |
| Phase 1-2 完了 | 5〜10% |
| Phase 1-3 完了 | 20〜30% |
| Phase 1-4 完了 | **60〜80%** |

**「必ずクリア」ではなく「Phase 4完了で60-80%」**が誠実な表現。
