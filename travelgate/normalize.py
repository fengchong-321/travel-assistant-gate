"""归一化匹配契约:答案关键词比对与工具参数比对共用的文本归一化。

为什么需要:LLM 输出中的空白与句末标点不影响语义(「3 月 31 日」=「3月31日」,
「288 元。」=「288元」),naive 字符串相等会把语义相同的输出判 FAIL。
归一化必须先于一切字符串比对,且只此一处实现 —— 评分器与工具层都从这里
import,保证全链路是同一个契约。
"""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")  # 全部空白(含全角空格、换行、制表符)统一去掉

# 句末标点不影响语义;半角全角都收
_TRAIL_PUNCT = "。．.！!？?；;，,"


def normalize(text: str) -> str:
    """去全部空白;用于关键词包含判断与工具参数字符串比对。"""
    return _WS.sub("", text)


def normalize_answer(text: str) -> str:
    """去全部空白 + 去句末标点;用于答案的精确比对。"""
    return normalize(text).rstrip(_TRAIL_PUNCT)
