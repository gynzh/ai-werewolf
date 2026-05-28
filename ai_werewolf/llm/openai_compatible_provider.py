from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ai_werewolf.llm.provider_base import ModelProvider


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 700
DEFAULT_TIMEOUT = 60.0
DEFAULT_JSON_MODE = False


@dataclass(slots=True)
class OpenAICompatibleConfig:
    """Configuration for OpenAI-compatible /v1/chat/completions APIs.

    Environment variables are intentionally accepted in two namespaces:
    - WEREWOLF_LLM_*: project-specific and preferred for this app.
    - OPENAI_*: convenient default for OpenAI-compatible providers.
    """

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = DEFAULT_TIMEOUT
    json_mode: bool = DEFAULT_JSON_MODE
    organization: str | None = None
    extra_headers: dict[str, str] | None = None

    @classmethod
    def from_env(
        cls,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        json_mode: bool | None = None,
        organization: str | None = None,
    ) -> "OpenAICompatibleConfig":
        resolved_key = api_key or os.getenv("AI_WEREWOLF_LLM_API_KEY") or os.getenv("WEREWOLF_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "LLM API key is required. Set AI_WEREWOLF_LLM_API_KEY, WEREWOLF_LLM_API_KEY, or OPENAI_API_KEY, "
                "or pass --llm-api-key when using --agent-mode llm."
            )
        return cls(
            api_key=resolved_key,
            model=model or os.getenv("AI_WEREWOLF_LLM_MODEL") or os.getenv("WEREWOLF_LLM_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            base_url=(base_url or os.getenv("AI_WEREWOLF_LLM_BASE_URL") or os.getenv("WEREWOLF_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            temperature=float(temperature if temperature is not None else os.getenv("AI_WEREWOLF_LLM_TEMPERATURE") or os.getenv("WEREWOLF_LLM_TEMPERATURE") or DEFAULT_TEMPERATURE),
            max_tokens=int(max_tokens if max_tokens is not None else os.getenv("AI_WEREWOLF_LLM_MAX_TOKENS") or os.getenv("WEREWOLF_LLM_MAX_TOKENS") or DEFAULT_MAX_TOKENS),
            timeout=float(timeout if timeout is not None else os.getenv("AI_WEREWOLF_LLM_TIMEOUT") or os.getenv("WEREWOLF_LLM_TIMEOUT") or DEFAULT_TIMEOUT),
            json_mode=_env_bool("AI_WEREWOLF_LLM_JSON_MODE", _env_bool("WEREWOLF_LLM_JSON_MODE", DEFAULT_JSON_MODE)) if json_mode is None else json_mode,
            organization=organization or os.getenv("AI_WEREWOLF_LLM_ORGANIZATION") or os.getenv("WEREWOLF_LLM_ORGANIZATION") or os.getenv("OPENAI_ORG_ID"),
        )


class OpenAICompatibleProvider(ModelProvider):
    """Real HTTP provider for OpenAI-compatible chat completion APIs.

    It uses only Python standard library modules so the project remains runnable
    without mandatory third-party dependencies. Compatible services include the
    OpenAI Chat Completions API and many local/proxy servers that expose
    `/v1/chat/completions`.
    """

    provider_name = "openai-compatible"

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config
        self.model_name = config.model
        self.last_latency_seconds: float | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"

    def generate(self, prompt: str) -> str:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an AI Werewolf game agent. Return exactly one valid JSON object. "
                        "Do not include Markdown fences or any prose outside JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.json_mode:
            body["response_format"] = {"type": "json_object"}

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": "ai-werewolf-agent-team/2.1",
        }
        if self.config.organization:
            headers["OpenAI-Organization"] = self.config.organization
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        request = urllib.request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = _safe_read_error(exc)
            raise RuntimeError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM API connection error: {exc.reason}") from exc
        finally:
            self.last_latency_seconds = time.perf_counter() - started

        data = json.loads(raw)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM API response has unexpected shape: {raw[:500]}") from exc


def _safe_read_error(exc: urllib.error.HTTPError) -> str:
    try:
        text = exc.read().decode("utf-8", errors="replace")
    except Exception:
        text = str(exc)
    return text[:1000]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
