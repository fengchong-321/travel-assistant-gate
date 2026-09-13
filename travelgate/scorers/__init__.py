"""四维评分器:plan / tools / trajectory / outcome,全部纯函数(case + trajectory → 结果)。

- tools:三档+free 匹配、forbidden 一票否决、参数逐个 diff
- trajectory:熔断 / 循环 / 追问(missing_slot 行为契约)/ 顺序约束
- plan:锚点优先(零 LLM),语义锚点落 PlanMatcher
- outcome:答案关键词(AND + 禁词)+ 世界断言 DSL(eq/ne/count/exists)
- evaluate_case:四维 AND → case 级判定
"""

from travelgate.scorers.aggregate import evaluate_case
from travelgate.scorers.outcome import score_outcome
from travelgate.scorers.plan import score_plan
from travelgate.scorers.tools import score_tools
from travelgate.scorers.trajectory import score_trajectory

__all__ = [
    "evaluate_case",
    "score_plan",
    "score_tools",
    "score_trajectory",
    "score_outcome",
]
