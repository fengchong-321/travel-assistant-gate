"""结果维评分器:答案语义 + 世界状态断言(验证世界,不验证文字)。

答案:keywords 全部包含(AND,归一化后);forbidden_keywords 任一出现即
FAIL(答案出现编造的金额/状态是比缺失更严重的失败)。
世界:断言 DSL 在 world 终态快照上执行 —— 评分器不碰 SQL,纯数据判定,
可离线表驱动单测。
"""

from __future__ import annotations

from typing import Any

from travelgate.normalize import normalize_answer
from travelgate.schema import AgentTaskCase, DimensionResult, Trajectory, WorldAssertion
from travelgate.scorers.common import value_match


def _eval_assertion(wa: WorldAssertion, world: dict[str, list[dict[str, Any]]]) -> str | None:
    """执行单条世界断言;返回 None = 通过,否则返回可定位的失败原因。"""
    rows = world.get(wa.table)
    if rows is None:
        return f"世界快照缺少表 {wa.table}(断言配置错或轨迹未交付世界)"
    selected = [r for r in rows if all(value_match(v, r.get(k)) for k, v in wa.where.items())]

    if wa.op == "count":
        if len(selected) != wa.value:
            return f"{wa.table} where {wa.where} 行数 {len(selected)} != 期望 {wa.value}"
        return None
    if wa.op == "exists":
        if bool(selected) != bool(wa.value):
            return f"{wa.table} where {wa.where} 行{'不存在' if wa.value else '仍存在'}"
        return None

    if not selected:
        return f"{wa.table} where {wa.where} 未选中任何行,无法断言 {wa.field}"
    if wa.field is None:  # count/exists 已返回,这里只剩 eq/ne;防御入库校验漏网
        return f"{wa.op} 断言缺少 field"
    bad = [r for r in selected if value_match(wa.value, r.get(wa.field)) != (wa.op == "eq")]
    if bad:
        actual = [r.get(wa.field) for r in bad]
        return f"{wa.table}.{wa.field} where {wa.where} 期望 {wa.op} {wa.value!r},实际 {actual}"
    return None


def score_outcome(case: AgentTaskCase, traj: Trajectory) -> DimensionResult:
    reasons: list[str] = []

    normalized = normalize_answer(traj.answer)
    missing = [k for k in case.answer_keywords if normalize_answer(k) not in normalized]
    if missing:
        reasons.append(f"答案缺少关键词:{missing}(答案:「{traj.answer[:80]}」)")
    hit_forbidden = [k for k in case.answer_forbidden_keywords if normalize_answer(k) in normalized]
    if hit_forbidden:
        reasons.append(f"答案出现禁词:{hit_forbidden}")

    for wa in case.world_assertions:
        failure = _eval_assertion(wa, traj.world)
        if failure:
            reasons.append(f"世界断言失败:{failure}")

    return DimensionResult(dimension="outcome", passed=not reasons, reasons=reasons)
