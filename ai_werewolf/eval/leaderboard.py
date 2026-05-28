from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ai_werewolf.models.schema import Faction


def load_reviews(review_paths: list[str | Path]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in review_paths:
        path = Path(path)
        if path.is_dir():
            reviews.extend(load_reviews(sorted(path.glob("**/*_review.json"))))
            continue
        if path.name.endswith("_review.json"):
            reviews.append(json.loads(path.read_text(encoding="utf-8")))
    return reviews


def build_leaderboard(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "total_games": len(reviews),
        "overall": _aggregate(reviews),
        "by_version": {version: _aggregate(items) for version, items in sorted(_group_by_version(reviews).items())},
        "role_survival": _role_survival(reviews),
        "role_win_rate": _role_win_rate(reviews),
        "games": [
            {
                "game_id": review.get("game_id"),
                "version_label": review.get("config", {}).get("version_label", "unknown"),
                "winner": review.get("winner"),
                "rounds": review.get("rounds"),
                "preset_roles": review.get("config", {}).get("roles"),
                "summary": review.get("summary"),
                "good_vote_to_wolf_rate": review.get("metrics", {}).get("process_metrics", {}).get("good_vote_to_wolf_rate"),
                "fallback_count": review.get("metrics", {}).get("process_metrics", {}).get("fallback_count"),
                "llm_action_count": review.get("metrics", {}).get("process_metrics", {}).get("llm_action_count"),
                "llm_rule_fallback_count": review.get("metrics", {}).get("process_metrics", {}).get("llm_rule_fallback_count"),
            }
            for review in reviews
        ],
    }


def save_leaderboard(leaderboard: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(leaderboard, ensure_ascii=False, indent=2), encoding="utf-8")


def save_leaderboard_markdown(leaderboard: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    overall = leaderboard.get("overall", {})
    lines = [
        "# AI 狼人杀 v2.0 批量评测 Leaderboard",
        "",
        f"- 总局数：{leaderboard.get('total_games', 0)}",
        f"- 好人胜率：{_pct(overall.get('good_win_rate'))}",
        f"- 狼人胜率：{_pct(overall.get('wolves_win_rate'))}",
        f"- 平均轮数：{overall.get('avg_rounds')}",
        f"- 好人投狼率：{_pct(overall.get('avg_good_vote_to_wolf_rate'))}",
        f"- 狼人投好人率：{_pct(overall.get('avg_wolf_vote_to_good_rate'))}",
        f"- 平均 fallback 数：{overall.get('avg_fallback_count')}",
        f"- 平均 LLM 行动数：{overall.get('avg_llm_action_count')}",
        f"- 平均 LLM 回退数：{overall.get('avg_llm_rule_fallback_count')}",
        "",
        "## 按版本统计",
        "",
        "| 版本 | 局数 | 好人胜率 | 狼人胜率 | 平均轮数 | 平均 fallback | 平均 LLM 行动 | 平均 LLM 回退 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for version, stats in leaderboard.get("by_version", {}).items():
        lines.append(f"| {version} | {stats.get('total_games')} | {_pct(stats.get('good_win_rate'))} | {_pct(stats.get('wolves_win_rate'))} | {stats.get('avg_rounds')} | {stats.get('avg_fallback_count')} | {stats.get('avg_llm_action_count')} | {stats.get('avg_llm_rule_fallback_count')} |")
    lines.extend(["", "## 角色存活统计", "", "| 角色 | 出场数 | 存活数 | 存活率 |", "|---|---:|---:|---:|"])
    for role, info in sorted(leaderboard.get("role_survival", {}).items()):
        lines.append(f"| {role} | {info['appearances']} | {info['survived']} | {_pct(info['survival_rate'])} |")
    lines.extend(["", "## 角色胜率", "", "| 角色 | 出场数 | 获胜数 | 胜率 |", "|---|---:|---:|---:|"])
    for role, info in sorted(leaderboard.get("role_win_rate", {}).items()):
        lines.append(f"| {role} | {info['appearances']} | {info['wins']} | {_pct(info['win_rate'])} |")
    lines.extend(["", "## 对局摘要", "", "| Game ID | 版本 | 胜者 | 轮数 | 摘要 |", "|---|---|---|---:|---|"])
    for game in leaderboard.get("games", []):
        summary = str(game.get("summary", "")).replace("|", "\\|")
        lines.append(f"| {game.get('game_id')} | {game.get('version_label')} | {game.get('winner')} | {game.get('rounds')} | {summary} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _group_by_version(reviews: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        groups[review.get("config", {}).get("version_label", "unknown")].append(review)
    return groups


def _aggregate(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(reviews)
    winners = Counter(review.get("winner") for review in reviews)
    rounds = [int(review.get("rounds", 0) or 0) for review in reviews]
    good_vote_rates = [_metric(review, "good_vote_to_wolf_rate") for review in reviews if _metric(review, "good_vote_to_wolf_rate") is not None]
    wolf_vote_rates = [_metric(review, "wolf_vote_to_good_rate") for review in reviews if _metric(review, "wolf_vote_to_good_rate") is not None]
    fallback_counts = [_metric(review, "fallback_count") or 0 for review in reviews]
    llm_action_counts = [_metric(review, "llm_action_count") or 0 for review in reviews]
    llm_rule_fallback_counts = [_metric(review, "llm_rule_fallback_count") or 0 for review in reviews]
    llm_error_counts = [_metric(review, "llm_error_count") or 0 for review in reviews]
    return {
        "total_games": total,
        "winner_counts": dict(winners),
        "good_win_rate": _rate(winners.get(Faction.GOOD.value, 0), total),
        "wolves_win_rate": _rate(winners.get(Faction.WOLVES.value, 0), total),
        "avg_rounds": round(sum(rounds) / total, 3) if total else None,
        "avg_good_vote_to_wolf_rate": _avg(good_vote_rates),
        "avg_wolf_vote_to_good_rate": _avg(wolf_vote_rates),
        "avg_fallback_count": round(sum(fallback_counts) / total, 3) if total else None,
        "avg_llm_action_count": round(sum(llm_action_counts) / total, 3) if total else None,
        "avg_llm_rule_fallback_count": round(sum(llm_rule_fallback_counts) / total, 3) if total else None,
        "avg_llm_error_count": round(sum(llm_error_counts) / total, 3) if total else None,
    }


def _metric(review: dict[str, Any], key: str) -> Any:
    pm = review.get("metrics", {}).get("process_metrics", {})
    if key in pm:
        return pm[key]
    return review.get("metrics", {}).get(key)


def _role_survival(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, Counter] = {}
    for review in reviews:
        for info in review.get("roles", {}).values():
            role = info.get("role", "unknown")
            stats.setdefault(role, Counter())
            stats[role]["appearances"] += 1
            if info.get("alive"):
                stats[role]["survived"] += 1
    return {role: {"appearances": c["appearances"], "survived": c["survived"], "survival_rate": _rate(c["survived"], c["appearances"])} for role, c in stats.items()}


def _role_win_rate(reviews: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, Counter] = {}
    for review in reviews:
        winner = review.get("winner")
        for info in review.get("roles", {}).values():
            role = info.get("role", "unknown")
            stats.setdefault(role, Counter())
            stats[role]["appearances"] += 1
            if info.get("faction") == winner:
                stats[role]["wins"] += 1
    return {role: {"appearances": c["appearances"], "wins": c["wins"], "win_rate": _rate(c["wins"], c["appearances"])} for role, c in stats.items()}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"
