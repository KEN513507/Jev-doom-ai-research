# CLEAR Controller V2 — Architecture Contract

この文書は `controller_v2` の最小アーキテクチャ契約です。
旧実装を段階的に移植する際も、以下を破らないこと。

## Objective

対象: `freedoom2 MAP01 / skill 3`

- `FULL_CLEAR = kills >= 18`
- `I_EXIT = actual level exit proven AND not death AND not timeout`
- `CLEAR = FULL_CLEAR AND I_EXIT`

診断指標の改善は CLEAR の代替ではない。

## Action ownership

1. **最終 `executed_action` を決定できるのは ActionArbitrator だけ。**
2. Jev、System1、Memory、Vision、Stuck、WallAvoider、DoorWait 等は action を直接上書きしない。
3. 各モジュールは以下だけを返す。
   - observation
   - proposal
   - veto
   - preference
   - confidence
   - reason
4. `proposed_action` と `executed_action` は必ず別々に記録する。
5. 実行された action には必ず provenance / reason を残す。

## Mode ownership

Mode は action を直接実行しない。Mode が所有するのは以下。

- candidate actions
- forbidden actions
- fallback
- execution profile / action duration
- allowed modifiers
- vision escalation policy

Initial modes:

- EXPLORE
- ROOM_ENTRY_SCAN
- THREAT_SCAN
- COMBAT
- STUCK_RECOVERY
- LOCAL_OPTIMUM_ESCAPE

## Policy routing

優先順位の基本形:

1. deterministic policy が十分に確定している場合は proposal を返す
2. それ以外は Jev を teacher / fallback policy として使う
3. 高リスクかつ低confidenceの場合のみ Vision escalation
4. すべて ActionArbitrator に集約する

Jev の戻り値は最終actionではなく `JevProposal`。

## Memory

Memory は直接ゲームボタンを押さない。

分離する:

- Working / Tactical State
- Spatial / Episodic Memory
- Experience Dataset

Memory は Mode transition、candidate preference、macro goal の入力になる。

## Outcome

各 decision で最低限記録する:

- state_before
- mode
- candidate_actions
- proposals
- vetoes
- Jev probabilities / margin
- executed_action
- reason
- state_after
- health_delta
- ammo_delta
- kill_delta
- progress_delta
- new_cell
- stuck_after

将来の Distillation / RL の教師データはこの Outcome を基準に作る。

## CLEAR_TRACK sensor boundary

Decision に利用可:

- GameVariable 由来のプレイヤー状態
- screen_buffer 由来の視覚特徴
- labels_buffer の現在画面内の可視対象情報
- depth_buffer の現在視界情報
- actual gameplay から蓄積した Runtime Memory

Audit-only:

- `get_objects_info()` 等の未視認object truth
- それを用いて計算した `audit_damage_side`

Audit-only 情報を Jev / Gemini / System1 / ActionArbitrator / ThreatMemory / Runtime Memory Query に入力しない。

## Development rule

- 1 behavior change → 1 verification
- 旧rewrite chainをそのまま V2へ移植しない
- まず interface / invariant / unit test を作る
- Distillation / RL は Controller が CLEAR可能になった後
