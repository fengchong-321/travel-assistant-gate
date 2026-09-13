"""四维聚合:case 级判定 = plan ∧ tools ∧ trajectory ∧ outcome。"""

from __future__ import annotations

from travelgate.judges.matcher import PlanMatcher
from travelgate.schema import AgentTaskCase, CaseResult, ToolMeta, Trajectory
from travelgate.scorers.outcome import score_outcome
from travelgate.scorers.plan import score_plan
from travelgate.scorers.tools import score_tools
from travelgate.scorers.trajectory import score_trajectory


def evaluate_case(
    case: AgentTaskCase,
    traj: Trajectory,
    tool_meta: dict[str, ToolMeta],
    matcher: PlanMatcher,
) -> CaseResult:
    """一条 golden × 一条轨迹 → 四维结果 + case 级判定。"""
    dimensions = [
        score_plan(case, traj, tool_meta, matcher),
        score_tools(case, traj, tool_meta),
        score_trajectory(case, traj, tool_meta),
        score_outcome(case, traj),
    ]
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        passed=all(d.passed for d in dimensions),
        dimensions=dimensions,
        answer=traj.answer,
    )
