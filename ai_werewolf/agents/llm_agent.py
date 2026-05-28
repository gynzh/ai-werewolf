from __future__ import annotations

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.llm.output_parser import parse_action_json
from ai_werewolf.llm.prompt_builder import build_agent_prompt
from ai_werewolf.llm.provider_base import ModelProvider
from ai_werewolf.models.schema import Action, AgentObservation


class LLMAgent(BaseAgent):
    """Agent that makes real LLM API calls through a ModelProvider.

    Every LLMAgent owns its provider instance. This lets a game run P1, P2, ...
    with different API keys, base URLs, models, temperatures, or JSON mode.
    """

    def __init__(self, player_id: str, provider: ModelProvider, fallback_agent: BaseAgent | None = None) -> None:
        super().__init__(player_id)
        self.provider = provider
        self.fallback_agent = fallback_agent
        self.call_count = 0
        self.fallback_count = 0

    def act(self, observation: AgentObservation) -> Action:
        prompt = build_agent_prompt(observation)
        self.call_count += 1
        try:
            raw = self.provider.generate(prompt)
            action = parse_action_json(self.player_id, raw)
            action.metadata.update(self._metadata())
            action.metadata["llm_call_count"] = self.call_count
            latency = getattr(self.provider, "last_latency_seconds", None)
            if latency is not None:
                action.metadata["llm_latency_seconds"] = latency
            return action
        except Exception as exc:
            if not self.fallback_agent:
                raise
            self.fallback_count += 1
            action = self.fallback_agent.act(observation)
            action.metadata.update(self._metadata(agent_mode="llm_with_rule_fallback"))
            action.metadata.update(
                {
                    "llm_error": str(exc),
                    "llm_fallback_count": self.fallback_count,
                }
            )
            action.reasoning_summary = f"LLM 调用失败，已回退到规则 Agent：{exc}"
            return action

    def _metadata(self, *, agent_mode: str = "llm") -> dict[str, object]:
        data: dict[str, object] = {
            "agent_mode": agent_mode,
            "provider": getattr(self.provider, "provider_name", self.provider.__class__.__name__),
            "model": getattr(self.provider, "model_name", "unknown"),
        }
        profile = getattr(self.provider, "profile_name", None)
        if profile:
            data["llm_profile"] = profile
        source = getattr(self.provider, "config_source", None)
        if source:
            data["llm_config_source"] = source
        return data
