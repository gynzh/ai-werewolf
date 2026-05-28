from __future__ import annotations

import json
from dataclasses import asdict

from ai_werewolf.models.schema import AgentObservation
from ai_werewolf.rules.roles import faction_name_cn, role_name_cn


def build_agent_prompt(observation: AgentObservation) -> str:
    """Build a deterministic, JSON-only prompt for future LLM agents.

    The MVP does not call external LLM APIs. This function is a stable extension
    point: an LLMAgent can pass this prompt to any provider and parse the returned
    JSON into ai_werewolf.models.schema.Action.
    """
    payload = asdict(observation)
    return f"""你正在参与一局狼人杀。你是一个独立玩家 Agent，必须严格遵守可见信息边界。

身份：{role_name_cn(observation.role)} / {observation.role}
阵营：{faction_name_cn(observation.faction)} / {observation.faction}
当前阶段：{observation.phase}
当前任务：{observation.current_task}

只允许基于下面 JSON 中的信息行动，不能假设或编造系统真相：
{json.dumps(payload, ensure_ascii=False, indent=2)}

请只输出 JSON，不要输出 Markdown 或解释文字。格式：
{{
  "action_type": "speak|vote|wolf_discuss|werewolf_kill|seer_check|witch_save|witch_poison|guard_protect|hunter_shoot|skip",
  "target_player_id": "P1 或 null",
  "content": "发言内容；非发言可为 null",
  "reasoning_summary": "一句话概括决策依据",
  "confidence": 0.0
}}
"""
