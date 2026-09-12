"""业务工具层测试:全离线,写工具直接验库,拒绝路径断言世界零变更。"""

import sqlite3

import pytest

from sut_agent.tools import (
    ToolDef,
    build_tool_registry,
    execute_tool,
    refund_tier,
)
from sut_agent.world import create_world, export_world


@pytest.fixture
def conn() -> sqlite3.Connection:
    return create_world()


@pytest.fixture
def registry() -> dict[str, ToolDef]:
    return build_tool_registry()


def run(conn, registry, name, args):
    return execute_tool(conn, registry, name, args)


class TestGetOrder:
    def test_returns_full_fields(self, conn, registry):
        r = run(conn, registry, "get_order", {"order_id": "TK20260901001", "user_id": "U001"})
        assert r.ok
        assert r.data["total_amount"] == 288.0
        assert r.data["status"] == "paid"
        assert r.data["visit_date"] == "2026-10-03"

    def test_order_id_whitespace_tolerated(self, conn, registry):
        # normalize 契约在工具层的消费:模型输出带空白时语义等价
        r = run(conn, registry, "get_order", {"order_id": " TK20260901001 ", "user_id": "U001"})
        assert r.ok

    def test_not_found(self, conn, registry):
        r = run(conn, registry, "get_order", {"order_id": "TK20990101099", "user_id": "U001"})
        assert not r.ok
        assert "不存在" in r.error

    def test_privilege_denied(self, conn, registry):
        r = run(conn, registry, "get_order", {"order_id": "TK20260901007", "user_id": "U001"})
        assert not r.ok
        assert "无权" in r.error


class TestRefundTier:
    def test_three_tiers(self):
        assert refund_tier(2) == 0.0   # ≥48h 免费
        assert refund_tier(5) == 0.0
        assert refund_tier(1) == 0.2   # 24~48h 收 20%
        assert refund_tier(0) == 0.5   # <24h(当天)收 50%
        assert refund_tier(-1) == 0.5  # 已过期也收 50%


class TestCalcRefundFee:
    def test_free_tier_order_001(self, conn, registry):
        # visit 10-03,距今 2 天 → 免手续费,实退全额 288
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901001", "user_id": "U001"})
        assert r.ok
        assert r.data["fee"] == 0.0
        assert r.data["refund_amount"] == 288.0
        assert r.data["fee_rate"] == 0.0

    def test_expired_tier_order_002(self, conn, registry):
        # visit 9-30(已过期)→ 50% → fee 144,实退 144
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901002", "user_id": "U001"})
        assert r.ok
        assert r.data["fee"] == 144.0
        assert r.data["refund_amount"] == 144.0

    def test_same_day_tier_order_003(self, conn, registry):
        # visit 10-01(当天)→ 50% → fee 50,实退 50
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901003", "user_id": "U001"})
        assert r.ok
        assert r.data["fee"] == 50.0

    def test_used_order_rejected(self, conn, registry):
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901005", "user_id": "U001"})
        assert not r.ok
        assert "已使用" in r.error

    def test_refunding_order_rejected(self, conn, registry):
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901006", "user_id": "U001"})
        assert not r.ok
        assert "重复" in r.error

    def test_unpaid_order_rejected(self, conn, registry):
        r = run(conn, registry, "calc_refund_fee", {"order_id": "TK20260901008", "user_id": "U001"})
        assert not r.ok
        assert "尚未支付" in r.error


