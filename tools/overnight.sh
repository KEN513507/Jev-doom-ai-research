#!/bin/bash
# 夜間の無人運転（5時間）: Phase 1（stuck_timeout の A/B 検証）→ Phase 2（criteria 探索ループ）
# 使い方: ./tools/overnight.sh [制限時間(分)=300] [基準 criteria=tactical_peeking] [seed=1000] [旧基準線レポート]
#
# Phase 1（約11分、保留なら約22分）
#   A: --no-stuck-timeout あり / B: なし（同じコード・criteria・seed）→ B を A と比較（stuck_timeout の効果）
#   A を旧基準線（003209）と比較 → use 文言・damage_side・死亡判定の3変更の合計効果（参考、追加実走なし）
#   A/B が保留なら両方に seed+5 で5エピソード追加し n=10 で再判定
#   Phase 2 のフラグ: B が悪化候補 → --no-stuck-timeout、それ以外（改善候補・保留・効果なし）→ stuck_timeout 有効
# Phase 2（残り時間）
#   self_correcting_loop.sh を Phase 1 で決めたフラグで起動。初期 champion は Phase 1 の採用側の実走を引き継ぐ
#   （同じ criteria・コード・フラグ・seed の実走なので再測定は不要。n=10 に延ばした分も引き継ぎ、5.5〜11分を節約）
# 出力: experiments/overnight_<時刻>/（iter_phase1.jsonl、phase1_*、loop/、SUMMARY.md）
cd "$(dirname "$0")/.."

DURATION_MIN="${1:-300}"
CRITERIA="${2:-tactical_peeking}"
SEED="${3:-1000}"
OLD_BASE="${4:-experiments/auto_logs/report_tactical_peeking_20260923_003209.json}"
SCENARIO=full_map
RUN_TIMEOUT_SEC=1500
export EPISODE_END_HOLD_SEC=0

# --- 起動前の確認（Phase 1 の11分後にループが起動できずに止まるのを防ぐため、ここで全部確かめる）---
for cmd in python claude git; do
    command -v "$cmd" >/dev/null || { echo "🛑 $cmd が見つかりません（conda activate vizdoom を確認）" >&2; exit 1; }
done
for var in TYPESAFE_API_KEY GEMINI_API_KEY; do
    [ -n "${!var}" ] || { echo "🛑 環境変数 $var が未設定です" >&2; exit 1; }
done
if ! git diff --quiet -- . ':(exclude)experiments' || ! git diff --cached --quiet -- . ':(exclude)experiments'; then
    echo "🛑 未コミットの変更があります（experiments/ 以外）。コミットしてから起動してください。" >&2
    git status --short -- . ':(exclude)experiments' >&2
    exit 1
fi
[ -f "$OLD_BASE" ] || echo "⚠ 旧基準線 $OLD_BASE がないため、3変更の合計効果の比較は省略します" >&2

OUT="experiments/overnight_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
LOG="$OUT/overnight.log"
START_EPOCH=$(date +%s)
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# 1実走。$1=ラベル $2=seed $3...=jev_agent への追加引数。レポートを $OUT/phase1_<ラベル>.json に保存
run_phase1() {
    local label="$1" seed="$2"; shift 2
    log "  実走 $label（$CRITERIA, seed $seed, $*）"
    SKIP_GEMINI_ANALYZE=1 timeout "$RUN_TIMEOUT_SEC" ./tools/run_and_report.sh "$CRITERIA" --scenario "$SCENARIO" \
        --seed "$seed" --system3 "$@" > "$OUT/phase1_${label}.log" 2>&1
    local rep
    rep=$(grep -o "experiments/auto_logs/report_[^ ]*\.json" "$OUT/phase1_${label}.log" | tail -n 1)
    [ -n "$rep" ] && [ -f "$rep" ] && cp "$rep" "$OUT/phase1_${label}.json" && return 0
    log "  ⚠ $label のレポートが得られない（ログ: $OUT/phase1_${label}.log）"
    return 1
}

verdict() {  # $1=比較表の出力先、以降 compare_reports の引数
    local out="$1"; shift
    python tools/compare_reports.py --decide score --json "$out.json" "$@" > "$out" 2>&1
    sed -n 's/^VERDICT=//p' "$out" | tail -n 1
}

# ═══════ Phase 1 ═══════
log "═══════ Phase 1: stuck_timeout の A/B 検証（$CRITERIA, seed $SEED）═══════"
A_OK=0; B_OK=0
run_phase1 no_stuck "$SEED" --no-stuck-timeout && A_OK=1
run_phase1 with_stuck "$SEED" && B_OK=1
A_REPORTS=("$OUT/phase1_no_stuck.json"); B_REPORTS=("$OUT/phase1_with_stuck.json")

