"""被测 Agent 配置:环境变量注入(TAG_ 前缀),密钥不落仓库。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAG_")

    # 为空 = 在线功能不可用;离线测试与轨迹回放不受影响
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    embedding_model: str = "embedding-3"
    temperature: float = 0.0  # 评测可复现性的前提
    max_steps: int = 8  # ReAct 步数硬熔断
    kb_dir: str = str(Path(__file__).resolve().parent / "kb")

    @field_validator("llm_base_url", "llm_model", "embedding_model", mode="before")
    @classmethod
    def _empty_env_falls_back_to_default(cls, v: str, info: ValidationInfo) -> str:
        """空环境变量回落默认值。

        CI 里 `TAG_X: ${{ secrets.TAG_X }}` 引用未配置的 secret 会注入空串
        (实踩:eval-gate 首跑 UnsupportedProtocol);.env 留空行同理。
        空串一律视为"未设置"。
        """
        if isinstance(v, str) and not v.strip():
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
