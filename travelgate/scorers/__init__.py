"""四维评分器:plan / tools / trajectory / outcome,全部纯函数(case + trajectory → 结果)。

D5 就位:tools(三档匹配 + forbidden 否决 + 参数 diff)、trajectory(熔断/
循环/追问/顺序)。plan 与 outcome 评分器按日程后续就位,契约已在 schema 定义。
"""

from travelgate.scorers.tools import score_tools
from travelgate.scorers.trajectory import score_trajectory

__all__ = ["score_tools", "score_trajectory"]
