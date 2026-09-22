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

## プロジェクト構造（重要）
- criteria定義: `train/jev_agent.py` の `CRITERIA_SETS` 辞書（JSONファイルではない）
- シナリオ定義: `train/scenarios.py`
- 実行コマンド: `python train/jev_agent.py --criteria <name> --use-labels`
- 利用可能なcriteria: baseline, aggressive, aggressive_p0, aggressive_p1, defensive, explorer
- `tactical_p1` などの新criteriaは `CRITERIA_SETS` に追加する必要がある
## 研究の目的
TypeSafe AI の Jev（クラウドAPI、レイテンシ250ms）にDOOMをプレイさせ、
「Jevの判断プロセス」と「評価関数（criteria）の影響」を研究する。
ゲームクリアは目的ではない。被弾ゼロも目的の一つだが、**Jevの判断が機能していること**が最優先。

## 現在のSystem 1/2アーキテクチャ
- System 1（反射）: ChaingunGuy検出時 or 至近距離の敵 → 即 attack
- System 2（Jev）: それ以外は Jev API に判断を委ねる
- 立上り限定: 前回 System 1 発動時は次ステップで System 2 に委ねる（allow_system1=not prev_system1）

## 直近の実験結果（JSON）
{report_json}

## あなたのタスク
以下の形式で分析結果をJSONで出力してください。

{{
  "diagnosis": "現状の問題を1-2文で",
  "sys_balance": {{
    "status": "healthy | sys1_dominant | sys2_dominant | jev_excluded",
    "comment": "sys1/sys2バランスの評価"
  }},
  "primary_issue": "最優先で対処すべき問題（1つだけ）",
  "root_cause_hypothesis": "その原因の仮説",
  "recommended_actions": [
    {{
      "priority": 1,
      "action_type": "criteria_edit | code_edit | param_change | none",
      "target_file": "train/jev_agent.py など",
      "description": "何をどう変えるか具体的に",
      "expected_effect": "期待される結果",
      "risk": "副作用のリスク"
    }}
  ],
  "next_iteration_command": "次に実行すべきコマンド（bash）",
  "should_stop": false,
  "stop_reason": "停止すべき場合の理由"
}}

JSON以外は出力しないでください。
"""


def analyze(report_json_path: Path) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-flash-latest")

    report = json.loads(report_json_path.read_text())
    prompt = PROMPT_TEMPLATE.format(
        report_json=json.dumps(report, indent=2, ensure_ascii=False)
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

    out_path = LOGDIR / f"analysis_{int(time.time())}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n✅ Analysis: {out_path}")

    # next_action.md も生成
    if "recommended_actions" in result:
        md = "# Next Action\n\n"
        md += f"## 診断\n{result.get('diagnosis', 'N/A')}\n\n"
        md += f"## 最優先課題\n{result.get('primary_issue', 'N/A')}\n\n"
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
