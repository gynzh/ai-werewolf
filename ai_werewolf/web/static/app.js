const $ = (id) => document.getElementById(id);

const state = {
  sessionId: sessionIdFromPath(),
  eventSource: null,
  pollTimer: null,
  lastEventKey: "",
  lastPendingKey: "",
};

const EVENT_LABELS = {
  game_started: "游戏开始",
  night_started: "夜晚开始",
  day_announced: "天亮公告",
  night_death: "夜间死亡",
  player_speech: "玩家发言",
  vote_cast: "投票",
  exile_resolved: "放逐结算",
  hunter_shot: "猎人开枪",
  hunter_skipped: "猎人跳过",
  game_end: "游戏结束",
};

const PHASE_LABELS = {
  init: "初始化",
  role_assignment: "分配身份",
  night_start: "夜晚开始",
  guard_action: "守卫行动",
  werewolf_discussion: "狼人讨论",
  werewolf_kill: "狼人击杀",
  seer_check: "预言家查验",
  witch_action: "女巫行动",
  night_resolution: "夜晚结算",
  day_announcement: "天亮",
  day_discussion: "白天发言",
  day_vote: "白天投票",
  exile_resolution: "放逐结算",
  hunter_shoot: "猎人开枪",
  win_check: "胜负检查",
  game_end: "游戏结束",
};

function sessionIdFromPath() {
  const match = window.location.pathname.match(/^\/game\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (s) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[s]));
}

function phaseName(phase) {
  return PHASE_LABELS[phase] || phase || "未知";
}

function categoryOf(event) {
  if (event.event_type === "player_speech") return "speech";
  if (event.event_type === "vote_cast") return "vote";
  return "system";
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, { cache: "no-store", ...options });
  const text = await res.text();
  const payload = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(payload.error || `${res.status} ${res.statusText}`);
  return payload;
}

function api(path) {
  if (!state.sessionId) throw new Error("尚未选择 Session");
  return `/api/sessions/${encodeURIComponent(state.sessionId)}${path}`;
}

function toNumberOrBlank(value) {
  return value === "" || value == null ? "" : Number(value);
}

async function boot() {
  bindHandlers();
  await loadSessions({ connectDefault: !state.sessionId });
  if (state.sessionId) connectSession(state.sessionId, false);
  else renderEmpty();
}

function bindHandlers() {
  $("createForm").addEventListener("submit", createSession);
  $("refreshButton").onclick = () => state.sessionId ? fetchState() : loadSessions({ connectDefault: false });
  $("copySessionButton").onclick = copySessionUrl;
  $("sessionPicker").onchange = () => {
    const id = $("sessionPicker").value;
    if (id) connectSession(id, true);
  };
  $("godToggle").onchange = () => reconnectStream();
  $("humanSelect").onchange = () => {
    state.lastPendingKey = "";
    pollPending();
  };
  $("eventSearch").oninput = () => {
    state.lastEventKey = "";
    fetchState();
  };
  $("eventFilter").onchange = () => {
    state.lastEventKey = "";
    fetchState();
  };
}

