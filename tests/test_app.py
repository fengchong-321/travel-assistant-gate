"""API 层测试:工厂注入 Fake,TestClient 全离线打三个端点。"""

from fastapi.testclient import TestClient

from sut_agent.agent import LlmResponse, LlmToolCall
from sut_agent.app import create_app
from sut_agent.knowledge import build_knowledge_base
from sut_agent.settings import Settings
from tests.test_knowledge import KB_DIR, FakeEmbedder


class FakeLlm:
    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)

    def chat(self, messages, tools):
        if not self.script:
            return LlmResponse(content="(剧本耗尽)")
        return self.script.pop(0)


def make_client(script: list[LlmResponse], with_kb: bool = True) -> TestClient:
    kb = (
        build_knowledge_base(KB_DIR, FakeEmbedder())
        if with_kb
        else None
    )
    app = create_app(
        llm_factory=lambda: FakeLlm(script),
        kb_factory=(lambda: kb) if with_kb else None,
        settings=Settings(max_steps=4),
    )
    return TestClient(app)


class TestChat:
    def test_refund_chain_end_to_end(self):
        client = make_client([
            LlmResponse(tool_calls=[LlmToolCall(
                "calc_refund_fee", {"order_id": "TK20260901001", "user_id": "U001"})]),
            LlmResponse(tool_calls=[LlmToolCall(
                "create_refund", {"order_id": "TK20260901001", "user_id": "U001"})]),
            LlmResponse(content="已提交退款,实退 288 元。"),
        ])
        resp = client.post("/chat", json={"user_id": "U001", "message": "退掉 TK20260901001"})
        assert resp.status_code == 200
        body = resp.json()
        assert "288" in body["answer"]
        traj = body["trajectory"]
        assert [s["name"] for s in traj["steps"]] == ["calc_refund_fee", "create_refund"]
        assert len(traj["world"]["refunds"]) == 2  # 世界终态随响应返回

    def test_kb_injected_into_search_knowledge(self):
        # 知识库经装配注入:search_knowledge 可用且返回假检索结果
        client = make_client([
            LlmResponse(tool_calls=[LlmToolCall(
                "search_knowledge", {"query": "退票手续费", "top_k": 2})]),
            LlmResponse(content="退票手续费分三档……"),
        ])
        resp = client.post("/chat", json={"user_id": "U001", "message": "退票收多少手续费"})
        body = resp.json()
        assert body["trajectory"]["steps"][0]["ok"]
        assert body["trajectory"]["steps"][0]["result"]["hits"]

    def test_missing_fields_rejected_by_validation(self):
        client = make_client([LlmResponse(content="x")])
        resp = client.post("/chat", json={"user_id": "U001"})  # 缺 message
        assert resp.status_code == 422


class TestHealth:
    def test_health_reports_assembly(self):
        client = make_client([LlmResponse(content="x")])
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["kb_loaded"] is True
        assert body["kb_chunks"] > 0
        assert body["tools"] == 9


class TestTools:
    def test_tools_endpoint_lists_registry_with_metadata(self):
        client = make_client([LlmResponse(content="x")])
        tools = client.get("/tools").json()
        names = {t["name"] for t in tools}
        assert "create_refund" in names and "ask_user" in names
        create_refund = next(t for t in tools if t["name"] == "create_refund")
        assert create_refund["writes"] is True
