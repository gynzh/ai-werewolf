from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ai_werewolf.logging.event_store import EventStore
from ai_werewolf.models.schema import Faction, GameState, Role
from ai_werewolf.rules.roles import faction_name_cn, role_name_cn


def build_review(state: GameState, store: EventStore) -> dict[str, Any]:
    events = store.snapshot()
    public_events = [e for e in events if e.visibility == "public"]
    role_map = {pid: p.role for pid, p in state.players.items()}
    faction_map = {pid: p.faction for pid, p in state.players.items()}

    votes = [e for e in public_events if e.event_type == "vote_cast"]
    speeches = [e for e in public_events if e.event_type == "player_speech"]
    deaths = _deaths(state)
    night_hidden = [e for e in events if e.event_type == "night_resolved_hidden"]
    wolf_kill_hits = _wolf_kill_targets(night_hidden, role_map, faction_map)
    seer_checks = _seer_checks(events)
    witch_actions = _witch_actions(events)
    guard_actions = _guard_actions(events)
    hunter_actions = _hunter_actions(events, role_map, faction_map)
    exiles = _exiles(public_events, role_map, faction_map)
    vote_accuracy = _vote_accuracy(votes, faction_map)
    process_metrics = _process_metrics(events, state, vote_accuracy, wolf_kill_hits, seer_checks, witch_actions, guard_actions, hunter_actions)
    player_reports = _player_reports(state, votes, speeches, deaths)
    turning_points = _turning_points(deaths, exiles, seer_checks, wolf_kill_hits, hunter_actions, state)

    return {
        "schema_version": "2.0",
        "game_id": state.game_id,
        "winner": state.winner,
        "winner_cn": faction_name_cn(state.winner or ""),
        "win_reason": state.win_reason,
        "rounds": state.round_index,
        "days": state.day_index,
        "config": {
            "player_count": state.config.player_count,
            "roles": state.config.roles,
            "win_mode": state.config.win_mode,
            "tie_policy": state.config.tie_policy,
            "max_days": state.config.max_days,
            "random_seed": state.config.random_seed,
            "human_players": state.config.human_players,
            "version_label": state.config.version_label,
        },
        "roles": {
            pid: {
                "seat": p.seat,
                "name": p.name,
                "role": p.role,
                "role_cn": role_name_cn(p.role),
                "faction": p.faction,
                "faction_cn": faction_name_cn(p.faction),
                "alive": p.alive,
                "death_reason": p.death_reason,
                "is_human": p.is_human,
            }
            for pid, p in sorted(state.players.items(), key=lambda item: item[1].seat)
        },
        "deaths": deaths,
        "metrics": {
            "total_events": len(events),
            "public_events": len(public_events),
            "private_events": len([e for e in events if e.visibility == "private"]),
            "faction_events": len([e for e in events if e.visibility == "faction"]),
            "system_events": len([e for e in events if e.visibility == "system"]),
            "speech_count_by_player": dict(Counter(e.actor_id for e in speeches)),
            "vote_accuracy_good_to_wolf": vote_accuracy["good_to_wolf_rate"],
            "vote_accuracy_wolf_to_good": vote_accuracy["wolf_to_good_rate"],
            "seer_checks": seer_checks,
            "witch_actions": witch_actions,
            "guard_actions": guard_actions,
            "hunter_actions": hunter_actions,
            "wolf_kill_targets": wolf_kill_hits,
            "exiles": exiles,
            "process_metrics": process_metrics,
            "player_reports": player_reports,
        },
        "turning_points": turning_points,
        "summary": _summary_text(state, deaths, turning_points, process_metrics),
    }


def _deaths(state: GameState) -> list[dict[str, Any]]:
    return [
        {
            "player_id": p.player_id,
            "seat": p.seat,
            "role": p.role,
            "role_cn": role_name_cn(p.role),
            "faction": p.faction,
            "faction_cn": faction_name_cn(p.faction),
            "death_round": p.death_round,
            "death_reason": p.death_reason,
        }
        for p in sorted(state.players.values(), key=lambda x: x.seat)
        if not p.alive
    ]


