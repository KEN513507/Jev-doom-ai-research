"""レポートをGeminiで分析し、次のアクションを提案する。

環境変数:
  GEMINI_API_KEY: Google AI Studio の API キー
"""
import os
import sys
import json
import time
from pathlib import Path

try:
    import google.generativeai as genai
except ImportError:
    print("ERROR: pip install google-generativeai")
    sys.exit(1)


PROJECT_DIR = Path(__file__).parent.parent
LOGDIR = PROJECT_DIR / "experiments" / "auto_logs"

PROMPT_TEMPLATE = """あなたはDOOMをプレイするAIエージェントの研究を支援する専門家です。

## 目標（SSOT: docs/ssot_clear_definition.md）
- 対象: freedoom2 MAP01、難易度3。敵は18体（Zombieman 11, ShotgunGuy 4, Imp 3）
- **目標達成（Clear）= 18体を全滅させたうえで EXIT すること**
- 研究の目的は、TypeSafe AI の Jev（クラウドAPI、レイテンシ約250ms）の判断プロセスを可視化し、
  評価基準（criteria）の影響を調べること。Jev の判断が機能していることを重視する

## アーキテクチャ
- System 1（反射層）: should_force_attack（至近の中央の敵を即 attack、幅閾値 20.0）、WallAvoider（壁前で use→旋回）、
  ForwardBlockDetector、AreaStagnationDetector、スタック脱出、旋回時の前進（TurnMove）、use 失敗検出、ドア待機の早期解除
- System 2（Jev）: criteria に従って毎判断で行動を1つ選ぶ。複合アクション（strafe_attack_left/right, advance_attack）あり
- System 3（Gemini、非同期）: 前方が塞がれた・同じ場所に留まったときだけ戦略指示を出す（有効時間 2秒）

## プロジェクト構造
- criteria 定義: `train/jev_agent.py` の `CRITERIA_SETS`（新しい criteria はここに追加する）
- 利用可能な criteria: {criteria_names}
- 実行: `./tools/run_and_report.sh <criteria> --scenario full_map --system3 --seed 1000`

## Jev の入力（state_text）の項目一覧
Jev が判断に使えるのは以下の項目**だけ**です。ここに無い情報を前提とする criteria は無効です。
criteria を変える提案は、これらの項目の組み合わせで表現できるものにしてください。

- var0: HP（残り体力）。被弾すると減るが「いつ・どこから撃たれたか」は分からない
- var1: kills（撃破数）、var2: 高度差
- red_mean: 赤チャンネル平均（画面の明るさ。敵の有無は表さない）
- enemy_visible: labels_buffer による敵検出 yes/no
- enemy_count / enemy_centered / enemy_types / enemy_side: 敵の数・中央有無・種類・左右（**画面に映っている敵のみ**）
- front_blocked: 前方が壁で塞がれているか yes/no（壁の手前で反射層が先に止めるため、yes になることは少ない）
- took_damage: 前回判断以降に被弾したか yes/no（**方向は分からない**）
- open_left / open_center / open_right: 左・正面・右の開け具合 far / mid / near（深度バッファ）
- item_visible / item_centered / item_types: 画面に映っているアイテム
- Memory: 訪問セル数・最大移動距離などの要約

**Jev に渡していない情報**（criteria では参照できない）: 被弾した方向、画面外の敵の位置、マップの形、
自分の向き（角度）、弾の残数、敵の体力、過去の自分の行動履歴。

実走ログから取り出した実際の state_text の例:
{state_samples}

## 変更の制約（R1〜R5）
- R1: train/jev_agent.py・train/state_utils.py への新しい if-then ロジックの追加は、自動ループでは行わない（人間の承認が必要）
- R2: state_text に新しい項目を追加することも、人間の承認が必要
- R3: criteria にマップ固有の情報（マップ名、座標、特定の敵配置）を書かない
- R4: DOOM 全般・FPS 全般に通用する戦略だけを書く
- R5: 自動ループで変えられるのは `CRITERIA_SETS` の criteria だけ
問題の解決に上の一覧に無い情報が必要な場合は、criteria を作らずに `solvable_by_criteria=false`、
`action_type="code_edit"` とし、`missing_info` に必要な情報を書いてください（人間が判断します）。

## これまでの分析と結果の履歴（同じシナリオ、古い順）
各行: 実行した criteria とその結果の数値、そのときの診断と提案。
{history}
**過去と同じ提案（名前だけ変えて中身が同じものを含む）はしないでください。** 同じ問題に対する criteria の変更が
過去に効果を出していないなら、criteria では解決できない可能性を検討し、`solvable_by_criteria=false` を選んでください。

## 測定項目と判定ルール（docs/test_items.md）
{test_items}

## 直近の実験結果（JSON。episodes[i].diag に B・D 項目）
{report_json}

## あなたのタスク
上の測定項目の数値に基づいて、目標達成を最も妨げている問題を1つ特定し、次に変える要素を**1つだけ**提案してください
（1回の比較で変える要素は1つ、という原則があります）。数値の根拠（項目IDと値）を必ず示してください。
以下の形式の JSON で出力してください。

{{
  "diagnosis": "現状の問題を1-2文で（項目IDと数値を含める）",
  "sys_balance": {{
    "status": "healthy | sys1_dominant | sys2_dominant | jev_excluded",
    "comment": "System 1/2 のバランスの評価"
  }},
  "primary_issue": "最優先で対処すべき問題（1つだけ）",
  "evidence": ["根拠となる項目IDと値（例: B5_offscreen_hit_rate=0.64）"],
  "root_cause_hypothesis": "その原因の仮説",
  "solvable_by_criteria": true,
  "missing_info": ["criteria で解決できない場合に必要な情報（解決できるなら空）"],
  "differs_from_history": "過去の提案と何が違うか（履歴が無ければ 'no history'）",
  "recommended_actions": [
    {{
      "priority": 1,
      "action_type": "criteria_edit | code_edit | param_change | none",
      "target_file": "train/jev_agent.py など",
      "description": "何をどう変えるか具体的に",
      "expected_effect": "どの測定項目がどう変わるはずか",
      "risk": "副作用のリスク（kills と被ダメージ合計の悪化がないか）"
    }}
  ],
  "next_iteration_command": "次に実行すべきコマンド（criteria を変える場合は --criteria <新しい名前> を含める）",
  "should_stop": false,
  "stop_reason": "停止すべき場合の理由"
}}

JSON以外は出力しないでください。
"""


