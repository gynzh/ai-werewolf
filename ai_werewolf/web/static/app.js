const $ = (id) => document.getElementById(id);

const state = {
  sessionId: sessionIdFromPath(),
  lastEventsFingerprint: "",
  lastPendingKey: "",
  eventSource: null,
  pollTimer: null,
  god: false,
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

function eventCategory(event) {
  if (event.event_type === "player_speech") return "speech";
  if (event.event_type === "vote_cast") return "vote";
  if (["night_started", "day_announced", "exile_resolved", "game_end"].includes(event.event_type)) return "system";
  return "system";
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, { cache: "no-store", ...options });
  const text = await res.text();
  const payload = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new Error(payload.error || `${res.status} ${res.statusText}`);
  }
  return payload;
}

function api(path) {
  if (!state.sessionId) throw new Error("尚未选择 Session");
  return `/api/sessions/${encodeURIComponent(state.sessionId)}${path}`;
}

async function boot() {
  bindHandlers();
  await loadSessions();
  if (state.sessionId) {
    connectToSession(state.sessionId, { replaceUrl: false });
  } else {
    setConnection("等待创建或选择一局", "idle");
    renderEmptyGame();
  }
}

function bindHandlers() {
  $("createForm").addEventListener("submit", createSession);
  $("refreshButton").onclick = () => state.sessionId ? fetchStateOnce() : loadSessions();
  $("godToggle").onchange = () => {
    state.god = $("godToggle").checked;
    state.lastEventsFingerprint = "";
    if (state.sessionId) connectEventStream();
  };
  $("humanSelect").onchange = () => {
    state.lastPendingKey = "";
    pollPendingForSelectedHuman();
  };
  $("eventSearch").oninput = () => {
    state.lastEventsFingerprint = "";
    fetchStateOnce();
  };
  $("eventFilter").onchange = () => {
    state.lastEventsFingerprint = "";
    fetchStateOnce();
  };
  $("copySessionButton").onclick = () => copySessionUrl();
}

async function createSession(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  payload.reveal_death_role = form.get("reveal_death_role") === "on";
  payload.llm_json_mode = form.get("llm_json_mode") === "on";
  payload.no_llm_rule_fallback = form.get("no_llm_rule_fallback") === "on";
  payload.no_leak_check = false;
  payload.seed = Number(payload.seed || 42);
  payload.max_days = Number(payload.max_days || 10);
  payload.event_delay = Number(payload.event_delay || 0);
  payload.llm_temperature = payload.llm_temperature === "" ? "" : Number(payload.llm_temperature);
  payload.llm_timeout = payload.llm_timeout === "" ? "" : Number(payload.llm_timeout);
  payload.llm_max_tokens = payload.llm_max_tokens === "" ? "" : Number(payload.llm_max_tokens);

  $("createStatus").textContent = "正在创建新局...";
  try {
    const data = await fetchJson("/api/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("createStatus").textContent = `已创建 ${data.session.session_id}`;
    await loadSessions();
    connectToSession(data.session.session_id, { replaceUrl: true });
  } catch (err) {
    $("createStatus").textContent = `创建失败：${err.message}`;
  }
}

async function loadSessions() {
  try {
    const data = await fetchJson("/api/sessions");
    renderSessions(data.sessions || [], data.default_session_id);
    $("serverMeta").textContent = `服务 ${data.server_instance_id || "-"} · Sessions ${data.session_count || 0}`;
  } catch (err) {
    $("serverMeta").textContent = `无法读取服务状态：${err.message}`;
  }
}

function renderSessions(sessions, defaultId) {
  const box = $("sessionsList");
  if (!sessions.length) {
    box.innerHTML = `<div class="empty">暂无 Session。使用上方表单创建。</div>`;
    return;
  }
  box.innerHTML = sessions.map((s) => {
    const active = s.session_id === state.sessionId ? "active" : "";
    const title = `${s.session_id}${s.session_id === defaultId ? " · 默认" : ""}`;
    const result = s.winner ? (s.winner === "wolves" ? "狼人胜利" : "好人胜利") : (s.done ? "已结束" : "进行中");
    return `<button class="session-item ${active}" data-session="${esc(s.session_id)}">
      <span class="session-title">${esc(title)}</span>
      <span class="session-meta">${esc(s.agent_mode)} · seed ${esc(s.seed)} · ${esc(result)}</span>
      <span class="session-meta">${esc(s.out_dir || "")}</span>
    </button>`;
  }).join("");
  box.querySelectorAll("[data-session]").forEach((el) => {
    el.addEventListener("click", () => connectToSession(el.getAttribute("data-session"), { replaceUrl: true }));
  });
}

function connectToSession(sessionId, { replaceUrl }) {
  if (!sessionId) return;
  state.sessionId = sessionId;
  state.lastEventsFingerprint = "";
  state.lastPendingKey = "";
  if (replaceUrl) history.pushState({}, "", `/game/${encodeURIComponent(sessionId)}`);
  setConnection(`连接 Session ${sessionId}`, "active");
  connectEventStream();
  fetchStateOnce();
  loadSessions();
}

function connectEventStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (!state.sessionId) return;

  const god = $("godToggle").checked ? "1" : "0";
  if (window.EventSource) {
    const source = new EventSource(api(`/stream?god=${god}`));
    state.eventSource = source;
    source.addEventListener("state", (event) => {
      const payload = JSON.parse(event.data);
      renderState(payload);
      pollPendingForSelectedHuman();
      setConnection(`实时同步中 · ${payload.session_id}`, "active");
    });
    source.onerror = () => {
      setConnection("SSE 中断，切换轮询", "warn");
      source.close();
      state.eventSource = null;
      startPolling();
    };
  } else {
    startPolling();
  }
}

