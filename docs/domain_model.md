# ドメインモデル: DOOM MAP クリア

**目的**: 本研究のドメインを DDD の語彙で整理し、実装の判断基準を明示する。
**SSOT との関係**: 目標の定義は `docs/ssot_clear_definition.md` を参照。本書は目標に至る構造のみを扱う。

最終更新: 2026-09-23

---

## 1. コアドメイン

**StageClearing（ステージ攻略）**

「未知のマップを、限られた情報とリソースで、目標状態（FULL_CLEAR + I_EXIT）に到達する」ことが本研究の本質的複雑さ。

他のすべてのサブドメインは、このコアを支えるために存在する。

| 分類 | サブドメイン | 本質的複雑さ |
|---|---|---|
| **コア** | StageClearing | 「どこへ進むか」「いつ戦うか」の意思決定 |
| 支援 | Perception | 画面・深度・ラベルから状態を構築 |
| 支援 | WorldModel | 未知のマップをトポロジー化 |
| 支援 | Evaluation | 結果をスコア化 |
| 支援 | Optimization | criteria 改善 |
| 汎用 | LLM Gateway | Jev / Gemini 呼び出し |
| 汎用 | Action Dispatch | ViZDoom へのボタン送信 |
| 汎用 | Persistence | ログ・JSON・mp4 |
| 共有カーネル | GoalDefinition | SSOT §2 と §7 |

---

## 2. 境界づけられたコンテキスト

### CC1: GoalDefinition（共有カーネル）

- **責務**: 目標の唯一の定義
- **成果物**: `docs/ssot_clear_definition.md`
- **含む概念**: `I_EXIT`、`FULL_CLEAR`、`CLEAR`、`monsters_total`、`skill`、`episode_timeout`
- **他コンテキストとの関係**: 全コンテキストが参照する。変更権は人間のみ（SSOT §6）

### CC2: Perception（知覚）

- **責務**: ViZDoom の生データを「判断可能な状態」に変換
- **集約ルート**: `Observation`
- **値オブジェクト**: `EnemyView`、`ItemView`、`DepthView`、`TookDamage`
- **ドメインサービス**: `detect_enemy_from_labels`、`open_directions`、`compute_red_metrics`
- **現状の実装**: `train/state_utils.py`、`state_to_text`
- **コアへの寄与**: 「今、何が見えているか」を Decision に渡す。ここが薄いと Decision が盲目になる

### CC3: WorldModel（地図構築）

- **責務**: 訪問履歴から地図トポロジーを構築
- **集約ルート**: `WorldMemory`
- **値オブジェクト**: `Cell`、`Edge`、`DeadEnd`、`DoorState`
- **不変条件**: `visited_cells` は単調増加、鍵とドアの対応は一意
- **現状の実装**: `train/world_memory.py`、`AreaStagnationDetector`
- **コアへの寄与**: 「どこを歩いたか」「どこへ戻るか」。MAP01 は鍵→戻る構造

### CC4: Decision（意思決定）— コア

- **責務**: 観測と地図から次の行動を選ぶ
- **集約ルート**: `Decision`
- **値オブジェクト**: `Action`、`Criteria`、`ReflexEvent`
- **ドメインサービス**:
  - `JevPolicy`（System 2）
  - `ReflexPolicy`（System 1: `should_force_attack`, `WallAvoider`, `ForwardBlockDetector`）
  - `StrategicPolicy`（System 3: Gemini）
- **不変条件**: 1ステップに1つの `Action` を選ぶ
- **現状の実装**: `train/jev_agent.py` main loop、`resolve_action`

### CC5: Episode（試行）

- **責務**: 1回の MAP 攻略を最初から最後まで実行
- **集約ルート**: `Episode`
- **エンティティ**: `Episode`（seed で識別）
- **値オブジェクト**: `EpisodeOutcome`（`FULL_CLEAR`、`I_EXIT`、`death`、`timeout`）、`Metrics`
- **不変条件**: 終了条件は `is_episode_finished()`。理由を区別して記録する
- **現状の実装**: `jev_agent.py` episode ループ。**「早期終了=死亡」の決め打ちバグあり**
- **コアへの寄与**: 1回の試行の結果を正しく記録する

### CC6: Evaluation（評価）

