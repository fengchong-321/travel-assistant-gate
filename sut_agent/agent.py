"""ReAct 执行循环:消息进 → 工具循环 → 答案 + 轨迹出。

LLM 通过 LlmClient 协议注入:真实实现走 function calling(OpenAI 兼容
接口),测试注入脚本化假客户端 —— 循环逻辑本身全离线可测。这也是协议
适配层:若 D4 实验发现 FC 不稳,只换 LlmClient 实现与消息格式,循环、
工具、轨迹全部不动。

两个确定性设计:
- ask_user 短路:追问即本轮终态(missing_slot 场景的行为锚点);
- max_steps 熔断:超限强制收尾,过程维断言的素材。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel

from travelgate.schema import ToolStep, Trajectory

from .prompts import build_system_prompt
from .settings import Settings
from .tools import ToolDef, build_tool_registry, execute_tool
from .world import create_world, export_world


@dataclass
class LlmToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class LlmResponse:
    content: str | None = None
    tool_calls: list[LlmToolCall] = field(default_factory=list)


class LlmClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LlmResponse: ...


class OpenAiCompatLlm:
    """真实客户端:OpenAI 兼容接口 + function calling,temperature=0。"""

    def __init__(self, settings: Settings):
        self.model_name = settings.llm_model
        # 无 key 时用占位符:构造不炸(服务可启动、可健康检查),真调用才报错
        self._client = OpenAI(
            api_key=settings.llm_api_key or "EMPTY", base_url=settings.llm_base_url
        )
        self._model = settings.llm_model
        self._temperature = settings.temperature

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LlmResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            temperature=self._temperature,
        )
        msg = resp.choices[0].message
        calls: list[LlmToolCall] = []
        for c in msg.tool_calls or []:
            if c.type != "function":
                continue  # 只消费 function calling,custom 工具调用不支持
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                args = {}
            calls.append(LlmToolCall(name=c.function.name, args=args))
        return LlmResponse(content=msg.content, tool_calls=calls)


def fc_tools_from_registry(registry: dict[str, ToolDef]) -> list[dict[str, Any]]:
    """注册表 → function calling 的 tools schema(元数据不外泄给模型)。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in registry.values()
    ]


class _Usage(BaseModel):
    """一次运行的粗略用量观测,进 Trajectory.meta(成本仪表盘的数据源)。"""

    llm_calls: int = 0


def run_agent(
    message: str,
    user_id: str,
    llm: LlmClient,
    registry: dict[str, ToolDef] | None = None,
    max_steps: int = 8,
) -> Trajectory:
    """一次完整执行:独立世界 → ReAct 循环 → 轨迹(含世界终态快照)。"""
    if registry is None:
        registry = build_tool_registry()
    conn = create_world()
    fc_tools = fc_tools_from_registry(registry)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(user_id)},
        {"role": "user", "content": message},
    ]
    steps: list[ToolStep] = []
    answer = ""
    asked_user = False
    hit_max_steps = False
    usage = _Usage()
    stop = False

    for _ in range(max_steps):
        usage.llm_calls += 1
        resp = llm.chat(messages, fc_tools)
        if not resp.tool_calls:
            answer = resp.content or ""
            break

        # 整轮 tool_calls 作为一条 assistant 消息,随后逐个回填 tool 消息
        base = len(steps)
        messages.append({
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {
                    "id": f"call_{base + i}",
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": json.dumps(c.args, ensure_ascii=False),
                    },
                }
                for i, c in enumerate(resp.tool_calls)
            ],
        })
        for i, call in enumerate(resp.tool_calls):
            tr = execute_tool(conn, registry, call.name, call.args)
            steps.append(
                ToolStep(
                    name=call.name, args=call.args, ok=tr.ok,
                    result=tr.data or None, error=tr.error,
                )
            )
            messages.append({
                "role": "tool",
                "tool_call_id": f"call_{base + i}",
                "content": json.dumps(
                    {"ok": tr.ok, "data": tr.data, "error": tr.error}, ensure_ascii=False
                ),
            })
            if call.name == "ask_user":
                # 追问即本轮终态:答案就是追问本身
                answer = tr.data.get("question", "")
                asked_user = True
                stop = True
                break
        if stop:
            break
    else:
        hit_max_steps = True
        answer = "抱歉,该请求处理步骤超出上限,请稍后再试或联系人工客服。"

    return Trajectory(
        user_id=user_id,
        message=message,
        steps=steps,
        answer=answer,
        hit_max_steps=hit_max_steps,
        asked_user=asked_user,
        world=export_world(conn),
        meta={
            "model": getattr(llm, "model_name", type(llm).__name__),
            "llm_calls": usage.llm_calls,
            "tool_steps": len(steps),
        },
    )
