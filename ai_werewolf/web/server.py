from __future__ import annotations

import json
import mimetypes
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
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

SessionFactory = Callable[[dict[str, Any]], "WebGameSession"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id() -> str:
    return uuid.uuid4().hex[:10]


class BrowserHumanAgent(BaseAgent):
    def __init__(self, player_id: str, session: "WebGameSession") -> None:
        super().__init__(player_id)
        self.session = session

    def act(self, observation: AgentObservation) -> Action:
        return self.session.wait_for_action(self.player_id, observation)


class WebGameSession:
    """A single isolated browser game session.

    A session owns its GameEngine, EventStore, pending human actions and output
    directory. The browser always addresses sessions by `session_id`, so a stale
    tab can no longer accidentally display another run on the same port.
    """

    def __init__(
        self,
        config: GameConfig,
        out_dir: str | Path,
        enable_leak_check: bool = True,
        agent_factory: Callable[[str, int | None], BaseAgent] | None = None,
        public_event_delay_seconds: float = 0.0,
        session_id: str | None = None,
        request: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id or _short_id()
        self.created_at = _utc_now_iso()
        self.request = request or {}
        self.config = config
        self.root_out_dir = Path(out_dir)
        self.out_dir = self.root_out_dir / f"session_{self.session_id}"
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.log_path = self.out_dir / "events.jsonl"
        self.review_path = self.out_dir / "review.json"
        self.html_path = self.out_dir / "replay.html"
        self.store = EventStore(self.log_path, public_event_delay_seconds=public_event_delay_seconds)

        self.engine: GameEngine | None = None
        self.state = None
        self.review: dict[str, Any] | None = None
        self.error: str | None = None
        self.done = False
        self.started = False
        self.finished_at: str | None = None
        self.enable_leak_check = enable_leak_check
        self.agent_factory = agent_factory
        self.public_event_delay_seconds = max(0.0, float(public_event_delay_seconds or 0.0))
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
        self._thread = threading.Thread(
            target=self._run,
            name=f"werewolf-session-{self.session_id}",
            daemon=True,
        )
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
            self.finished_at = _utc_now_iso()
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
            metadata={"source": "browser_human", "session_id": self.session_id},
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
        public_events = [e.to_dict() for e in self.store.public_events()]
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
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
            "seed": self.config.random_seed,
            "roles": list(self.config.roles),
            "players": players_god if god else players_public,
            "public_events": public_events,
            "event_count": len(public_events),
            "pending_players": sorted(self._pending.keys()),
            "artifacts": {
                "session_dir": str(self.out_dir),
                "log_path": str(self.log_path),
                "review_path": str(self.review_path),
                "html_path": str(self.html_path),
                "log_url": f"/artifacts/{self.session_id}/log",
                "review_url": f"/artifacts/{self.session_id}/review",
                "html_url": f"/artifacts/{self.session_id}/html",
            },
            "llm_agent_configs": self._llm_agent_config_summaries(),
            "public_event_delay_seconds": self.public_event_delay_seconds,
            "request": self.request,
        }

    def summary(self) -> dict[str, Any]:
        state = self.engine.state if self.engine else self.state
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "started": self.started,
            "done": self.done,
            "error": self.error,
            "game_id": state.game_id if state else None,
            "phase": state.phase if state else None,
            "winner": state.winner if state else None,
            "win_reason": state.win_reason if state else None,
            "agent_mode": self.agent_mode,
            "version_label": self.config.version_label,
            "seed": self.config.random_seed,
            "human_players": self.config.human_players,
            "event_count": len(self.store.public_events()),
            "out_dir": str(self.out_dir),
        }

    def review_state(self) -> dict[str, Any] | None:
        return self.review

    def pending_observation(self, player_id: str) -> dict[str, Any] | None:
        with self._condition:
            obs = self._pending.get(player_id.upper())
        return asdict(obs) if obs else None

    def artifact_path(self, kind: str) -> Path:
        mapping = {
            "log": self.log_path,
            "jsonl": self.log_path,
            "review": self.review_path,
            "html": self.html_path,
            "replay": self.html_path,
        }
        if kind not in mapping:
            raise ValueError(f"unknown artifact kind: {kind}")
        return mapping[kind]

    def _llm_agent_config_summaries(self) -> dict[str, Any]:
        factory = self.agent_factory
        if factory is None:
            return {}
        value = getattr(factory, "llm_provider_summaries", {})
        return dict(value) if isinstance(value, dict) else {}


class WebSessionManager:
    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory = session_factory
        self.server_instance_id = _short_id()
        self.created_at = _utc_now_iso()
        self._sessions: dict[str, WebGameSession] = {}
        self._default_session_id: str | None = None
        self._lock = threading.RLock()

    @property
    def default_session_id(self) -> str | None:
        with self._lock:
            return self._default_session_id

    def add(self, session: WebGameSession, *, start: bool = True, make_default: bool = True) -> WebGameSession:
        with self._lock:
            self._sessions[session.session_id] = session
            if make_default or self._default_session_id is None:
                self._default_session_id = session.session_id
        if start:
            session.start()
        return session

    def create_from_request(self, data: dict[str, Any]) -> WebGameSession:
        if self.session_factory is None:
            raise ValueError("this server was not configured to create sessions from the browser")
        session = self.session_factory(data)
        return self.add(session, start=True, make_default=True)

    def get(self, session_id: str | None) -> WebGameSession | None:
        with self._lock:
            if not session_id:
                session_id = self._default_session_id
            return self._sessions.get(session_id or "")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())
        return sorted((session.summary() for session in sessions), key=lambda item: item["created_at"], reverse=True)

    def meta(self) -> dict[str, Any]:
        return {
            "server_instance_id": self.server_instance_id,
            "created_at": self.created_at,
            "default_session_id": self.default_session_id,
            "session_count": len(self.list()),
            "can_create_sessions": self.session_factory is not None,
        }