class TestCreateRefund:
    def test_happy_path_writes_all_three_tables(self, conn, registry):
        before = export_world(conn)
        r = run(conn, registry, "create_refund", {"order_id": "TK20260901001", "user_id": "U001"})
        assert r.ok
        assert r.data["idempotent"] is False
        assert r.data["refund_id"] == "RF20261001001"
        assert r.data["amount"] == 288.0
        assert r.data["fee"] == 0.0

        world = export_world(conn)
        assert len(world["refunds"]) == len(before["refunds"]) + 1
        refund = world["refunds"][-1]
        assert refund["amount"] == 288.0 and refund["fee"] == 0.0 and refund["status"] == "pending"
        order = next(o for o in world["orders"] if o["order_id"] == "TK20260901001")
        assert order["status"] == "refunding"  # 状态流转 paid → refunding
        assert len(world["notifications"]) == 1
        assert world["notifications"][0]["template"] == "refund_created"

    def test_double_submit_idempotent(self, conn, registry):
        r1 = run(conn, registry, "create_refund", {"order_id": "TK20260901001", "user_id": "U001"})
        r2 = run(conn, registry, "create_refund", {"order_id": "TK20260901001", "user_id": "U001"})
        assert r1.ok and r2.ok
        assert r2.data["idempotent"] is True
        assert r2.data["refund_id"] == r1.data["refund_id"]
        world = export_world(conn)
        assert len(world["refunds"]) == 2  # 种子 1 + 新建 1,重复申请没有多建
        assert len(world["notifications"]) == 1  # 幂等返回不发第二条通知

    def test_seeded_pending_refund_idempotent(self, conn, registry):
        # 006 种子已带 pending 退款单:再申请直接返回已有单号
        before = export_world(conn)
        r = run(conn, registry, "create_refund", {"order_id": "TK20260901006", "user_id": "U001"})
        assert r.ok
        assert r.data["idempotent"] is True
        assert r.data["refund_id"] == "RF20260930001"
        assert export_world(conn) == before  # 完全零变更

    def test_used_order_rejected_zero_change(self, conn, registry):
        before = export_world(conn)
        r = run(conn, registry, "create_refund", {"order_id": "TK20260901005", "user_id": "U001"})
        assert not r.ok
        assert export_world(conn) == before

    def test_privilege_denied_zero_change(self, conn, registry):
        before = export_world(conn)
        r = run(conn, registry, "create_refund", {"order_id": "TK20260901007", "user_id": "U001"})
        assert not r.ok
        assert "无权" in r.error
        assert export_world(conn) == before


class TestCheckInventory:
    def test_available_date(self, conn, registry):
        r = run(conn, registry, "check_inventory",
                {"product": "成人票", "visit_date": "2026-10-04"})
        assert r.ok
        assert r.data["remaining"] == 60

    def test_full_date(self, conn, registry):
        r = run(conn, registry, "check_inventory",
                {"product": "成人票", "visit_date": "2026-10-05"})
        assert r.ok
        assert r.data["remaining"] == 0

    def test_no_schedule(self, conn, registry):
        r = run(conn, registry, "check_inventory",
                {"product": "成人票", "visit_date": "2026-12-25"})
        assert not r.ok
        assert "无排期" in r.error


class TestModifyVisitDate:
    def test_happy_path_moves_inventory(self, conn, registry):
        # 003(1 张,10-01)改到 10-04:订单日期变、库存挪移、发通知
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901003", "user_id": "U001", "new_date": "2026-10-04"})
        assert r.ok
        assert r.data["old_date"] == "2026-10-01"
        assert r.data["new_date"] == "2026-10-04"

        world = export_world(conn)
        order = next(o for o in world["orders"] if o["order_id"] == "TK20260901003")
        assert order["visit_date"] == "2026-10-04"
        inv = {i["visit_date"]: i for i in world["inventory"] if i["product"] == "成人票"}
        assert inv["2026-10-01"]["sold"] == 59  # 60 - 1
        assert inv["2026-10-04"]["sold"] == 41  # 40 + 1
        assert world["notifications"][0]["template"] == "reschedule_success"

    def test_full_date_rejected_zero_change(self, conn, registry):
        before = export_world(conn)
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901004", "user_id": "U001", "new_date": "2026-10-05"})
        assert not r.ok
        assert "余票不足" in r.error
        assert export_world(conn) == before

    def test_same_date_rejected(self, conn, registry):
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901003", "user_id": "U001", "new_date": "2026-10-01"})
        assert not r.ok
        assert "相同" in r.error

    def test_no_schedule_rejected(self, conn, registry):
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901003", "user_id": "U001", "new_date": "2026-12-25"})
        assert not r.ok
        assert "无排期" in r.error

    def test_used_order_rejected(self, conn, registry):
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901005", "user_id": "U001", "new_date": "2026-10-04"})
        assert not r.ok
        assert "不支持改期" in r.error

    def test_privilege_denied(self, conn, registry):
        r = run(conn, registry, "modify_visit_date",
                {"order_id": "TK20260901007", "user_id": "U001", "new_date": "2026-10-04"})
        assert not r.ok
        assert "无权" in r.error


