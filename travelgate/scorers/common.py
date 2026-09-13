"""评分器共享的值比对契约:参数 diff 与世界断言共用的归一化比对。

数值统一 float(288 / 288.0 / "288" 同值),字符串去空白,其余精确相等。
"""

from __future__ import annotations

from typing import Any

from travelgate.normalize import normalize


def value_match(expected: Any, actual: Any) -> bool:
    try:
        return float(expected) == float(actual)  # 数值形态漂移归一
    except (TypeError, ValueError):
        pass
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize(expected) == normalize(actual)
    return expected == actual


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """expected 是 actual 的参数子集且值逐个相等(锚点/断言的宽松匹配)。"""
    return all(k in actual and value_match(v, actual[k]) for k, v in expected.items())
