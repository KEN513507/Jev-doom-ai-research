# Next Action

## 診断
Sys1とSys2の呼び出し比率は約1:1と良好に機能しているが、全エピソードで遭遇直後（Step 16-20）および中盤（Step 48前後）に回避のない撃ち合いによる大ダメージ（30-48HP）を被弾している。

## 最優先課題
aggressive_p1の評価基準により敵視認時に棒立ち・直進攻撃を選択し、被弾回避（strafe/退避）の優先度が著しく低くなっている。

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETSに被弾抑止と側方移動（strafe）による射線外しを評価する新基準 'tactical_p1' を追加し、交戦時の生存行動に対する重みを引き上げる。
- 期待: Sys1による初撃後のJev判断において、攻撃一辺倒から回避・間合い管理が選択され、初回交戦（Step 16-20）の被弾ダメージが大幅に軽減される。
- リスク: 消極的な行動（逃亡継続）が増え、敵撃破までのステップ数が延びる可能性がある。

## 次のコマンド
```bash
python train/jev_agent.py --criteria defensive --use-labels
```
