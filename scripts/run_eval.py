"""全量评测入口:golden 任务集 × 真实 SUT → 四维记分卡。

流程:加载 golden(入库校验)→ 逐 case 跑 N 遍(pass^k,写操作/对抗类
标注 3)→ 四维 evaluate_case → stdout 摘要 + experiments 记分卡 markdown。

judge 用量:工具锚确定性命中零 LLM;仅 9 个语义锚落 LlmMatcher(binary
JSON,失败保守 False)—— 一轮全量的 judge 成本由标注纪律决定。

用法:TAG_LLM_API_KEY=... uv run python scripts/run_eval.py [--repeats 1] [--limit 15]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from sut_agent.agent import LlmClient
from travelgate.baseline import (
    BaselineMetrics,
    diff_against_baseline,
    save_baseline,
)
from travelgate.judges import LlmMatcher, PlanMatcher
from travelgate.schema import AgentTaskCase, CaseResult, ToolMeta, load_tasks
from travelgate.scorers import evaluate_case

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sut_agent.agent import OpenAiCompatLlm, run_agent  # noqa: E402
from sut_agent.settings import get_settings  # noqa: E402
from sut_agent.tools import build_tool_registry, tool_meta_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "tasks.jsonl"
OUT_PATH = ROOT / "experiments" / "eval-report.md"

DIMS = ("plan", "tools", "trajectory", "outcome")


def run_repetition(
    case: AgentTaskCase,
    llm: LlmClient,
    meta: dict[str, ToolMeta],
    matcher: PlanMatcher,
) -> CaseResult:
    traj = run_agent(message=case.message, user_id=case.user_id, llm=llm)
    return evaluate_case(case, traj, meta, matcher)


def dim_mark(result: CaseResult, dim: str) -> str:
    for d in result.dimensions:
        if d.dimension == dim:
            return "✓" if d.passed else "✗"
    return "?"


def write_report(
    results: list[CaseResult],
    llm_stats: dict,
    judge_stats: dict,
    repeats_mode: str,
    path: Path,
) -> None:
    total = len(results)
    passed = sum(r.passed for r in results)
    by_dim = {d: sum(dim_mark(r, d) == "✓" for r in results) for d in DIMS}
    lines = [
        "# 评测记分卡:四维轨迹评测",
        "",
        f"- 时间:{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 模型:{get_settings().llm_model},temperature=0",
        f"- 任务:{total} 条(golden/tasks.jsonl),每条 {repeats_mode} 遍",
        f"- **case 通过率:{passed}/{total}({passed / total:.0%})**",
        f"- 维度分:{' / '.join(f'{d} {by_dim[d]}/{total}' for d in DIMS)}",
        f"- SUT 用量:llm_calls={llm_stats.get('calls', 0)},"
        f"parse_errors={llm_stats.get('parse_errors', 0)}",
        f"- judge 用量:judge_calls={judge_stats.get('judge_calls', 0)},"
        f"parse_failures={judge_stats.get('parse_failures', 0)}(仅语义锚)",
        "",
        "## 类别切片",
        "",
        "| 类别 | case | pass | " + " | ".join(DIMS) + " |",
        "|---|---|---|---|---|---|---|---|",
    ]
    cats = sorted({r.category for r in results})
    for cat in cats:
        sub = [r for r in results if r.category == cat]
        cp = sum(r.passed for r in sub)
        cd = {d: sum(dim_mark(r, d) == "✓" for r in sub) for d in DIMS}
        lines.append(
            f"| {cat} | {len(sub)} | {cp} | "
            + " | ".join(f"{cd[d]}/{len(sub)}" for d in DIMS)
            + " |"
        )
    lines += [
        "",
        "## 明细",
        "",
        "| case | 类别 | pass | " + " | ".join(DIMS) + " | 失败摘要 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fails = [d for d in r.dimensions if not d.passed]
        brief = ";".join(d.reasons[0][:40] for d in fails) if fails else ""
        lines.append(
            f"| {r.case_id} | {r.category} | {'✓' if r.passed else '✗'} | "
            + " | ".join(dim_mark(r, d) for d in DIMS)
            + f" | {brief} |"
        )
    lines.append("")
    fails = [r for r in results if not r.passed]
    if fails:
        lines.append("## 失败详情")
        for r in fails:
            lines.append(f"\n### {r.case_id}({r.category})")
            lines.append(f"- 回答:「{r.answer[:120]}」")
            for d in r.dimensions:
                if not d.passed:
                    lines.append(f"- **{d.dimension}**:" + ";".join(d.reasons))
    else:
        lines.append("全部通过。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def to_metrics(results: list[CaseResult], model: str) -> BaselineMetrics:
    """CaseResult 列表 → 基线指标(总体/四维/类别三层,小而稳)。"""
    total = len(results)
    cats = sorted({r.category for r in results})
    return BaselineMetrics(
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        sut_model=model,
        pass_rate=round(sum(r.passed for r in results) / total, 4),
        dimension_scores={
            d: round(sum(dim_mark(r, d) == "✓" for r in results) / total, 4)
            for d in DIMS
        },
        per_category_pass_rate={
            c: round(
                sum(r.passed for r in results if r.category == c)
                / max(1, sum(1 for r in results if r.category == c)),
                4,
            )
            for c in cats
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=None,
                        help="统一覆盖每 case 遍数(默认用各 case 的 repeats 标注)")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条(冒烟用)")
    parser.add_argument("--save-baseline", type=Path, default=None,
                        help="把本次指标写入基线文件(认可版落盘)")
    parser.add_argument("--gate", type=Path, default=None,
                        help="对比基线,退化超容差即 exit 1(eval-gated CI 用)")
    parser.add_argument("--tolerance", type=float, default=0.0,
                        help="门禁容差(0-1,须大于多轮重跑方差)")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.llm_api_key:
        raise SystemExit("缺少 TAG_LLM_API_KEY(或 TAG_LLM_BASE_URL/TAG_LLM_MODEL)")

    meta = tool_meta_snapshot(build_tool_registry())
    cases = load_tasks(GOLDEN, meta)
    if args.limit:
        cases = cases[: args.limit]

    llm = OpenAiCompatLlm(settings)
    matcher = LlmMatcher(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    results: list[CaseResult] = []
    for case in cases:
        n = args.repeats if args.repeats is not None else case.repeats
        rep_results = [run_repetition(case, llm, meta, matcher) for _ in range(n)]
        case_result = rep_results[0].model_copy(deep=True)
        case_result.passed = all(r.passed for r in rep_results)  # pass^k
        for i, r in enumerate(rep_results[1:], 2):
            for d, rd in zip(case_result.dimensions, r.dimensions, strict=False):
                if not rd.passed:
                    d.passed = False
                    d.reasons.extend(f"[第{i}遍] {x}" for x in rd.reasons)
        results.append(case_result)
        marks = "".join(dim_mark(case_result, d) for d in DIMS)
        print(f"{case.case_id:<24} {'PASS' if case_result.passed else 'FAIL'}"
              f"  [{marks}] ×{n}")

    passed = sum(r.passed for r in results)
    by_dim = {d: sum(dim_mark(r, d) == "✓" for r in results) for d in DIMS}
    print(f"\ncase 通过率 {passed}/{len(results)}  "
          + "  ".join(f"{d}={by_dim[d]}" for d in DIMS))
    print(f"llm_calls={llm.stats.get('calls', 0)}  "
          f"judge_calls={matcher.stats['judge_calls']}"
          f"(parse_failures={matcher.stats['parse_failures']})")

    write_report(
        results,
        dict(llm.stats),
        dict(matcher.stats),
        str(args.repeats) if args.repeats is not None else "标注遍数(1 或 3)",
        OUT_PATH,
    )
    print(f"记分卡 → {OUT_PATH}")

    if args.save_baseline:
        save_baseline(to_metrics(results, settings.llm_model), args.save_baseline)
        print(f"基线落盘 → {args.save_baseline}")
    if args.gate:
        from travelgate.baseline import load_baseline

        regressions = diff_against_baseline(
            to_metrics(results, settings.llm_model),
            load_baseline(args.gate),
            tolerance=args.tolerance,
        )
        if regressions:
            print("\n⛔ 门禁拦截:对比基线退化 ——")
            for r in regressions:
                print(f"  - {r}")
            raise SystemExit(1)
        print("✅ 门禁通过:无超容差退化")


if __name__ == "__main__":
    main()
