# Next Action

## 診断
Sys2の関与率は約68%と健全に機能しているが、defensive特性による消極性から敵を排除できず、4ステップ間隔の連続追撃を受けて瀕死に陥っている。

## 最優先課題
敵を素早く排除しないことによる4ステップ間隔の連続被弾（多段ヒット）

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETSに新規criteria「tactical_p1」を追加し、被弾回避（安全確保）を重視しつつも視界内の至近距離・射線上の敵に対する先制排除・反撃の重み付けを強化する。
- 期待: Sys1発動後または敵遭遇時にSys2が迅速な無力化を選択し、4ステップ後の連続被弾ループを遮断できる。
- リスク: 好戦的になりすぎて被弾リスクを冒して突撃する（aggressive化する）可能性がある。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p1 --use-labels
```