async function createSession(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  payload.seed = Number(payload.seed || 42);
  payload.max_days = Number(payload.max_days || 10);
  payload.event_delay = Number(payload.event_delay || 0);
  payload.llm_temperature = toNumberOrBlank(payload.llm_temperature);
  payload.llm_timeout = toNumberOrBlank(payload.llm_timeout);
  payload.llm_max_tokens = toNumberOrBlank(payload.llm_max_tokens);
  payload.llm_json_mode = form.get("llm_json_mode") === "on";
  payload.no_llm_rule_fallback = form.get("no_llm_rule_fallback") === "on";
  payload.reveal_death_role = form.get("reveal_death_role") === "on";
  payload.no_leak_check = false;

  setCreateStatus("正在创建新局...");
  try {
    const data = await fetchJson("/api/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    setCreateStatus(`已创建 ${data.session.session_id}`);
    await loadSessions({ connectDefault: false });
    connectSession(data.session.session_id, true);
  } catch (err) {
    setCreateStatus(`创建失败：${err.message}`);
  }
}

async function loadSessions({ connectDefault } = { connectDefault: false }) {
  try {
    const data = await fetchJson("/api/sessions");
    renderSessionPicker(data.sessions || [], data.default_session_id);
    $("serverMeta").textContent = `服务 ${data.server_instance_id || "-"} · ${data.session_count || 0} 局`;
    if (connectDefault && !state.sessionId && data.default_session_id) connectSession(data.default_session_id, true);
  } catch (err) {
    $("serverMeta").textContent = `服务状态读取失败：${err.message}`;
  }
}

function renderSessionPicker(sessions, defaultId) {
  const picker = $("sessionPicker");
  if (!sessions.length) {
    picker.innerHTML = '<option value="">暂无 Session</option>';
    return;
  }
  picker.innerHTML = sessions.map((s) => {
    const result = s.winner ? (s.winner === "wolves" ? "狼人胜" : "好人胜") : (s.done ? "已结束" : "进行中");
    const label = `${s.session_id}${s.session_id === defaultId ? " · 默认" : ""} · ${s.agent_mode} · seed ${s.seed} · ${result}`;
    return `<option value="${esc(s.session_id)}" ${s.session_id === state.sessionId ? "selected" : ""}>${esc(label)}</option>`;
  }).join("");
}

function connectSession(sessionId, pushUrl) {
  if (!sessionId) return;
  state.sessionId = sessionId;
  state.lastEventKey = "";
  state.lastPendingKey = "";
  $("sessionIdText").textContent = sessionId;
  if (pushUrl) history.pushState({}, "", `/game/${encodeURIComponent(sessionId)}`);
  setConnection(`连接 ${sessionId}`, "active");
  reconnectStream();
  fetchState();
  loadSessions({ connectDefault: false });
}

function reconnectStream() {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = null;
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = null;
  if (!state.sessionId) return;

  const god = $("godToggle").checked ? "1" : "0";
  if (!window.EventSource) {
    startPolling();
    return;
  }

  const source = new EventSource(api(`/stream?god=${god}`));
  state.eventSource = source;
  source.addEventListener("state", (event) => {
    const payload = JSON.parse(event.data);
    renderState(payload);
    pollPending();
    setConnection("实时同步", "active");
  });
  source.onerror = () => {
    source.close();
    state.eventSource = null;
    setConnection("SSE 中断，轮询中", "warn");
    startPolling();
  };
}

function startPolling() {
  fetchState();
  state.pollTimer = setInterval(fetchState, 1200);
}

async function fetchState() {
  if (!state.sessionId) return;
  try {
    const god = $("godToggle").checked ? "1" : "0";
    const data = await fetchJson(api(`/state?god=${god}`));
    renderState(data);
    await pollPending();
  } catch (err) {
    setConnection(`连接失败：${err.message}`, "error");
  }
}

function renderEmpty() {
  $("heroTitle").textContent = "创建或选择一局";
  $("heroSubtitle").textContent = "使用上方表单启动规则 Agent 或 LLM Agent。";
  $("statusChips").innerHTML = '<span class="chip">未选择 Session</span>';
  $("players").innerHTML = '<div class="empty">暂无玩家。</div>';
  $("events").innerHTML = '<div class="empty">暂无公开事件。</div>';
  $("pending").textContent = "请选择人类玩家席位。";
  $("artifacts").innerHTML = '<div class="empty">暂无输出文件。</div>';
  $("llmConfigs").innerHTML = '<div class="empty">暂无 LLM 配置。</div>';
}

function renderState(data) {
  state.sessionId = data.session_id;
  $("sessionIdText").textContent = data.session_id || "-";
  $("heroTitle").textContent = data.game_id ? `Game ${data.game_id}` : `Session ${data.session_id}`;
  $("heroSubtitle").textContent = `${phaseName(data.phase)} · 第 ${data.round_index || 0} 轮 · ${data.agent_mode || "rule"} · ${data.version_label || ""}`;

  const chips = [
    ["Seed", data.seed],
    ["阶段", phaseName(data.phase)],
    ["轮次", data.round_index || 0],
    ["白天", data.day_index || 0],
    ["夜晚", data.night_index || 0],
    ["模式", data.agent_mode || "rule"],
    ["状态", data.done ? "已结束" : "进行中"],
    ["事件", data.event_count || 0],
  ];
  if (data.error) chips.push(["错误", data.error]);
  $("statusChips").innerHTML = chips.map(([k, v]) => `<span class="chip"><strong>${esc(k)}</strong>${esc(v)}</span>`).join("");

  renderWinner(data);
  renderHumanOptions(data.human_players || []);
  renderPlayers(data.players || []);
  renderArtifacts(data.artifacts || {});
  renderEvents(data.public_events || []);
  renderLLMConfigs(data.llm_agent_configs || {}, data.agent_mode);
}

function renderWinner(data) {
  const box = $("winnerCard");
  if (!data.winner) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = `<p class="eyebrow">Winner</p><strong>${data.winner === "wolves" ? "狼人阵营" : "好人阵营"}</strong><p class="muted">${esc(data.win_reason || "")}</p>`;
}

function renderHumanOptions(humans) {
  const current = $("humanSelect").value;
  const html = ['<option value="">选择人类玩家</option>']
    .concat(humans.map((p) => `<option value="${esc(p)}" ${p === current ? "selected" : ""}>${esc(p)}</option>`));
  $("humanSelect").innerHTML = html.join("");
}

function renderPlayers(players) {
  if (!players.length) {
    $("players").innerHTML = '<div class="empty">玩家尚未初始化。</div>';
    return;
  }
  $("players").innerHTML = players.map((p) => {
    const factionClass = p.faction === "wolves" ? "wolves" : (p.faction ? "good" : "");
    const role = p.role_cn ? `<span>身份：<strong>${esc(p.role_cn)}</strong></span><span>阵营：<strong>${esc(p.faction_cn)}</strong></span>` : "";
    const statusClass = p.alive ? factionClass : "dead-pill";
    const status = p.alive ? "存活" : `死亡：${p.death_reason || "未知"}`;
    return `<article class="player ${p.alive ? "" : "dead"}">
      <div class="player-head"><span class="player-id">${esc(p.player_id)}</span><span class="pill ${statusClass}">${esc(status)}</span></div>
      <div class="player-meta"><span>${esc(p.name || "")}</span>${role}<span>${p.is_human ? "Human" : "AI Agent"}</span></div>
    </article>`;
  }).join("");
}

function renderEvents(events) {
  const search = $("eventSearch").value.trim().toLowerCase();
  const filter = $("eventFilter").value;
  const key = `${state.sessionId}:${events.length}:${events.at(-1)?.event_id || ""}:${search}:${filter}`;
  if (key === state.lastEventKey) return;
  state.lastEventKey = key;

  const filtered = events.filter((event) => {
    if (filter !== "all" && categoryOf(event) !== filter) return false;
    if (!search) return true;
    return JSON.stringify(event).toLowerCase().includes(search);
  }).slice(-80).reverse();

  $("events").innerHTML = filtered.map(renderEvent).join("") || '<div class="empty">没有匹配的公开事件。</div>';
}

function renderEvent(event) {
  const payload = event.payload || {};
  const label = EVENT_LABELS[event.event_type] || event.event_type;
  let content = "";
  if (event.event_type === "player_speech") content = payload.content || "（无发言内容）";
  else if (event.event_type === "vote_cast") content = `投票给 ${payload.target_player_id || "弃票"}`;
  else if (event.event_type === "day_announced") content = payload.message || "天亮了";
  else if (event.event_type === "exile_resolved") content = payload.exiled_player_id ? `放逐 ${payload.exiled_player_id}` : "平票，无人被放逐";
  else if (event.event_type === "game_end") content = payload.win_reason || "游戏结束";
  else content = payload.message || payload.target_player_id || payload.exiled_player_id || payload.player_count || JSON.stringify(payload);

  return `<article class="event ${categoryOf(event)}">
    <div class="event-time">R${esc(event.round_index)}<br>${esc(phaseName(event.phase))}</div>
    <div>
      <div class="event-title"><span class="pill">${esc(label)}</span><strong>${esc(event.actor_id || "系统")}</strong></div>
      <div class="event-content">${esc(content)}</div>
    </div>
  </article>`;
}

function renderArtifacts(artifacts) {
  const rows = [
    ["事件日志", artifacts.log_url],
    ["复盘 JSON", artifacts.review_url],
    ["HTML 回放", artifacts.html_url],
  ];
  $("artifacts").innerHTML = rows.map(([label, url]) => `<div class="artifact-row"><span>${esc(label)}</span><a href="${esc(url)}" target="_blank" rel="noreferrer">打开</a></div>`).join("") || '<div class="empty">暂无输出文件。</div>';
}

function renderLLMConfigs(configs, agentMode) {
  const entries = Object.entries(configs || {});
  if (!entries.length) {
    $("llmConfigs").innerHTML = `<div class="empty">${agentMode === "llm" ? "首次 LLM 调用后显示配置摘要。" : "当前为规则 Agent。"}</div>`;
    return;
  }
  $("llmConfigs").innerHTML = entries.map(([pid, cfg]) => `<div class="config-item">
    <strong>${esc(pid)}</strong><br>
    <span>${esc(cfg.model || "-")}</span><br>
    <span class="muted">${esc(cfg.base_url || "-")} · ${esc(cfg.profile || cfg.source || "default")}</span>
  </div>`).join("");
}

async function pollPending() {
  const human = $("humanSelect").value;
  if (!state.sessionId || !human) return;
  try {
    const data = await fetchJson(api(`/pending?player_id=${encodeURIComponent(human)}`));
    renderPending(data.pending, human);
  } catch (err) {
    $("pending").textContent = `读取行动失败：${err.message}`;
  }
}

function renderPending(obs, pid) {
  if (!obs) {
    $("pendingBadge").textContent = "等待";
    $("pending").textContent = `当前没有等待 ${pid} 的行动。`;
    state.lastPendingKey = "";
    return;
  }
  $("pendingBadge").textContent = "需要操作";
  const key = `${obs.player_id}|${obs.phase}|${obs.round_index}|${obs.day_index}|${obs.night_index}`;
  if (key === state.lastPendingKey) return;
  state.lastPendingKey = key;

  const options = [];
  (obs.available_actions || []).forEach((spec) => {
    const targets = spec.target_options || [];
    if (!targets.length) options.push({ action: spec.action_type, target: "" });
    else targets.forEach((target) => options.push({ action: spec.action_type, target: target.player_id }));
  });
  const actionTypes = [...new Set(options.map((o) => o.action))];

  $("pending").innerHTML = `<div class="form-stack">
    <div>${esc(obs.player_id)}：${esc(obs.current_task)}</div>
    <label>动作<select id="actionType">${actionTypes.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}</select></label>
    <label>目标<select id="targetPlayer"></select></label>
    <label>发言 / 备注<textarea id="actionContent" placeholder="可选"></textarea></label>
    <button id="submitActionButton" class="button" type="button">提交行动</button>
  </div>`;
  const refreshTargets = () => {
    const action = $("actionType").value;
    const targets = options.filter((o) => o.action === action && o.target).map((o) => o.target);
    $("targetPlayer").innerHTML = '<option value="">无</option>' + targets.map((target) => `<option value="${esc(target)}">${esc(target)}</option>`).join("");
  };
  $("actionType").onchange = refreshTargets;
  $("submitActionButton").onclick = () => submitAction(obs.player_id);
  refreshTargets();
}

async function submitAction(pid) {
  const body = {
    player_id: pid,
    action_type: $("actionType").value,
    target_player_id: $("targetPlayer").value || null,
    content: $("actionContent").value || null,
  };
  const res = await fetch(api("/action"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());
  if (!res.ok) alert(res.error);
  else {
    $("pending").textContent = "已提交，等待下一步。";
    state.lastPendingKey = "";
    fetchState();
  }
}

function setConnection(text, mode) {
  const el = $("connectionStatus");
  el.textContent = text;
  el.className = `status-dot ${mode || ""}`;
}

function setCreateStatus(text) {
  $("createStatus").textContent = text;
}

function copySessionUrl() {
  const url = state.sessionId ? `${location.origin}/game/${state.sessionId}` : location.href;
  navigator.clipboard?.writeText(url);
  $("copySessionButton").textContent = "已复制";
  setTimeout(() => ($("copySessionButton").textContent = "复制链接"), 1200);
}

window.addEventListener("popstate", () => {
  state.sessionId = sessionIdFromPath();
  if (state.sessionId) connectSession(state.sessionId, false);
  else renderEmpty();
});

boot();
