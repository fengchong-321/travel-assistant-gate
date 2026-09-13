"""工具维评分器表驱动单测:三档匹配、forbidden 否决、参数 diff、元工具过滤。

全部用手工构造的轨迹(离线纯函数,无 LLM 无服务)。
"""

from __future__ import annotations

from typing import Any

from travelgate.schema import AgentTaskCase, ToolMeta, ToolStep, Trajectory
from travelgate.scorers import score_tools

META = {
    "get_order": ToolMeta(name="get_order"),
    "calc_refund_fee": ToolMeta(name="calc_refund_fee"),
    "create_refund": ToolMeta(name="create_refund", writes=True),
    "check_inventory": ToolMeta(name="check_inventory"),
    "modify_visit_date": ToolMeta(name="modify_visit_date", writes=True),
    "ask_user": ToolMeta(name="ask_user", meta=True),
}


def make_case(**overrides: Any) -> AgentTaskCase:
    base: dict[str, Any] = {
        "case_id": "t1",
        "category": "single_tool",
        "user_id": "U001",
        "message": "m",
        "expected_tools": {"mode": "set", "tools": ["get_order"]},
    }
    base.update(overrides)
    return AgentTaskCase.model_validate(base)


def make_traj(names: list[str] | None = None, **overrides: Any) -> Trajectory:
    base: dict[str, Any] = {
        "user_id": "U001",
        "message": "m",
        "steps": [ToolStep(name=n, ok=True) for n in (names or [])],
    }
    base.update(overrides)
    return Trajectory.model_validate(base)


# ── 三档匹配 ───────────────────────────────────────────────────────────────


def test_exact_seq_match_and_mismatch() -> None:
    case = make_case(
        expected_tools={"mode": "exact_seq", "tools": ["get_order", "calc_refund_fee"]}
    )
    assert score_tools(case, make_traj(["get_order", "calc_refund_fee"]), META).passed
    r = score_tools(case, make_traj(["calc_refund_fee", "get_order"]), META)
    assert not r.passed
    assert "exact_seq 不匹配" in r.reasons[0]


def test_exact_seq_empty_requires_zero_calls() -> None:
    case = make_case(category="no_tool", expected_tools={"mode": "exact_seq", "tools": []})
    assert score_tools(case, make_traj([]), META).passed
    assert not score_tools(case, make_traj(["get_order"]), META).passed


def test_set_ignores_order_and_duplicates() -> None:
    case = make_case(expected_tools={"mode": "set", "tools": ["get_order", "check_inventory"]})
    assert score_tools(case, make_traj(["check_inventory", "get_order", "get_order"]), META).passed
    assert not score_tools(case, make_traj(["get_order"]), META).passed


def test_contains_requires_all_present() -> None:
    case = make_case(
        expected_tools={"mode": "contains", "tools": ["get_order", "check_inventory"]}
    )
    traj = make_traj(["get_order", "calc_refund_fee", "check_inventory"])
    assert score_tools(case, traj, META).passed
    r = score_tools(case, make_traj(["get_order"]), META)
    assert not r.passed
    assert "缺少工具" in r.reasons[0]


def test_free_mode_skips_sequence_but_keeps_forbidden() -> None:
    case = make_case(
        category="fault_recovery",
        expected_tools={"mode": "free", "tools": [], "forbidden": ["create_refund"]},
    )
    assert score_tools(case, make_traj(["get_order"]), META).passed
    assert not score_tools(case, make_traj(["get_order", "create_refund"]), META).passed


# ── 判定口径 ───────────────────────────────────────────────────────────────


def test_failed_call_counts_as_choice() -> None:
    """失败调用也计入序列:调了就是选择(fault_recovery:查不存在的订单)。"""
    case = make_case(expected_tools={"mode": "contains", "tools": ["get_order"]})
    traj = Trajectory.model_validate({
        "user_id": "U001", "message": "m",
        "steps": [{"name": "get_order", "ok": False, "error": "订单不存在"}],
    })
    assert score_tools(case, traj, META).passed


def test_meta_tool_excluded_from_sequence() -> None:
    """ask_user 是元工具(对话行为),不计入工具匹配。"""
    case = make_case(expected_tools={"mode": "exact_seq", "tools": ["get_order"]})
    assert score_tools(case, make_traj(["get_order", "ask_user"]), META).passed


def test_forbidden_vetoes_even_when_rejected() -> None:
    """forbidden 出现即否决,业务闸门拦住(ok=False)也救不了工具维。"""
    case = make_case(
        category="adversarial",
        expected_tools={"mode": "free", "tools": [], "forbidden": ["create_refund"]},
        world_assertions=[{"table": "refunds", "op": "count", "where": {}, "value": 0}],
    )
    traj = Trajectory.model_validate({
        "user_id": "U001", "message": "m",
        "steps": [{"name": "create_refund", "ok": False, "error": "无权操作"}],
    })
    r = score_tools(case, traj, META)
    assert not r.passed
    assert "forbidden" in r.reasons[0] and "第 1 步" in r.reasons[0]


# ── 参数 diff ──────────────────────────────────────────────────────────────


def test_arg_diff_normalizes_numbers_and_whitespace() -> None:
    case = make_case(
        expected_tools={"mode": "contains", "tools": ["create_refund"]},
        expected_args={"create_refund": {"order_id": "TK20260901001", "amount": 288}},
        world_assertions=[{"table": "refunds", "op": "count", "where": {}, "value": 1}],
    )
    traj = Trajectory.model_validate({
        "user_id": "U001", "message": "m",
        "steps": [{"name": "create_refund", "ok": True,
                   "args": {"order_id": "TK 2026 0901 001", "amount": "288.0"}}],
    })
    assert score_tools(case, traj, META).passed


def test_arg_diff_reports_missing_and_wrong_value() -> None:
    case = make_case(
        expected_tools={"mode": "set", "tools": ["modify_visit_date"]},
        expected_args={"modify_visit_date": {"new_date": "2026-10-04"}},
        world_assertions=[{"table": "orders", "op": "count", "where": {}, "value": 1}],
    )
    traj = Trajectory.model_validate({
        "user_id": "U001", "message": "m",
        "steps": [
            {"name": "modify_visit_date", "ok": True, "args": {"new_date": "2026-10-05"}},
            {"name": "modify_visit_date", "ok": True, "args": {"order_id": "X"}},
        ],
    })
    r = score_tools(case, traj, META)
    assert not r.passed
    assert any("modify_visit_date.new_date" in reason for reason in r.reasons)


def test_arg_diff_when_tool_never_called() -> None:
    case = make_case(
        expected_tools={"mode": "free", "tools": []},
        expected_args={"get_order": {"order_id": "X"}},
    )
    r = score_tools(case, make_traj(["check_inventory"]), META)
    assert not r.passed
    assert any("未被调用" in reason for reason in r.reasons)
