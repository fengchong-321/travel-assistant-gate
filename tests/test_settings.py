"""settings 行为合同:空环境变量视为未设置,回落字段默认值。

来源:CI 里 `TAG_X: ${{ secrets.TAG_X }}` 引用未配置的 secret 会注入空串,
曾覆盖 llm_base_url 默认值导致 openai 客户端 UnsupportedProtocol。
"""

from __future__ import annotations

import pytest

from sut_agent.settings import Settings


def test_empty_base_url_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAG_LLM_BASE_URL", "")
    s = Settings(_env_file=None)
    assert s.llm_base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_nonempty_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAG_LLM_BASE_URL", "https://example.com/v1")
    s = Settings(_env_file=None)
    assert s.llm_base_url == "https://example.com/v1"
