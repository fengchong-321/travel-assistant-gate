"""规划维评分器表驱动单测:工具锚确定性命中、语义锚落 PlanMatcher、无锚点跳过。

FakeMatcher 注入验证:语义锚的判定权完全在注入的 matcher,评分器只负责
把「未覆盖」写进 reasons —— LLM judge 从不进单测。
"""

from __future__ import annotations

from typing import Any

from travelgate.judges import AnchorMatcher
from travelgate.schema import AgentTaskCase, PlanAnchor, ToolMeta, Trajectory
from travelgate.scorers import score_plan

META = {
    "get_order": ToolMeta(name="get_order"),
    "calc_refund_fee": ToolMeta(name="calc_refund_fee"),
    "create_refund": ToolMeta(name="create_refund", writes=True),
    "ask_user": ToolMeta(name="ask_user", meta=True),
}


class FakeMatcher:
    """可控语义判定:按描述回 True/False,并记录收到的锚点。"""

    def __init__(self, verdicts: dict[str, bool]):
        self.verdicts = verdicts
        self.seen: list[str] = []

    def covered(self, anchor: PlanAnchor, traj: Trajectory) -> bool:
        self.seen.append(anchor.description)
        return self.verdicts[anchor.description]


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


def make_traj(steps: list[dict[str, Any]] | None = None) -> Trajectory:
    return Trajectory.model_validate({
        "user_id": "U001", "message": "m", "steps": steps or [],
    })


# ── 无锚点 / 工具锚 ─────────────────────────────────────────────────────────


def test_no_anchors_skips_pass() -> None:
    r = score_plan(make_case(), make_traj(), META, FakeMatcher({}))
    assert r.passed and "跳过" in r.reasons[0]


def test_tool_anchor_hit_by_name() -> None:
    case = make_case(plan_anchors=[{"description": "查询订单", "tool": "get_order"}])
    traj = make_traj([
        {"name": "get_order", "ok": True, "args": {"order_id": "TK1"}},
    ])
    assert score_plan(case, traj, META, FakeMatcher({})).passed


def test_tool_anchor_miss_reports_uncoved() -> None:
    case = make_case(plan_anchors=[{"description": "查询订单", "tool": "get_order"}])
    r = score_plan(case, make_traj(), META, FakeMatcher({}))
    assert not r.passed
    assert "查询订单" in r.reasons[0] and "get_order" in r.reasons[0]


def test_tool_anchor_with_args_constraint() -> None:
    case = make_case(
        plan_anchors=[{
            "description": "按订单算费", "tool": "calc_refund_fee",
            "args_match": {"order_id": "TK2"},
        }]
    )
    miss = make_traj([
        {"name": "calc_refund_fee", "ok": True, "args": {"order_id": "TK1"}},
    ])
    r = score_plan(case, miss, META, FakeMatcher({}))
    assert not r.passed and "TK2" in r.reasons[0]
    hit = make_traj([
        {"name": "get_order", "ok": True},
        {"name": "calc_refund_fee", "ok": True, "args": {"order_id": "TK2"}},
    ])
    assert score_plan(case, hit, META, FakeMatcher({})).passed


def test_meta_tool_never_satisfies_tool_anchor() -> None:
    """ask_user 是对话行为不是工具选择,不能覆盖工具锚。"""
    case = make_case(plan_anchors=[{"description": "查询订单", "tool": "get_order"}])
    traj = make_traj([{"name": "ask_user", "ok": True, "args": {"q": "订单号?"}}])
    assert not score_plan(case, traj, META, FakeMatcher({})).passed


# ── 语义锚:判定权在注入的 matcher ──────────────────────────────────────────


def test_semantic_anchor_delegates_to_matcher() -> None:
    case = make_case(plan_anchors=[{"description": "拒绝超出能力范围的请求"}])
    yes = FakeMatcher({"拒绝超出能力范围的请求": True})
    no = FakeMatcher({"拒绝超出能力范围的请求": False})
    assert score_plan(case, make_traj(), META, yes).passed
    r = score_plan(case, make_traj(), META, no)
    assert not r.passed and "语义判定" in r.reasons[0]


def test_anchor_matcher_defaults_semantic_to_uncovered() -> None:
    """确定性默认匹配器不认语义锚,明确返回未覆盖(不静默)。"""
    case = make_case(plan_anchors=[{"description": "拒绝越权请求"}])
    r = score_plan(case, make_traj(), META, AnchorMatcher())
    assert not r.passed


def test_mixed_anchors_only_missed_ones_reported() -> None:
    """工具锚命中 + 语义锚 miss = 只报 miss 的那一个(分层定位)。"""
    case = make_case(plan_anchors=[
        {"description": "查询订单", "tool": "get_order"},
        {"description": "如实告知订单不存在"},
    ])
    traj = make_traj([{"name": "get_order", "ok": False, "error": "订单不存在"}])
    fake = FakeMatcher({"如实告知订单不存在": False})
    r = score_plan(case, traj, META, fake)
    assert not r.passed
    assert len(r.reasons) == 1
    assert "如实告知" in r.reasons[0]
    assert fake.seen == ["如实告知订单不存在"]  # 工具锚没进 matcher(零 LLM)
