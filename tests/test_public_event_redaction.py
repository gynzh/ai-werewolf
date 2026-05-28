from __future__ import annotations

import json

from ai_werewolf.logging.event_store import EventStore
from ai_werewolf.models.schema import GameEvent


def _event(payload: dict) -> GameEvent:
    return GameEvent.create(
        game_id="g_test",
        round_index=1,
        day_index=1,
        night_index=0,
        phase="day_discussion",
        visibility="public",
        visible_to=["all"],
        actor_id="P2",
        event_type="player_speech",
        payload=payload,
    )


def test_public_events_remove_private_reasoning_from_memory_and_jsonl(tmp_path):
    path = tmp_path / "game.jsonl"
    store = EventStore(path)
    store.append(
        _event(
            {
                "content": "我是好人，P3 发言偏划水。",
                "reasoning_summary": "作为狼人，我要隐藏身份并带票 P3。",
                "confidence": 0.8,
                "metadata": {"model": "demo", "llm_error": "secret provider error"},
            }
        )
    )

    public_payload = store.public_events()[0].payload
    assert public_payload == {
        "content": "我是好人，P3 发言偏划水。",
        "confidence": 0.8,
        "metadata": {"model": "demo"},
    }

    text = path.read_text(encoding="utf-8")
    assert "作为狼人" not in text
    assert "reasoning_summary" not in text
    assert "llm_error" not in text

    row = json.loads(text)
    assert row["payload"]["content"] == "我是好人，P3 发言偏划水。"


def test_private_events_keep_reasoning_for_review():
    store = EventStore()
    private = GameEvent.create(
        game_id="g_test",
        round_index=1,
        day_index=0,
        night_index=1,
        phase="seer_check",
        visibility="private",
        visible_to=["P3"],
        actor_id="P3",
        event_type="seer_check_result",
        payload={"action_reasoning_summary": "我查验 P5 是狼人。"},
    )
    store.append(private)
    assert store.visible_events("P3")[0].payload["action_reasoning_summary"] == "我查验 P5 是狼人。"
