# Next Action

## 診断
Sys2の稼働率（約53%）は保たれているものの、中盤（step 12〜16）に78などの特大被弾が集中し、生存性が急激に低下している。

## 最優先課題
step 12〜16付近における高火力攻撃（78ダメージ等）に対する回避行動の欠如

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETS['tactical_p1']（または新規criteria）において、被弾リスク回避や安全距離維持（distance_to_enemy、strafe回避行動）の評価重みを引き上げ、突出しを抑制するプロンプト/重み調整を行う。
- 期待: Jevが射線切りや距離調整を優先した行動を選択するようになり、ステップ12〜16での一撃大ダメージ（78dmg）を回避できる。
- リスク: 消極的になりすぎて接敵・攻撃行動の頻度が下がる可能性がある。

### Priority 2: code_edit
- 対象: `train/jev_agent.py`
- 内容: System 1（反射行動）で至近距離の敵を検知した際の挙動を単なる「attack」から「attack + 後退/左右移動」の複合反射、または被弾直後の緊急退避アクションに変更する。
- 期待: 撃ち合い時の即死リスクが軽減され、Sys2判断までの生存猶予が伸びる。
- リスク: System 1の複雑化による意図しない挙動（壁スタック等）の誘発。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p1 --use-labels
```
