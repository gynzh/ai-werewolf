from __future__ import annotations

from ai_werewolf.models.schema import Action, GameState, Phase, Role


class ActionValidationError(ValueError):
    pass


class ActionValidator:
    """Validate that an Agent action is legal in the current game phase."""

    def validate(self, state: GameState, action: Action) -> None:
        if action.player_id not in state.players:
            raise ActionValidationError(f"unknown player_id: {action.player_id}")
        player = state.players[action.player_id]
        phase = state.phase

        if phase == Phase.HUNTER_SHOOT.value:
            if player.role != Role.HUNTER.value or action.action_type not in {"hunter_shoot", "skip"}:
                raise ActionValidationError("only hunter may shoot in hunter_shoot phase")
            if not player.skill_state.get("bullet", False):
                raise ActionValidationError("hunter bullet already used")
            if action.action_type == "hunter_shoot":
                self._validate_living_target(state, action, allow_self=False)
            return

        if not player.alive:
            raise ActionValidationError(f"dead player cannot act: {action.player_id}")

        if phase == Phase.GUARD_ACTION.value:
            if player.role != Role.GUARD.value or action.action_type not in {"guard_protect", "skip"}:
                raise ActionValidationError("only living guard may protect")
            if action.action_type == "guard_protect":
                self._validate_living_target(state, action, allow_self=True)
                if player.skill_state.get("last_protected") == action.target_player_id:
                    raise ActionValidationError("guard cannot protect the same player on consecutive nights")
            return

        if phase == Phase.WEREWOLF_DISCUSSION.value:
            if player.role != Role.WEREWOLF.value or action.action_type != "wolf_discuss":
                raise ActionValidationError("only living wolves may discuss at night")
            if action.target_player_id:
                self._validate_living_target(state, action, allow_self=False)
            return

        if phase == Phase.WEREWOLF_KILL.value:
            if player.role != Role.WEREWOLF.value or action.action_type != "werewolf_kill":
                raise ActionValidationError("only living wolves may choose night kill")
            self._validate_living_target(state, action, allow_self=False)
            if state.players[action.target_player_id].role == Role.WEREWOLF.value:
                raise ActionValidationError("wolves cannot kill a wolf teammate")
            return

        if phase == Phase.SEER_CHECK.value:
            if player.role != Role.SEER.value or action.action_type != "seer_check":
                raise ActionValidationError("only living seer may check")
            self._validate_living_target(state, action, allow_self=False)
            return

        if phase == Phase.WITCH_ACTION.value:
            if player.role != Role.WITCH.value or action.action_type not in {"witch_save", "witch_poison", "skip"}:
                raise ActionValidationError("only living witch may use witch action")
            if action.action_type == "witch_save":
                if not player.skill_state.get("antidote", False):
                    raise ActionValidationError("witch antidote already used")
            if action.action_type == "witch_poison":
                if not player.skill_state.get("poison", False):
                    raise ActionValidationError("witch poison already used")
                self._validate_living_target(state, action, allow_self=False)
            return

        if phase == Phase.DAY_DISCUSSION.value:
            if action.action_type != "speak":
                raise ActionValidationError("day discussion requires speak action")
            if not action.content:
                raise ActionValidationError("speech content is required")
            return

        if phase == Phase.DAY_VOTE.value:
            if action.action_type != "vote":
                raise ActionValidationError("day vote requires vote action")
            self._validate_living_target(state, action, allow_self=False)
            return

        raise ActionValidationError(f"no player actions accepted in phase: {phase}")

    @staticmethod
    def _validate_living_target(state: GameState, action: Action, allow_self: bool) -> None:
        if not action.target_player_id:
            raise ActionValidationError("target_player_id is required")
        if action.target_player_id not in state.players:
            raise ActionValidationError(f"unknown target: {action.target_player_id}")
        if not state.players[action.target_player_id].alive:
            raise ActionValidationError(f"target is dead: {action.target_player_id}")
        if not allow_self and action.target_player_id == action.player_id:
            raise ActionValidationError("self-target is not allowed")
