"""结果维评分器表驱动单测:答案关键词 AND + 禁词 + 世界断言 DSL 全算子。

世界断言在构造好的 world 快照 dict 上执行 —— 评分器不碰 SQL,纯数据判定。
"""

from __future__ import annotations

from typing import Any

from travelgate.schema import AgentTaskCase, Trajectory
from travelgate.scorers import score_outcome

WORLD: dict[str, list[dict[str, Any]]] = {
    "orders": [
        {"order_id": "TK1", "status": "refunding", "amount": 288.0},
        {"order_id": "TK2", "status": "paid", "amount": 144.0},
    ],
    "refunds": [
        {"order_id": "TK1", "amount": 288.0, "fee": 0.0},
    ],
    "notifications": [],
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


def make_traj(answer: str = "", world: dict[str, list[dict[str, Any]]] | None = None) -> Trajectory:
    return Trajectory.model_validate({
        "user_id": "U001", "message": "m", "answer": answer, "world": world or {},
    })


# ── 答案关键词 ──────────────────────────────────────────────────────────────


def test_keywords_are_and() -> None:
    case = make_case(answer_keywords=["288", "退"])
    assert score_outcome(case, make_traj("已退 288 元")).passed
    r = score_outcome(case, make_traj("已退 144 元"))
    assert not r.passed and "288" in r.reasons[0]


def test_keywords_normalized_for_whitespace() -> None:
    case = make_case(answer_keywords=["288 元"])
    assert score_outcome(case, make_traj("实退 288元。")).passed


def test_empty_keywords_pass_on_any_answer() -> None:
    assert score_outcome(make_case(), make_traj("")).passed


def test_forbidden_keyword_vetoes() -> None:
    """答案出现编造金额比缺失更严重 —— 禁词一票否决。"""
    case = make_case(
        answer_keywords=["已使用"], answer_forbidden_keywords=["已退款", "退款成功"]
    )
    r = score_outcome(case, make_traj("该订单已使用,退款成功"))
    assert not r.passed
    assert any("禁词" in reason for reason in r.reasons)


# ── 世界断言:eq / ne / count / exists ──────────────────────────────────────


def test_eq_selects_rows_by_where() -> None:
    case = make_case(
        answer_keywords=["288"],
        world_assertions=[
            {"table": "refunds", "op": "eq", "where": {"order_id": "TK1"},
             "field": "amount", "value": 288},
        ],
    )
    assert score_outcome(case, make_traj("288", WORLD)).passed


def test_eq_number_forms_normalized() -> None:
    case = make_case(world_assertions=[
        {"table": "refunds", "op": "eq", "where": {"order_id": "TK1"},
         "field": "amount", "value": "288.0"},
    ])
    assert score_outcome(case, make_traj("", WORLD)).passed


def test_eq_failure_reports_actual_value() -> None:
    case = make_case(world_assertions=[
        {"table": "orders", "op": "eq", "where": {"order_id": "TK2"},
         "field": "status", "value": "refunding"},
    ])
    r = score_outcome(case, make_traj("", WORLD))
    assert not r.passed
    assert "实际 [None, 'paid', 144.0]" not in r.reasons[0]  # 只报 field 列
    assert "'paid'" in r.reasons[0]


def test_ne_passes_when_value_differs() -> None:
    case = make_case(world_assertions=[
        {"table": "orders", "op": "ne", "where": {"order_id": "TK2"},
         "field": "status", "value": "refunding"},
    ])
    assert score_outcome(case, make_traj("", WORLD)).passed


def test_count_asserts_row_count() -> None:
    ok = make_case(world_assertions=[
        {"table": "refunds", "op": "count", "where": {}, "value": 1},
    ])
    assert score_outcome(ok, make_traj("", WORLD)).passed
    bad = make_case(world_assertions=[
        {"table": "refunds", "op": "count", "where": {"order_id": "TK2"}, "value": 1},
    ])
    r = score_outcome(bad, make_traj("", WORLD))
    assert not r.passed and "行数 0 != 期望 1" in r.reasons[0]


def test_exists_asserts_presence_and_absence() -> None:
    present = make_case(world_assertions=[
        {"table": "refunds", "op": "exists", "where": {"order_id": "TK1"},
         "field": "amount", "value": True},
    ])
    assert score_outcome(present, make_traj("", WORLD)).passed
    gone = make_case(world_assertions=[
        {"table": "notifications", "op": "exists", "where": {}, "value": False},
    ])
    assert score_outcome(gone, make_traj("", WORLD)).passed


def test_missing_table_is_config_or_delivery_error() -> None:
    """表缺失 = 断言写错表名,或 SUT 没交付世界快照;两者都必须显式失败。"""
    case = make_case(world_assertions=[
        {"table": "nope", "op": "count", "where": {}, "value": 0},
    ])
    r = score_outcome(case, make_traj("", WORLD))
    assert not r.passed and "缺少表" in r.reasons[0]


def test_no_rows_selected_cannot_assert_field() -> None:
    case = make_case(world_assertions=[
        {"table": "orders", "op": "eq", "where": {"order_id": "TK404"},
         "field": "status", "value": "paid"},
    ])
    r = score_outcome(case, make_traj("", WORLD))
    assert not r.passed and "未选中任何行" in r.reasons[0]
