from __future__ import annotations

from abc import ABC, abstractmethod


class ModelProvider(ABC):
    """Minimal LLM provider interface used by LLMAgent.

    Providers should return a string containing one JSON object that can be
    parsed into ai_werewolf.models.schema.Action by output_parser.parse_action_json.
    """

    provider_name: str = "base"
    model_name: str = "unknown"

    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class EchoProvider(ModelProvider):
    """Safe local provider for tests and demos; it does not call external APIs."""

    provider_name = "echo"
    model_name = "echo-local"

    def generate(self, prompt: str) -> str:
        return '{"action_type":"skip","target_player_id":null,"content":null,"reasoning_summary":"EchoProvider fallback output.","confidence":0.1}'
