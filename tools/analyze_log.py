"""実走ログをエピソードごとに集計する（docs/test_items.md の B1〜B8・D2〜D3・被ダメージ）。

使い方:
    python tools/analyze_log.py <run.log>                  # JSON を表示
    python tools/analyze_log.py <run.log> --merge <report.json>
        # report.json の各 episodes[i] に "diag" として追記（run_and_report.sh が呼ぶ）

行動は変えない計測専用。完走したエピソード（"Episode N done:" がある）だけを対象にする。
"""
import argparse
import json
import re
from pathlib import Path

ATTACK_ACTIONS = {"attack", "strafe_attack_left", "strafe_attack_right", "advance_attack"}

RE_EP_START = re.compile(r"^--- Episode (\d+) ---")
RE_EP_DONE = re.compile(r"^Episode (\d+) done:")
RE_JEV = re.compile(r"^step=(\d+) Jev -> ([a-z_]+) \|.*enemy_visible=(yes|no)")
RE_SYS1 = re.compile(r"^step=(\d+) \[System1\] FORCED attack")
RE_REFLEX = re.compile(r"^step=(\d+) \[Reflex\] ([a-z_]+) -> ([a-z_]+)")
RE_USEFAIL = re.compile(r"^step=(\d+) \[UseFail\].* -> ([a-z_]+)")
RE_HIT = re.compile(r"^!!! HIT #\d+ at step=(\d+): (-?\d+) -> (-?\d+)")
RE_SIDE = re.compile(r"enemy_side=(left|right)")


def split_episodes(lines: list[str]) -> dict[int, list[str]]:
    """完走したエピソードの行だけを {番号: 行リスト} で返す"""
    episodes, current, buf, done = {}, None, [], set()
    for line in lines:
        m = RE_EP_START.match(line)
        if m:
            if current is not None:
                episodes[current] = buf
            current, buf = int(m.group(1)), []
            continue
        if current is not None:
            buf.append(line)
            m = RE_EP_DONE.match(line)
            if m:
                done.add(int(m.group(1)))
    if current is not None:
        episodes[current] = buf
    return {k: v for k, v in episodes.items() if k in done}


def _longest_run(seq: list[str], values: set[str]) -> tuple[str | None, int]:
    best, best_v, run, prev = 0, None, 0, None
    for v in seq:
        run = run + 1 if v == prev else 1
        prev = v
        if v in values and run > best:
            best, best_v = run, v
    return best_v, best


def analyze_episode(lines: list[str]) -> dict:
    decisions = []  # 判断ごとの {"jev", "final", "enemy", "side"}
    hits = []  # (step, before, after)
    counts = {"stuck": 0, "turn_move": 0, "use_fail": 0, "door_opened": 0, "door_no_door": 0,
              "wall_shot": 0, "skip": 0, "sys3_calls": 0, "sys3_errors": 0, "system1": 0}
    for i, line in enumerate(lines):
        m = RE_JEV.match(line)
        if m:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            side = RE_SIDE.search(nxt) if "state_text:" in nxt else None
            decisions.append({"step": int(m.group(1)), "jev": m.group(2), "final": m.group(2),
                              "enemy": m.group(3) == "yes", "side": side.group(1) if side else None})
            continue
        if RE_SYS1.match(line):
            counts["system1"] += 1
            decisions.append({"step": int(RE_SYS1.match(line).group(1)), "jev": None,
                              "final": "attack", "enemy": True, "side": None})
            continue
        m = RE_REFLEX.match(line)
        if m:
            if decisions and decisions[-1]["step"] == int(m.group(1)):
                decisions[-1]["final"] = m.group(3)
            if m.group(2).startswith("strafe_attack") and m.group(3) == "attack":
                counts["wall_shot"] += 1
            continue
        m = RE_USEFAIL.match(line)
        if m:
            counts["use_fail"] += 1
            if decisions and decisions[-1]["step"] == int(m.group(1)):
                decisions[-1]["final"] = m.group(2)
            continue
        m = RE_HIT.match(line)
        if m:
            hits.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
            continue
        if "[Stuck]" in line:
            counts["stuck"] += 1
        elif "[TurnMove]" in line:
            counts["turn_move"] += 1
        elif "[DoorWait] opened" in line:
            counts["door_opened"] += 1
        elif "[DoorWait] no_door" in line:
            counts["door_no_door"] += 1
        elif line.startswith("[skip]"):
            counts["skip"] += 1
        elif line.startswith("[System 3] triggers="):
            counts["sys3_calls"] += 1
        elif "[System 3] Gemini error" in line:
            counts["sys3_errors"] += 1

    jev = [d["jev"] for d in decisions if d["jev"]]
    final = [d["final"] for d in decisions]
    turn_dir, turn_run = _longest_run(jev, {"turn_left", "turn_right"})
    _, use_run = _longest_run(final, {"use"})
    enemy_decisions = [d for d in decisions if d["enemy"]]
    flee = sum(1 for d in decisions if d["enemy"] and d["jev"] and d["side"]
               and ((d["jev"] == "move_right" and d["side"] == "left")
                    or (d["jev"] == "move_left" and d["side"] == "right")))
    engage = sum(1 for d in enemy_decisions if d["final"] in ATTACK_ACTIONS)

    # 被弾の直前の判断で敵が見えていなかった = 画面外からの被弾
    offscreen = 0
    for step, _, _ in hits:
        prev = [d for d in decisions if d["step"] <= step and d["jev"] is not None]
        if prev and not prev[-1]["enemy"]:
            offscreen += 1

    n_jev = len(jev)
    return {
        "B1_longest_turn_run": turn_run,
        "B1_longest_turn_dir": turn_dir,
        "B2_turn_left": jev.count("turn_left"),
        "B2_turn_right": jev.count("turn_right"),
        "B3_flee_strafe": flee,
        "B4_engage_rate": engage / len(enemy_decisions) if enemy_decisions else None,
        "B4_enemy_decisions": len(enemy_decisions),
        "B5_offscreen_hit_rate": offscreen / len(hits) if hits else None,
        "B5_offscreen_hits": offscreen,
        "B6_longest_use_run": use_run,
        "B7_wall_shots": counts["wall_shot"],
        "B8_stuck": counts["stuck"],
        "B8_turn_move": counts["turn_move"],
        "B8_use_fail": counts["use_fail"],
        "B8_door_opened": counts["door_opened"],
        "B8_door_no_door": counts["door_no_door"],
        "D2_jev_decisions": n_jev,
        "D2_skip_rate": counts["skip"] / (n_jev + counts["skip"]) if (n_jev + counts["skip"]) else 0.0,
        "D3_sys3_calls": counts["sys3_calls"],
        "D3_sys3_errors": counts["sys3_errors"],
        "A4_damage_taken_log": sum(max(0, b - a) for _, b, a in hits),
        "A4_hits_log": len(hits),
    }


def analyze_log(path: str) -> dict[int, dict]:
    lines = Path(path).read_text(errors="replace").splitlines()
    return {ep: analyze_episode(ls) for ep, ls in split_episodes(lines).items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("--merge", help="episodes[i].diag に追記する report.json")
    args = parser.parse_args()
    result = analyze_log(args.log)
    if args.merge:
        report = json.loads(Path(args.merge).read_text())
        for e in report.get("episodes", []):
            e["diag"] = result.get(e["episode"])
        Path(args.merge).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"✅ diag merged: {args.merge} ({len(result)} episodes)")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
