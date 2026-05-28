from __future__ import annotations

import random
import uuid
from collections import Counter
from pathlib import Path
from typing import Callable

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.agents.human_agent import ConsoleHumanAgent
from ai_werewolf.agents.rule_based_agent import RuleBasedAgent
from ai_werewolf.logging.event_store import EventStore
from ai_werewolf.models.schema import Action, Faction, GameConfig, GameEvent, GameState, Phase, PlayerState, Role
from ai_werewolf.rules.actions import ActionValidator
from ai_werewolf.rules.roles import faction_of, role_name_cn
from ai_werewolf.visibility.visibility_manager import LeakChecker, VisibilityManager

AgentFactory = Callable[[str, int | None], BaseAgent]


class GameEngine:
    """Complete local game engine for AI Werewolf.

    The engine owns GameState and is the only component allowed to access hidden
    truth. Agents only receive filtered AgentObservation objects.
    """

    def __init__(
        self,
        config: GameConfig | None = None,
        event_store: EventStore | None = None,
        agent_factory: AgentFactory | None = None,
        enable_leak_check: bool = True,
    ) -> None:
        self.config = config or GameConfig()
        self.config.validate()
        self.rng = random.Random(self.config.random_seed)
        self.state = GameState(game_id=f"game_{uuid.uuid4().hex[:8]}", config=self.config)
        self.event_store = event_store or EventStore()
        self.visibility = VisibilityManager()
        self.leak_checker = LeakChecker()
        self.validator = ActionValidator()
        self.agent_factory = agent_factory or self._default_agent_factory
        self.agents: dict[str, BaseAgent] = {}
        self.enable_leak_check = enable_leak_check
        self._night_attack_target: str | None = None
        self._night_saved_target: str | None = None
        self._night_poison_target: str | None = None
        self._night_guard_target: str | None = None

    def _default_agent_factory(self, player_id: str, seed: int | None = None) -> BaseAgent:
        if player_id in self.config.human_players:
            return ConsoleHumanAgent(player_id)
        return RuleBasedAgent(player_id, seed=seed)

    def run(self) -> GameState:
        self._assign_roles()
        self._check_win_and_emit_if_finished()
        while not self.state.winner and self.state.day_index < self.config.max_days:
            self.state.round_index += 1
            self.state.night_index += 1
            self._run_night()
            if self._check_win_and_emit_if_finished():
                break
            self.state.day_index += 1
            self._run_day()
            if self._check_win_and_emit_if_finished():
                break
        if not self.state.winner:
            self.state.winner = Faction.WOLVES.value
            self.state.win_reason = f"达到最大天数 {self.config.max_days}，按规则判定狼人获胜。"
            self._emit_public_game_end()
        return self.state

    def _assign_roles(self) -> None:
        self.state.phase = Phase.ROLE_ASSIGNMENT.value
        roles = list(self.config.roles)
        self.rng.shuffle(roles)
        for index, role in enumerate(roles, start=1):
            player_id = f"P{index}"
            player = PlayerState(
                player_id=player_id,
                seat=index,
                name=f"{index}号玩家",
                role=role,
                faction=faction_of(role),
                alive=True,
                skill_state=self._initial_skill_state(role),
                is_human=player_id in self.config.human_players,
            )
            self.state.players[player_id] = player
            self.agents[player_id] = self.agent_factory(player_id, (self.config.random_seed or 0) + index)

        wolf_ids = [p.player_id for p in self.state.players.values() if p.role == Role.WEREWOLF.value]
        self._emit(
            visibility="public",
            visible_to=["all"],
            actor_id=None,
            event_type="game_started",
            payload={
                "game_id": self.state.game_id,
                "player_count": self.config.player_count,
                "players": [p.public_view() for p in self.state.living_players()],
                "roles_config": list(self.config.roles),
                "rule_set": "AI Werewolf v2.0 local multi-agent rules",
                "version_label": self.config.version_label,
            },
        )
        for player in self.state.players.values():
            payload = {
                "role": player.role,
                "role_cn": role_name_cn(player.role),
                "faction": player.faction,
                "skill_state": dict(player.skill_state),
            }
            if player.role == Role.WEREWOLF.value:
                payload["wolf_teammates"] = sorted(wolf_ids)
            self._emit("private", [player.player_id], None, "role_assigned", payload)

    @staticmethod
    def _initial_skill_state(role: str) -> dict:
        if role == Role.WITCH.value:
            return {"antidote": True, "poison": True}
        if role == Role.SEER.value:
            return {"checked": []}
        if role == Role.HUNTER.value:
            return {"bullet": True}
        if role == Role.GUARD.value:
            return {"last_protected": None}
        return {}

    def _run_night(self) -> None:
        self._night_attack_target = None
        self._night_saved_target = None
        self._night_poison_target = None
        self._night_guard_target = None
        self.state.phase = Phase.NIGHT_START.value
        self._emit_public("night_started", {"night_index": self.state.night_index})
        self._run_guard()
        self._run_werewolves()
        self._run_seer()
        self._run_witch()
        self._resolve_night()

    def _run_guard(self) -> None:
        guard = self._living_role(Role.GUARD.value)
        if not guard or not self.config.enable_guard:
            return
        self.state.phase = Phase.GUARD_ACTION.value
        action = self._ask_agent(guard.player_id)
        if action.action_type == "guard_protect" and action.target_player_id:
            self._night_guard_target = action.target_player_id
            guard.skill_state["last_protected"] = action.target_player_id
        else:
            guard.skill_state["last_protected"] = None
        self._emit("private", [guard.player_id], guard.player_id, "guard_action_taken", action.to_dict())

    def _run_werewolves(self) -> None:
        wolves = self.state.living_wolves()
        if not wolves:
            return
        wolf_ids = [p.player_id for p in wolves]
        self.state.phase = Phase.WEREWOLF_DISCUSSION.value
        for wolf in wolves:
            action = self._ask_agent(wolf.player_id)
            self._emit("faction", wolf_ids, wolf.player_id, "wolf_discussion", action.to_dict())

        self.state.phase = Phase.WEREWOLF_KILL.value
        kill_votes: list[str] = []
        for wolf in wolves:
            action = self._ask_agent(wolf.player_id)
            if action.target_player_id:
                kill_votes.append(action.target_player_id)
            self._emit("faction", wolf_ids, wolf.player_id, "wolf_kill_vote", action.to_dict())
        self._night_attack_target = self._majority_choice(kill_votes)
        self._emit("faction", wolf_ids, None, "wolf_kill_decided", {"target_player_id": self._night_attack_target, "votes": kill_votes})

    def _run_seer(self) -> None:
        seer = self._living_role(Role.SEER.value)
        if not seer:
            return
        self.state.phase = Phase.SEER_CHECK.value
        action = self._ask_agent(seer.player_id)
        if not action.target_player_id:
            return
        target = self.state.players[action.target_player_id]
        seer.skill_state.setdefault("checked", []).append(action.target_player_id)
        result_faction = Faction.WOLVES.value if target.role == Role.WEREWOLF.value else Faction.GOOD.value
        self._emit(
            "private",
            [seer.player_id],
            seer.player_id,
            "seer_check_result",
            {
                "target_player_id": target.player_id,
                "target_seat": target.seat,
                "target_faction": result_faction,
                "action_reasoning_summary": action.reasoning_summary,
            },
        )

    def _run_witch(self) -> None:
        witch = self._living_role(Role.WITCH.value)
        if not witch:
            return
        self.state.phase = Phase.WITCH_ACTION.value
        self._emit(
            "private",
            [witch.player_id],
            None,
            "witch_night_info",
            {
                "attacked_player_id": self._night_attack_target,
                "has_antidote": witch.skill_state.get("antidote", False),
                "has_poison": witch.skill_state.get("poison", False),
            },
        )
        action = self._ask_agent(witch.player_id)
        if action.action_type == "witch_save" and witch.skill_state.get("antidote", False) and self.config.enable_witch_save:
            self._night_saved_target = self._night_attack_target
            witch.skill_state["antidote"] = False
        elif action.action_type == "witch_poison" and witch.skill_state.get("poison", False) and self.config.enable_witch_poison:
            self._night_poison_target = action.target_player_id
            witch.skill_state["poison"] = False
        self._emit("private", [witch.player_id], witch.player_id, "witch_action_taken", action.to_dict())

    def _resolve_night(self) -> None:
        self.state.phase = Phase.NIGHT_RESOLUTION.value
        deaths: list[tuple[str, str]] = []
        protected = {pid for pid in [self._night_saved_target, self._night_guard_target] if pid}
        if self._night_attack_target and self._night_attack_target not in protected:
            deaths.append((self._night_attack_target, "werewolf_kill"))
        if self._night_poison_target and self._night_poison_target not in [pid for pid, _ in deaths]:
            deaths.append((self._night_poison_target, "witch_poison"))

        for player_id, reason in deaths:
            self._kill_player(player_id, reason)

        self._emit(
            "system",
            [],
            None,
            "night_resolved_hidden",
            {
                "attacked_player_id": self._night_attack_target,
                "saved_player_id": self._night_saved_target,
                "guarded_player_id": self._night_guard_target,
                "poisoned_player_id": self._night_poison_target,
                "deaths": [{"player_id": pid, "reason": reason} for pid, reason in deaths],
            },
        )
        for player_id, reason in list(deaths):
            self._maybe_hunter_shoot(player_id, reason)

    def _run_day(self) -> None:
        self.state.phase = Phase.DAY_ANNOUNCEMENT.value
        last_night_deaths = []
        for p in self.state.dead_players():
            if p.death_round == self.state.round_index and p.death_reason in {"werewolf_kill", "witch_poison", "hunter_shot"}:
                item = p.public_view()
                if self.config.reveal_death_role:
                    item.update({"role": p.role, "role_cn": role_name_cn(p.role), "faction": p.faction})
                last_night_deaths.append(item)
        self._emit_public(
            "day_announced",
            {"day_index": self.state.day_index, "last_night_deaths": last_night_deaths, "message": "昨夜无人死亡" if not last_night_deaths else "昨夜有玩家死亡"},
        )
        if self._check_win_and_emit_if_finished():
            return

        self.state.phase = Phase.DAY_DISCUSSION.value
        for player in list(self.state.living_players()):
            action = self._ask_agent(player.player_id)
            self._emit("public", ["all"], player.player_id, "player_speech", {"content": action.content, "reasoning_summary": action.reasoning_summary, "confidence": action.confidence})

        self.state.phase = Phase.DAY_VOTE.value
        self.state.votes = {}
        for player in list(self.state.living_players()):
            action = self._ask_agent(player.player_id)
            if action.target_player_id:
                self.state.votes[player.player_id] = action.target_player_id
            self._emit("public", ["all"], player.player_id, "vote_cast", {"target_player_id": action.target_player_id, "reasoning_summary": action.reasoning_summary, "confidence": action.confidence})

        self._resolve_exile()

    def _resolve_exile(self) -> None:
        self.state.phase = Phase.EXILE_RESOLUTION.value
        target = self._majority_choice(list(self.state.votes.values()), tie_policy=self.config.tie_policy)
        if target:
            self._kill_player(target, "exiled")
            payload = {"exiled_player_id": target, "votes": dict(self.state.votes)}
            if self.config.reveal_death_role:
                p = self.state.players[target]
                payload.update({"role": p.role, "role_cn": role_name_cn(p.role), "faction": p.faction})
        else:
            payload = {"exiled_player_id": None, "votes": dict(self.state.votes), "reason": "tie_no_exile"}
        self._emit_public("exile_resolved", payload)
        if target:
            self._maybe_hunter_shoot(target, "exiled")

    def _maybe_hunter_shoot(self, hunter_id: str, death_reason: str) -> None:
        if not self.config.enable_hunter:
            return
        if hunter_id not in self.state.players:
            return
        hunter = self.state.players[hunter_id]
        if hunter.role != Role.HUNTER.value or not hunter.skill_state.get("bullet", False):
            return
        if death_reason == "witch_poison":
            self._emit("system", [], hunter_id, "hunter_shot_blocked", {"reason": "witch_poison"})
            return
        if not self.state.living_players():
            return
        self.state.phase = Phase.HUNTER_SHOOT.value
        self._emit_public("hunter_can_shoot", {"hunter_player_id": hunter_id, "death_reason": death_reason})
        action = self._ask_agent(hunter_id)
        hunter.skill_state["bullet"] = False
        if action.action_type == "hunter_shoot" and action.target_player_id:
            self._kill_player(action.target_player_id, "hunter_shot")
            self._emit_public("hunter_shot", {"hunter_player_id": hunter_id, "target_player_id": action.target_player_id, "reasoning_summary": action.reasoning_summary})
        else:
            self._emit_public("hunter_skipped", {"hunter_player_id": hunter_id})

    def _ask_agent(self, player_id: str) -> Action:
        observation = self.visibility.build_observation(self.state, self.event_store, player_id)
        if self.enable_leak_check:
            self.leak_checker.assert_no_obvious_leak(self.state, observation)
        agent = self.agents[player_id]
        try:
            action = agent.act(observation)
            self._emit(
                "system",
                [],
                player_id,
                "agent_action_received",
                {
                    "action_type": action.action_type,
                    "target_player_id": action.target_player_id,
                    "confidence": action.confidence,
                    "metadata": dict(action.metadata),
                },
            )
            self.validator.validate(self.state, action)
            self._emit(
                "system",
                [],
                player_id,
                "agent_action_taken",
                {
                    "action_type": action.action_type,
                    "target_player_id": action.target_player_id,
                    "confidence": action.confidence,
                    "metadata": dict(action.metadata),
                },
            )
            return action
        except Exception as exc:
            fallback = self._fallback_action(player_id, str(exc))
            self._emit("system", [], player_id, "agent_action_fallback", {"error": str(exc), "fallback": fallback.to_dict()})
            return fallback

    def _fallback_action(self, player_id: str, reason: str) -> Action:
        living_targets = [p.player_id for p in self.state.living_players() if p.player_id != player_id]
        phase = self.state.phase
        if phase == Phase.GUARD_ACTION.value:
            choices = [p.player_id for p in self.state.living_players()]
            return Action(player_id, "guard_protect", self.rng.choice(choices) if choices else None, None, reason)
        if phase == Phase.WEREWOLF_DISCUSSION.value:
            choices = [p.player_id for p in self.state.living_good()]
            return Action(player_id, "wolf_discuss", self.rng.choice(choices) if choices else None, "fallback wolf discussion", reason)
        if phase == Phase.WEREWOLF_KILL.value:
            choices = [p.player_id for p in self.state.living_good()]
            return Action(player_id, "werewolf_kill", self.rng.choice(choices) if choices else None, None, reason)
        if phase == Phase.SEER_CHECK.value:
            return Action(player_id, "seer_check", self.rng.choice(living_targets) if living_targets else None, None, reason)
        if phase == Phase.WITCH_ACTION.value:
            return Action(player_id, "skip", None, None, reason)
        if phase == Phase.DAY_DISCUSSION.value:
            return Action(player_id, "speak", None, "我暂时没有更多信息，先听后置位发言。", reason)
        if phase == Phase.DAY_VOTE.value:
            return Action(player_id, "vote", self.rng.choice(living_targets) if living_targets else None, None, reason)
        if phase == Phase.HUNTER_SHOOT.value:
            return Action(player_id, "hunter_shoot", self.rng.choice(living_targets) if living_targets else None, None, reason)
        return Action(player_id, "skip", None, None, reason)

    def _check_win_and_emit_if_finished(self) -> bool:
        self.state.phase = Phase.WIN_CHECK.value
        living_wolves = self.state.living_wolves()
        living_good = self.state.living_good()
        if not living_wolves:
            self.state.winner = Faction.GOOD.value
            self.state.win_reason = "所有狼人均已死亡，好人阵营胜利。"
        elif not living_good:
            self.state.winner = Faction.WOLVES.value
            self.state.win_reason = "所有好人均已死亡，狼人阵营胜利。"
        elif self.config.win_mode == "kill_side":
            if not self.state.living_villagers():
                self.state.winner = Faction.WOLVES.value
                self.state.win_reason = "平民全部死亡，狼人屠边胜利。"
            elif not self.state.living_gods():
                self.state.winner = Faction.WOLVES.value
                self.state.win_reason = "神职全部死亡，狼人屠边胜利。"
        if self.state.winner:
            self._emit_public_game_end()
            return True
        return False

    def _emit_public_game_end(self) -> None:
        self.state.phase = Phase.GAME_END.value
        if any(e.event_type == "game_ended" for e in self.event_store.snapshot()):
            return
        roles = {
            pid: {
                "seat": p.seat,
                "name": p.name,
                "role": p.role,
                "role_cn": role_name_cn(p.role),
                "faction": p.faction,
                "alive": p.alive,
                "death_reason": p.death_reason,
                "is_human": p.is_human,
            }
            for pid, p in sorted(self.state.players.items(), key=lambda item: item[1].seat)
        }
        self._emit("public", ["all"], None, "game_ended", {"winner": self.state.winner, "win_reason": self.state.win_reason, "roles": roles})

    def _kill_player(self, player_id: str, reason: str) -> None:
        player = self.state.players[player_id]
        if not player.alive:
            return
        player.alive = False
        player.death_round = self.state.round_index
        player.death_reason = reason

    def _living_role(self, role: str) -> PlayerState | None:
        for player in self.state.living_players():
            if player.role == role:
                return player
        return None

    def _majority_choice(self, votes: list[str], tie_policy: str | None = None) -> str | None:
        if not votes:
            return None
        counts = Counter(votes)
        max_count = max(counts.values())
        best = [target for target, count in counts.items() if count == max_count]
        if len(best) == 1:
            return best[0]
        policy = tie_policy or "random"
        if policy == "no_exile":
            return None
        return self.rng.choice(best)

    def _emit_public(self, event_type: str, payload: dict) -> None:
        self._emit("public", ["all"], None, event_type, payload)

    def _emit(self, visibility: str, visible_to: list[str], actor_id: str | None, event_type: str, payload: dict) -> None:
        event = GameEvent.create(
            game_id=self.state.game_id,
            round_index=self.state.round_index,
            day_index=self.state.day_index,
            night_index=self.state.night_index,
            phase=self.state.phase,
            visibility=visibility,  # type: ignore[arg-type]
            visible_to=visible_to,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
        )
        self.event_store.append(event)


def run_game(
    seed: int | None = 42,
    log_path: str | Path | None = None,
    enable_leak_check: bool = True,
    config: GameConfig | None = None,
    agent_factory: AgentFactory | None = None,
) -> tuple[GameState, EventStore]:
    game_config = config or GameConfig(random_seed=seed)
    store = EventStore(log_path)
    engine = GameEngine(config=game_config, event_store=store, agent_factory=agent_factory, enable_leak_check=enable_leak_check)
    state = engine.run()
    return state, store
