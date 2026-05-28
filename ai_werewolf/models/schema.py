from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Literal
import time
import uuid


class Role(str, Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    GUARD = "guard"
    VILLAGER = "villager"


class Faction(str, Enum):
    WOLVES = "wolves"
    GOOD = "good"


class Phase(str, Enum):
    INIT = "init"
    ROLE_ASSIGNMENT = "role_assignment"
    NIGHT_START = "night_start"
    GUARD_ACTION = "guard_action"
    WEREWOLF_DISCUSSION = "werewolf_discussion"
    WEREWOLF_KILL = "werewolf_kill"
    SEER_CHECK = "seer_check"
    WITCH_ACTION = "witch_action"
    NIGHT_RESOLUTION = "night_resolution"
    DAY_ANNOUNCEMENT = "day_announcement"
    DAY_DISCUSSION = "day_discussion"
    DAY_VOTE = "day_vote"
    EXILE_RESOLUTION = "exile_resolution"
    HUNTER_SHOOT = "hunter_shoot"
    WIN_CHECK = "win_check"
    GAME_END = "game_end"


Visibility = Literal["public", "private", "faction", "system"]


@dataclass
class GameConfig:
    player_count: int = 6
    roles: list[str] = field(default_factory=lambda: [
        Role.WEREWOLF.value,
        Role.WEREWOLF.value,
        Role.SEER.value,
        Role.WITCH.value,
        Role.VILLAGER.value,
        Role.VILLAGER.value,
    ])
    win_mode: str = "kill_side"
    random_seed: int | None = 42
    max_days: int = 10
    enable_witch_save: bool = True
    enable_witch_poison: bool = True
    enable_guard: bool = True
    enable_hunter: bool = True
    tie_policy: str = "no_exile"  # no_exile | random
    reveal_death_role: bool = False
    human_players: list[str] = field(default_factory=list)
    version_label: str = "rule_based_v2"

    def validate(self) -> None:
        if self.player_count != len(self.roles):
            raise ValueError("player_count must equal len(roles)")
        valid_roles = {role.value for role in Role}
        invalid = [role for role in self.roles if role not in valid_roles]
        if invalid:
            raise ValueError(f"unknown role(s): {', '.join(invalid)}; valid: {', '.join(sorted(valid_roles))}")
        if self.roles.count(Role.WEREWOLF.value) < 1:
            raise ValueError("at least one werewolf is required")
        if self.tie_policy not in {"no_exile", "random"}:
            raise ValueError("tie_policy must be 'no_exile' or 'random'")
        if self.win_mode not in {"kill_side", "kill_all"}:
            raise ValueError("win_mode must be 'kill_side' or 'kill_all'")
        for pid in self.human_players:
            if not pid.startswith("P") or not pid[1:].isdigit():
                raise ValueError(f"human player id must look like P1/P2/...: {pid}")


@dataclass
class PlayerState:
    player_id: str
    seat: int
    name: str
    role: str
    faction: str
    alive: bool = True
    death_round: int | None = None
    death_reason: str | None = None
    skill_state: dict[str, Any] = field(default_factory=dict)
    is_human: bool = False

    def public_view(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "seat": self.seat,
            "name": self.name,
            "alive": self.alive,
            "death_round": self.death_round,
            "death_reason": self.death_reason,
            "is_human": self.is_human,
        }


@dataclass
class GameEvent:
    event_id: str
    game_id: str
    timestamp: float
    round_index: int
    day_index: int
    night_index: int
    phase: str
    visibility: Visibility
    visible_to: list[str]
    actor_id: str | None
    event_type: str
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        game_id: str,
        round_index: int,
        day_index: int,
        night_index: int,
        phase: str,
        visibility: Visibility,
        visible_to: list[str],
        actor_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> "GameEvent":
        return cls(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            game_id=game_id,
            timestamp=time.time(),
            round_index=round_index,
            day_index=day_index,
            night_index=night_index,
            phase=phase,
            visibility=visibility,
            visible_to=visible_to,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Action:
    player_id: str
    action_type: str
    target_player_id: str | None = None
    content: str | None = None
    reasoning_summary: str | None = None
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentObservation:
    game_id: str
    player_id: str
    seat: int
    role: str
    faction: str
    phase: str
    round_index: int
    day_index: int
    night_index: int
    alive_players: list[dict[str, Any]]
    dead_players: list[dict[str, Any]]
    public_history: list[dict[str, Any]]
    private_history: list[dict[str, Any]]
    faction_history: list[dict[str, Any]]
    available_actions: list[dict[str, Any]]
    current_task: str


@dataclass
class GameState:
    game_id: str
    config: GameConfig
    phase: str = Phase.INIT.value
    round_index: int = 0
    day_index: int = 0
    night_index: int = 0
    players: dict[str, PlayerState] = field(default_factory=dict)
    votes: dict[str, str] = field(default_factory=dict)
    winner: str | None = None
    win_reason: str | None = None

    def living_players(self) -> list[PlayerState]:
        return [p for p in sorted(self.players.values(), key=lambda x: x.seat) if p.alive]

    def dead_players(self) -> list[PlayerState]:
        return [p for p in sorted(self.players.values(), key=lambda x: x.seat) if not p.alive]

    def living_ids(self) -> list[str]:
        return [p.player_id for p in self.living_players()]

    def living_wolves(self) -> list[PlayerState]:
        return [p for p in self.living_players() if p.role == Role.WEREWOLF.value]

    def living_good(self) -> list[PlayerState]:
        return [p for p in self.living_players() if p.faction == Faction.GOOD.value]

    def living_villagers(self) -> list[PlayerState]:
        return [p for p in self.living_good() if p.role == Role.VILLAGER.value]

    def living_gods(self) -> list[PlayerState]:
        return [p for p in self.living_good() if p.role != Role.VILLAGER.value]
