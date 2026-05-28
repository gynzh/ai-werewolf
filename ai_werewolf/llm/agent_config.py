from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_werewolf.llm.openai_compatible_provider import (
    DEFAULT_BASE_URL,
    DEFAULT_JSON_MODE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    OpenAICompatibleConfig,
)


@dataclass(frozen=True, slots=True)
class ResolvedLLMConfig:
    """Per-player LLM provider configuration.

    API keys are available at runtime, but `safe_summary` intentionally avoids
    returning secrets so it can be placed in logs, reviews, or web state.
    """

    player_id: str
    api_key: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    timeout: float
    json_mode: bool
    organization: str | None = None
    profile: str | None = None
    source: str = "global"

    def to_openai_compatible_config(self) -> OpenAICompatibleConfig:
        return OpenAICompatibleConfig(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url.rstrip("/"),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            json_mode=self.json_mode,
            organization=self.organization,
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "json_mode": self.json_mode,
            "organization_set": bool(self.organization),
            "profile": self.profile,
            "source": self.source,
            "api_key_set": bool(self.api_key),
        }


class LLMAgentConfigResolver:
    """Resolve independent LLM configuration for every AI player.

    Precedence, from strongest to weakest:
    1. Player-specific environment variables, e.g. AI_WEREWOLF_LLM_P1_MODEL
    2. `agents.P1` block in --llm-agent-config JSON
    3. Player profile block selected by `agents.P1.profile`
    4. `default_profile` / --llm-agent-profile profile block
    5. `default` block in --llm-agent-config JSON
    6. Global CLI arguments and global environment variables
    """

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        global_overrides: dict[str, Any] | None = None,
        default_profile: str | None = None,
    ) -> None:
        self.path = Path(config_path) if config_path else None
        self.global_overrides = {k: v for k, v in (global_overrides or {}).items() if v is not None}
        self.config_data = self._load_json(self.path)
        self.default_profile = default_profile or self.config_data.get("default_profile")

    @classmethod
    def from_args(cls, args: Any) -> "LLMAgentConfigResolver":
        return cls(
            config_path=getattr(args, "llm_agent_config", None),
            default_profile=getattr(args, "llm_agent_profile", None),
            global_overrides={
                "api_key": getattr(args, "llm_api_key", None),
                "base_url": getattr(args, "llm_base_url", None),
                "model": getattr(args, "llm_model", None),
                "temperature": getattr(args, "llm_temperature", None),
                "max_tokens": getattr(args, "llm_max_tokens", None),
                "timeout": getattr(args, "llm_timeout", None),
                "json_mode": True if getattr(args, "llm_json_mode", False) else None,
            },
        )

    def resolve(self, player_id: str) -> ResolvedLLMConfig:
        pid = player_id.upper()
        default_block = _dict(self.config_data.get("default"))
        profiles = _dict(self.config_data.get("profiles"))
        agents = _dict(self.config_data.get("agents"))
        player_block = _dict(agents.get(pid))

        profile_name = player_block.get("profile") or self.default_profile
        profile_block = _dict(profiles.get(profile_name)) if profile_name else {}
        env_block = self._player_env(pid)
        global_env_block = self._global_env()

        merged: dict[str, Any] = {}
        for block in (
            global_env_block,
            self.global_overrides,
            default_block,
            profile_block,
            player_block,
            env_block,
        ):
            merged.update({key: value for key, value in block.items() if value is not None})

        api_key = self._resolve_api_key(merged)
        if not api_key:
            raise ValueError(
                f"LLM API key is required for {pid}. Set AI_WEREWOLF_LLM_{pid}_API_KEY, "
                "AI_WEREWOLF_LLM_API_KEY, OPENAI_API_KEY, or provide api_key_env in --llm-agent-config."
            )

        source = "global"
        if profile_block:
            source = f"profile:{profile_name}"
        if player_block:
            source = f"agent:{pid}"
        if env_block:
            source = f"env:{pid}"

        return ResolvedLLMConfig(
            player_id=pid,
            api_key=api_key,
            model=str(merged.get("model") or DEFAULT_MODEL),
            base_url=str(merged.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
            temperature=_float(merged.get("temperature"), DEFAULT_TEMPERATURE),
            max_tokens=_int(merged.get("max_tokens"), DEFAULT_MAX_TOKENS),
            timeout=_float(merged.get("timeout"), DEFAULT_TIMEOUT),
            json_mode=_bool(merged.get("json_mode"), DEFAULT_JSON_MODE),
            organization=merged.get("organization") or merged.get("org_id"),
            profile=profile_name,
            source=source,
        )

    def describe(self, player_ids: list[str]) -> dict[str, Any]:
        return {pid: self.resolve(pid).safe_summary() for pid in player_ids}

    def _load_json(self, path: Path | None) -> dict[str, Any]:
        if not path:
            return {}
        if not path.exists():
            raise ValueError(f"LLM agent config file does not exist: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("LLM agent config must be a JSON object")
        return data

    def _resolve_api_key(self, data: dict[str, Any]) -> str | None:
        if data.get("api_key_env"):
            env_value = os.getenv(str(data["api_key_env"]))
            if env_value:
                return env_value
        return data.get("api_key")

    def _player_env(self, player_id: str) -> dict[str, Any]:
        prefixes = [f"AI_WEREWOLF_LLM_{player_id}_", f"WEREWOLF_LLM_{player_id}_"]
        return _collect_env(prefixes)

    def _global_env(self) -> dict[str, Any]:
        data = _collect_env(["AI_WEREWOLF_LLM_", "WEREWOLF_LLM_"])
        data.update(
            {
                "api_key": data.get("api_key") or os.getenv("OPENAI_API_KEY"),
                "model": data.get("model") or os.getenv("OPENAI_MODEL"),
                "base_url": data.get("base_url") or os.getenv("OPENAI_BASE_URL"),
                "organization": data.get("organization") or os.getenv("OPENAI_ORG_ID"),
            }
        )
        return data


def _collect_env(prefixes: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    key_map = {
        "API_KEY": "api_key",
        "API_KEY_ENV": "api_key_env",
        "MODEL": "model",
        "BASE_URL": "base_url",
        "TEMPERATURE": "temperature",
        "MAX_TOKENS": "max_tokens",
        "TIMEOUT": "timeout",
        "JSON_MODE": "json_mode",
        "ORGANIZATION": "organization",
        "ORG_ID": "organization",
    }
    for prefix in prefixes:
        for suffix, name in key_map.items():
            value = os.getenv(prefix + suffix)
            if value is not None:
                result[name] = value
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
