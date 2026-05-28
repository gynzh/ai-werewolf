from __future__ import annotations

import json
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
from ai_werewolf.rules.roles import role_name_cn, faction_name_cn


class BrowserHumanAgent(BaseAgent):
    def __init__(self, player_id: str, session: "WebGameSession") -> None:
        super().__init__(player_id)
        self.session = session

    def act(self, observation: AgentObservation) -> Action:
        return self.session.wait_for_action(self.player_id, observation)


class WebGameSession:
    def __init__(self, config: GameConfig, out_dir: str | Path, enable_leak_check: bool = True, agent_factory: Callable[[str, int | None], BaseAgent] | None = None) -> None:
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
            self.engine = GameEngine(config=self.config, event_store=self.store, agent_factory=factory, enable_leak_check=self.enable_leak_check)
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
            for p in sorted(state.players.values(), key=lambda x: x.seat):
                base = p.public_view()
                players_public.append(base)
                players_god.append({**base, "role": p.role, "role_cn": role_name_cn(p.role), "faction": p.faction, "faction_cn": faction_name_cn(p.faction)})
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
            "players": players_god if god else players_public,
            "public_events": [e.to_dict() for e in self.store.public_events()],
            "log_path": str(self.log_path),
            "review_path": str(self.review_path),
            "html_path": str(self.html_path),
        }

    def pending_observation(self, player_id: str) -> dict[str, Any] | None:
        with self._condition:
            obs = self._pending.get(player_id.upper())
            return asdict(obs) if obs else None


def run_web_server(session: WebGameSession, host: str = "127.0.0.1", port: int = 8765) -> None:
    session.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(INDEX_HTML)
                return
            if parsed.path == "/api/state":
                qs = parse_qs(parsed.query)
                god = qs.get("god", ["0"])[0] in {"1", "true", "yes"}
                self._send_json(session.public_state(god=god))
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
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI 狼人杀 Web 观战/人机混战服务已启动：http://{host}:{port}")
    print(f"人类玩家：{', '.join(session.config.human_players) if session.config.human_players else '无，纯 AI 对战'}")
    print("按 Ctrl+C 退出服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>AI 狼人杀观战 UI</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f6f7fb;color:#1f2937}.wrap{max-width:1200px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap}.card{background:white;border-radius:16px;padding:16px;box-shadow:0 1px 6px rgba(0,0,0,.08);margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.player{border-left:5px solid #d1d5db}.dead{opacity:.6}.wolf{border-left-color:#ef4444}.good{border-left-color:#10b981}.badge{display:inline-block;background:#eef2ff;border-radius:999px;padding:3px 9px;margin:2px;font-size:12px}.events{max-height:520px;overflow:auto}.event{border-bottom:1px solid #eee;padding:10px 0}.phase{font-weight:700}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}button{border:0;background:#2563eb;color:white;border-radius:10px;padding:9px 14px;cursor:pointer}button:disabled{background:#9ca3af}select,input,textarea{border:1px solid #d1d5db;border-radius:10px;padding:8px;width:100%;box-sizing:border-box}textarea{min-height:80px}.cols{display:grid;grid-template-columns:2fr 1fr;gap:16px}@media(max-width:850px){.cols{grid-template-columns:1fr}}
</style>
</head>
<body><div class="wrap">
<div class="top"><div><h1>AI 狼人杀观战 UI</h1><div id="status"></div></div><div class="controls"><label><input type="checkbox" id="god"> 上帝视角</label><select id="human"></select></div></div>
<div class="grid" id="players"></div>
<div class="cols"><div class="card"><h2>公开事件时间线</h2><div class="events" id="events"></div></div><div class="card"><h2>人类行动面板</h2><div id="pending">请选择人类玩家席位，等待该玩家行动。</div></div></div>
</div>
<script>
const $=id=>document.getElementById(id); let lastPendingKey="";
function esc(x){return String(x??"").replace(/[&<>]/g,s=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[s]));}
async function poll(){
  const god=$('god').checked?'1':'0';
  const st=await fetch('/api/state?god='+god).then(r=>r.json());
  $('status').innerHTML=`<span class="badge">Game ${esc(st.game_id)}</span><span class="badge">阶段 ${esc(st.phase)}</span><span class="badge">轮次 ${st.round_index}</span><span class="badge">胜者 ${esc(st.winner||'未结束')}</span>`+(st.error?`<span class="badge">错误 ${esc(st.error)}</span>`:'');
  const currentHuman=$('human').value; $('human').innerHTML='<option value="">选择人类玩家</option>'+st.human_players.map(p=>`<option ${p===currentHuman?'selected':''}>${p}</option>`).join('');
  $('players').innerHTML=st.players.map(p=>`<div class="card player ${p.alive?'':'dead'} ${p.faction==='wolves'?'wolf':(p.faction?'good':'')}"><b>${esc(p.player_id)} · ${esc(p.name)}</b><br>状态：${p.alive?'存活':'死亡 '+esc(p.death_reason)}<br>${p.role_cn?`身份：${esc(p.role_cn)}<br>阵营：${esc(p.faction_cn)}`:''}${p.is_human?'<br><span class="badge">Human</span>':''}</div>`).join('');
  $('events').innerHTML=st.public_events.slice().reverse().map(e=>`<div class="event"><div><span class="badge">R${e.round_index}</span><span class="badge">${esc(e.phase)}</span><b>${esc(e.event_type)}</b> ${esc(e.actor_id||'系统')}</div><pre>${esc(JSON.stringify(e.payload,null,2))}</pre></div>`).join('');
  const hp=$('human').value; if(hp){ await pollPending(hp); }
}
async function pollPending(pid){
  const data=await fetch('/api/pending?player_id='+encodeURIComponent(pid)).then(r=>r.json());
  const obs=data.pending; if(!obs){$('pending').innerHTML='当前没有等待 '+esc(pid)+' 的行动。'; lastPendingKey=''; return;}
  const key=obs.player_id+'|'+obs.phase+'|'+obs.round_index+'|'+obs.day_index+'|'+obs.night_index;
  if(key===lastPendingKey) return; lastPendingKey=key;
  let options=[]; obs.available_actions.forEach(spec=>{ const targets=spec.target_options||[]; if(!targets.length) options.push({a:spec.action_type,t:''}); else targets.forEach(t=>options.push({a:spec.action_type,t:t.player_id})); });
  const actionTypes=[...new Set(options.map(o=>o.a))];
  $('pending').innerHTML=`<p><b>${esc(obs.player_id)}</b>：${esc(obs.current_task)}</p><label>动作</label><select id="act">${actionTypes.map(a=>`<option>${esc(a)}</option>`).join('')}</select><label>目标</label><select id="target"></select><label>发言内容</label><textarea id="content"></textarea><button onclick="submitAction('${esc(obs.player_id)}')">提交行动</button>`;
  const refreshTargets=()=>{ const a=$('act').value; const ts=options.filter(o=>o.a===a&&o.t).map(o=>o.t); $('target').innerHTML='<option value="">无</option>'+ts.map(t=>`<option>${esc(t)}</option>`).join(''); };
  $('act').onchange=refreshTargets; refreshTargets();
}
async function submitAction(pid){
  const body={player_id:pid,action_type:$('act').value,target_player_id:$('target').value||null,content:$('content').value||null};
  const res=await fetch('/api/action',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  if(!res.ok) alert(res.error); else { $('pending').innerHTML='已提交，等待下一步。'; lastPendingKey=''; poll(); }
}
$('god').onchange=poll; $('human').onchange=()=>{lastPendingKey=''; poll();}; setInterval(poll,1000); poll();
</script></body></html>'''
