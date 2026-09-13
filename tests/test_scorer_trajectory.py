"""过程维评分器表驱动单测:熔断、循环、追问、顺序约束。"""

from __future__ import annotations

from typing import Any

from travelgate.schema import AgentTaskCase, ToolMeta, Trajectory
from travelgate.scorers import score_trajectory

META = {
    "get_order": ToolMeta(name="get_order"),
    "calc_refund_fee": ToolMeta(name="calc_refund_fee"),
    "create_refund": ToolMeta(name="create_refund", writes=True),
    "ask_user": ToolMeta(name="ask_user", meta=True),
}


def make_case(**overrides: Any) -> AgentTaskCase:
    base: dict[str, Any] = {
        "case_id": "t1",
        "category": "single_tool",
        "user_id": "U001",
        "message": "m",
        "expected_tools": {"mode": "free", "tools": []},
    }
    base.update(overrides)
    return AgentTaskCase.model_validate(base)


def make_traj(**overrides: Any) -> Trajectory:
    base: dict[str, Any] = {"user_id": "U001", "message": "m"}
    base.update(overrides)
    return Trajectory.model_validate(base)


# ── 熔断 ───────────────────────────────────────────────────────────────────


def test_fuse_fails_when_forbidden() -> None:
    case = make_case()
    traj = make_traj(hit_max_steps=True, answer="抱歉,超出步数上限")
    r = score_trajectory(case, traj, META)
    assert not r.passed
    assert any("熔断" in reason for reason in r.reasons)


def test_fuse_allowed_passes() -> None:
    case = make_case(trajectory_expectation={"fuse": "allow"})
    assert score_trajectory(case, make_traj(hit_max_steps=True), META).passed


# ── 循环 ───────────────────────────────────────────────────────────────────


def test_loop_detected_on_identical_call() -> None:
    case = make_case()
    step = {"name": "get_order", "ok": False, "error": "网络抖动",
            "args": {"order_id": "TK20260901001"}}
    traj = make_traj(steps=[step, step])
    r = score_trajectory(case, traj, META)
    assert not r.passed
    assert any("循环" in reason for reason in r.reasons)


def test_same_tool_different_args_is_not_loop() -> None:
    case = make_case()
    traj = make_traj(steps=[
        {"name": "get_order", "ok": True, "args": {"order_id": "TK20260901001"}},
        {"name": "get_order", "ok": True, "args": {"order_id": "TK20260901002"}},
    ])
    assert score_trajectory(case, traj, META).passed


def test_loop_check_disabled() -> None:
    case = make_case(trajectory_expectation={"no_loop": False})
    step = {"name": "get_order", "ok": True, "args": {"order_id": "X"}}
    assert score_trajectory(case, make_traj(steps=[step, step]), META).passed


# ── 追问(missing_slot 契约,按 D4 实验口径)──────────────────────────────


def _clarify_case(**extra: Any) -> AgentTaskCase:
    base: dict[str, Any] = {
        "case_id": "t1",
        "category": "missing_slot",
        "user_id": "U001",
        "message": "把我上次的订单退了",
        "expected_tools": {"mode": "free", "tools": [], "forbidden": ["create_refund"]},
        "trajectory_expectation": {"clarify": "required"},
        "world_assertions": [{"table": "refunds", "op": "count", "where": {}, "value": 0}],
    }
    base.update(extra)
    return AgentTaskCase.model_validate(base)


def test_clarify_passes_via_ask_user_short_circuit() -> None:
    traj = make_traj(asked_user=True, answer="请问您的订单号是多少?")
    assert score_trajectory(_clarify_case(), traj, META).passed


def test_clarify_passes_via_text_question_semantics() -> None:
    """D4 结论:文字追问也算追问(语用现实),底线是不盲调写工具。"""
    traj = make_traj(answer="好的,请提供一下您的订单号,我帮您办理。")
    assert score_trajectory(_clarify_case(), traj, META).passed


def test_clarify_fails_on_blind_write() -> None:
    traj = make_traj(steps=[
        {"name": "create_refund", "ok": False, "error": "订单不存在",
         "args": {"order_id": "TK20260901001"}},
    ], answer="请提供订单号")
    r = score_trajectory(_clarify_case(), traj, META)
    assert not r.passed
    assert any("盲调写工具" in reason for reason in r.reasons)


def test_clarify_fails_without_question_semantics() -> None:
    traj = make_traj(answer="您的退款已提交,请耐心等待。")
    r = score_trajectory(_clarify_case(), traj, META)
    assert any("追问" in reason for reason in r.reasons)


def test_clarify_keywords_overridable() -> None:
    case = _clarify_case(trajectory_expectation={
        "clarify": "required", "clarify_keywords": ["单号"],
    })
    assert score_trajectory(case, make_traj(answer="请提供单号"), META).passed


def test_clarify_keywords_ignore_punctuation_forms() -> None:
    """D4 全半角之坑:判定用语义关键词,答案里全角问号不干扰。"""
    traj = make_traj(answer="方便告诉我订单号吗??")
    assert score_trajectory(_clarify_case(), traj, META).passed


# ── 顺序约束 ───────────────────────────────────────────────────────────────


def test_order_constraint_satisfied() -> None:
    case = make_case(trajectory_expectation={
        "order": [{"before": "calc_refund_fee", "after": "create_refund"}]
    })
    traj = make_traj(steps=[
        {"name": "get_order", "ok": True},
        {"name": "calc_refund_fee", "ok": True},
        {"name": "create_refund", "ok": True},
    ])
    assert score_trajectory(case, traj, META).passed


def test_order_constraint_violated() -> None:
    case = make_case(trajectory_expectation={
        "order": [{"before": "calc_refund_fee", "after": "create_refund"}]
    })
    traj = make_traj(steps=[
        {"name": "create_refund", "ok": True},
        {"name": "calc_refund_fee", "ok": True},
    ])
    r = score_trajectory(case, traj, META)
    assert any("被违反" in reason for reason in r.reasons)


def test_order_constraint_not_both_called() -> None:
    case = make_case(trajectory_expectation={
        "order": [{"before": "calc_refund_fee", "after": "create_refund"}]
    })
    r = score_trajectory(case, make_traj(steps=[{"name": "get_order", "ok": True}]), META)
    assert any("未满足" in reason for reason in r.reasons)


def test_multiple_reasons_reported_together() -> None:
    """多个子检查同时失败,reasons 全部落盘(可定位)。"""
    case = make_case(trajectory_expectation={
        "order": [{"before": "get_order", "after": "calc_refund_fee"}]
    })
    step = {"name": "get_order", "ok": True}
    traj = make_traj(hit_max_steps=True, steps=[step, step])
    r = score_trajectory(case, traj, META)
    assert not r.passed
    assert len(r.reasons) >= 2
