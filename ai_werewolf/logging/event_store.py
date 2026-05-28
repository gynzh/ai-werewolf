from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from ai_werewolf.models.schema import GameEvent


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
        with self._lock:
            self.events.append(event)
            if self.jsonl_path:
                with self.jsonl_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def extend(self, events: Iterable[GameEvent]) -> None:
        for event in events:
            self.append(event)

    def snapshot(self) -> list[GameEvent]:
        with self._lock:
            return list(self.events)

    def public_events(self) -> list[GameEvent]:
        return [e for e in self.snapshot() if e.visibility == "public"]

    def visible_events(self, player_id: str) -> list[GameEvent]:
        visible = []
        for event in self.snapshot():
            if event.visibility == "public":
                visible.append(event)
            elif player_id in event.visible_to:
                visible.append(event)
        return visible

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in self.snapshot())
