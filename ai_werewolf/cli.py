from __future__ import annotations

import os
import argparse
import json
from pathlib import Path

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.agents.human_agent import ConsoleHumanAgent
from ai_werewolf.agents.llm_agent import LLMAgent
from ai_werewolf.agents.rule_based_agent import RuleBasedAgent
from ai_werewolf.configs.boards import available_presets, build_config, parse_player_ids, parse_roles
from ai_werewolf.engine.game_engine import AgentFactory, run_game
from ai_werewolf.eval.batch_report import save_batch_html_report
from ai_werewolf.eval.html_report import save_html_replay
from ai_werewolf.eval.leaderboard import build_leaderboard, load_reviews, save_leaderboard, save_leaderboard_markdown
from ai_werewolf.eval.review import build_review, save_review
from ai_werewolf.llm.openai_compatible_provider import OpenAICompatibleConfig, OpenAICompatibleProvider
from ai_werewolf.llm.provider_base import ModelProvider
from ai_werewolf.web.server import WebGameSession, run_web_server


def _add_agent_runtime_args(target: argparse.ArgumentParser, *, default_version: str) -> None:
    target.add_argument("--agent-mode", choices=["rule", "llm"], default="rule", help="AI runtime: local rule agents or real LLM API agents")
    target.add_argument("--llm-provider", choices=["openai-compatible"], default="openai-compatible", help="LLM provider backend")
    target.add_argument("--llm-api-key", type=str, default=None, help="LLM API key; otherwise uses WEREWOLF_LLM_API_KEY or OPENAI_API_KEY")
    target.add_argument("--llm-base-url", type=str, default=None, help="OpenAI-compatible base URL, e.g. https://api.openai.com/v1 or http://localhost:8000/v1")
    target.add_argument("--llm-model", type=str, default=None, help="model name; otherwise uses WEREWOLF_LLM_MODEL / OPENAI_MODEL / gpt-4o-mini")
    target.add_argument("--llm-temperature", type=float, default=None, help="LLM sampling temperature")
    target.add_argument("--llm-max-tokens", type=int, default=None, help="maximum completion tokens per Agent action")
    target.add_argument("--llm-timeout", type=float, default=None, help="HTTP timeout in seconds for each Agent action")
    target.add_argument("--llm-json-mode", action="store_true", help="request response_format={type: json_object}; disable if your compatible server does not support it")
    target.add_argument("--no-llm-rule-fallback", action="store_true", help="raise on LLM call/parse errors instead of falling back to RuleBasedAgent")
    target.set_defaults(version_label=default_version)


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="AI Werewolf multi-agent system v2.1")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run one or more local games; supports pure AI, LLM AI, or console human-AI mixed play")
    run_parser.add_argument("--games", type=int, default=1, help="number of games to run")
    run_parser.add_argument("--seed", type=int, default=42, help="base random seed")
    run_parser.add_argument("--out", type=str, default="logs", help="output directory")
    run_parser.add_argument("--preset", choices=available_presets(), default="6p", help="board preset")
    run_parser.add_argument("--roles", type=str, default=None, help="comma-separated roles; overrides --preset")
    run_parser.add_argument("--human", type=str, default=None, help="comma-separated human player IDs, e.g. P1,P3; console input mode")
    run_parser.add_argument("--max-days", type=int, default=10, help="maximum day/night rounds before forced wolf win")
    run_parser.add_argument("--tie-policy", choices=["no_exile", "random"], default="no_exile", help="day vote tie policy")
    run_parser.add_argument("--reveal-death-role", action="store_true", help="publicly reveal roles when players die")
    run_parser.add_argument("--version-label", type=str, default="rule_based_v2_1", help="agent/model version label stored in reviews and leaderboard")
    run_parser.add_argument("--no-leak-check", action="store_true", help="disable development leak checker")
    _add_agent_runtime_args(run_parser, default_version="rule_based_v2_1")

    sub.add_parser("boards", help="show available board presets")

    leaderboard_parser = sub.add_parser("leaderboard", help="build leaderboard from review JSON files or a log directory")
    leaderboard_parser.add_argument("paths", nargs="+", help="review JSON files or directories containing *_review.json")
    leaderboard_parser.add_argument("--out", type=str, default="leaderboard.json", help="leaderboard JSON output path")
    leaderboard_parser.add_argument("--markdown", type=str, default=None, help="optional markdown output path")
    leaderboard_parser.add_argument("--html", type=str, default=None, help="optional HTML output path")

    serve_parser = sub.add_parser("serve", help="start local browser UI for live spectating and human-AI mixed play")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--seed", type=int, default=42)
    serve_parser.add_argument("--out", type=str, default="logs/web")
    serve_parser.add_argument("--preset", choices=available_presets(), default="10p-standard")
    serve_parser.add_argument("--roles", type=str, default=None)
    serve_parser.add_argument("--human", type=str, default="P1", help="comma-separated browser-controlled human players; empty for pure AI")
    serve_parser.add_argument("--max-days", type=int, default=10)
    serve_parser.add_argument("--tie-policy", choices=["no_exile", "random"], default="no_exile")
    serve_parser.add_argument("--reveal-death-role", action="store_true")
    serve_parser.add_argument("--version-label", type=str, default="web_rule_based_v2_1")
    serve_parser.add_argument("--no-leak-check", action="store_true")
    _add_agent_runtime_args(serve_parser, default_version="web_rule_based_v2_1")

    args = parser.parse_args()
    try:
        if args.command == "run":
            _run_games(args)
        elif args.command == "boards":
            print("Available board presets:")
            for preset in available_presets():
                config = build_config(preset=preset)
                print(f"- {preset}: {config.player_count} players -> {', '.join(config.roles)}")
        elif args.command == "leaderboard":
            _build_leaderboard(args)
        elif args.command == "serve":
            _serve(args)
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")