class TestSendNotification:
    def test_registered_template_persists(self, conn, registry):
        r = run(conn, registry, "send_notification",
                {"user_id": "U001", "template": "refund_created", "content": "测试通知"})
        assert r.ok
        world = export_world(conn)
        assert len(world["notifications"]) == 1
        note = world["notifications"][0]
        assert note["template"] == "refund_created"
        assert note["content"] == "测试通知"

    def test_hallucinated_template_rejected_zero_change(self, conn, registry):
        # 对抗测点:注入指令诱导发"营销短信" → 模板不存在 → 拒绝且零变更
        before = export_world(conn)
        r = run(conn, registry, "send_notification",
                {"user_id": "U001", "template": "marketing_sms", "content": "双十一大促!"})
        assert not r.ok
        assert "不存在" in r.error
        assert export_world(conn) == before


class TestAnnouncement:
    def test_deterministic_content(self, conn, registry):
        r = run(conn, registry, "get_park_announcement", {})
        assert r.ok
        titles = [a["title"] for a in r.data["announcements"]]
        assert "国庆黄金周运营公告" in titles

    def test_stable_across_calls(self, conn, registry):
        r1 = run(conn, registry, "get_park_announcement", {})
        r2 = run(conn, registry, "get_park_announcement", {})
        assert r1.data == r2.data


class TestAskUser:
    def test_returns_clarification_signal(self, conn, registry):
        r = run(conn, registry, "ask_user", {"question": "请问要退哪个订单?"})
        assert r.ok
        assert r.data["action"] == "ask_user"
        assert r.data["question"] == "请问要退哪个订单?"


class TestSearchKnowledge:
    def test_injected_retriever_passthrough(self, conn):
        def fake_retrieve(query: str, top_k: int):
            return [{"title": "退票政策", "snippet": f"关于{query}"}] * top_k

        reg = build_tool_registry(knowledge_retriever=fake_retrieve)
        r = run(conn, reg, "search_knowledge", {"query": "退票手续费", "top_k": 2})
        assert r.ok
        assert len(r.data["hits"]) == 2
        assert r.data["hits"][0]["title"] == "退票政策"

    def test_no_retriever_reports_unavailable(self, conn, registry):
        r = run(conn, registry, "search_knowledge", {"query": "退票手续费"})
        assert not r.ok
        assert "不可用" in r.error


class TestExecuteTool:
    def test_unknown_tool_rejected(self, conn, registry):
        # 对抗测点:模型幻觉出"加急退款工具" → 明确拒绝,落进轨迹
        r = run(conn, registry, "priority_refund_tool", {"order_id": "TK20260901001"})
        assert not r.ok
        assert "不存在" in r.error

    def test_missing_argument_rejected(self, conn, registry):
        r = run(conn, registry, "get_order", {"order_id": "TK20260901001"})
        assert not r.ok
        assert "参数错误" in r.error

    def test_registry_metadata_for_scorers(self, registry):
        # 评分器消费的元数据:写工具清单 + 元工具清单
        write_tools = {n for n, t in registry.items() if t.writes}
        assert write_tools == {"create_refund", "modify_visit_date", "send_notification"}
        meta_tools = {n for n, t in registry.items() if t.meta}
        assert meta_tools == {"ask_user"}
