from __future__ import annotations

import json
import re
from typing import Any

from ai_werewolf.models.schema import Action


_FENCED_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_ALLOWED_ACTIONS = {
    "speak",
    "vote",
    "wolf_discuss",
    "werewolf_kill",
    "seer_check",
    "witch_save",
    "witch_poison",
    "guard_protect",
    "hunter_shoot",
    "skip",
}


class LLMOutputParseError(ValueError):
    pass


def parse_action_json(player_id: str, raw: str) -> Action:
    """Parse a provider response into an Action.

    Accepts pure JSON, fenced JSON, or a response containing one JSON object.
    This parser validates schema shape only. Game legality is still enforced by
    ActionValidator after parsing.
    """
    data = _load_first_json_object(raw)
    action_type = str(data.get("action_type", "skip")).strip()
    if action_type not in _ALLOWED_ACTIONS:
        raise LLMOutputParseError(f"unknown action_type from LLM: {action_type!r}")

    target = data.get("target_player_id")
    if target in {"", "null", "None", "none"}:
        target = None
    if isinstance(target, str):
        target = target.strip().upper() or None
    elif target is not None:
        target = str(target).strip().upper() or None

    confidence = data.get("confidence", 0.5)
    try:
        confidence_float = float(confidence)
    except (TypeError, ValueError):
        confidence_float = 0.5
    confidence_float = max(0.0, min(1.0, confidence_float))

    content = data.get("content")
    reasoning = data.get("reasoning_summary") or data.get("reason") or data.get("rationale")
    return Action(
        player_id=player_id,
        action_type=action_type,
        target_player_id=target,
        content=str(content) if content is not None else None,
        reasoning_summary=str(reasoning) if reasoning is not None else "LLM output parsed successfully.",
        confidence=confidence_float,
        metadata={"raw_model_response": raw},
    )


def _load_first_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise LLMOutputParseError("empty LLM response")

    fenced = _FENCED_JSON_BLOCK.search(text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        match = _JSON_BLOCK.search(text)
        if match:
            text = match.group(0).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputParseError(f"failed to parse LLM JSON: {exc}; raw={raw[:300]!r}") from exc

    if not isinstance(data, dict):
        raise LLMOutputParseError("LLM JSON must be an object")
    return data