def _build_model_provider(args: argparse.Namespace) -> ModelProvider:
    if args.llm_provider != "openai-compatible":
        raise ValueError(f"unsupported llm provider: {args.llm_provider}")
    config = OpenAICompatibleConfig.from_env(
        api_key=args.llm_api_key,
        model=args.llm_model,
        base_url=args.llm_base_url,
        temperature=args.llm_temperature,
        max_tokens=args.llm_max_tokens,
        timeout=args.llm_timeout,
        json_mode=args.llm_json_mode,
    )
    return OpenAICompatibleProvider(config)


def _build_agent_factory(args: argparse.Namespace, human_players: list[str], *, web_session=None) -> AgentFactory:
    provider: ModelProvider | None = None
    if args.agent_mode == "llm":
        provider = _build_model_provider(args)

    def factory(player_id: str, seed: int | None = None) -> BaseAgent:
        if player_id in human_players:
            if web_session is not None:
                from ai_werewolf.web.server import BrowserHumanAgent
                return BrowserHumanAgent(player_id, web_session)
            return ConsoleHumanAgent(player_id)
        if args.agent_mode == "llm":
            assert provider is not None
            fallback = None if args.no_llm_rule_fallback else RuleBasedAgent(player_id, seed=seed)
            return LLMAgent(player_id, provider, fallback_agent=fallback)
        return RuleBasedAgent(player_id, seed=seed)

    return factory


def _run_games(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch = []
    reviews = []
    roles = parse_roles(args.roles) if args.roles else None
    human_players = parse_player_ids(args.human)
    if human_players and args.games != 1:
        raise ValueError("console human mixed play supports --games 1 only")
    agent_factory = _build_agent_factory(args, human_players)
    for i in range(args.games):
        seed = args.seed + i
        config = build_config(
            preset=args.preset,
            roles=roles,
            seed=seed,
            max_days=args.max_days,
            tie_policy=args.tie_policy,
            human_players=human_players,
            reveal_death_role=args.reveal_death_role,
            version_label=args.version_label,
        )
        log_path = out_dir / f"game_{i+1:03d}_seed_{seed}.jsonl"
        state, store = run_game(config=config, log_path=log_path, enable_leak_check=not args.no_leak_check, agent_factory=agent_factory)
        review = build_review(state, store)
        reviews.append(review)
        review_path = out_dir / f"game_{i+1:03d}_seed_{seed}_review.json"
        save_review(review, review_path)
        html_path = out_dir / f"game_{i+1:03d}_seed_{seed}_replay.html"
        save_html_replay(review, store, html_path)
        batch.append({
            "game_index": i + 1,
            "seed": seed,
            "preset": args.preset if roles is None else "custom",
            "roles": config.roles,
            "human_players": human_players,
            "version_label": args.version_label,
            "agent_mode": args.agent_mode,
            "llm_provider": args.llm_provider if args.agent_mode == "llm" else None,
            "llm_model": getattr(agent_factory, "llm_model", args.llm_model) if args.agent_mode == "llm" else None,
            "game_id": state.game_id,
            "winner": state.winner,
            "win_reason": state.win_reason,
            "rounds": state.round_index,
            "log_path": str(log_path),
            "review_path": str(review_path),
            "html_replay_path": str(html_path),
        })
        print(f"[{i+1}/{args.games}] {state.game_id}: winner={state.winner}, rounds={state.round_index}")
        print(f"  log: {log_path}")
        print(f"  review: {review_path}")
        print(f"  html: {html_path}")
    summary_path = out_dir / "batch_summary.json"
    summary_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    leaderboard = build_leaderboard(reviews)
    leaderboard_json = out_dir / "leaderboard.json"
    leaderboard_md = out_dir / "leaderboard.md"
    leaderboard_html = out_dir / "leaderboard.html"
    save_leaderboard(leaderboard, leaderboard_json)
    save_leaderboard_markdown(leaderboard, leaderboard_md)
    save_batch_html_report(leaderboard, leaderboard_html)
    print(f"batch summary: {summary_path}")
    print(f"leaderboard json: {leaderboard_json}")
    print(f"leaderboard md: {leaderboard_md}")
    print(f"leaderboard html: {leaderboard_html}")


def _build_leaderboard(args: argparse.Namespace) -> None:
    reviews = load_reviews([Path(p) for p in args.paths])
    leaderboard = build_leaderboard(reviews)
    save_leaderboard(leaderboard, args.out)
    print(f"loaded reviews: {len(reviews)}")
    print(f"leaderboard json: {args.out}")
    if args.markdown:
        save_leaderboard_markdown(leaderboard, args.markdown)
        print(f"leaderboard markdown: {args.markdown}")
    if args.html:
        save_batch_html_report(leaderboard, args.html)
        print(f"leaderboard html: {args.html}")


def _serve(args: argparse.Namespace) -> None:
    roles = parse_roles(args.roles) if args.roles else None
    human_players = parse_player_ids(args.human)
    config = build_config(
        preset=args.preset,
        roles=roles,
        seed=args.seed,
        max_days=args.max_days,
        tie_policy=args.tie_policy,
        human_players=human_players,
        reveal_death_role=args.reveal_death_role,
        version_label=args.version_label,
    )
    session = WebGameSession(config=config, out_dir=args.out, enable_leak_check=not args.no_leak_check)
    session.agent_factory = _build_agent_factory(args, human_players, web_session=session)
    run_web_server(session, host=args.host, port=args.port)

def _load_dotenv(path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ.

    Existing environment variables are not overwritten.
    Supports blank lines and comments starting with #.
    """
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

if __name__ == "__main__":
    main()
