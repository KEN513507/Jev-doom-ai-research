"""基準線と変更後のレポートを項目ごとに比較する（判定ルールは docs/test_items.md）。

使い方:
    python tools/compare_reports.py --base base1.json [base2.json ...] --new new1.json [new2.json ...]

- 各レポートの episodes をプールし、項目ごとに全エピソードの値・平均・標準偏差を並べる
- 効果量 d = (新平均 - 基準平均) / プール標準偏差。良い方向に揃えた d で判定する
    d >= 1.5 : 改善候補 / d <= -1.5 : 悪化候補 / |d| < 0.5 : 効果なし / それ以外 : 保留（追加実走）
- Welch の t 検定の p 値は参考表示のみ（n=5 同士では検出力が低いため判定に使わない）
- 悪化の確認は kills と被ダメージ合計（A2・A4 主指標）
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from score_report import compute_score  # noqa: E402

IMPROVE_D = 1.5
NO_EFFECT_D = 0.5
GUARD_METRICS = ("kills", "damage_taken")

# (項目名, 取り出し関数, 良い方向 +1=大きいほど良い / -1=小さいほど良い)
METRICS = [
    ("clear", lambda e: float(e.get("i_exit", 0) and _full_clear(e)), +1),
    ("kills", lambda e: e.get("kills"), +1),
    ("i_exit", lambda e: e.get("i_exit"), +1),
    ("damage_taken", lambda e: e.get("damage_taken", _diag(e, "A4_damage_taken_log")), -1),
    ("hits", lambda e: e.get("hits"), -1),
    ("final_health", lambda e: e.get("final_health"), +1),
    ("died", lambda e: float(e.get("final_health", 1) <= 0), -1),
    ("visited_cells", lambda e: e.get("visited_cells"), +1),
    ("score", lambda e: _episode_score(e), +1),
    ("ammo_used", lambda e: e.get("ammo_used"), 0),
    ("accuracy", lambda e: e["dmg_hits"] / e["ammo_used"] if e.get("ammo_used") else None, +1),
    ("ammo_min", lambda e: None if e.get("ammo_min", -1) < 0 else e["ammo_min"], +1),
    ("B1_longest_turn_run", lambda e: _diag(e, "B1_longest_turn_run"), -1),
    ("B3_flee_strafe", lambda e: _diag(e, "B3_flee_strafe"), -1),
    ("B4_engage_rate", lambda e: _diag(e, "B4_engage_rate"), +1),
    ("B5_offscreen_hit_rate", lambda e: _diag(e, "B5_offscreen_hit_rate"), -1),
    ("B6_longest_use_run", lambda e: _diag(e, "B6_longest_use_run"), -1),
    ("B7_wall_shots", lambda e: _diag(e, "B7_wall_shots"), -1),
    ("D2_skip_rate", lambda e: _diag(e, "D2_skip_rate"), -1),
]


def _diag(e: dict, key: str):
    return (e.get("diag") or {}).get(key)


def _full_clear(e: dict) -> bool:
    return bool(e.get("kills_total")) and e.get("kills", 0) >= e["kills_total"]


def _episode_score(e: dict) -> float:
    """1エピソードをレポート形式に包んで score_report と同じ式で採点する"""
    summary = {
        "n_episodes": 1, "avg_hits": e["hits"], "avg_health": e["final_health"],
        "avg_steps": e["steps"], "avg_kills": e.get("kills", 0),
        "avg_visited_cells": e.get("visited_cells", 0), "avg_i_exit": e.get("i_exit", 0),
        "full_clears": int(_full_clear(e)),
    }
    return compute_score({"scenario": "full_map", "summary": summary}, expected_episodes=1)


def mean_sd(xs: list[float]) -> tuple[float, float]:
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0
    return m, sd


def effect_size(base: list[float], new: list[float]) -> float | None:
    """平均差 / プール標準偏差。ばらつきゼロで差があれば ±inf"""
    if len(base) < 2 or len(new) < 2:
        return None
    (m1, s1), (m2, s2) = mean_sd(base), mean_sd(new)
    pooled = math.sqrt(((len(base) - 1) * s1 ** 2 + (len(new) - 1) * s2 ** 2) / (len(base) + len(new) - 2))
    if pooled == 0:
        return 0.0 if m1 == m2 else math.copysign(math.inf, m2 - m1)
    return (m2 - m1) / pooled


def _betainc(a: float, b: float, x: float) -> float:
    """正則化不完全ベータ関数（連分数展開、Numerical Recipes の betacf）"""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                     + a * math.log(x) + b * math.log(1 - x))
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betainc(b, a, 1 - x)
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1)
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    f = d
    for i in range(2, 400):  # 初項 d1 は上の初期値で使用済み
        m = i // 2
        if i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + num / c
        c = c if abs(c) > 1e-30 else 1e-30
        f *= c * d
        if abs(c * d - 1.0) < 1e-12:
            break
    return front * f / a


def welch_p(base: list[float], new: list[float]) -> float | None:
    """Welch の t 検定（両側）の p 値。参考表示用"""
    if len(base) < 2 or len(new) < 2:
        return None
    (m1, s1), (m2, s2) = mean_sd(base), mean_sd(new)
    v1, v2 = s1 ** 2 / len(base), s2 ** 2 / len(new)
    if v1 + v2 == 0:
        return None
    t = (m2 - m1) / math.sqrt(v1 + v2)
    df = (v1 + v2) ** 2 / ((v1 ** 2 / (len(base) - 1) if v1 else 0) + (v2 ** 2 / (len(new) - 1) if v2 else 0))
    return _betainc(df / 2, 0.5, df / (df + t * t))


def verdict(d: float | None, direction: int) -> str:
    if d is None:
        return "判定不可"
    if direction == 0:
        return "記録のみ"
    g = d * direction  # 良い方向を正にそろえる
    if g >= IMPROVE_D:
        return "改善候補"
    if g <= -IMPROVE_D:
        return "悪化候補"
    if abs(g) < NO_EFFECT_D:
        return "効果なし"
    return "保留（追加実走）"


def load_episodes(paths: list[str]) -> list[dict]:
    episodes = []
    for p in paths:
        report = json.loads(Path(p).read_text())
        if report.get("valid") is False:
            print(f"⚠ 無効な実行を除外: {p}", file=sys.stderr)
            continue
        episodes.extend(report.get("episodes", []))
    return episodes


def compare(base_eps: list[dict], new_eps: list[dict]) -> list[dict]:
    rows = []
    for name, get, direction in METRICS:
        b = [float(v) for v in (get(e) for e in base_eps) if v is not None]
        n = [float(v) for v in (get(e) for e in new_eps) if v is not None]
        d = effect_size(b, n)
        rows.append({
            "metric": name, "direction": direction, "base": b, "new": n,
            "base_mean_sd": mean_sd(b) if b else None, "new_mean_sd": mean_sd(n) if n else None,
            "d": d, "p": welch_p(b, n), "verdict": verdict(d, direction),
        })
    return rows


def decide(rows: list[dict], primary: str = "score") -> str:
    """ループの採否に使う1語の判定。kills・被ダメージ合計のどちらかが悪化候補なら、主指標に関わらず悪化候補"""
    by_name = {r["metric"]: r for r in rows}
    if any(by_name.get(m, {}).get("verdict") == "悪化候補" for m in GUARD_METRICS):
        return "悪化候補"
    return by_name.get(primary, {}).get("verdict", "判定不可")


def _fmt(xs: list[float]) -> str:
    return "[" + " ".join(f"{x:g}" if abs(x) >= 1 or x == 0 else f"{x:.2f}" for x in xs) + "]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", nargs="+", required=True)
    parser.add_argument("--new", nargs="+", required=True)
    parser.add_argument("--json", help="結果を JSON で保存")
    parser.add_argument("--decide", metavar="METRIC",
                        help="最終行に VERDICT=<判定> を出す（主指標 METRIC ＋ kills・被ダメージの悪化確認）")
    args = parser.parse_args()
    rows = compare(load_episodes(args.base), load_episodes(args.new))

    print(f"{'項目':<24}{'基準 平均±SD':>16}{'変更後 平均±SD':>18}{'d':>7}{'p':>7}  判定")
    for r in rows:
        if not r["base"] and not r["new"]:
            continue
        bm = f"{r['base_mean_sd'][0]:.2f}±{r['base_mean_sd'][1]:.2f}" if r["base"] else "-"
        nm = f"{r['new_mean_sd'][0]:.2f}±{r['new_mean_sd'][1]:.2f}" if r["new"] else "-"
        d = "-" if r["d"] is None else f"{r['d']:+.2f}"
        p = "-" if r["p"] is None else f"{r['p']:.3f}"
        guard = " ⚠悪化確認" if r["metric"] in GUARD_METRICS and r["verdict"] == "悪化候補" else ""
        print(f"{r['metric']:<24}{bm:>16}{nm:>18}{d:>7}{p:>7}  {r['verdict']}{guard}")
        print(f"{'':<24}基準 {_fmt(r['base'])}  変更後 {_fmt(r['new'])}")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    if args.decide:
        print(f"VERDICT={decide(rows, args.decide)}")


if __name__ == "__main__":
    main()