- **責務**: N エピソードを集計し、criteria 間を比較可能にする
- **集約ルート**: `EvaluationRun`
- **値オブジェクト**: `Summary`、`Score`、`Diag`
- **不変条件**: 5エピソード完走、skip率20%以下
- **現状の実装**: `tools/run_and_report.sh`、`tools/analyze_log.py`、`tools/compare_reports.py`、`tools/score_report.py`

### CC7: Optimization（最適化）

- **責務**: 複数の EvaluationRun から次の criteria を選ぶ
- **集約ルート**: `Campaign`
- **値オブジェクト**: `Generation`、`Champion`、`SelectionPolicy`
- **ドメインサービス**: `Selector`（Greedy / UCB / ES）
- **現状の実装**: `tools/self_correcting_loop.sh`、`tools/gemini_analyze.py`

---

## 3. コンテキストマップ

```
        GoalDefinition (共有カーネル)
              ↑ 参照
    ┌─────────┼─────────┐
    │         │         │
Perception → Decision → Episode ← Evaluation ← Optimization
    ↑         ↑         ↑
    │         │         │
 WorldModel ──┘         │
                        │
              LLM Gateway (汎用)
              Action Dispatch (汎用)
              Persistence (汎用)
```

| 関係 | パターン | 備考 |
|---|---|---|
| GoalDefinition → 全 | 共有カーネル | 人間のみ変更可 |
| Perception → Decision | Conformist | Decision が Perception の形式に従う |
| WorldModel → Decision | 上流下流 | Decision は WorldModel のサマリを参照 |
| Decision → Episode | 制御の反転 | Episode が Decision を駆動 |
| Episode → Evaluation | 上流下流 | 結果を渡す |
| Evaluation → Optimization | 上流下流 | スコアを渡す |
| Optimization → Decision | 上流下流 | criteria を渡す |
| Gemini API → Optimization | アンチコルプション層 | `GeminiAdvisor` が変換 |

---

## 4. Episode 集約（中心）

```
Episode（集約ルート）
├── Observation（値）           ← CC2 Perception
├── Decision（エンティティ）    ← CC4 Decision
│   ├── step, action, source
│   └── reflex_events
├── WorldMemory（値）           ← CC3 WorldModel
└── EpisodeOutcome（値）
    ├── FULL_CLEAR: bool
    ├── I_EXIT: bool
    ├── death: bool
    └── metrics: Metrics
```

**集約ルートの根拠**:

- 「1回の MAP 攻略」がドメイン上の最小単位
- 途中で criteria を変えない（Episode 内では固定）
- 終了時に `EpisodeOutcome` を一意に確定する

`Campaign` は Episode を束ねる別の集約。コアが StageClearing である以上、Episode が中心で、Campaign は最適化のための外側の枠。

---

## 5. Campaign 集約（最適化の枠）

```
Campaign（集約ルート）
├── Generation 1（値オブジェクト）
│   ├── EvaluationRun(criteria=A, seed=1000..1004) → Score
│   ├── EvaluationRun(criteria=B, seed=1000..1004) → Score
│   └── EvaluationRun(criteria=C, seed=1000..1004) → Score
├── SelectionPolicy（値オブジェクト）
└── Champion（値オブジェクト）
```

**不変条件**:

- 同一 Generation 内の全 EvaluationRun は同じ seed 集合を使う
- Champion は Generation 内で SelectionPolicy に従って一意に決まる
- Generation は前の Generation の Champion を親とする（ES の場合）

---

## 6. ドメインサービス

### SelectionPolicy

「複数の Score から次を選ぶ」ロジックは、Criteria にも EvaluationRun にも属さない。

```
interface SelectionPolicy:
    select(runs: List[EvaluationRun]) -> Champion
    next_candidates(champion: Champion, history: List[Generation]) -> List[Criteria]
```

| 実装 | 内容 | 現状 |
|---|---|---|
| GreedyPolicy | 最高 Score を選ぶ | `self_correcting_loop.sh` |
| UCBPolicy | 未探索 criteria を優先（bandit） | 未実装 |
| ESPolicy | Gemini に mutation させる | `gemini_analyze.py` が部分的に担う |

### GeminiAdvisor（アンチコルプション層）

外部の Gemini API を Optimization コンテキストの語彙に翻訳する。

```
class GeminiAdvisor:
    """外部 LLM を Optimization コンテキストの語彙に翻訳する"""
    def propose_criteria(self, campaign: Campaign) -> Criteria:
        # Gemini の JSON 応答を Criteria 値オブジェクトに変換
```