function startPolling() {
  fetchStateOnce();
  state.pollTimer = setInterval(fetchStateOnce, 1000);
}

async function fetchStateOnce() {
  if (!state.sessionId) return;
  try {
    const god = $("godToggle").checked ? "1" : "0";
    const data = await fetchJson(api(`/state?god=${god}`));
    renderState(data);
    await pollPendingForSelectedHuman();
  } catch (err) {
    setConnection(`连接失败：${err.message}`, "error");
  }
}

function renderEmptyGame() {
  $("heroTitle").textContent = "创建或选择一局";
  $("heroSubtitle").textContent = "每一局都有独立 Session ID、输出目录和事件流。";
  $("statusChips").innerHTML = `<span class="badge">状态：未选择</span>`;
  $("players").innerHTML = `<div class="empty">暂无玩家。</div>`;
  $("events").innerHTML = `<div class="empty">暂无公开事件。</div>`;
  $("pending").innerHTML = "请选择人类玩家席位，等待该玩家行动。";
  $("artifacts").innerHTML = "暂无输出文件";
  $("llmConfigs").innerHTML = `<div class="empty">暂无 LLM 配置。</div>`;
}

function renderState(data) {
  state.sessionId = data.session_id;
  const title = data.game_id ? `Game ${data.game_id}` : `Session ${data.session_id}`;
  $("heroTitle").textContent = title;
  $("heroSubtitle").textContent = `${phaseName(data.phase)} · 第 ${data.round_index || 0} 轮 · ${data.agent_mode || "rule"} · ${data.version_label || ""}`;
  $("sessionIdText").textContent = data.session_id || "-";

  const chips = [
    ["Session", data.session_id],
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
  $("statusChips").innerHTML = chips.map(([k, v]) => `<span class="badge">${esc(k)}：${esc(v)}</span>`).join("");

  const winner = data.winner;
  $("winnerCard").classList.toggle("hidden", !winner);
  if (winner) {
    $("winnerCard").innerHTML = `<div class="eyebrow">Winner</div><h3>${winner === "wolves" ? "狼人阵营" : "好人阵营"}</h3><p>${esc(data.win_reason || "")}</p>`;
  }

  renderHumans(data.human_players || []);
  renderArtifacts(data.artifacts || {});
  renderPlayers(data.players || []);
  renderEvents(data.public_events || []);
  renderLLMConfigs(data.llm_agent_configs || {}, data.agent_mode);
}

function renderHumans(humans) {
  const current = $("humanSelect").value;
  const options = ['<option value="">选择人类玩家</option>']
    .concat(humans.map((p) => `<option value="${esc(p)}" ${p === current ? "selected" : ""}>${esc(p)}</option>`));
  $("humanSelect").innerHTML = options.join("");
}

function renderArtifacts(artifacts) {
  const links = [
    ["事件日志", artifacts.log_path, artifacts.log_url],
    ["复盘 JSON", artifacts.review_path, artifacts.review_url],
    ["HTML 回放", artifacts.html_path, artifacts.html_url],
  ];
  $("artifacts").innerHTML = links.map(([label, path, url]) => `<div class="artifact-row">
    <span class="muted">${esc(label)}</span>
    <a href="${esc(url)}" target="_blank" rel="noreferrer">打开</a>
    <code>${esc(path || "")}</code>
  </div>`).join("");
}

function renderPlayers(players) {
  const alive = players.filter((p) => p.alive).length;
  $("aliveSummary").textContent = `${alive}/${players.length} 存活`;
  if (!players.length) {
    $("players").innerHTML = `<div class="empty">玩家尚未初始化。</div>`;
    return;
  }
  $("players").innerHTML = players.map((p) => {
    const factionClass = p.faction === "wolves" ? "wolves" : (p.faction ? "good" : "");
    const status = p.alive ? "存活" : `死亡：${p.death_reason || "未知"}`;
    const role = p.role_cn ? `<div>身份：<strong>${esc(p.role_cn)}</strong></div><div>阵营：<strong>${esc(p.faction_cn)}</strong></div>` : "";
    return `<div class="player-card ${factionClass} ${p.alive ? "" : "dead"}">
      <div class="player-title"><div><div class="player-id">${esc(p.player_id)}</div><div class="seat">${esc(p.name || "")}</div></div><span class="pill ${p.alive ? factionClass : "dead"}">${esc(status)}</span></div>
      <div class="player-meta">${role}${p.is_human ? '<span class="pill human">Human</span>' : '<span class="pill">AI Agent</span>'}</div>
    </div>`;
  }).join("");
}

function renderEvents(events) {
  const fingerprint = `${state.sessionId}:${events.length}:${events.at(-1)?.event_id || ""}:${$("eventSearch").value}:${$("eventFilter").value}`;
  if (fingerprint === state.lastEventsFingerprint) return;
  state.lastEventsFingerprint = fingerprint;

  const query = $("eventSearch").value.trim().toLowerCase();
  const filter = $("eventFilter").value;
  const filtered = events.filter((event) => {
    if (filter !== "all" && eventCategory(event) !== filter) return false;
    if (!query) return true;
    return JSON.stringify(event).toLowerCase().includes(query);
  });

  $("events").innerHTML = filtered.slice().reverse().map((event) => renderEvent(event)).join("") || "<div class='empty'>没有匹配的公开事件。</div>";
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
  else content = shortPayload(payload);
  return `<article class="event-card ${eventCategory(event)}">
    <div class="event-time"><strong>R${esc(event.round_index)}</strong><span>${esc(phaseName(event.phase))}</span></div>
    <div class="event-main">
      <div class="event-title"><span class="pill">${esc(label)}</span><strong>${esc(event.actor_id || "系统")}</strong></div>
      <div class="event-content">${esc(content)}</div>
      <details><summary>安全公开载荷</summary><pre>${esc(JSON.stringify(payload, null, 2))}</pre></details>
    </div>
  </article>`;
}

function shortPayload(payload) {
  if (!payload || typeof payload !== "object") return String(payload ?? "");
  if (payload.message) return payload.message;
  if (payload.target_player_id) return `目标 ${payload.target_player_id}`;
  if (payload.player_count) return `${payload.player_count} 名玩家已入场`;
  return JSON.stringify(payload);
}

function renderLLMConfigs(configs, agentMode) {
  const entries = Object.entries(configs || {});
  if (!entries.length) {
    $("llmConfigs").innerHTML = `<div class="empty">${agentMode === "llm" ? "LLM Agent 正在初始化，配置会在首次调用后出现。" : "当前为规则 Agent 模式。"}</div>`;
    return;
  }
  $("llmConfigs").innerHTML = entries.map(([pid, cfg]) => `<div class="config-card">
    <strong>${esc(pid)}</strong>
    <dl>
      <dt>模型</dt><dd>${esc(cfg.model)}</dd>
      <dt>Base URL</dt><dd>${esc(cfg.base_url)}</dd>
      <dt>来源</dt><dd>${esc(cfg.source)}</dd>
      <dt>Profile</dt><dd>${esc(cfg.profile || "-")}</dd>
      <dt>JSON</dt><dd>${cfg.json_mode ? "on" : "off"}</dd>
      <dt>Key</dt><dd>${cfg.api_key_set ? "已设置" : "未设置"}</dd>
    </dl>
  </div>`).join("");
}

async function pollPendingForSelectedHuman() {
  const human = $("humanSelect").value;
  if (!state.sessionId || !human) return;
  try {
    const data = await fetchJson(api(`/pending?player_id=${encodeURIComponent(human)}`));
    renderPending(data.pending, human);
  } catch (err) {
    $("pending").innerHTML = `读取行动失败：${esc(err.message)}`;
  }
}

function renderPending(obs, pid) {
  if (!obs) {
    $("pendingBadge").textContent = "等待";
    $("pending").innerHTML = `当前没有等待 ${esc(pid)} 的行动。`;
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
  $("pending").innerHTML = `<div class="form-grid">
    <div class="muted">${esc(obs.player_id)}：${esc(obs.current_task)}</div>
    <label>动作<select id="actionType">${actionTypes.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}</select></label>
    <label>目标<select id="targetPlayer"></select></label>
    <label>发言 / 备注<textarea id="actionContent" placeholder="可选"></textarea></label>
    <button id="submitActionButton" class="button">提交行动</button>
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
    $("pending").innerHTML = "已提交，等待下一步。";
    state.lastPendingKey = "";
    fetchStateOnce();
  }
}

function setConnection(text, mode) {
  const el = $("connectionStatus");
  el.textContent = text;
  el.className = `connection ${mode || ""}`;
}

function copySessionUrl() {
  const url = state.sessionId ? `${location.origin}/game/${state.sessionId}` : location.href;
  navigator.clipboard?.writeText(url);
  $("copySessionButton").textContent = "已复制";
  setTimeout(() => ($("copySessionButton").textContent = "复制当前链接"), 1200);
}

window.addEventListener("popstate", () => {
  state.sessionId = sessionIdFromPath();
  if (state.sessionId) connectToSession(state.sessionId, { replaceUrl: false });
  else renderEmptyGame();
});

boot();