def _wolf_kill_targets(events: list[Any], role_map: dict[str, str], faction_map: dict[str, str]) -> list[dict[str, Any]]:
    hits = []
    for event in events:
        target = event.payload.get("attacked_player_id")
        if target:
            hits.append({
                "night": event.night_index,
                "target": target,
                "target_role": role_map.get(target),
                "target_role_cn": role_name_cn(role_map.get(target, "")),
                "target_faction": faction_map.get(target),
                "saved_by_witch": event.payload.get("saved_player_id") == target,
                "saved_by_guard": event.payload.get("guarded_player_id") == target,
                "killed": target in [d.get("player_id") for d in event.payload.get("deaths", [])],
            })
    return hits


def _seer_checks(events: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "night": e.night_index,
            "seer": e.actor_id,
            "target": e.payload.get("target_player_id"),
            "target_faction": e.payload.get("target_faction"),
            "target_faction_cn": faction_name_cn(e.payload.get("target_faction", "")),
        }
        for e in events
        if e.event_type == "seer_check_result"
    ]


def _witch_actions(events: list[Any]) -> list[dict[str, Any]]:
    actions = []
    for e in events:
        if e.event_type != "witch_action_taken":
            continue
        payload = e.payload or {}
        actions.append({"night": e.night_index, "witch": e.actor_id, "action_type": payload.get("action_type"), "target": payload.get("target_player_id"), "reasoning_summary": payload.get("reasoning_summary")})
    return actions


def _guard_actions(events: list[Any]) -> list[dict[str, Any]]:
    actions = []
    for e in events:
        if e.event_type != "guard_action_taken":
            continue
        payload = e.payload or {}
        actions.append({"night": e.night_index, "guard": e.actor_id, "action_type": payload.get("action_type"), "target": payload.get("target_player_id"), "reasoning_summary": payload.get("reasoning_summary")})
    return actions


def _hunter_actions(events: list[Any], role_map: dict[str, str], faction_map: dict[str, str]) -> list[dict[str, Any]]:
    actions = []
    for e in events:
        if e.event_type != "hunter_shot":
            continue
        target = e.payload.get("target_player_id")
        actions.append({"round": e.round_index, "hunter": e.payload.get("hunter_player_id"), "target": target, "target_role": role_map.get(target), "target_faction": faction_map.get(target), "reasoning_summary": e.payload.get("reasoning_summary")})
    return actions


def _exiles(public_events: list[Any], role_map: dict[str, str], faction_map: dict[str, str]) -> list[dict[str, Any]]:
    exiles = []
    for e in public_events:
        if e.event_type != "exile_resolved":
            continue
        target = e.payload.get("exiled_player_id")
        exiles.append({"day": e.day_index, "target": target, "target_role": role_map.get(target) if target else None, "target_role_cn": role_name_cn(role_map.get(target, "")) if target else None, "target_faction": faction_map.get(target) if target else None, "votes": e.payload.get("votes", {}), "reason": e.payload.get("reason")})
    return exiles


