from __future__ import annotations

import json
import mimetypes
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ai_werewolf.agents.base_agent import BaseAgent
from ai_werewolf.agents.rule_based_agent import RuleBasedAgent
from ai_werewolf.engine.game_engine import GameEngine
from ai_werewolf.eval.html_report import save_html_replay
from ai_werewolf.eval.review import build_review, save_review
from ai_werewolf.logging.event_store import EventStore
from ai_werewolf.models.schema import Action, AgentObservation, GameConfig
from ai_werewolf.rules.roles import faction_name_cn, role_name_cn

STATIC_DIR = Path(__file__).with_name("static")


class BrowserHumanAgent(BaseAgent):
    def __init__(self, player_id: str, session: "WebGameSession") -> None:
        super().__init__(player_id)
        self.session = session

    def act(self, observation: AgentObservation) -> Action:
        return self.session.wait_for_action(self.player_id, observation)


class WebGameSession:
    def __init__(
        self,
        config: GameConfig,
        out_dir: str | Path,
        enable_leak_check: bool = True,
        agent_factory: Callable[[str, int | None], BaseAgent] | None = None,
    ) -> None:
        self.config = config
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.out_dir / f"web_game_seed_{config.random_seed}.jsonl"
        self.review_path = self.out_dir / f"web_game_seed_{config.random_seed}_review.json"
        self.html_path = self.out_dir / f"web_game_seed_{config.random_seed}_replay.html"
        self.store = EventStore(self.log_path)
        self.engine: GameEngine | None = None
        self.state = None
        self.review: dict[str, Any] | None = None
        self.error: str | None = None
        self.done = False
        self.started = False
        self.enable_leak_check = enable_leak_check
        self.agent_factory = agent_factory
        self.agent_mode = "rule"
        self.llm_agent_config_path: str | None = None
        self._condition = threading.Condition()
        self._pending: dict[str, AgentObservation] = {}
        self._submitted: dict[str, Action] = {}
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._thread = threading.Thread(target=self._run, name="werewolf-web-game", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            def default_factory(pid: str, seed: int | None = None) -> BaseAgent:
                if pid in self.config.human_players:
                    return BrowserHumanAgent(pid, self)
                return RuleBasedAgent(pid, seed=seed)

            factory = self.agent_factory or default_factory
            self.engine = GameEngine(
                config=self.config,
                event_store=self.store,
                agent_factory=factory,
                enable_leak_check=self.enable_leak_check,
            )
            self.state = self.engine.run()
            self.review = build_review(self.state, self.store)
            save_review(self.review, self.review_path)
            save_html_replay(self.review, self.store, self.html_path)
        except Exception as exc:  # pragma: no cover - surfaced in browser/API
            self.error = repr(exc)
        finally:
            with self._condition:
                self.done = True
                self._pending.clear()
                self._condition.notify_all()

    def wait_for_action(self, player_id: str, observation: AgentObservation) -> Action:
        with self._condition:
            self._pending[player_id] = observation
            self._submitted.pop(player_id, None)
            self._condition.notify_all()
            while player_id not in self._submitted and not self.done:
                self._condition.wait(timeout=0.5)
            if player_id in self._submitted:
                action = self._submitted.pop(player_id)
                self._pending.pop(player_id, None)
                self._condition.notify_all()
                return action
        return Action(player_id=player_id, action_type="skip", reasoning_summary="web session ended before action")

    def submit_action(self, data: dict[str, Any]) -> None:
        player_id = str(data.get("player_id", "")).upper()
        if not player_id:
            raise ValueError("player_id is required")
        action = Action(
            player_id=player_id,
            action_type=str(data.get("action_type", "skip")),
            target_player_id=(str(data.get("target_player_id")).upper() if data.get("target_player_id") else None),
            content=data.get("content") or None,
            reasoning_summary="浏览器人类玩家输入",
            confidence=1.0,
            metadata={"source": "browser_human"},
        )
        with self._condition:
            if player_id not in self._pending:
                raise ValueError(f"no pending action for {player_id}")
            self._submitted[player_id] = action
            self._condition.notify_all()

    def public_state(self, god: bool = False) -> dict[str, Any]:
        state = self.engine.state if self.engine else self.state
        players_public = []
        players_god = []
        if state:
            for player in sorted(state.players.values(), key=lambda x: x.seat):
                base = player.public_view()
                players_public.append(base)
                players_god.append(
                    {
                        **base,
                        "role": player.role,
                        "role_cn": role_name_cn(player.role),
                        "faction": player.faction,
                        "faction_cn": faction_name_cn(player.faction),
                    }
                )
        return {
            "started": self.started,
            "done": self.done,
            "error": self.error,
            "game_id": state.game_id if state else None,
            "phase": state.phase if state else None,
            "round_index": state.round_index if state else 0,
            "day_index": state.day_index if state else 0,
            "night_index": state.night_index if state else 0,
            "winner": state.winner if state else None,
            "win_reason": state.win_reason if state else None,
            "human_players": self.config.human_players,
            "agent_mode": self.agent_mode,
            "version_label": self.config.version_label,
            "players": players_god if god else players_public,
            "public_events": [e.to_dict() for e in self.store.public_events()],
            "pending_players": sorted(self._pending.keys()),
            "artifacts": {
                "log_path": str(self.log_path),
                "review_path": str(self.review_path),
                "html_path": str(self.html_path),
            },
            "llm_agent_configs": self._llm_agent_config_summaries(),
        }

    def review_state(self) -> dict[str, Any] | None:
        return self.review

    def pending_observation(self, player_id: str) -> dict[str, Any] | None:
        with self._condition:
            obs = self._pending.get(player_id.upper())
        return asdict(obs) if obs else None

    def _llm_agent_config_summaries(self) -> dict[str, Any]:
        factory = self.agent_factory
        if factory is None:
            return {}
        value = getattr(factory, "llm_provider_summaries", {})
        return dict(value) if isinstance(value, dict) else {}


def run_web_server(session: WebGameSession, host: str = "127.0.0.1", port: int = 8765) -> None:
    session.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_static(STATIC_DIR / "index.html")
                return
            if parsed.path.startswith("/static/"):
                self._send_static(STATIC_DIR / parsed.path.removeprefix("/static/"))
                return
            if parsed.path == "/api/state":
                qs = parse_qs(parsed.query)
                god = qs.get("god", ["0"])[0] in {"1", "true", "yes"}
                self._send_json(session.public_state(god=god))
                return
            if parsed.path == "/api/review":
                self._send_json({"review": session.review_state()})
                return
            if parsed.path == "/api/pending":
                qs = parse_qs(parsed.query)
                player_id = qs.get("player_id", [""])[0].upper()
                self._send_json({"pending": session.pending_observation(player_id)})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/action":
                length = int(self.headers.get("content-length", "0") or "0")
                data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                try:
                    session.submit_action(data)
                    self._send_json({"ok": True})
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, path: Path) -> None:
            safe_root = STATIC_DIR.resolve()
            try:
                resolved = path.resolve()
                if safe_root not in resolved.parents and resolved != safe_root:
                    raise ValueError("invalid static path")
                if not resolved.exists() or not resolved.is_file():
                    self.send_error(404)
                    return
                body = resolved.read_bytes()
            except Exception:
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            if resolved.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            elif resolved.suffix in {".html", ".css"}:
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI 狼人杀 Web 服务已启动：http://{host}:{port}")
    print(f"运行模式：{session.agent_mode}；人类玩家：{', '.join(session.config.human_players) if session.config.human_players else '无，纯 AI 对战'}")
    print("按 Ctrl+C 退出服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()