def _criteria_names() -> str:
    """CRITERIA_SETS のキー一覧（import できなければ定義行から拾う）"""
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        from train.jev_agent import CRITERIA_SETS
        return ", ".join(CRITERIA_SETS)
    except Exception:
        import re
        src = (PROJECT_DIR / "train" / "jev_agent.py").read_text()
        return ", ".join(re.findall(r'^    "([a-z0-9_]+)": \{', src, re.M))


def _test_items() -> str:
    path = PROJECT_DIR / "docs" / "test_items.md"
    return path.read_text() if path.exists() else "(docs/test_items.md なし)"


HISTORY_FILE = LOGDIR / "analysis_history.jsonl"
HISTORY_LIMIT = 8


def _state_samples(report: dict) -> str:
    """レポートの実走ログから、実際に Jev に渡した state_text を敵あり・なしで1つずつ取り出す"""
    try:
        lines = Path(report["log_path"]).read_text(errors="replace").splitlines()
    except (KeyError, OSError):
        return "(実走ログが読めないため例なし)"
    samples = {}
    for line in lines:
        if not line.startswith("    state_text:"):
            continue
        text = line.split("state_text:", 1)[1].strip()
        text = text[text.find("Current state:"):] if "Current state:" in text else text
        key = "敵あり" if "enemy_visible=yes" in text else "敵なし"
        samples.setdefault(key, text)
        if len(samples) == 2:
            break
    return "\n".join(f"- {k}: `{v}`" for k, v in samples.items()) or "(state_text の行なし)"


def proposed_criteria(cmd: str) -> str | None:
    """次のコマンドから criteria 名を取り出す（--criteria X と run_and_report.sh X の両方）"""
    import re
    m = re.search(r"(?:--criteria\s+|run_and_report\.sh\s+)([a-z0-9_]+)", cmd)
    return m.group(1) if m else None


