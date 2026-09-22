# Next Action

## 診断
Jev(System 2)の判断率は約98%と高水準で意思決定は機能しているが、250msのレイテンシ中に敵の射線にとどまり大ダメージ被弾を重ねている。

## 最優先課題
tactical_p3の評価関数において射線回避・距離維持への動機付けが弱く、Jevが被弾リスクの高い行動を選択している点。

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETS に 'tactical_p4' を追加。被弾リスク回避（avoid line of fire / strafe to cover）、敵との安全距離維持（keep safe distance）、危険度に応じた遮蔽物利用の評価ウェイトを高める。
- 期待: Jevが射線を切る移動（strafe/retreat）を選択しやすくなり、平均被弾数（2.67回）および大ダメージの低減が期待できる。
- リスク: 消極的になりすぎて接敵・攻撃行動が減少し、エピソードのステップ数が長期化・タイムアウトするリスク。

### Priority 2: code_edit
- 対象: `train/jev_agent.py`
- 内容: System 1の発動判定を見直し、ChaingunGuyだけでなくShotgunGuyなどの即時大ダメージ源、または至近距離閾値（distance）を緩和して反射射撃/回避を誘発させる。
- 期待: Ep0で見られた単発78ダメージのような即死級攻撃を未然に防ぐ。
- リスク: Sys1の発動比率が増えすぎ、Jevの判断余地（Sys2）を阻害するリスク。

## 次のコマンド
```bash
python train/jev_agent.py --criteria tactical_p4 --use-labels
```
