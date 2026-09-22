# Next Action

## 診断
Sys2稼働率は約55%とJevの意思決定プロセスは機能しているが、aggressive_p1の攻撃偏重評価により接敵直後（step 12-20）および連続被弾時の被ダメージが深刻である。

## 最優先課題
aggressive_p1の評価基準において被弾回避・射線管理の重みが不足しており、初動接敵時および追撃フェーズで大ダメージを許容してしまっている。

### Priority 1: criteria_edit
- 対象: `train/jev_agent.py`
- 内容: CRITERIA_SETSに'tactical_p1'を新規追加。Sys1が即座に敵を排除できなかった場合に、Sys2が被弾リスクを最小化しつつクロスヘアを合わせるポジショニング（strafe_left/right, retreat等）を高く評価する基準を定義する。
- 期待: Jevが敵の射線から外れる行動を選択する頻度が増加し、特にstep 12-20付近の初動大ダメージおよび連続被弾が抑制される。
- リスク: 消極的な行動（逃げ回り）が増加し、敵の撃破速度が低下して総ステップ数が増加する可能性がある。

### Priority 2: none
- 対象: `train/jev_agent.py`
- 内容: 比較対象として既存の'defensive'基準を実行し、基準変更に対するJevの判断変化（行動選択ログの差異）を定量化する。
- 期待: aggressive_p1とdefensive間でのJevの判断傾向の差分が明確になり、評価関数の感度を検証できる。
- リスク: なし（既存コードでの検証のため）

## 次のコマンド
```bash
python train/jev_agent.py --criteria defensive --use-labels
```
