"""self_correcting_loop の結果を summary.md にまとめる（人間が朝に見るファイル）。

使い方: python tools/loop_summary.py <LOG_DIR>
入力: <LOG_DIR>/iterations.jsonl（ループが1反復ごとに1行追記）、champion.json、iter*_next.md
"""
import json
import sys
from pathlib import Path


def load_iterations(log_dir: Path) -> list[dict]:
    path = log_dir / "iterations.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def human_items(log_dir: Path, rows: list[dict]) -> list[str]:
    """人間が判断すべき事項: criteria では解決できないという Gemini の判断、無効な実行、実装失敗"""
    items = []
    for f in sorted(log_dir.glob("iter*_next.md")):
        text = f.read_text(errors="replace")
        if "criteria では解決できない" in text:
            needs = [ln[len("- 必要な情報: "):] for ln in text.splitlines() if ln.startswith("- 必要な情報: ")]
            items.append(f"{f.name}: Gemini が criteria では解決できないと判断。必要な情報: {', '.join(needs) or '（記載なし）'}")
    for r in rows:
        if r.get("status") in ("invalid", "impl_failed", "compile_failed"):
            items.append(f"iter {r['iter']}: {r['status']}（{r.get('proposed') or '-'}）。ログ: iter{r['iter']}_*.log")
    return items


def exit_candidates(log_dir: Path) -> list[str]:
    """EXIT 候補（生存したまま timeout 前に終了）のエピソード。EXIT の確定は人間が行う（決定3）"""
    found = []
    for f in sorted(log_dir.glob("*.json")):
        try:
            report = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        for e in report.get("episodes", []):
            if e.get("exit_candidate"):
                found.append(f"{f.name}: criteria={report.get('criteria')} episode={e.get('episode')} "
                             f"seed={e.get('seed')} kills={e.get('kills')} steps={e.get('steps')} "
                             f"（ログ: {report.get('log_path')}）")
    return found


def _fmt(v, nd=2):
    return "-" if v is None else (f"{v:+.{nd}f}" if isinstance(v, float) else str(v))


def render(log_dir: Path) -> str:
    rows = load_iterations(log_dir)
    champ = {}
    if (log_dir / "champion.json").exists():
        champ = json.loads((log_dir / "champion.json").read_text())
    s = champ.get("summary", {})
    adopted = [r for r in rows if r.get("status") == "adopted"]
    total_min = sum(r.get("duration_s", 0) for r in rows) / 60

    out = ["# 無人ループの結果", "", f"- ログ: `{log_dir}`", f"- 反復: {len(rows)} 回（採用 {len(adopted)} 回）、合計 {total_min:.0f} 分"]
    out += ["", "## Champion", "",
            f"- criteria: **{champ.get('criteria', '?')}**",
            f"- kills {s.get('avg_kills', '-')} / {s.get('kills_total', 18)}、全滅 {s.get('full_clears', '-')} 回、"
            f"EXIT 率 {s.get('avg_i_exit', '-')}、被ダメージ {s.get('avg_damage_taken', '-')}、訪問セル {s.get('avg_visited_cells', '-')}",
            "- コード: `git show champion:train/jev_agent.py`（ループが採用時に commit・tag 済み）"]
    out += ["", "## 反復の履歴", "",
            "| iter | 提案 criteria | 結果 | 判定 | n | d(score) | d(kills) | d(被ダメージ) | 分 |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['iter']} | {r.get('proposed') or '-'} | {r.get('status')} | {r.get('verdict') or '-'} | "
                   f"{r.get('n') or '-'} | {_fmt(r.get('d_score'))} | {_fmt(r.get('d_kills'))} | "
                   f"{_fmt(r.get('d_damage_taken'))} | {r.get('duration_s', 0) / 60:.1f} |")
    items = human_items(log_dir, rows)
    cands = exit_candidates(log_dir)
    out += ["", "## EXIT 候補（人間が確認して確定する）", ""] + ([f"- {x}" for x in cands] or ["- なし"])
    out += ["", "## 人間が判断すべき事項", ""] + ([f"- {x}" for x in items] or ["- なし"])
    stop = log_dir / "stop_reason.txt"
    out += ["", "## 終了理由", "", stop.read_text().strip() if stop.exists() else "（記録なし：途中で強制終了された可能性）"]
    return "\n".join(out) + "\n"


def main() -> None:
    log_dir = Path(sys.argv[1])
    (log_dir / "summary.md").write_text(render(log_dir))
    print(f"✅ {log_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
