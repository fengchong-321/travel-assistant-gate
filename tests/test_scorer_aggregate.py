"""四维聚合单测:case 级判定 = plan ∧ tools ∧ trajectory ∧ outcome。

验证维度分解可定位:单维失败只报该维,整体 passed 为 False;这是报告层
「哪个维度掉了分」叙事的合同。
"""

from __future__ import annotations

from typing import Any

from travelgate.judges import AnchorMatcher
from travelgate.schema import AgentTaskCase, ToolMeta, Trajectory
from travelgate.scorers import evaluate_case

META = {
    "get_order": ToolMeta(name="get_order"),
    "create_refund": ToolMeta(name="create_refund", writes=True),
    "ask_user": ToolMeta(name="ask_user", meta=True),
}


class YesMatcher:
    def covered(self, anchor: Any, traj: Trajectory) -> bool:
        return True


def make_case(**overrides: Any) -> AgentTaskCase:
    base: dict[str, Any] = {
        "case_id": "t1",
        "category": "multi_tool_chain",
        "user_id": "U001",
        "message": "退了 TK1",
        "expected_tools": {"mode": "contains", "tools": ["create_refund"]},
        "expected_args": {"create_refund": {"order_id": "TK1"}},
        "world_assertions": [
            {"table": "refunds", "op": "count", "where": {"order_id": "TK1"}, "value": 1},
        ],
        "answer_keywords": ["288"],
    }
    base.update(overrides)
    return AgentTaskCase.model_validate(base)


def good_traj() -> Trajectory:
    return Trajectory.model_validate({
        "user_id": "U001", "message": "退了 TK1",
        "steps": [
            {"name": "create_refund", "ok": True, "args": {"order_id": "TK1"}},
        ],
        "answer": "已退款 288 元",
        "world": {"refunds": [{"order_id": "TK1", "amount": 288.0}]},
    })


def test_all_four_dimensions_present_and_pass() -> None:
    result = evaluate_case(make_case(), good_traj(), META, YesMatcher())
    assert result.passed
    assert [d.dimension for d in result.dimensions] == ["plan", "tools", "trajectory", "outcome"]
    assert all(d.passed for d in result.dimensions)
    assert result.answer == "已退款 288 元"


def test_single_dimension_failure_isolated_and_reported() -> None:
    # 世界没改成:outcome 失败,其余三维全绿 → 分层定位
    traj = good_traj()
    traj.world = {}
    result = evaluate_case(make_case(), traj, META, YesMatcher())
    assert not result.passed
    failed = [d for d in result.dimensions if not d.passed]
    assert [d.dimension for d in failed] == ["outcome"]
    assert "缺少表" in failed[0].reasons[0]


def test_plan_failure_via_anchor_matcher_default() -> None:
    # 语义锚 + 确定性 AnchorMatcher = plan 维失败,但工具/轨迹/结果照常评
    case = make_case(plan_anchors=[{"description": "解释手续费政策"}])
    result = evaluate_case(case, good_traj(), META, AnchorMatcher())
    dims = {d.dimension: d.passed for d in result.dimensions}
    assert dims["plan"] is False
    assert dims["tools"] and dims["trajectory"] and dims["outcome"]


def test_multiple_dimensions_fail_all_reported() -> None:
    # 参数错 + 金额错:工具维与结果维同时掉,两个维度都有可定位 reasons
    case = make_case(expected_args={"create_refund": {"order_id": "TK9"}})
    traj = Trajectory.model_validate({
        "user_id": "U001", "message": "退了 TK1",
        "steps": [{"name": "create_refund", "ok": True, "args": {"order_id": "TK1"}}],
        "answer": "已退款 999 元",
        "world": {"refunds": [{"order_id": "TK1", "amount": 999.0}]},
    })
    result = evaluate_case(case, traj, META, YesMatcher())
    assert not result.passed
    failed = {d.dimension for d in result.dimensions if not d.passed}
    assert failed == {"tools", "outcome"}


def test_case_result_carries_identity_fields() -> None:
    result = evaluate_case(make_case(), good_traj(), META, YesMatcher())
    assert result.case_id == "t1"
    assert result.category == "multi_tool_chain"
