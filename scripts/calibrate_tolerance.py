"""门禁容差校准:同一代码跑 N 轮,量指标自然波动,推荐 tolerance。

门禁 tolerance 必须 > 正常波动带,否则拦截噪声;又不能大到放过真实退化。
本脚本跑 N 轮(--limit 子集),输出各指标极差与建议容差(极差向上取
0.05 档),写入/更新 baselines/tolerance.json 供 eval-gate 参考。

用法:TAG_LLM_API_KEY=... uv run python scripts/calibrate_tolerance.py [--rounds 3] [--limit 20]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from travelgate.schema import load_tasks

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sut_agent.judges import LlmMatcher  # noqa: E402

from scripts.run_eval import to_metrics  # noqa: E402
from sut_agent.agent import OpenAiCompatLlm, run_agent  # noqa: E402
from sut_agent.settings import get_settings  # noqa: E402
from sut_agent.tools import build_tool_registry, tool_meta_snapshot  # noqa: E402
from travelgate.scorers import evaluate_case  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "baselines" / "tolerance.json"
DIMS = ("plan", "tools", "trajectory", "outcome")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.llm_api_key:
        raise SystemExit("缺少 TAG_LLM_API_KEY")

    meta = tool_meta_snapshot(build_tool_registry())
    cases = load_tasks(ROOT / "golden" / "tasks.jsonl", meta)[: args.limit]
    llm = OpenAiCompatLlm(settings)
    matcher = LlmMatcher(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    metrics = []
    for i in range(args.rounds):
        results = []
        for case in cases:
            traj = run_agent(message=case.message, user_id=case.user_id, llm=llm)
            results.append(evaluate_case(case, traj, meta, matcher))
        m = to_metrics(results, settings.llm_model)
        metrics.append(m)
        print(f"round {i + 1}: pass_rate={m.pass_rate} "
              + " ".join(f"{d}={m.dimension_scores[d]}" for d in DIMS))

    def spread(key: str, getter) -> tuple[float, float]:
        vals = [getter(m) for m in metrics]
        lo, hi = min(vals), max(vals)
        return hi - lo, math.ceil((hi - lo) / 0.05) * 0.05  # 极差,建议容差(0.05 档向上取整)

    report = {"rounds": args.rounds, "limit": args.limit, "metrics": {}}
    spread_total, rec_total = spread("pass_rate", lambda m: m.pass_rate)
    report["metrics"]["pass_rate"] = {"spread": spread_total, "tolerance": rec_total}
    for d in DIMS:
        s, r = spread(d, lambda m, d=d: m.dimension_scores[d])
        report["metrics"][f"dim:{d}"] = {"spread": s, "tolerance": r}
    for c in sorted({c for m in metrics for c in m.per_category_pass_rate}):
        s, r = spread(c, lambda m, c=c: m.per_category_pass_rate.get(c, 0.0))
        report["metrics"][f"cat:{c}"] = {"spread": s, "tolerance": r}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n波动带 → {OUT_PATH}")
    for k, v in report["metrics"].items():
        print(f"  {k:<28} 极差 {v['spread']:.3f} → 建议容差 {v['tolerance']:.2f}")


if __name__ == "__main__":
    main()
