# SSOT: DOOM ステージクリアの定義と評価

**Single Source of Truth** — 本研究における判定・評価の唯一の基準。
この文書に反する判定・評価・アーキテクチャ図は無効とする。

最終更新: 2026-09-22（監査済み）

---

## 1. 行動的定義（エージェントがなすべき物理的条件）

- **EXITへの到達と起動**: EXITスイッチを押す、またはEXITテレポーターに入る
- **前提条件の踏破**: 鍵（Keycard / Skull Key）の取得、ドア・スイッチの解除
- **例外（ボスステージ）**: 指定ボスの撃破をもってクリアとする

## 2. システム判定の定義（ViZDoom API）

クリア成立条件:
game.is_episode_finished() == True
AND HEALTH > 0
AND steps < episode_timeout（2100）

text

- `steps >= 2100` は**タイムアウト**（クリアではない）
- `HEALTH == 0` は**死亡**（クリアではない）
- 上記AND条件を満たす場合のみ `I_EXIT = 1`、それ以外は `I_EXIT = 0`

## 3. 評価的定義（Clear Score）
Clear Score = I_EXIT × 10000

kills × 500

visited_cells × 10

health

hits × 100

text

### 係数の意味

| 項 | 意味 | レンジ |
|----|------|--------|
| `I_EXIT × 10000` | クリア達成ボーナス | 0 or 10000 |
| `kills × 500` | 撃破の評価 | 0〜2500 |
| `visited_cells × 10` | 探索量（累積・128単位グリッド） | 0〜1000 |
| `+ health` | 生存 | 0〜100 |
| `- hits × 100` | 被弾ペナルティ | 0〜-1000 |

### 設計根拠

- **`I_EXIT` は 10000点** → タイムアウト（0点）と明確に区別
- **`max_distance` は使わない** → 迷路で戻る時に減点されるため
- **`visited_cells` を採用** → 累積・単調増加・迷路に強い
- **係数バランス** → 撃破1体 = 探索50セル相当

## 4. 無効実行の扱い

以下は `valid=false` として `score = -999999`:

- Jev API 呼び出し失敗 > 20%
- エピソード数 < 5
- ViZDoom プロセスの予期しない終了

## 5. 3層アーキテクチャ（実装の実態）

**注意: 設計図ではなく、コードから抽出した事実**

### System 1（後処理層）
- **タイミング**: Jev API 呼び出しの**後**
- **実装**: WallAvoider, ForwardBlockDetector, AreaStagnationDetector
- **遅延**: **0ms ではない**。Jev API の 250ms を毎判断で支払う
- **役割**: Jev が返した行動の**事後補正**

### System 2（Jev API）
- **タイミング**: 同期・毎判断
- **タイムアウト**: 1.0s
- **実測レイテンシ**: median 249ms
- **役割**: 戦術判断の中核

### System 3（Gemini Flash）
- **タイミング**: 非同期スレッド
- **ブロッキング**: なし（Thread + Lock + 非ブロッキング read）
- **モデル**: gemini-flash-latest
- **配線**: `order` 変数で Jev に指示を渡す（※名前衝突問題あり）
- **役割**: 戦略司令

### 既知の問題（未解決）

1. **`order` 変数の上書き**: System 3 の指示と Tactical の戻り値が衝突
2. **滞留検出の二重定義**: `StagnationDetector` と `AreaStagnationDetector` が同時稼働
3. **時間上限なし**: `MAX_ITER` のみ。5時間の自律性は未実装
4. **`sys2=0` 問題**: Tactical が全上書きし、Jev が呼ばれないケースあり

## 6. 変更手順

この文書の変更は **必ずGit経由** で行い、変更理由をコミットメッセージに記す。
AIエージェントはこの文書を変更してはならない。

---

## 付録: 用語定義

| 用語 | 定義 |
|------|------|
| `I_EXIT` | クリア判定の指示関数（0 or 1） |
| `valid` | 実行が評価対象として有効かどうか |
| `visited_cells` | 累積訪問セル数（128単位グリッド、unique） |
| `sys1_count` | System 1 発動回数 |
| `sys2_count` | Jev API 呼び出し回数 |
| `hits` | 被弾イベント数（Health減少検出） |
