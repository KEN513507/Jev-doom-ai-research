"""マップ構造の自動検査：スクリーンショット + 座標 + レポート生成。

使い方:
    python tools/map_inspect.py
    python tools/map_inspect.py --scenario full_map --steps 100
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import vizdoom as vzd
from PIL import Image


def save_screenshot(game, out_dir: Path, name: str):
    """現在の画面を PNG 保存"""
    state = game.get_state()
    if state is None or state.screen_buffer is None:
        return None
    img_array = np.transpose(state.screen_buffer, (1, 2, 0))
    img = Image.fromarray(img_array.astype("uint8"))
    path = out_dir / f"{name}.png"
    img.save(path)
    return path


def get_position(game):
    """現在の (x, y) を取得"""
    state = game.get_state()
    if state is None:
        return None, None
    v = list(state.game_variables)
    if len(v) < 2:
        return None, None
    return float(v[-2]), float(v[-1])


def run_inspection(scenario_cfg: str, map_name: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = out_dir / "screenshots"
    shots.mkdir(exist_ok=True)

    report = []
    positions = []

    def log(msg):
        print(msg)
        report.append(msg)

    log(f"# Map Inspection Report")
    log(f"")
    log(f"- Timestamp: {datetime.now().isoformat()}")
    log(f"- Scenario cfg: {scenario_cfg}")
    log(f"- Map: {map_name}")
    log(f"- Output: {out_dir}")
    log(f"")

    # --- ゲーム初期化 ---
    game = vzd.DoomGame()
    game.load_config(f"{vzd.scenarios_path}/{scenario_cfg}")
    game.add_available_game_variable(vzd.GameVariable.POSITION_X)
    game.add_available_game_variable(vzd.GameVariable.POSITION_Y)
    game.set_window_visible(True)
    game.set_screen_resolution(vzd.ScreenResolution.RES_320X240)
    game.init()
    game.new_episode(map_name)

    # --- Phase 0: 開始直後 ---
    time.sleep(1)
    x, y = get_position(game)
    positions.append({"phase": "start", "x": x, "y": y})
    save_screenshot(game, shots, "00_start")
    log(f"## Phase 0: Start")
    log(f"- Position: ({x:.1f}, {y:.1f})")
    log(f"- Screenshot: screenshots/00_start.png")
    log(f"")

    # --- Phase 1: 前進 30 step ---
    for _ in range(30):
        game.make_action([0, 0, 0, 0, 1, 0, 0, 0])
    time.sleep(0.5)
    x1, y1 = get_position(game)
    positions.append({"phase": "forward_30", "x": x1, "y": y1})
    save_screenshot(game, shots, "01_forward_30")
    log(f"## Phase 1: Forward 30 steps")
    log(f"- Position: ({x1:.1f}, {y1:.1f})  Δ=({x1-x:.1f}, {y1-y:.1f})")
    log(f"- Screenshot: screenshots/01_forward_30.png")
    log(f"")

    # --- Phase 2: さらに前進 30 step（壁衝突確認）---
    for _ in range(30):
        game.make_action([0, 0, 0, 0, 1, 0, 0, 0])
    time.sleep(0.5)
    x2, y2 = get_position(game)
    positions.append({"phase": "forward_60", "x": x2, "y": y2})
    save_screenshot(game, shots, "02_forward_60")
    log(f"## Phase 2: Forward 60 steps total")
    log(f"- Position: ({x2:.1f}, {y2:.1f})  Δ=({x2-x1:.1f}, {y2-y1:.1f})")
    log(f"- Screenshot: screenshots/02_forward_60.png")
    log(f"")

    # --- Phase 3: 左旋回 90 tics ---
    for _ in range(90):
        game.make_action([0, 0, 0, 0, 0, 1, 0, 0])
    time.sleep(0.5)
    x3, y3 = get_position(game)
    positions.append({"phase": "turn_left_90", "x": x3, "y": y3})
    save_screenshot(game, shots, "03_turn_left_90")
    log(f"## Phase 3: Turn left 90 tics")
    log(f"- Position: ({x3:.1f}, {y3:.1f})  Δ=({x3-x2:.1f}, {y3-y2:.1f})")
    log(f"- Screenshot: screenshots/03_turn_left_90.png")
    log(f"")

    # --- Phase 4: 旋回後、前進 30 step ---
    for _ in range(30):
        game.make_action([0, 0, 0, 0, 1, 0, 0, 0])
    time.sleep(0.5)
    x4, y4 = get_position(game)
    positions.append({"phase": "forward_after_turn", "x": x4, "y": y4})
    save_screenshot(game, shots, "04_forward_after_turn")
    log(f"## Phase 4: Forward 30 after turn")
    log(f"- Position: ({x4:.1f}, {y4:.1f})  Δ=({x4-x3:.1f}, {y4-y3:.1f})")
    log(f"- Screenshot: screenshots/04_forward_after_turn.png")
    log(f"")

    # --- Phase 5: 右旋回 180 tics + 前進 30 ---
    for _ in range(180):
        game.make_action([0, 1, 0, 0, 0, 0, 0, 0])
    for _ in range(30):
        game.make_action([0, 0, 0, 0, 1, 0, 0, 0])
    time.sleep(0.5)
    x5, y5 = get_position(game)
    positions.append({"phase": "turn_right_180_then_forward", "x": x5, "y": y5})
    save_screenshot(game, shots, "05_turn_right_180_forward")
    log(f"## Phase 5: Turn right 180 + Forward 30")
    log(f"- Position: ({x5:.1f}, {y5:.1f})  Δ=({x5-x4:.1f}, {y5-y4:.1f})")
    log(f"- Screenshot: screenshots/05_turn_right_180_forward.png")
    log(f"")

    # --- 移動量サマリー ---
    log(f"## Movement Summary")
    log(f"")
    log(f"| Phase | ΔX | ΔY | 距離 |")
    log(f"|-------|-----|-----|------|")
    for i in range(1, len(positions)):
        prev, cur = positions[i-1], positions[i]
        if prev["x"] is None or cur["x"] is None:
            continue
        dx = cur["x"] - prev["x"]
        dy = cur["y"] - prev["y"]
        dist = (dx**2 + dy**2) ** 0.5
        log(f"| {cur['phase']} | {dx:+.1f} | {dy:+.1f} | {dist:.1f} |")
    log(f"")

    game.close()

    # --- ファイル保存 ---
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(report))

    json_path = out_dir / "positions.json"
    json_path.write_text(json.dumps(positions, indent=2, ensure_ascii=False))

    print()
    print(f"═══ DONE ═══")
    print(f"  Report:      {report_path}")
    print(f"  Positions:   {json_path}")
    print(f"  Screenshots: {shots}/")
    print(f"  Total files: {len(list(shots.glob('*.png')))} screenshots")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="full_map")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    # シナリオ → cfg, map
    if args.scenario == "full_map":
        cfg, map_name = "freedoom2.cfg", "map01"
    else:
        cfg, map_name = f"{args.scenario}.cfg", None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else Path(f"experiments/map_inspect_{ts}")
    run_inspection(cfg, map_name, out_dir)


if __name__ == "__main__":
    main()
