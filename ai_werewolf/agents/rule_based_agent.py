from __future__ import annotations

import random
from collections import Counter
from typing import Any

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.models.schema import Action, AgentObservation, Faction, Phase, Role
from ai_werewolf.rules.roles import role_name_cn


class RuleBasedAgent(BaseAgent):
    """Local baseline agent using only AgentObservation.

    It is intentionally transparent and deterministic-ish: enough to validate
    multi-agent flow, information isolation, metrics, and UI before real LLM
    providers are plugged in.
    """

    def __init__(self, player_id: str, seed: int | None = None) -> None:
        super().__init__(player_id)
        self.rng = random.Random(seed)

    def act(self, observation: AgentObservation) -> Action:
        phase = observation.phase
        if phase == Phase.GUARD_ACTION.value:
            return self._guard_action(observation)
        if phase == Phase.WEREWOLF_DISCUSSION.value:
            return self._wolf_discuss(observation)
        if phase == Phase.WEREWOLF_KILL.value:
            return self._wolf_kill(observation)
        if phase == Phase.SEER_CHECK.value:
            return self._seer_check(observation)
        if phase == Phase.WITCH_ACTION.value:
            return self._witch_action(observation)
        if phase == Phase.DAY_DISCUSSION.value:
            return self._speak(observation)
        if phase == Phase.DAY_VOTE.value:
            return self._vote(observation)
        if phase == Phase.HUNTER_SHOOT.value:
            return self._hunter_shoot(observation)
        return Action(player_id=observation.player_id, action_type="skip", reasoning_summary="当前阶段无需行动")

    def _target_options(self, observation: AgentObservation, action_type: str) -> list[str]:
        for spec in observation.available_actions:
            if spec.get("action_type") == action_type:
                return [item["player_id"] for item in spec.get("target_options", [])]
        return []

    def _wolf_teammates(self, observation: AgentObservation) -> set[str]:
        teammates = set()
        for event in observation.private_history:
            if event.get("event_type") == "role_assigned":
                teammates.update(event.get("payload", {}).get("wolf_teammates", []))
        teammates.add(observation.player_id)
        return teammates

    def _seer_checks(self, observation: AgentObservation) -> dict[str, str]:
        checks = {}
        for event in observation.private_history:
            if event.get("event_type") == "seer_check_result":
                payload = event.get("payload", {})
                checks[payload.get("target_player_id")] = payload.get("target_faction")
        return {k: v for k, v in checks.items() if k and v}

    def _last_witch_info(self, observation: AgentObservation) -> dict[str, Any]:
        infos = [e.get("payload", {}) for e in observation.private_history if e.get("event_type") == "witch_night_info"]
        return infos[-1] if infos else {}

    def _public_speeches(self, observation: AgentObservation) -> list[dict[str, Any]]:
        return [e for e in observation.public_history if e.get("event_type") == "player_speech"]

    def _votes(self, observation: AgentObservation) -> list[dict[str, Any]]:
        return [e for e in observation.public_history if e.get("event_type") == "vote_cast"]

    def _suspicions(self, observation: AgentObservation) -> dict[str, float]:
        alive_ids = [p["player_id"] for p in observation.alive_players if p["player_id"] != observation.player_id]
        scores = {pid: 0.0 for pid in alive_ids}
        checks = self._seer_checks(observation)
        for pid, faction in checks.items():
            if pid in scores:
                if faction == Faction.WOLVES.value:
                    scores[pid] += 100.0
                else:
                    scores[pid] -= 60.0

        for speech in self._public_speeches(observation):
            actor = speech.get("actor_id")
            payload = speech.get("payload", {})
            content = payload.get("content", "") or ""
            if actor in scores:
                if "我是预言家" in content or "查验结果" in content:
                    if observation.role == Role.SEER.value:
                        scores[actor] += 35.0
                    elif observation.role == Role.WEREWOLF.value:
                        scores[actor] += 10.0
                if "怀疑" in content and observation.player_id in content:
                    scores[actor] += 6.0
                if "没有夜间信息" in content:
                    scores[actor] -= 1.0

        vote_targets = Counter(v.get("payload", {}).get("target_player_id") for v in self._votes(observation))
        for target, count in vote_targets.items():
            if target in scores and count >= 2:
                scores[target] += 4.0

        if observation.role == Role.WEREWOLF.value:
            for teammate in self._wolf_teammates(observation):
                if teammate in scores:
                    scores[teammate] -= 100.0
        return scores

    def _choose_highest(self, scores: dict[str, float], fallback_targets: list[str]) -> str | None:
        if not fallback_targets:
            return None
        if not scores:
            return self.rng.choice(fallback_targets)
        max_score = max(scores.get(t, 0.0) for t in fallback_targets)
        best = [t for t in fallback_targets if scores.get(t, 0.0) == max_score]
        return self.rng.choice(best)

    def _guard_action(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "guard_protect")
        if not targets:
            return Action(observation.player_id, "skip", reasoning_summary="没有合法守护目标")
        # Prioritize public seer claimers, otherwise self early, then random high-value alive.
        seer_claimers = []
        for speech in self._public_speeches(observation):
            content = speech.get("payload", {}).get("content", "") or ""
            actor = speech.get("actor_id")
            if actor in targets and ("我是预言家" in content or "查验结果" in content):
                seer_claimers.append(actor)
        target = self.rng.choice(seer_claimers) if seer_claimers else (observation.player_id if observation.player_id in targets and observation.night_index <= 1 else self.rng.choice(targets))
        return Action(observation.player_id, "guard_protect", target, reasoning_summary=f"守护 {target}，优先保护关键或高风险位置。", confidence=0.62)

    def _wolf_discuss(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "wolf_discuss")
        scores = self._suspicions(observation)
        for speech in self._public_speeches(observation):
            actor = speech.get("actor_id")
            content = speech.get("payload", {}).get("content", "") or ""
            if actor in scores and ("我是预言家" in content or "查验" in content):
                scores[actor] += 45.0
        target = self._choose_highest(scores, targets)
        content = f"建议今晚优先刀 {target}，其公开信息或发言威胁较高。" if target else "暂时没有明确刀口。"
        return Action(observation.player_id, "wolf_discuss", target, content, "狼队夜间协商，优先处理威胁位。", 0.64)

    def _wolf_kill(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "werewolf_kill")
        scores = self._suspicions(observation)
        for speech in self._public_speeches(observation):
            actor = speech.get("actor_id")
            content = speech.get("payload", {}).get("content", "") or ""
            if actor in scores and ("我是预言家" in content or "查验" in content):
                scores[actor] += 55.0
        target = self._choose_highest(scores, targets)
        return Action(observation.player_id, "werewolf_kill", target, reasoning_summary=f"选择击杀 {target}，压制好人信息链。", confidence=0.68)

    def _seer_check(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "seer_check")
        checked = set(self._seer_checks(observation).keys())
        unchecked = [t for t in targets if t not in checked]
        target = self._choose_highest(self._suspicions(observation), unchecked or targets)
        return Action(observation.player_id, "seer_check", target, reasoning_summary=f"查验 {target}，优先覆盖未确认且有疑点的位置。", confidence=0.72)

    def _witch_action(self, observation: AgentObservation) -> Action:
        info = self._last_witch_info(observation)
        attacked = info.get("attacked_player_id")
        has_antidote = bool(info.get("has_antidote"))
        has_poison = bool(info.get("has_poison"))
        if attacked and has_antidote and observation.night_index <= 1:
            return Action(observation.player_id, "witch_save", attacked, reasoning_summary=f"第 {observation.night_index} 夜使用解药救 {attacked}，避免好人过早减员。", confidence=0.65)
        if has_poison and observation.night_index >= 3:
            targets = self._target_options(observation, "witch_poison")
            scores = self._suspicions(observation)
            target = self._choose_highest(scores, targets)
            if target and scores.get(target, 0.0) >= 10.0:
                return Action(observation.player_id, "witch_poison", target, reasoning_summary=f"后期毒杀高疑点目标 {target}。", confidence=0.62)
        return Action(observation.player_id, "skip", reasoning_summary="当前用药收益不足，选择保留或跳过。", confidence=0.55)

    def _hunter_shoot(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "hunter_shoot")
        scores = self._suspicions(observation)
        target = self._choose_highest(scores, targets)
        if target:
            return Action(observation.player_id, "hunter_shoot", target, reasoning_summary=f"猎人带走当前最高疑点目标 {target}。", confidence=0.58)
        return Action(observation.player_id, "skip", reasoning_summary="没有合适开枪目标。", confidence=0.4)

    def _speak(self, observation: AgentObservation) -> Action:
        scores = self._suspicions(observation)
        targets = [p["player_id"] for p in observation.alive_players if p["player_id"] != observation.player_id]
        suspect = self._choose_highest(scores, targets) or "未知"
        checks = self._seer_checks(observation)
        role_cn = role_name_cn(observation.role)

        if observation.role == Role.SEER.value and checks:
            found_wolves = [pid for pid, fac in checks.items() if fac == Faction.WOLVES.value]
            if found_wolves or observation.day_index >= 2:
                parts = [f"{pid} 是{'狼人' if fac == Faction.WOLVES.value else '好人'}" for pid, fac in checks.items()]
                content = f"我是预言家，目前查验结果：{'；'.join(parts)}。今天建议重点处理 {suspect}，不要被模糊发言带偏。"
            else:
                content = f"我是{role_cn}，目前没有查到狼人。我更想听 {suspect} 解释自己的发言和投票逻辑。"
        elif observation.role == Role.WEREWOLF.value:
            content = f"我这里是好人视角。当前 {suspect} 的发言和站边最需要解释，建议先听清楚他的逻辑，不要急着跟票。"
        elif observation.role == Role.WITCH.value:
            content = f"我是{role_cn}，暂时不展开夜间细节。今天我比较关注 {suspect}，他的行为和场上节奏不够一致。"
        elif observation.role == Role.GUARD.value:
            content = f"我是{role_cn}，会结合夜间局势看发言。现在更关注 {suspect}，希望他说明为什么这样站边。"
        elif observation.role == Role.HUNTER.value:
            content = f"我是{role_cn}，我会看谁在强行带节奏。当前我更怀疑 {suspect}，如果我被推也会认真考虑开枪目标。"
        else:
            content = f"我是{role_cn}，没有夜间信息。我主要看发言和投票一致性，目前更怀疑 {suspect}。"

        return Action(observation.player_id, "speak", content=content, reasoning_summary=f"基于可见历史，将 {suspect} 作为当前主要关注对象。", confidence=0.6)

    def _vote(self, observation: AgentObservation) -> Action:
        targets = self._target_options(observation, "vote")
        target = self._choose_highest(self._suspicions(observation), targets)
        return Action(observation.player_id, "vote", target, reasoning_summary=f"投票给 {target}，其公开行为或信息链疑点最高。", confidence=0.61)
