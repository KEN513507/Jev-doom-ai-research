# Next Action

## 診断
System 2の関与率は約65%と健全に機能しているが、全エピソードで開始12〜20ステップ以内に大ダメージ被弾（24〜66dmg）が発生し、耐久力を大きく削られている。

## 最優先課題
開幕直後（step 12〜20）におけるヒットスキャン敵との接敵時初動被弾

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETSに`tactical_p6`を新設し、敵視認時の初動において射線回避（strafe/take cover）と交戦距離維持を促す評価軸（例: 'prioritize dodging or breaking line of sight when first encountering hitscan enemies'）を強化する。
- 期待: 開幕step 12〜20での初弾被弾率およびダメージ量の低減、初期ヘルス残量の維持。
- リスク: 消極的な行動（物陰に隠れ続ける、探索停滞）が増加し、ステップ数あたりの進行効率が落ちるリスク。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p6 --use-labels
```