def _history_entry(report_path: Path, report: dict, result: dict) -> dict:
    s = report.get("summary", {})
    b5 = [e["diag"]["B5_offscreen_hit_rate"] for e in report.get("episodes", [])
          if (e.get("diag") or {}).get("B5_offscreen_hit_rate") is not None]
    proposed = proposed_criteria(result.get("next_iteration_command", "") or "")
    actions = result.get("recommended_actions") or [{}]
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "report": str(report_path.resolve()),
        "scenario": report.get("scenario"),
        "criteria": report.get("criteria"),
        "seeds": s.get("seeds"),
        "result": {
            "kills": s.get("avg_kills"), "damage_taken": s.get("avg_damage_taken"),
            "visited_cells": s.get("avg_visited_cells"), "hits": s.get("avg_hits"),
            "i_exit": s.get("avg_i_exit"), "full_clears": s.get("full_clears"),
            "B5_offscreen_hit_rate": round(sum(b5) / len(b5), 3) if b5 else None,
        },
        "primary_issue": result.get("primary_issue"),
        "action_type": actions[0].get("action_type"),
        "proposal": actions[0].get("description"),
        "proposed_criteria": proposed,
        "solvable_by_criteria": result.get("solvable_by_criteria"),
    }


def load_history(scenario: str | None, exclude_report: str | None = None) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    entries = []
    for line in HISTORY_FILE.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("scenario") == scenario and e.get("report") != exclude_report:
            entries.append(e)
    return entries[-HISTORY_LIMIT:]


def save_history(entry: dict) -> None:
    """同じレポートの既存の行は置き換える（再分析で重複させない）"""
    kept = []
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            try:
                if json.loads(line).get("report") == entry["report"]:
                    continue
            except json.JSONDecodeError:
                continue
            kept.append(line)
    kept.append(json.dumps(entry, ensure_ascii=False))
    HISTORY_FILE.write_text("\n".join(kept) + "\n")


def analyze(report_json_path: Path) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-flash-latest")

    report = json.loads(report_json_path.read_text())
    history = load_history(report.get("scenario"), exclude_report=str(report_json_path.resolve()))
    prompt = PROMPT_TEMPLATE.format(
        report_json=json.dumps(report, indent=2, ensure_ascii=False),
        criteria_names=_criteria_names(),
        test_items=_test_items(),
        state_samples=_state_samples(report),
        history="\n".join(json.dumps(h, ensure_ascii=False) for h in history) or "(履歴なし)",
    )

    t0 = time.time()
    response = model.generate_content(prompt)
    elapsed = time.time() - t0
    print(f"Gemini分析完了: {elapsed:.1f}s", file=sys.stderr)

    text = response.text.strip()
    # コードブロック除去
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {"error": str(e), "raw": text}


def main():
    report_path = LOGDIR / "latest_report.json"
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])

    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}")
        sys.exit(1)

    result = analyze(report_path)

    result["_report"] = str(report_path)
    if "error" not in result:
        save_history(_history_entry(report_path, json.loads(report_path.read_text()), result))
    out_path = report_path.resolve().with_name(report_path.resolve().stem + "_analysis.json")
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n✅ Analysis: {out_path}")

    # next_action.md も生成
    if "recommended_actions" in result:
        md = "# Next Action\n\n"
        md += f"## 診断\n{result.get('diagnosis', 'N/A')}\n\n"
        md += f"## 最優先課題\n{result.get('primary_issue', 'N/A')}\n\n"
        if result.get("evidence"):
            md += "## 根拠\n" + "".join(f"- {e}\n" for e in result["evidence"]) + "\n"
        if result.get("solvable_by_criteria") is False:
            md += ("## ⚠ criteria では解決できない（人間の判断が必要）\n"
                   + "".join(f"- 必要な情報: {m}\n" for m in result.get("missing_info") or []) + "\n")
        if result.get("differs_from_history"):
            md += f"## 過去の提案との違い\n{result['differs_from_history']}\n\n"
        for a in result["recommended_actions"]:
            md += f"### Priority {a['priority']}: {a['action_type']}\n"
            md += f"- 対象: `{a.get('target_file', 'N/A')}`\n"
            md += f"- 内容: {a['description']}\n"
            md += f"- 期待: {a.get('expected_effect', 'N/A')}\n"
            md += f"- リスク: {a.get('risk', 'N/A')}\n\n"
        md += f"## 次のコマンド\n```bash\n{result.get('next_iteration_command', 'N/A')}\n```\n"
        (LOGDIR / "next_action.md").write_text(md)
        print(f"✅ Next action: {LOGDIR / 'next_action.md'}")


if __name__ == "__main__":
    main()
