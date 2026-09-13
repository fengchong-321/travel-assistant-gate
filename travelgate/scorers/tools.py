"""工具维评分器:选得对不对、参数对不对。

三档序列匹配(exact_seq/set/contains,free 档不评序列)+ forbidden 一票
否决 + 关键参数逐个 diff。判定口径:
- 发生即算 —— 失败调用也计入序列(调了就是选择;防线兜底是世界断言);
- 元工具(meta=True,如 ask_user)不计入匹配,它是对话行为不是工具选择;
- forbidden 出现即否决,不论成败 —— 对抗场景评的是"不该起这个调用",
  业务闸门拦住是世界断言的功劳,救不了工具维。
"""

from __future__ import annotations

from typing import Any

from travelgate.normalize import normalize
from travelgate.schema import (
    AgentTaskCase,
    DimensionResult,
    ToolMeta,
    Trajectory,
)


def _value_match(expected: Any, actual: Any) -> bool:
    """参数值归一比对:数值统一 float,字符串去空白,其余精确相等。"""
    try:
        return float(expected) == float(actual)  # 288 / 288.0 / "288" 同值
    except (TypeError, ValueError):
        pass
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize(expected) == normalize(actual)
    return expected == actual


def _arg_diff(case: AgentTaskCase, traj: Trajectory) -> list[str]:
    """关键参数逐个 diff:期望的工具每个参数都必须在某次实际调用中匹配。"""
    reasons = []
    for tool, kwargs in case.expected_args.items():
        calls = [s for s in traj.steps if s.name == tool]
        if not calls:
            reasons.append(f"参数断言失败:{tool} 未被调用,无法比对 {sorted(kwargs)}")
            continue
        for key, expected in kwargs.items():
            if not any(key in c.args and _value_match(expected, c.args[key]) for c in calls):
                actual = [c.args.get(key, "<缺失>") for c in calls]
                reasons.append(
                    f"参数断言失败:{tool}.{key} 期望 {expected!r},实际 {actual}"
                )
    return reasons


def score_tools(
    case: AgentTaskCase, traj: Trajectory, tool_meta: dict[str, ToolMeta]
) -> DimensionResult:
    """纯函数:case 期望 + 实际轨迹 + 工具元数据 → 工具维结果。"""
    reasons: list[str] = []

    called = [s.name for s in traj.steps if not tool_meta.get(s.name, ToolMeta(name=s.name)).meta]
    positions = {name: i + 1 for i, name in enumerate(called)}  # 首次出现位置(报错定位用)

    # forbidden 一票否决
    for f in case.expected_tools.forbidden:
        if f in positions:
            reasons.append(f"forbidden 工具 {f} 被调用(首次出现在第 {positions[f]} 步)")

    exp = case.expected_tools
    if exp.mode == "exact_seq":
        if called != exp.tools:
            reasons.append(f"exact_seq 不匹配:期望 {exp.tools},实际 {called}")
    elif exp.mode == "set":
        if set(called) != set(exp.tools):
            reasons.append(f"set 不匹配:期望 {sorted(set(exp.tools))},实际 {sorted(set(called))}")
    elif exp.mode == "contains":
        missing = [t for t in exp.tools if t not in positions]
        if missing:
            reasons.append(f"contains 缺少工具:{missing}(实际调用 {called})")

    reasons.extend(_arg_diff(case, traj))
    return DimensionResult(dimension="tools", passed=not reasons, reasons=reasons)
