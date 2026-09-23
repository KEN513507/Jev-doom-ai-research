# SSOT: DOOM ステージクリアの定義と評価

**Single Source of Truth** — 本研究における判定・評価の唯一の基準。
この文書に反する判定・評価・アーキテクチャ図は無効とする。

最終更新: 2026-09-22（§7 追加、§3 整合）

---

## 1. 行動的定義（エージェントがなすべき物理的条件）

- **EXITへの到達と起動**: EXITスイッチを押す、またはEXITテレポーターに入る
- **前提条件の踏破**: 鍵（Keycard / Skull Key）の取得、ドア・スイッチの解除
- **例外（ボスステージ）**: 指定ボスの撃破をもってクリアとする

## 2. システム判定の定義（ViZDoom API）

KNOWN FACTS
-----------
sys2_ratioは二峰性
~0.50群と~0.98群が存在

step 12-20 damage concentration
UNVERIFIED

ChaingunGuy damage source
UNVERIFIED

250ms Jev latency
UNVERIFIED

latency causes damage
UNVERIFIED

aggressive > defensive
UNVERIFIED

criteria is root cause
UNVERIFIED

lower control layer is root cause
UNVERIFIED