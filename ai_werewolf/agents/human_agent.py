from __future__ import annotations

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.models.schema import Action, AgentObservation


class ConsoleHumanAgent(BaseAgent):
    """Terminal human player for human-AI mixed games."""

    def act(self, observation: AgentObservation) -> Action:
        print("\n" + "=" * 72)
        print(f"轮次 {observation.round_index} | 阶段 {observation.phase} | 你是 {observation.player_id} / {observation.role} / {observation.faction}")
        print(observation.current_task)
        print("存活玩家：" + ", ".join(f"{p['player_id']}({p['name']})" for p in observation.alive_players))
        print("可选动作：")
        flat_options: list[tuple[str, str | None]] = []
        for spec in observation.available_actions:
            action_type = spec["action_type"]
            targets = spec.get("target_options", [])
            if not targets:
                flat_options.append((action_type, None))
                print(f"  - {action_type}")
            else:
                ids = [t["player_id"] for t in targets]
                flat_options.extend((action_type, pid) for pid in ids)
                print(f"  - {action_type}: {', '.join(ids)}")
        action_type = self._ask_action_type({a for a, _ in flat_options})
        target = None
        target_options = [target for action, target in flat_options if action == action_type and target]
        if target_options:
            target = self._ask_target(target_options)
        content = None
        if action_type == "speak":
            content = input("请输入你的发言：").strip() or "我暂时没有更多信息。"
        return Action(
            player_id=observation.player_id,
            action_type=action_type,
            target_player_id=target,
            content=content,
            reasoning_summary="人类玩家输入",
            confidence=1.0,
            metadata={"source": "console_human"},
        )

    @staticmethod
    def _ask_action_type(valid: set[str]) -> str:
        while True:
            value = input(f"动作类型 {sorted(valid)}：").strip()
            if value in valid:
                return value
            print("动作无效，请重新输入。")

    @staticmethod
    def _ask_target(valid: list[str]) -> str:
        while True:
            value = input(f"目标 {valid}：").strip().upper()
            if value in valid:
                return value
            print("目标无效，请重新输入。")
