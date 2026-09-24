# CLEAR Controller V2 — Sprint Plan

現行実装は「個別機能は動作しているが、MAP01 CLEARを合理的に期待できる制御構造には未到達」と定義する。

## Sprint 0 — Freeze V1

目的:
- 現行 `main` を比較対象として保持
- baseline / known failures / tests を記録

完了条件:
- V1の参照commitを固定
- CLEAR/FULL_CLEAR/kills/stuck/crashの既知結果を再参照可能

## Sprint 1 — V2 skeleton

目的:
- 既存decision loopを移植せず、V2の依存方向を固定

最小構成:

```text
train/controller_v2/
  __init__.py
  observation.py
  state.py
  mode.py
  proposals.py
  arbitrator.py
  outcome.py
  controller.py
```

## Sprint 2 — Action ownership

目的:
- `executed_action` の所有者を ActionArbitrator へ一本化

Gate:
- 最終action生成箇所が1つ
- 他moduleは proposal/veto/preference のみ
- proposed/executed/reason を記録

## Sprint 3 — Rewrite migration

旧機能を1個ずつ proposal/veto 化する。

順序:
1. WallAvoider
2. DoorWait
3. UseFail
4. Stuck recovery
5. TurnMove
6. CautiousForward

各移植を独立検証する。

## Sprint 4 — Mode Controller

Modeを記録ラベルから実Controllerへ変更。

Modeが所有:
- candidate set
- fallback
- action duration
- allowed modifiers
- vision escalation policy

## Sprint 5 — Jev as teacher/fallback

Jevは最終actionを決めない。

記録:
- candidate actions
- probability distribution
- choice_score
- top_margin
- entropy
- JevProposal

## Sprint 6 — Combat Gate migration

既に確認された off-center fire 禁止をV2へ移植。

Gate:
- illegal-fire rate を低水準維持
- combat low-margin改善を維持
- damage/killsも別途評価

## Sprint 7 — ProgressPressure fix

正しい定義:
- revisit = 3D navigation cell
- `last_new_cell_tic` = never-seen cellへ初到達したtic
- blocked forward = proposed_action基準
- visual place != geographic place

このSprintでは行動を変えない。

## Sprint 8 — LOCAL_OPTIMUM_ESCAPE

high pressure + no combat/threat でMode遷移。

目的:
- 「動けないstuck」と「動いているが進展しないlocal optimum」を分離

## Sprint 9 — Spatial / Transition / Frontier Memory

最低限:
- Place
- Transition
- Frontier
- Interaction

Backtrackingを正常な攻略行動として扱う。

## Sprint 10 — Outcome dataset

Distillation/RL用に proposal → executed → outcome を完全記録。

まだStudentを作らない。

## Sprint 11 — Event-triggered Vision

常時画像送信はしない。

条件:
- high risk
- low confidence
- text/sensor stateだけでは視覚判断不足

Visionも proposal provider とし、ActionArbitratorへ渡す。

## Sprint 12 — MAP01 CLEAR

最上位評価:
1. CLEAR
2. FULL_CLEAR
3. I_EXIT
4. kills
5. survival/progress

`CLEAR=0` のままならSprint未完。

## Sprint 13+ — Teacher quality → Distillation → optional RL

CLEARを複数runで評価した後:

- successful teacher dataを選別
- Studentへ蒸留
- Jevはlow-confidence/novel/high-risk fallbackへ縮小
- 必要なlocal policyだけRLでfine-tune
