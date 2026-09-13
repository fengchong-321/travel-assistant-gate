"""PlanMatcher 匹配器:规划维语义判定的注入点。

- AnchorMatcher:确定性(默认)—— 但它只认工具锚;纯语义锚点超出其
  能力,返回 False 并说明,评分器会把这个事实写进 reasons(不静默);
- LlmMatcher:语义兜底 —— glm-4-flash,temperature=0,binary JSON prompt
  (「轨迹中是否有一步完成了 X?答 {"covered": bool, "evidence": str}」),
  解析失败重试一次,再失败取保守 False 并计入 judge_degraded。

judge 用量控制是设计目标:锚点优先命中即零 LLM 成本,只有纯语义锚点
才落到这里 —— 任务集标注纪律决定 judge 调用量,而不是运行时碰运气。
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from openai import OpenAI

from travelgate.schema import PlanAnchor, Trajectory

_JUDGE_PROMPT = """你是 Agent 轨迹评测的裁判,只做二元判定。

【规划步骤】{description}
【用户任务】{message}
【工具调用序列】{tools}
【Agent 最终回答】{answer}

问题:Agent 的执行是否完成了上述规划步骤?(工具完成或回答中体现皆算完成)
只输出 JSON:{{"covered": true/false, "evidence": "一句话依据"}}"""


class PlanMatcher(Protocol):
    def covered(self, anchor: PlanAnchor, traj: Trajectory) -> bool: ...


class AnchorMatcher:
    """确定性匹配器:无 LLM。语义锚点超能力范围,明确返回未覆盖。"""

    def covered(self, anchor: PlanAnchor, traj: Trajectory) -> bool:
        return False


def parse_verdict(content: str) -> dict[str, Any] | None:
    """解析 judge 回复为 dict;容忍 markdown 围栏与前后闲话(实测 glm-4-flash
    会输出 ```json {...} ```,无视「只输出 JSON」指令)。"""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class LlmMatcher:
    """LLM 语义兜底:binary JSON 输出,失败保守 False。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self._client = OpenAI(api_key=api_key or "EMPTY", base_url=base_url)
        self._model = model
        self.stats: dict[str, int] = {"judge_calls": 0, "parse_failures": 0}

    def _ask(self, anchor: PlanAnchor, traj: Trajectory) -> dict[str, Any] | None:
        prompt = _JUDGE_PROMPT.format(
            description=anchor.description,
            message=traj.message,
            tools=[s.name for s in traj.steps] or "(无)",
            answer=traj.answer or "(无)",
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return parse_verdict(resp.choices[0].message.content or "")

    def covered(self, anchor: PlanAnchor, traj: Trajectory) -> bool:
        self.stats["judge_calls"] += 1
        for attempt in range(2):  # 解析失败重试一次
            data = self._ask(anchor, traj)
            if data is not None and isinstance(data.get("covered"), bool):
                return data["covered"]
            self.stats["parse_failures"] += 1
            if attempt == 0:
                continue
        return False  # 保守判定:judge 失败不放过可能的规划缺失