def run_web_server(
    session_or_manager: WebGameSession | WebSessionManager,
    host: str = "127.0.0.1",
    port: int = 0,
    session_factory: SessionFactory | None = None,
) -> None:
    if isinstance(session_or_manager, WebSessionManager):
        manager = session_or_manager
        if session_factory is not None:
            manager.session_factory = session_factory
    else:
        manager = WebSessionManager(session_factory=session_factory)
        manager.add(session_or_manager, start=True, make_default=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/", "/sessions"} or path.startswith("/game/"):
                self._send_static(STATIC_DIR / "index.html")
                return
            if path.startswith("/static/"):
                self._send_static(STATIC_DIR / path.removeprefix("/static/"))
                return
            if path == "/api/health":
                self._send_json({"ok": True, **manager.meta()})
                return
            if path == "/api/options":
                self._send_json(_runtime_options(manager))
                return
            if path == "/api/sessions":
                self._send_json({"sessions": manager.list(), **manager.meta()})
                return
            if path == "/api/state":
                session = manager.get(None)
                if not session:
                    self._send_json({"ok": False, "error": "no session"}, status=404)
                    return
                self._send_json(session.public_state(god=_god_flag(parsed.query)))
                return

            routed = self._route_session_api(path)
            if routed:
                session_id, action = routed
                session = manager.get(session_id)
                if not session:
                    self._send_json({"ok": False, "error": f"unknown session: {session_id}"}, status=404)
                    return
                if action == "state":
                    self._send_json(session.public_state(god=_god_flag(parsed.query)))
                    return
                if action == "review":
                    self._send_json({"review": session.review_state()})
                    return
                if action == "pending":
                    qs = parse_qs(parsed.query)
                    player_id = qs.get("player_id", [""])[0].upper()
                    self._send_json({"pending": session.pending_observation(player_id)})
                    return
                if action == "stream":
                    self._send_event_stream(session, god=_god_flag(parsed.query))
                    return

            artifact = self._route_artifact(path)
            if artifact:
                session_id, kind = artifact
                session = manager.get(session_id)
                if not session:
                    self.send_error(404)
                    return
                try:
                    self._send_file(session.artifact_path(kind))
                except Exception:
                    self.send_error(404)
                return

            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/sessions":
                try:
                    data = self._read_json_body()
                    session = manager.create_from_request(data)
                    self._send_json({"ok": True, "session": session.summary(), "url": f"/game/{session.session_id}"}, status=201)
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                return

            routed = self._route_session_api(parsed.path)
            if routed:
                session_id, action = routed
                session = manager.get(session_id)
                if not session:
                    self._send_json({"ok": False, "error": f"unknown session: {session_id}"}, status=404)
                    return
                if action == "action":
                    try:
                        session.submit_action(self._read_json_body())
                        self._send_json({"ok": True})
                    except Exception as exc:
                        self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _route_session_api(self, path: str) -> tuple[str, str] | None:
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "sessions":
                return parts[2], parts[3]
            return None

        def _route_artifact(self, path: str) -> tuple[str, str] | None:
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "artifacts":
                return parts[1], parts[2]
            return None

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_event_stream(self, session: WebGameSession, *, god: bool) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            last_fingerprint = ""
            idle_ticks = 0
            while True:
                state = session.public_state(god=god)
                fingerprint = f"{state['event_count']}:{state['phase']}:{state['done']}:{state.get('winner')}:{state['pending_players']}"
                if fingerprint != last_fingerprint:
                    last_fingerprint = fingerprint
                    payload = json.dumps(state, ensure_ascii=False)
                    try:
                        self.wfile.write(f"event: state\ndata: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    try:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                if session.done and idle_ticks >= 2:
                    return
                time.sleep(0.7)

        def _send_static(self, path: Path) -> None:
            safe_root = STATIC_DIR.resolve()
            try:
                resolved = path.resolve()
                if safe_root not in resolved.parents and resolved != safe_root:
                    raise ValueError("invalid static path")
                self._send_file(resolved)
            except Exception:
                self.send_error(404)

        def _send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if path.suffix == ".js":
                content_type = "text/javascript; charset=utf-8"
            elif path.suffix in {".html", ".css", ".json", ".jsonl"}:
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in {"0.0.0.0", ""} else actual_host
    default_id = manager.default_session_id
    default_url = f"http://{display_host}:{actual_port}/game/{default_id}" if default_id else f"http://{display_host}:{actual_port}"

    print(f"AI 狼人杀 Web 服务已启动：{default_url}")
    print(f"服务实例：{manager.server_instance_id}；端口：{actual_port}；会话数：{len(manager.list())}")
    default_session = manager.get(default_id)
    if default_session:
        humans = ", ".join(default_session.config.human_players) if default_session.config.human_players else "无，纯 AI 对战"
        print(f"默认会话：{default_session.session_id}；运行模式：{default_session.agent_mode}；人类玩家：{humans}")
    print("按 Ctrl+C 退出服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


def _god_flag(query: str) -> bool:
    qs = parse_qs(query)
    return qs.get("god", ["0"])[0] in {"1", "true", "yes"}


def _runtime_options(manager: WebSessionManager) -> dict[str, Any]:
    # Keep this endpoint independent from CLI internals. The browser form can
    # still create sessions through the CLI-provided session factory.
    return {
        "ok": True,
        **manager.meta(),
        "presets": ["6p", "8p-simple", "10p-standard"],
        "agent_modes": ["rule", "llm"],
        "tie_policies": ["no_exile", "random"],
        "artifact_kinds": ["log", "review", "html"],
    }
