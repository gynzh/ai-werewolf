from __future__ import annotations

from ai_werewolf.logging.event_store import EventStore
from ai_werewolf.models.schema import AgentObservation, GameEvent, GameState, Phase, Role
from ai_werewolf.rules.roles import faction_name_cn, role_name_cn


class VisibilityManager:
    """Builds per-agent observations from hidden GameState and event stream."""

    def build_observation(self, state: GameState, events: EventStore, player_id: str) -> AgentObservation:
        player = state.players[player_id]
        visible_events = events.visible_events(player_id)
        public_history = [self._event_dict(e) for e in visible_events if e.visibility == "public"]
        private_history = [self._event_dict(e) for e in visible_events if e.visibility == "private"]
        faction_history = [self._event_dict(e) for e in visible_events if e.visibility == "faction"]

        return AgentObservation(
            game_id=state.game_id,
            player_id=player.player_id,
            seat=player.seat,
            role=player.role,
            faction=player.faction,
            phase=state.phase,
            round_index=state.round_index,
            day_index=state.day_index,
            night_index=state.night_index,
            alive_players=[p.public_view() for p in state.living_players()],
            dead_players=[p.public_view() for p in state.dead_players()],
            public_history=public_history,
            private_history=private_history,
            faction_history=faction_history,
            available_actions=self._available_actions(state, player_id),
            current_task=self._task(state, player_id),
        )

    @staticmethod
    def _event_dict(event: GameEvent) -> dict:
        return {
            "round_index": event.round_index,
            "day_index": event.day_index,
            "night_index": event.night_index,
            "phase": event.phase,
            "actor_id": event.actor_id,
            "event_type": event.event_type,
            "payload": event.payload,
        }

    def _available_actions(self, state: GameState, player_id: str) -> list[dict]:
        player = state.players[player_id]
        living_targets = [
            {"player_id": p.player_id, "seat": p.seat, "name": p.name}
            for p in state.living_players()
            if p.player_id != player_id
        ]
        living_targets_allow_self = [
            {"player_id": p.player_id, "seat": p.seat, "name": p.name}
            for p in state.living_players()
        ]
        if state.phase == Phase.HUNTER_SHOOT.value and player.role == Role.HUNTER.value and player.skill_state.get("bullet", False):
            return [
                {"action_type": "skip", "target_options": []},
                {"action_type": "hunter_shoot", "target_options": living_targets},
            ]
        if not player.alive:
            return []
        if state.phase == Phase.GUARD_ACTION.value and player.role == Role.GUARD.value:
            last = player.skill_state.get("last_protected")
            targets = [t for t in living_targets_allow_self if t["player_id"] != last]
            return [
                {"action_type": "skip", "target_options": []},
                {"action_type": "guard_protect", "target_options": targets},
            ]
        if state.phase == Phase.WEREWOLF_DISCUSSION.value and player.role == Role.WEREWOLF.value:
            targets = [t for t in living_targets if state.players[t["player_id"]].role != Role.WEREWOLF.value]
            return [{"action_type": "wolf_discuss", "target_options": targets}]
        if state.phase == Phase.WEREWOLF_KILL.value and player.role == Role.WEREWOLF.value:
            targets = [t for t in living_targets if state.players[t["player_id"]].role != Role.WEREWOLF.value]
            return [{"action_type": "werewolf_kill", "target_options": targets}]
        if state.phase == Phase.SEER_CHECK.value and player.role == Role.SEER.value:
            return [{"action_type": "seer_check", "target_options": living_targets}]
        if state.phase == Phase.WITCH_ACTION.value and player.role == Role.WITCH.value:
            actions = [{"action_type": "skip", "target_options": []}]
            if player.skill_state.get("antidote", False):
                actions.append({"action_type": "witch_save", "target_options": []})
            if player.skill_state.get("poison", False):
                actions.append({"action_type": "witch_poison", "target_options": living_targets})
            return actions
        if state.phase == Phase.DAY_DISCUSSION.value:
            return [{"action_type": "speak", "target_options": []}]
        if state.phase == Phase.DAY_VOTE.value:
            return [{"action_type": "vote", "target_options": living_targets}]
        return []

    def _task(self, state: GameState, player_id: str) -> str:
        player = state.players[player_id]
        role_cn = role_name_cn(player.role)
        faction_cn = faction_name_cn(player.faction)
        if state.phase == Phase.HUNTER_SHOOT.value and player.role == Role.HUNTER.value:
            return f"你是{role_cn}。你已死亡且仍有子弹，可以选择开枪带走一名存活玩家，也可以跳过。"
        if not player.alive:
            return "你已经死亡，当前无需行动。"
        phase = state.phase
        if phase == Phase.GUARD_ACTION.value and player.role == Role.GUARD.value:
            return f"你是{role_cn}，请选择今晚守护目标，不能连续两晚守护同一人。"
        if phase == Phase.WEREWOLF_DISCUSSION.value and player.role == Role.WEREWOLF.value:
            return f"你是{role_cn}，属于{faction_cn}。请与狼队友协商夜间击杀目标。"
        if phase == Phase.WEREWOLF_KILL.value and player.role == Role.WEREWOLF.value:
            return f"你是{role_cn}，请从非狼人存活玩家中选择夜间击杀目标。"
        if phase == Phase.SEER_CHECK.value and player.role == Role.SEER.value:
            return f"你是{role_cn}，请选择一名存活玩家进行查验。"
        if phase == Phase.WITCH_ACTION.value and player.role == Role.WITCH.value:
            return f"你是{role_cn}，请根据夜间刀口和药品状态决定是否用药。"
        if phase == Phase.DAY_DISCUSSION.value:
            return f"白天发言阶段。你是{role_cn}，属于{faction_cn}。请基于可见信息发表立场。"
        if phase == Phase.DAY_VOTE.value:
            return f"白天投票阶段。你是{role_cn}，请选择一名存活玩家投票放逐。"
        return "当前阶段无需你行动。"


class LeakChecker:
    """Development helper: catches obvious hidden-information leakage in observations."""

    def assert_no_obvious_leak(self, state: GameState, observation: AgentObservation) -> None:
        player = state.players[observation.player_id]
        # game_ended deliberately reveals all roles.
        visible_history = [
            e for e in observation.public_history + observation.private_history + observation.faction_history
            if e.get("event_type") != "game_ended"
        ]
        obs_text = repr(visible_history)
        for other in state.players.values():
            if other.player_id == player.player_id:
                continue
            if other.role == player.role:
                continue
            if player.role == Role.WEREWOLF.value and other.role == Role.WEREWOLF.value:
                continue
            leak_token = f"'role': '{other.role}'"
            if leak_token in obs_text or f'"role": "{other.role}"' in obs_text:
                raise AssertionError(f"possible role leak to {player.player_id}: {other.player_id} {other.role}")
