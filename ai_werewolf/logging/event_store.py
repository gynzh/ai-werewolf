from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from ai_werewolf.models.schema import GameEvent

# Public events are part of every AgentObservation.public_history and are also
# rendered in the browser UI. Never let private chain-of-thought, role claims
# from hidden prompts, raw provider responses, or fallback internals leak there.
_PUBLIC_PAYLOAD_BLOCKLIST = {
    "reasoning_summary",
    "action_reasoning_summary",
    "private_reasoning_summary",
    "chain_of_thought",
    "cot",
    "thought",
    "thinking",
    "raw_prompt",
    "raw_response",
    "messages",
    "system_prompt",
    "private_history",
}

_PUBLIC_METADATA_BLOCKLIST = {
    "llm_error",
    "raw_prompt",
    "raw_response",
    "provider_request",
    "provider_response",
}


def _redact_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in _PUBLIC_PAYLOAD_BLOCKLIST:
                continue
            if key == "metadata" and isinstance(item, dict):
                redacted[key] = {
                    meta_key: _redact_public_value(meta_value)
                    for meta_key, meta_value in item.items()
                    if meta_key not in _PUBLIC_METADATA_BLOCKLIST
                }
                continue
            redacted[key] = _redact_public_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_public_value(item) for item in value]
    return value


def sanitize_public_event(event: GameEvent) -> GameEvent:
    """Return a copy of a public event with private-only fields removed.

    This is deliberately applied at the EventStore boundary so both the browser
    API and future AgentObservation.public_history receive the same safe event.
    System, private and faction events keep their full payload for review.
    """
    if event.visibility != "public":
        return event
    return replace(event, payload=_redact_public_value(event.payload))


class EventStore:
    """Thread-safe in-memory event stream with optional JSONL persistence."""

    def __init__(self, jsonl_path: str | Path | None = None) -> None:
        self.events: list[GameEvent] = []
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self._lock = threading.RLock()
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            self.jsonl_path.write_text("", encoding="utf-8")

    def append(self, event: GameEvent) -> None:
        safe_event = sanitize_public_event(event)
        with self._lock:
            self.events.append(safe_event)
            if self.jsonl_path:
                with self.jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(safe_event.to_dict(), ensure_ascii=False) + "\n")

    def extend(self, events: Iterable[GameEvent]) -> None:
        for event in events:
            self.append(event)

    def snapshot(self) -> list[GameEvent]:
        with self._lock:
            return list(self.events)

    def public_events(self) -> list[GameEvent]:
        return [sanitize_public_event(e) for e in self.snapshot() if e.visibility == "public"]

    def visible_events(self, player_id: str) -> list[GameEvent]:
        visible = []
        for event in self.snapshot():
            if event.visibility == "public":
                visible.append(sanitize_public_event(event))
            elif player_id in event.visible_to:
                visible.append(event)
        return visible

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in self.snapshot())
