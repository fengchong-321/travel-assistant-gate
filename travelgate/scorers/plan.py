"""规划维评分器:任务拆解是否覆盖关键步骤(意图层,不看顺序不看多余)。

锚点优先:工具锚在轨迹中命中即覆盖,零 LLM 成本;纯语义锚点才落到注入的
PlanMatcher。与工具维的分工 —— 工具维对账"调用的序列精确与否",规划维
只问"任务需要的动作都发生了吗":这是分层定位故事的支点(顺序错/多一步
会掉工具维分,漏步骤才会掉规划维分)。
"""

from __future__ import annotations

from travelgate.judges.matcher import PlanMatcher
from travelgate.schema import AgentTaskCase, DimensionResult, ToolMeta, Trajectory
from travelgate.scorers.common import args_match


def score_plan(
    case: AgentTaskCase,
    traj: Trajectory,
    tool_meta: dict[str, ToolMeta],
    matcher: PlanMatcher,
) -> DimensionResult:
    reasons: list[str] = []

    if not case.plan_anchors:
        return DimensionResult(dimension="plan", passed=True, reasons=["未标注规划锚点,跳过"])

    calls = [
        (s.name, s.args)
        for s in traj.steps
        if not tool_meta.get(s.name, ToolMeta(name=s.name)).meta
    ]
    for anchor in case.plan_anchors:
        if anchor.tool is not None:
            hit = any(n == anchor.tool and args_match(anchor.args_match, a) for n, a in calls)
            if not hit:
                reasons.append(
                    f"锚点未覆盖:{anchor.description}(工具 {anchor.tool} 未命中"
                    + (f",参数 {anchor.args_match}" if anchor.args_match else "")
                    + ")"
                )
        elif not matcher.covered(anchor, traj):
            reasons.append(f"锚点未覆盖:{anchor.description}(语义判定:否)")

    return DimensionResult(dimension="plan", passed=not reasons, reasons=reasons)
