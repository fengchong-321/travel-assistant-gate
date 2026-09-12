"""FastAPI 服务:每请求一次独立世界执行。

create_app 工厂接收 llm/kb 两个工厂 —— 生产装配真实实现,测试装配假
实现,不做 monkeypatch。评测端(agent_runner)把 /chat 当作 SUT 的
执行入口:请求进、轨迹出。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

from travelgate.schema import Trajectory

from .agent import LlmClient, OpenAiCompatLlm, run_agent
from .knowledge import KnowledgeBase, build_knowledge_base
from .settings import Settings, get_settings
from .tools import build_tool_registry


class ChatRequest(BaseModel):
    user_id: str = Field(description="当前用户 ID,如 U001")
    message: str = Field(description="用户消息")


class ChatResponse(BaseModel):
    answer: str
    trajectory: Trajectory


def create_app(
    llm_factory: Callable[[], LlmClient],
    kb_factory: Callable[[], KnowledgeBase | None] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """装配应用:llm/kb 在此构造一次,请求间复用(世界才是每请求新建)。"""
    cfg = settings or get_settings()
    llm = llm_factory()
    kb = kb_factory() if kb_factory else None
    registry = build_tool_registry(kb.search if kb else None)

    app = FastAPI(
        title="TravelAssistantGate SUT",
        description="被测的门票客服 Agent:每请求一次独立世界执行,返回答案与完整轨迹。",
    )

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        # llm/registry 来自工厂闭包:测试换实现 = 换工厂,无需依赖覆盖
        traj = run_agent(req.message, req.user_id, llm, registry, max_steps=cfg.max_steps)
        return ChatResponse(answer=traj.answer, trajectory=traj)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "model": cfg.llm_model,
            "kb_loaded": kb is not None,
            "kb_chunks": len(kb.chunks) if kb else 0,
            "tools": len(registry),
        }

    @app.get("/tools")
    def tools() -> list[dict[str, object]]:
        return [
            {"name": t.name, "description": t.description, "writes": t.writes, "meta": t.meta}
            for t in registry.values()
        ]

    return app


def _default_llm() -> LlmClient:
    return OpenAiCompatLlm(get_settings())


def _default_kb() -> KnowledgeBase | None:
    cfg = get_settings()
    if not cfg.llm_api_key:
        return None
    from .knowledge import ApiEmbedder  # 在线依赖,延迟导入

    return build_knowledge_base(Path(cfg.kb_dir), ApiEmbedder(cfg))


app = create_app(llm_factory=_default_llm, kb_factory=_default_kb)
