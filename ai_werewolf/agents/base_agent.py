from __future__ import annotations

from abc import ABC, abstractmethod

from ai_werewolf.models.schema import Action, AgentObservation


class BaseAgent(ABC):
    def __init__(self, player_id: str) -> None:
        self.player_id = player_id

    @abstractmethod
    def act(self, observation: AgentObservation) -> Action:
        raise NotImplementedError
