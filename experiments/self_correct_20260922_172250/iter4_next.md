# Next Action

## 診断
System 1とSystem 2の稼働バランス（Sys2比率約52%）は健全ですが、交戦開始直後（Step 16-20）および中期（Step 48前後）に大ダメージを被弾し瀕死に陥っています。

## 最優先課題
敵遭遇・交戦開始直後（Step 16-20）における大ダメージ被弾（30-48dmg）

### Priority 1: param_change
- 対象: `train/jev_agent.py`
- 内容: 評価基準の影響を比較検証するため、既存の defensive criteria で同一環境を実行し、Jevの判断傾向と被弾ステップ・ダメージの差異を観察する。
- 期待: 交戦時の引き撃ちや回避行動が増加し、Step 16-20での初弾被弾ダメージが軽減されるか検証できる。
- リスク: 消極的になりすぎて敵の排除が遅れ、長時間の被弾リスクに晒される可能性がある。

### Priority 2: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: defensiveの結果を踏まえ、CRITERIA_SETSに攻撃と被弾回避のバランスを取った `tactical_p1`（被弾回避・射線管理を重視しつつ至近距離撃破を促す）を定義・追加する。
- 期待: Sys2が状況に応じて攻撃と退避を適切に選択できるようになる。
- リスク: プロンプト調整に複数回の試行が必要となる。

## 次のコマンド
```bash
python train/jev_agent.py --criteria defensive --use-labels
```
