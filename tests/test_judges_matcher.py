"""judge 匹配器单测:纯函数解析(围栏容忍),不碰网络。

parse_verdict 的围栏容忍来自真实首跑教训:glm-4-flash 实测会输出
```json {...} ``` 而无视「只输出 JSON」指令 —— 9 个语义锚全部解析失败
保守 False,plan 维整体误杀。
"""

from __future__ import annotations

from travelgate.judges import AnchorMatcher
from travelgate.judges.matcher import parse_verdict


def test_parses_plain_json() -> None:
    assert parse_verdict('{"covered": true, "evidence": "x"}') == {
        "covered": True, "evidence": "x",
    }


def test_parses_markdown_fenced_json() -> None:
    content = '```json\n{"covered": true, "evidence": "Agent 拒绝了请求"}\n```'
    assert parse_verdict(content) is not None
    assert parse_verdict(content)["covered"] is True


def test_parses_json_with_surrounding_prose() -> None:
    content = '好的,判定如下:{"covered": false, "evidence": "无依据"} 以上。'
    assert parse_verdict(content) == {"covered": False, "evidence": "无依据"}


def test_returns_none_on_no_braces_or_bad_json() -> None:
    assert parse_verdict("covered: true") is None
    assert parse_verdict("") is None
    assert parse_verdict("{not json}") is None
    assert parse_verdict("[1, 2]") is None  # 数组不是判定 dict


def test_anchor_matcher_is_deterministic_no() -> None:
    assert AnchorMatcher().covered(object(), object()) is False  # type: ignore[arg-type]