if [ "$A_OK" -eq 1 ] && [ "$B_OK" -eq 1 ]; then
    AB=$(verdict "$OUT/phase1_ab_n5.txt" --base "${A_REPORTS[@]}" --new "${B_REPORTS[@]}")
    N=5
    log "  stuck_timeout あり vs なし (n=5): $AB"
    if [ "$AB" = "保留（追加実走）" ]; then
        EXT=$((SEED + 5))
        log "  保留 → 両方に seed $EXT で5エピソード追加"
        run_phase1 no_stuck_ext "$EXT" --no-stuck-timeout && A_REPORTS+=("$OUT/phase1_no_stuck_ext.json")
        run_phase1 with_stuck_ext "$EXT" && B_REPORTS+=("$OUT/phase1_with_stuck_ext.json")
        AB=$(verdict "$OUT/phase1_ab_n10.txt" --base "${A_REPORTS[@]}" --new "${B_REPORTS[@]}")
        N=10
        log "  stuck_timeout あり vs なし (n=10): $AB"
    fi
else
    AB="判定不可"; N=0
    log "  ⚠ A/B のどちらかが得られないため判定不可"
fi

COMBINED="判定不可"
if [ "$A_OK" -eq 1 ] && [ -f "$OLD_BASE" ]; then
    COMBINED=$(verdict "$OUT/phase1_combined_vs_old.txt" --base "$OLD_BASE" --new "$OUT/phase1_no_stuck.json")
    log "  3変更の合計効果（stuck_timeout なし vs 旧基準線）: $COMBINED"
fi

# Phase 2 のフラグと初期 champion
if [ "$AB" = "悪化候補" ]; then
    FLAGS="--system3 --no-stuck-timeout"; INIT=("${A_REPORTS[@]}"); CHOSEN=no_stuck
elif [ "$B_OK" -eq 1 ]; then
    FLAGS="--system3"; INIT=("${B_REPORTS[@]}"); CHOSEN=with_stuck
else
    FLAGS="--system3"; INIT=(); CHOSEN=with_stuck   # B が得られなければループが初期実走する
fi
log "  → Phase 2 のフラグ: $FLAGS（初期 champion: ${INIT[*]:-ループで初期実走}）"

# iter_phase1.jsonl（要件の形式）
python - "$OUT/iter_phase1.jsonl" "$CRITERIA" "$SEED" "$AB" "$COMBINED" "$N" "$CHOSEN" "$FLAGS" \
    "$OUT/phase1_no_stuck.json" "$OUT/phase1_with_stuck.json" <<'PYEOF'
import json, sys
path, crit, seed, ab, combined, n, chosen, flags, a_path, b_path = sys.argv[1:]
def s(p):
    try:
        x = json.load(open(p))["summary"]
        return x.get("avg_kills"), x.get("avg_visited_cells")
    except (OSError, ValueError, KeyError):
        return None, None
ka, va = s(a_path); kb, vb = s(b_path)
rows = [
    {"run": "no_stuck_timeout", "criteria": crit, "seed": int(seed), "verdict_vs_003209": combined, "kills": ka, "visited": va},
    {"run": "with_stuck_timeout", "criteria": crit, "seed": int(seed), "verdict_vs_no_stuck": ab, "n": int(n), "kills": kb, "visited": vb},
    {"combined_3changes_vs_003209": {"verdict": combined, "comment": "use文言+damage_side+死亡判定の合計効果"}},
    {"phase2": {"stuck_timeout": chosen != "no_stuck", "agent_args": flags,
                "init_champion": "Phase 1 の採用側の実走を引き継ぐ（同一条件のため再測定不要、5.5〜11分節約）"}},
]
with open(path, "w") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
PYEOF

# ═══════ Phase 2 ═══════
ELAPSED_MIN=$(( ($(date +%s) - START_EPOCH) / 60 ))
REMAIN_MIN=$((DURATION_MIN - ELAPSED_MIN))
log "═══════ Phase 2: criteria 探索ループ（残り ${REMAIN_MIN}分）═══════"
LOOP_LOG_DIR="$OUT/loop" AGENT_EXTRA_ARGS="$FLAGS" INIT_REPORTS="${INIT[*]}" \
    ./tools/self_correcting_loop.sh 100 "$CRITERIA" "$SCENARIO" "$SEED" "$REMAIN_MIN" >> "$LOG" 2>&1
log "Phase 2 終了（終了コード $?）"

# ═══════ まとめ ═══════
{
    echo "# 夜間運転の結果（$OUT）"
    echo
    echo "## Phase 1: stuck_timeout の A/B（$CRITERIA, seed $SEED, n=$N）"
    echo
    echo "- stuck_timeout あり vs なし: **$AB**（比較表: phase1_ab_n${N}.txt）"
    echo "- 3変更（use文言・damage_side・死亡判定）の合計 vs 旧基準線: **$COMBINED**（参考。phase1_combined_vs_old.txt）"
    echo "- Phase 2 のフラグ: \`$FLAGS\`"
    echo "- Phase 1 の EXIT 候補（人間が確認して確定する）:"
    python -c "import sys; sys.path.insert(0, 'tools'); from loop_summary import exit_candidates; from pathlib import Path; c = exit_candidates(Path(sys.argv[1])); print(''.join(f'  - {x}\n' for x in c) or '  - なし')" "$OUT"
    echo
    echo "## Phase 2: criteria 探索"
    echo
    if [ -f "$OUT/loop/summary.md" ]; then sed 's/^# /### /' "$OUT/loop/summary.md"; else echo "（loop/summary.md なし。overnight.log を確認）"; fi
} > "$OUT/SUMMARY.md"
log "✅ まとめ: $OUT/SUMMARY.md"
