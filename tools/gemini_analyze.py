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


def analyze(report_json_path: Path) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-flash-latest")

    report = json.loads(report_json_path.read_text())
    prompt = PROMPT_TEMPLATE.format(
        report_json=json.dumps(report, indent=2, ensure_ascii=False),
        criteria_names=_criteria_names(),
        test_items=_test_items(),
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
