"""过程维评分器:执行过程对不对。

子检查(各自独立 pass/fail,任一失败即维度失败):
- 熔断:hit_max_steps 且期望 forbid → 失败(熔断是兜底不是正常路径);
- 循环:相同 (工具, 归一化参数) 的重复调用 = 原地打转;
- 追问:missing_slot 场景必须以追问收尾且零盲调写工具 —— 口径按 D4 实验
  结论定为行为契约:追问走 ask_user 工具或答案含追问语义皆可,底线是不
  猜参数盲调写工具(那才是灾难);
- 顺序:before 的首次调用必须早于 after(先算费后建单、先查后写)。
"""

from __future__ import annotations

from travelgate.normalize import normalize, normalize_answer
from travelgate.schema import (
    DEFAULT_CLARIFY_KEYWORDS,
    AgentTaskCase,
    DimensionResult,
    ToolMeta,
    Trajectory,
)


def _loop_check(traj: Trajectory) -> list[str]:
    seen: set[tuple[str, str]] = set()
    reasons = []
    for i, s in enumerate(traj.steps, 1):
        key = (s.name, normalize(str(sorted(s.args.items(), key=lambda kv: kv[0]))))
        if key in seen:
            reasons.append(f"循环调用:第 {i} 步 {s.name} 与此前某步参数完全相同")
        seen.add(key)
    return reasons


def _clarify_check(
    case: AgentTaskCase, traj: Trajectory, tool_meta: dict[str, ToolMeta]
) -> list[str]:
    reasons = []
    write_tools = {n for n, m in tool_meta.items() if m.writes}
    blind = [f"{s.name}(第 {i} 步)" for i, s in enumerate(traj.steps, 1) if s.name in write_tools]
    if blind:
        reasons.append(f"缺槽位盲调写工具:{blind} —— 关键信息不足时期望追问而非带猜调用")

    keywords = tuple(case.trajectory_expectation.clarify_keywords or DEFAULT_CLARIFY_KEYWORDS)
    if not traj.asked_user:
        normalized = normalize_answer(traj.answer)
        if not any(k in normalized for k in keywords):
            reasons.append(
                f"未以追问收尾:asked_user=False 且答案不含追问语义关键词 {list(keywords)}"
            )
    return reasons


def _order_check(case: AgentTaskCase, traj: Trajectory) -> list[str]:
    reasons = []
    called = [s.name for s in traj.steps]
    for oc in case.trajectory_expectation.order:
        if oc.before not in called or oc.after not in called:
            reasons.append(f"顺序约束 {oc.before}→{oc.after} 未满足:两者未都被调用(实际 {called})")
        elif called.index(oc.before) > called.index(oc.after):
            reasons.append(f"顺序约束 {oc.before}→{oc.after} 被违反:{oc.after} 先于 {oc.before}")
    return reasons


def score_trajectory(
    case: AgentTaskCase, traj: Trajectory, tool_meta: dict[str, ToolMeta]
) -> DimensionResult:
    """纯函数:case 过程期望 + 实际轨迹 → 过程维结果。"""
    reasons: list[str] = []
    exp = case.trajectory_expectation

    if exp.fuse == "forbid" and traj.hit_max_steps:
        reasons.append("触发步数熔断(hit_max_steps=True):任务未在步数上限内完成")

    if exp.no_loop:
        reasons.extend(_loop_check(traj))

    if exp.clarify == "required":
        reasons.extend(_clarify_check(case, traj, tool_meta))

    reasons.extend(_order_check(case, traj))
    return DimensionResult(dimension="trajectory", passed=not reasons, reasons=reasons)
