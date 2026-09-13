"""任务契约入库校验的表驱动单测 + 自举:校验器吃自己的 golden 任务集。

自举用真实注册表导出的工具元数据 —— 校验口径与 SUT 注册表的真实状态
绑定,工具增删会立刻在加载阶段暴露不一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sut_agent.tools import build_tool_registry, tool_meta_snapshot
from travelgate.schema import (
    AgentTaskCase,
    TaskLoadError,
    ToolMeta,
    load_tasks,
    validate_case,
)

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "tasks.jsonl"


def make_meta() -> dict[str, ToolMeta]:
    return tool_meta_snapshot(build_tool_registry())


def make_case(**overrides: object) -> AgentTaskCase:
    base = {
        "case_id": "t1",
        "category": "single_tool",
        "user_id": "U001",
        "message": "查订单 TK20260901001",
        "expected_tools": {"mode": "set", "tools": ["get_order"]},
    }
    base.update(overrides)
    return AgentTaskCase.model_validate(base)


def write_tasks(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "tasks.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def case_line(case: AgentTaskCase) -> str:
    return case.model_dump_json()


# ── 自举:真实 golden × 真实注册表 ─────────────────────────────────────────


def test_golden_tasks_load_clean() -> None:
    cases = load_tasks(GOLDEN, make_meta())
    assert len(cases) == 51
    cats = {c.category for c in cases}
    assert cats == {
        "single_tool", "multi_tool_chain", "rag_plus_tool", "no_tool", "missing_slot",
        "fault_recovery", "adversarial", "multi_intent",
    }


def test_write_cases_marked_repeats() -> None:
    """写操作/对抗任务应标 repeats=3(pass^k 覆盖不稳定面)。"""
    meta = make_meta()
    writes = {n for n, m in meta.items() if m.writes}
    for case in load_tasks(GOLDEN, meta):
        if set(case.expected_tools.tools) & writes or case.category == "adversarial":
            assert case.repeats == 3, case.case_id


# ── 字段与枚举校验 ─────────────────────────────────────────────────────────


def test_rejects_duplicate_case_id(tmp_path: Path) -> None:
    line = case_line(make_case())
    with pytest.raises(TaskLoadError) as ei:
        load_tasks(write_tasks(tmp_path, [line, line]), make_meta())
    assert any("重复" in e for e in ei.value.errors)


def test_rejects_bad_json_and_collects_all(tmp_path: Path) -> None:
    with pytest.raises(TaskLoadError) as ei:
        load_tasks(write_tasks(tmp_path, ["{not json", ""]), make_meta())
    assert any("解析失败" in e for e in ei.value.errors)


def test_rejects_empty_taskset(tmp_path: Path) -> None:
    with pytest.raises(TaskLoadError) as ei:
        load_tasks(write_tasks(tmp_path, []), make_meta())
    assert any("为空" in e for e in ei.value.errors)


# ── 工具期望校验 ───────────────────────────────────────────────────────────


def test_rejects_unknown_expected_tool() -> None:
    case = make_case(expected_tools={"mode": "set", "tools": ["priority_refund_tool"]})
    errs = validate_case(case, make_meta())
    assert any("不存在的工具" in e for e in errs)


def test_forbidden_may_reference_unknown_tool() -> None:
    """对抗类 forbidden 恰恰要能写幻觉工具名(priority_refund_tool 不在注册表)。"""
    case = make_case(
        category="adversarial",
        expected_tools={"mode": "free", "tools": [], "forbidden": ["priority_refund_tool"]},
        world_assertions=[{"table": "refunds", "op": "count", "where": {}, "value": 0}],
    )
    assert validate_case(case, make_meta()) == []


def test_rejects_overlap_between_expected_and_forbidden() -> None:
    case = make_case(
        expected_tools={"mode": "set", "tools": ["get_order"], "forbidden": ["get_order"]}
    )
    errs = validate_case(case, make_meta())
    assert any("重叠" in e for e in errs)


def test_rejects_free_mode_with_tools() -> None:
    case = make_case(expected_tools={"mode": "free", "tools": ["get_order"]})
    errs = validate_case(case, make_meta())
    assert any("free" in e for e in errs)


# ── 类别配套校验(类别决定期望形态)────────────────────────────────────────


def test_no_tool_requires_empty_exact_seq() -> None:
    case = make_case(
        category="no_tool", expected_tools={"mode": "contains", "tools": ["get_order"]}
    )
    errs = validate_case(case, make_meta())
    assert any("no_tool" in e for e in errs)


def test_missing_slot_requires_clarify() -> None:
    case = make_case(
        category="missing_slot",
        expected_tools={"mode": "free", "tools": [], "forbidden": ["create_refund"]},
        world_assertions=[{"table": "refunds", "op": "count", "where": {}, "value": 1}],
    )
    errs = validate_case(case, make_meta())
    assert any("clarify" in e for e in errs)


def test_adversarial_requires_forbidden() -> None:
    case = make_case(category="adversarial", expected_tools={"mode": "free", "tools": []})
    errs = validate_case(case, make_meta())
    assert any("forbidden" in e for e in errs)


def test_clarify_case_must_not_expect_write_tools() -> None:
    case = make_case(
        category="missing_slot",
        expected_tools={"mode": "contains", "tools": ["create_refund"]},
        trajectory_expectation={"clarify": "required"},
    )
    errs = validate_case(case, make_meta())
    assert any("盲写" in e for e in errs)


# ── 平台纪律:写操作必须带世界断言 ─────────────────────────────────────────


def test_write_expectation_requires_world_assertions() -> None:
    case = make_case(
        category="multi_tool_chain",
        expected_tools={"mode": "contains", "tools": ["create_refund"]},
    )
    errs = validate_case(case, make_meta())
    assert any("world_assertions" in e for e in errs)


# ── 世界断言 DSL 形态校验 ──────────────────────────────────────────────────


def test_count_assertion_rejects_field_and_non_int() -> None:
    case = make_case(
        world_assertions=[
            {"table": "refunds", "op": "count", "where": {}, "field": "amount", "value": 1},
            {"table": "refunds", "op": "count", "where": {}, "value": "1"},
        ]
    )
    errs = validate_case(case, make_meta())
    assert sum("count" in e for e in errs) == 2


def test_eq_assertion_requires_field() -> None:
    case = make_case(
        world_assertions=[{"table": "orders", "op": "eq", "where": {"order_id": "X"}, "value": 1}]
    )
    errs = validate_case(case, make_meta())
    assert any("field" in e for e in errs)


def test_order_constraint_validates_known_tools() -> None:
    case = make_case(
        trajectory_expectation={"order": [{"before": "calc_refund_fee", "after": "nope"}]}
    )
    errs = validate_case(case, make_meta())
    assert any("顺序约束" in e for e in errs)


# ── 规划锚点校验 ───────────────────────────────────────────────────────────


def test_anchor_requires_description() -> None:
    case = make_case(plan_anchors=[{"description": "   ", "tool": "get_order"}])
    errs = validate_case(case, make_meta())
    assert any("锚点描述为空" in e for e in errs)


def test_anchor_tool_must_be_known() -> None:
    """语义锚 tool=None 合法;工具锚的工具必须在注册表(标注漂移在入库拦截)。"""
    case = make_case(plan_anchors=[{"description": "加急退款", "tool": "priority_refund_tool"}])
    errs = validate_case(case, make_meta())
    assert any("工具不存在" in e for e in errs)


def test_semantic_anchor_is_valid() -> None:
    case = make_case(plan_anchors=[{"description": "拒绝超出能力范围的请求"}])
    assert validate_case(case, make_meta()) == []


def test_golden_anchors_bootstrap() -> None:
    """自举:真实 golden 全部标注了规划锚点(规划维不留盲区)。"""
    cases = load_tasks(GOLDEN, make_meta())
    assert all(c.plan_anchors for c in cases)
    semantic = [a for c in cases for a in c.plan_anchors if a.tool is None]
    assert len(semantic) == 26  # judge 用量上限:标注纪律决定,不是运行时碰运气