def _player_reports(state: GameState, votes: list[Any], speeches: list[Any], deaths: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    votes_cast = Counter(e.actor_id for e in votes)
    votes_received = Counter(e.payload.get("target_player_id") for e in votes)
    wolf_votes_cast = Counter()
    good_votes_cast = Counter()
    for e in votes:
        actor = e.actor_id
        target = e.payload.get("target_player_id")
        if not actor or not target:
            continue
        target_faction = state.players[target].faction
        if target_faction == Faction.WOLVES.value:
            wolf_votes_cast[actor] += 1
        else:
            good_votes_cast[actor] += 1
    speech_counts = Counter(e.actor_id for e in speeches)
    death_by_player = {d["player_id"]: d for d in deaths}
    reports = {}
    for pid, p in sorted(state.players.items(), key=lambda item: item[1].seat):
        reports[pid] = {
            "seat": p.seat,
            "role": p.role,
            "role_cn": role_name_cn(p.role),
            "faction": p.faction,
            "alive": p.alive,
            "death_reason": death_by_player.get(pid, {}).get("death_reason"),
            "speeches": speech_counts.get(pid, 0),
            "votes_cast": votes_cast.get(pid, 0),
            "votes_received": votes_received.get(pid, 0),
            "votes_to_wolves": wolf_votes_cast.get(pid, 0),
            "votes_to_good": good_votes_cast.get(pid, 0),
        }
    return reports


def _vote_accuracy(votes: list[Any], faction_map: dict[str, str]) -> dict[str, float | None]:
    good_votes = good_to_wolf = wolf_votes = wolf_to_good = 0
    for event in votes:
        actor = event.actor_id
        target = event.payload.get("target_player_id")
        if not actor or not target:
            continue
        if faction_map.get(actor) == Faction.GOOD.value:
            good_votes += 1
            if faction_map.get(target) == Faction.WOLVES.value:
                good_to_wolf += 1
        elif faction_map.get(actor) == Faction.WOLVES.value:
            wolf_votes += 1
            if faction_map.get(target) == Faction.GOOD.value:
                wolf_to_good += 1
    return {"good_to_wolf_rate": round(good_to_wolf / good_votes, 3) if good_votes else None, "wolf_to_good_rate": round(wolf_to_good / wolf_votes, 3) if wolf_votes else None}


def _process_metrics(events: list[Any], state: GameState, vote_accuracy: dict[str, Any], wolf_kill_hits: list[dict[str, Any]], seer_checks: list[dict[str, Any]], witch_actions: list[dict[str, Any]], guard_actions: list[dict[str, Any]], hunter_actions: list[dict[str, Any]]) -> dict[str, Any]:
    fallbacks = [e for e in events if e.event_type == "agent_action_fallback"]
    agent_received = [e for e in events if e.event_type == "agent_action_received"]
    agent_taken = [e for e in events if e.event_type == "agent_action_taken"]
    llm_actions = [e for e in agent_received if str((e.payload.get("metadata") or {}).get("agent_mode", "")).startswith("llm")]
    llm_rule_fallbacks = [e for e in llm_actions if (e.payload.get("metadata") or {}).get("agent_mode") == "llm_with_rule_fallback"]
    llm_errors = [e for e in llm_actions if (e.payload.get("metadata") or {}).get("llm_error")]
    llm_latencies = [float((e.payload.get("metadata") or {}).get("llm_latency_seconds")) for e in llm_actions if (e.payload.get("metadata") or {}).get("llm_latency_seconds") is not None]
    wolf_kills_good = [h for h in wolf_kill_hits if h.get("target_faction") == Faction.GOOD.value]
    wolf_kills_god = [h for h in wolf_kill_hits if h.get("target_role") in {Role.SEER.value, Role.WITCH.value, Role.HUNTER.value, Role.GUARD.value}]
    seer_found_wolf = [c for c in seer_checks if c.get("target_faction") == Faction.WOLVES.value]
    witch_poison = [a for a in witch_actions if a.get("action_type") == "witch_poison"]
    guard_saves = [h for h in wolf_kill_hits if h.get("saved_by_guard")]
    return {
        "fallback_count": len(fallbacks),
        "fallback_rate_per_event": round(len(fallbacks) / len(events), 3) if events else 0,
        "agent_action_count": len(agent_taken),
        "agent_action_received_count": len(agent_received),
        "llm_action_count": len(llm_actions),
        "llm_rule_fallback_count": len(llm_rule_fallbacks),
        "llm_error_count": len(llm_errors),
        "llm_avg_latency_seconds": round(sum(llm_latencies) / len(llm_latencies), 3) if llm_latencies else None,
        "wolf_kill_good_rate": round(len(wolf_kills_good) / len(wolf_kill_hits), 3) if wolf_kill_hits else None,
        "wolf_kill_god_rate": round(len(wolf_kills_god) / len(wolf_kill_hits), 3) if wolf_kill_hits else None,
        "seer_found_wolf_count": len(seer_found_wolf),
        "witch_poison_count": len(witch_poison),
        "guard_protect_count": len([a for a in guard_actions if a.get("action_type") == "guard_protect"]),
        "guard_successful_save_count": len(guard_saves),
        "hunter_shot_count": len(hunter_actions),
        "good_vote_to_wolf_rate": vote_accuracy.get("good_to_wolf_rate"),
        "wolf_vote_to_good_rate": vote_accuracy.get("wolf_to_good_rate"),
    }


def _turning_points(deaths: list[dict[str, Any]], exiles: list[dict[str, Any]], seer_checks: list[dict[str, Any]], wolf_kill_hits: list[dict[str, Any]], hunter_actions: list[dict[str, Any]], state: GameState) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for death in deaths:
        if death["role"] == Role.SEER.value and death["death_reason"] == "exiled":
            points.append({"round": death["death_round"], "description": "预言家被白天放逐，好人信息链受损。", "impact": "high"})
        if death["role"] == Role.WEREWOLF.value and death["death_reason"] in {"exiled", "hunter_shot", "witch_poison"}:
            points.append({"round": death["death_round"], "description": f"狼人因 {death['death_reason']} 出局，好人阵营获得关键优势。", "impact": "high"})
    for exile in exiles:
        if exile.get("target_faction") == Faction.GOOD.value:
            points.append({"round": exile.get("day"), "description": f"白天放逐了好人 {exile.get('target')}，狼人阵营获得节奏收益。", "impact": "medium"})
    if any(hit.get("target_role") == Role.SEER.value and hit.get("killed") for hit in wolf_kill_hits):
        points.append({"round": None, "description": "狼人夜间成功击杀预言家，好人信息来源受损。", "impact": "high"})
    if any(hit.get("saved_by_guard") or hit.get("saved_by_witch") for hit in wolf_kill_hits):
        points.append({"round": None, "description": "好人神职成功阻止至少一次狼刀，改变夜间减员节奏。", "impact": "medium"})
    if any(check.get("target_faction") == Faction.WOLVES.value for check in seer_checks):
        points.append({"round": None, "description": "预言家查到狼人，场上出现关键身份信息。", "impact": "medium"})
    if any(a.get("target_faction") == Faction.WOLVES.value for a in hunter_actions):
        points.append({"round": None, "description": "猎人开枪命中狼人，显著改变人数结构。", "impact": "high"})
    if not points:
        points.append({"round": state.round_index, "description": "本局胜负主要由常规发言、投票与夜间击杀累积决定。", "impact": "low"})
    return points


def _summary_text(state: GameState, deaths: list[dict[str, Any]], turning_points: list[dict[str, Any]], process_metrics: dict[str, Any]) -> str:
    winner = faction_name_cn(state.winner or "")
    death_desc = "、".join(f"{d['player_id']}({d['role_cn']},{d['death_reason']})" for d in deaths) or "无人死亡"
    turn_desc = "；".join(tp["description"] for tp in turning_points[:3])
    llm_desc = ""
    if process_metrics.get("llm_action_count"):
        llm_desc = f"LLM 行动次数：{process_metrics.get('llm_action_count')}，LLM 回退次数：{process_metrics.get('llm_rule_fallback_count')}。"
    return f"本局共进行 {state.round_index} 轮，{winner}获胜。死亡记录：{death_desc}。好人投狼率：{_pct(process_metrics.get('good_vote_to_wolf_rate'))}；狼人投好人率：{_pct(process_metrics.get('wolf_vote_to_good_rate'))}。{llm_desc}关键转折：{turn_desc}"


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"


def save_review(review: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
