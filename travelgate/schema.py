"""轨迹契约:一次 Agent 执行的全部可观测行为。

由评测平台定义、被测 Agent 遵守 —— 单一事实源:评分器、报告、基线全部
消费这里的结构,SUT 只负责产出它。工具维评分的对象是 steps,过程维看
steps + hit_max_steps/asked_user,结果维消费 answer + world 终态快照。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolStep(BaseModel):
    """一次工具调用:名字、参数、结果。参数 diff 与 forbidden 判定的对象。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class Trajectory(BaseModel):
    """一次执行的完整轨迹:输入、步骤序列、最终回答、世界终态。"""

    user_id: str
    message: str
    steps: list[ToolStep] = Field(default_factory=list)
    answer: str = ""
    hit_max_steps: bool = False  # 步数熔断:过程维断言素材
    asked_user: bool = False  # 以追问收尾:missing_slot 场景判定素材
    world: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)  # model/latency 等运行信息
