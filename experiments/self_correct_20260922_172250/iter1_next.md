# Next Action

## 診断
System 2（Jev）の稼働率は約88.6%と高く判断は機能しているが、一度敵に捕捉されると短間隔（4〜12ステップ）で連続被弾し致命傷に至っている。

## 最優先課題
被弾発生後の連続被弾（被弾直後の緊急退避・射線切り判断の遅れ）

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETSに'tactical_p3'を追加。tactical_p2をベースに、ヘルス低下時および敵近接時の回避行動（strafe/backward）および被弾回避へのペナルティ/報酬ウェイトを強化する。
- 期待: 被弾直後の連続ダメージが抑制され、エピソード生存時間および最終体力が向上する。
- リスク: 回避を優先しすぎて敵撃破が遅れ、長期的には敵に包囲されるリスクがある。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p3 --use-labels
```
