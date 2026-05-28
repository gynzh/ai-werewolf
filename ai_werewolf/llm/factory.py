from __future__ import annotations

import os

from ai_werewolf.llm.openai_compatible_provider import OpenAICompatibleConfig, OpenAICompatibleProvider
from ai_werewolf.llm.provider_base import ModelProvider


def build_openai_compatible_provider(
    *,
    api_key_env: str = "AI_WEREWOLF_LLM_API_KEY",
    base_url: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    retries: int | None = None,  # kept for CLI compatibility; stdlib provider is single request
) -> ModelProvider:
    api_key = os.getenv(api_key_env)
    # Support both the newly documented AI_WEREWOLF_* env and the provider's WEREWOLF_/OPENAI_ aliases.
    config = OpenAICompatibleConfig.from_env(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        json_mode=True,
    )
    return OpenAICompatibleProvider(config)
