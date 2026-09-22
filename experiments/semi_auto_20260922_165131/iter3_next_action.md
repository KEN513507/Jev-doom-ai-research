# Next Action

## 診断
Sys2の稼働率は約60%を維持しJevの判断は機能しているが、全エピソードで開幕直後（step 12〜16）に大ダメージ（12〜48）を受けており、初期接敵時の生存戦術が破綻している。

## 最優先課題
開幕直後（step 12〜16）におけるChaingunGuy等からの初撃被弾および大ダメージ。

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETS に 'tactical_p1' を追加し、脅威度が最も高い敵の早期無力化と射線切断（遮蔽物利用）を両立させた評価プロンプト/重みを定義する。
- 期待: 開幕接敵時の無駄な被弾回避行動を減らし、射撃による敵無力化と安全確保のメリハリをつけて開幕ダメージを抑制する。
- リスク: Sys1との競合が増加し、Sys2比率が低下して反射的攻撃に偏る可能性がある。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p1 --use-labels
```