現状は `gemini_analyze.py` が直接 JSON を扱っている。変換層を挟むことで、Gemini の API 変更やモデル差し替えが Optimization コンテキストに波及しない。

---

## 7. リポジトリ

```
CriteriaRepository:
    find_by_name(name) -> Criteria
    add(criteria) -> void

EvaluationRepository:
    save(run: EvaluationRun) -> void
    find_by_criteria(criteria_name, seed) -> EvaluationRun
    latest() -> EvaluationRun

CampaignRepository:
    save(campaign) -> void
    load(campaign_id) -> Campaign
```

現状のファイルシステムがリポジトリの実装:

| リポジトリ | 実装 |
|---|---|
| CriteriaRepository | `train/jev_agent.py` の `CRITERIA_SETS` |
| EvaluationRepository | `experiments/auto_logs/*.json` |
| CampaignRepository | `experiments/self_correct_*/` |

---

## 8. ユビキタス言語

| 現状の語 | DDD での種別 | CC | DOOM での意味 |
|---|---|---|---|
| SSOT | 共有カーネル | GoalDefinition | クリアの定義 |
| FULL_CLEAR | 値オブジェクト | GoalDefinition | 18体全滅 |
| I_EXIT | 値オブジェクト | GoalDefinition | EXIT到達 |
| CLEAR | 値オブジェクト | GoalDefinition | 両方達成 |
| map01 | 値オブジェクト | WorldModel | 攻略対象のマップ |
| visited_cells | 値オブジェクト | WorldModel | 踏破範囲 |
| keys | 値オブジェクト | WorldModel | 取得した鍵 |
| dead_ends | 値オブジェクト | WorldModel | 行き止まり数 |
| observation | 集約ルート | Perception | 現フレームの状態 |
| enemy_visible | 値オブジェクト | Perception | 敵の視認 |
| open_left/center/right | 値オブジェクト | Perception | 通路の開き具合 |
| took_damage | 値オブジェクト | Perception | 直前の被弾 |
| criteria | 値オブジェクト | Decision | 判断方針 |
| action | 値オブジェクト | Decision | 選ばれた行動 |
| reflex_event | 値オブジェクト | Decision | 反射層の発動 |
| episode | エンティティ | Episode | 1回の試行 |
| seed | 値オブジェクト | Episode | 環境の同一性 |
| kills | 値オブジェクト | Episode | 撃破数 |
| damage_taken | 値オブジェクト | Episode | 被ダメ合計 |
| evaluation_run | 集約ルート | Evaluation | 5エピソードの評価 |
| score | 値オブジェクト | Evaluation | 評価値 |
| campaign | 集約ルート | Optimization | 最適化セッション |
| champion | 値オブジェクト | Optimization | 最良 criteria |

---

## 9. MAP クリアに足りないもの（CC 別）

| 症状 | 未成熟な CC | 具体的な欠落 |
|---|---|---|
| visited_cells 11〜32 | Perception | `open_left/center/right` が Decision に渡っていない |
| EXIT 0 | Episode | `is_player_dead()` 未実装で `I_EXIT` が常に 0 |
| kills 3〜5 | Decision | criteria が戦闘に最適化されていない。弾切れで撃てない |
| keys 0 | WorldModel | 鍵→ドアのトポロジー未完成。A* 未実装 |
| dead_ends 0 | WorldModel | 行き止まり記録が機能していない |
| sys2=0（旧） | Decision | Tactical が全上書き。修正済みだが監視が要る |

---

## 10. 適用範囲

- **フル DDD は過剰**。コード数百行、1人開発、criteria 10個
- **CC 境界を意識する価値はある**。特に CC2 Perception と CC4 Decision の分離。現状 `state_to_text` が両方を混ぜている
- **Episode 集約を明示する価値は高い**。`is_player_dead()` バグは「Episode の終了理由が記録されない」CC5 の問題として整理できる
- **Campaign を Episode の上位に置き直す**。コアが MAP クリアである以上、Episode が中心

---

## 付録: 用語の対比

| よくある誤用 | 正しい位置づけ |
|---|---|
| 「強化学習の重み」 | 本研究は RL ではない。criteria は自然言語、勾配なし |
| 「報酬関数」 | `score_report.py` の式は報酬ではなく評価指標。最適化対象ではない |
| 「criteria を学習する」 | criteria を提案するのは LLM。勾配による学習ではない |
| 「複数 criteria を最適化する」 | Campaign 集約内の SelectionPolicy の問題 |
