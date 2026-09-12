"""ReAct 循环测试:FakeLlm 脚本化注入,循环逻辑全离线验证。"""

import pytest

from sut_agent.agent import LlmResponse, LlmToolCall, fc_tools_from_registry, run_agent
from sut_agent.tools import build_tool_registry


class FakeLlm:
    """按剧本应答的假客户端;剧本耗尽后返回空内容(防死循环)。"""

    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)
        self.seen_messages: list[int] = []  # 每轮收到的消息数(验证回填)

    def chat(self, messages, tools):
        self.seen_messages.append(len(messages))
        if not self.script:
            return LlmResponse(content="(剧本耗尽)")
        return self.script.pop(0)


def tool_call(name: str, **args) -> LlmToolCall:
    return LlmToolCall(name=name, args=args)


class TestHappyPath:
    def test_refund_chain_produces_trajectory_and_world_change(self):
        # 退票全链:算费 → 建单 → 总结回答
        llm = FakeLlm([
            LlmResponse(tool_calls=[tool_call(
                "calc_refund_fee", order_id="TK20260901001", user_id="U001")]),
            LlmResponse(tool_calls=[tool_call(
                "create_refund", order_id="TK20260901001", user_id="U001")]),
            LlmResponse(content="已为您提交退款申请,免手续费,实退 288 元。"),
        ])
        traj = run_agent("退掉订单 TK20260901001", "U001", llm)
        assert [s.name for s in traj.steps] == ["calc_refund_fee", "create_refund"]
        assert all(s.ok for s in traj.steps)
        assert not traj.hit_max_steps and not traj.asked_user
        assert "288" in traj.answer

        # 世界终态:退款单建了、订单流转了、通知发了
        assert len(traj.world["refunds"]) == 2  # 种子 1 + 新建 1
        order = next(o for o in traj.world["orders"] if o["order_id"] == "TK20260901001")
        assert order["status"] == "refunding"
        assert traj.world["notifications"]

    def test_tool_results_fed_back_to_llm(self):
        # 第二轮 LLM 应看到第一轮的 assistant+tool 消息(4 条:system/user/assistant/tool)
        llm = FakeLlm([
            LlmResponse(tool_calls=[tool_call(
                "get_order", order_id="TK20260901001", user_id="U001")]),
            LlmResponse(content="done"),
        ])
        run_agent("查单", "U001", llm)
        assert llm.seen_messages == [2, 4]


class TestAskUserShortCircuit:
    def test_ask_user_ends_run_with_question_as_answer(self):
        # missing_slot:无订单号 → 追问即终态,不再消耗剩余步数
        llm = FakeLlm([
            LlmResponse(tool_calls=[tool_call("ask_user", question="请问要退哪个订单?")]),
            LlmResponse(content="不应到达这里"),
        ])
        traj = run_agent("把我上次的订单退了", "U001", llm)
        assert traj.asked_user
        assert traj.answer == "请问要退哪个订单?"
        assert len(traj.steps) == 1
        assert len(llm.seen_messages) == 1  # 短路:第二次 chat 没发生


class TestMaxStepsFuse:
    def test_runaway_loop_hit_fuse(self):
        # 失控循环:每轮都想查单 → 熔断收尾,轨迹完整保留
        endless = LlmResponse(tool_calls=[tool_call(
            "get_order", order_id="TK20260901001", user_id="U001")])
        llm = FakeLlm([endless] * 20)
        traj = run_agent("查单", "U001", llm, max_steps=3)
        assert traj.hit_max_steps
        assert len(traj.steps) == 3
        assert "上限" in traj.answer


class TestFailurePathsStayInTrajectory:
    def test_unknown_tool_error_recorded_not_raised(self):
        # 幻觉工具:错误落轨迹,循环继续,LLM 收到错误后正常收尾
        llm = FakeLlm([
            LlmResponse(tool_calls=[tool_call(
                "priority_refund_tool", order_id="TK20260901001")]),
            LlmResponse(content="抱歉,没有加急退款功能,已为您走普通退款流程。"),
        ])
        traj = run_agent("加急退款", "U001", llm)
        assert len(traj.steps) == 1
        assert not traj.steps[0].ok
        assert "不存在" in traj.steps[0].error
        assert "加急" in traj.answer


class TestWorldIsolation:
    def test_each_run_gets_fresh_world(self):
        # 两次执行互不影响:第一次退了 001,第二次的世界里 001 仍是 paid
        llm1 = FakeLlm([
            LlmResponse(tool_calls=[tool_call(
                "create_refund", order_id="TK20260901001", user_id="U001")]),
            LlmResponse(content="已提交退款。"),
        ])
        t1 = run_agent("退 001", "U001", llm1)
        assert len(t1.world["refunds"]) == 2

        llm2 = FakeLlm([
            LlmResponse(tool_calls=[tool_call(
                "get_order", order_id="TK20260901001", user_id="U001")]),
            LlmResponse(content="done"),
        ])
        t2 = run_agent("再查 001", "U001", llm2)
        order = next(o for o in t2.world["orders"] if o["order_id"] == "TK20260901001")
        assert order["status"] == "paid"
        assert len(t2.world["refunds"]) == 1  # 只有种子单


class TestFcSchema:
    def test_registry_to_fc_schema(self):
        registry = build_tool_registry()
        schema = fc_tools_from_registry(registry)
        assert len(schema) == len(registry)
        first = schema[0]["function"]
        assert first["name"] == "get_order"
        assert first["parameters"]["type"] == "object"
        # 元数据(writes/meta)不外泄给模型
        assert "writes" not in first and "meta" not in first


@pytest.mark.parametrize("model_attr", ["meta"])
def test_trajectory_meta_records_model(model_attr):
    llm = FakeLlm([LlmResponse(content="你好,我是门票客服助手。")])
    traj = run_agent("在吗", "U001", llm)
    assert traj.meta["model"] == "FakeLlm"
    assert traj.meta["llm_calls"] == 1
    assert traj.meta["tool_steps"] == 0
