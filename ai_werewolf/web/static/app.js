const $ = (id) => document.getElementById(id);

let lastPendingKey = "";
let lastEventsFingerprint = "";

const EVENT_LABELS = {
  game_started: "游戏开始",
  night_started: "夜晚开始",
  day_announced: "天亮公告",
  player_speech: "玩家发言",
  vote_cast: "投票",
  exile_resolved: "放逐结算",
  hunter_shot: "猎人开枪",
  hunter_skipped: "猎人跳过",
  game_end: "游戏结束",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (s) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[s]));
}

function phaseName(phase) {
  const map = {
    init: "初始化", role_assignment: "分配身份", night_start: "夜晚开始",
    guard_action: "守卫行动", werewolf_discussion: "狼人讨论", werewolf_kill: "狼人击杀",
    seer_check: "预言家查验", witch_action: "女巫行动", night_resolution: "夜晚结算",
    day_announcement: "天亮", day_discussion: "白天发言", day_vote: "白天投票",
    exile_resolution: "放逐结算", hunter_shoot: "猎人开枪", win_check: "胜负检查", game_end: "游戏结束",
  };
  return map[phase] || phase || "未知";
}

function eventCategory(event) {
  if (event.event_type === "player_speech") return "speech";
  if (event.event_type === "vote_cast") return "vote";
  return "system";
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function poll() {
  try {
    const god = $("godToggle").checked ? "1" : "0";
    const state = await fetchJson(`/api/state?god=${god}`);
    renderState(state);
    const human = $("humanSelect").value;
    if (human) await pollPending(human);
  } catch (err) {
    $("heroSubtitle").textContent = `连接失败：${err.message}`;
  }
}

function renderState(state) {
  const title = state.game_id ? `Game ${state.game_id}` : "等待对局启动";
  $("heroTitle").textContent = title;
  $("heroSubtitle").textContent = `${phaseName(state.phase)} · 第 ${state.round_index || 0} 轮 · ${state.agent_mode || "rule"} · ${state.version_label || ""}`;

  const chips = [
    ["阶段", phaseName(state.phase)], ["轮次", state.round_index || 0],
    ["白天", state.day_index || 0], ["夜晚", state.night_index || 0],
    ["模式", state.agent_mode || "rule"], ["状态", state.done ? "已结束" : "进行中"],
  ];
  if (state.error) chips.push(["错误", state.error]);
  $("statusChips").innerHTML = chips.map(([k, v]) => `<span class="badge">${esc(k)}：${esc(v)}</span>`).join("");

  const winner = state.winner;
  $("winnerCard").classList.toggle("hidden", !winner);
  if (winner) {
    $("winnerCard").innerHTML = `<div class="eyebrow">Winner</div><h3>${winner === "wolves" ? "狼人阵营" : "好人阵营"}</h3><p>${esc(state.win_reason || "")}</p>`;
  }

  renderHumans(state.human_players || []);
  renderArtifacts(state.artifacts || {});
  renderPlayers(state.players || []);
  renderEvents(state.public_events || []);
  renderLLMConfigs(state.llm_agent_configs || {});
}

function renderHumans(humans) {
  const current = $("humanSelect").value;
  const options = ['<option value="">选择人类玩家</option>']
    .concat(humans.map((p) => `<option value="${esc(p)}" ${p === current ? "selected" : ""}>${esc(p)}</option>`));
  $("humanSelect").innerHTML = options.join("");
}

function renderArtifacts(artifacts) {
  const rows = Object.entries(artifacts).map(([key, value]) => `<div><span class="muted">${esc(key)}</span><br>${esc(value)}</div>`);
  $("artifacts").innerHTML = rows.length ? rows.join("") : "暂无输出文件";
}

function renderPlayers(players) {
  const alive = players.filter((p) => p.alive).length;
  $("aliveSummary").textContent = `${alive}/${players.length} 存活`;
  $("players").innerHTML = players.map((p) => {
    const factionClass = p.faction === "wolves" ? "wolves" : (p.faction ? "good" : "");
    const status = p.alive ? "存活" : `死亡：${p.death_reason || "未知"}`;
    const role = p.role_cn ? `<div>身份：<strong>${esc(p.role_cn)}</strong></div><div>阵营：<strong>${esc(p.faction_cn)}</strong></div>` : "";
    return `<div class="player-card ${factionClass} ${p.alive ? "" : "dead"}">
      <div class="player-title"><div><div class="player-id">${esc(p.player_id)}</div><div class="seat">${esc(p.name || "")}</div></div><span class="pill ${p.alive ? factionClass : "dead"}">${esc(status)}</span></div>
      <div class="player-meta">${role}${p.is_human ? '<span class="pill">Human</span>' : '<span class="pill">AI Agent</span>'}</div>
    </div>`;
  }).join("");
}

function renderEvents(events) {
  const fingerprint = `${events.length}:${events.at(-1)?.event_id || ""}:${$("eventSearch").value}:${$("eventFilter").value}`;
  if (fingerprint === lastEventsFingerprint) return;
  lastEventsFingerprint = fingerprint;

  const query = $("eventSearch").value.trim().toLowerCase();
  const filter = $("eventFilter").value;
  const filtered = events.filter((event) => {
    if (filter !== "all" && eventCategory(event) !== filter) return false;
    if (!query) return true;
    return JSON.stringify(event).toLowerCase().includes(query);
  });

  $("events").innerHTML = filtered.slice().reverse().map((event) => renderEvent(event)).join("") || "<div class='muted'>没有匹配的公开事件。</div>";
}

function renderEvent(event) {
  const payload = event.payload || {};
  const label = EVENT_LABELS[event.event_type] || event.event_type;
  let content = "";
  if (event.event_type === "player_speech") {
    content = payload.content || "（无发言内容）";
  } else if (event.event_type === "vote_cast") {
    content = `投票给 ${payload.target_player_id || "弃票"}`;
  } else if (event.event_type === "day_announced") {
    content = payload.message || "天亮了";
  } else if (event.event_type === "exile_resolved") {
    content = payload.exiled_player_id ? `放逐 ${payload.exiled_player_id}` : "平票，无人被放逐";
  } else if (event.event_type === "game_end") {
    content = payload.win_reason || "游戏结束";
  } else {
    content = shortPayload(payload);
  }
  return `<article class="event-card">
    <div class="event-time"><div>R${esc(event.round_index)}</div><div>${esc(phaseName(event.phase))}</div></div>
    <div class="event-main">
      <div class="event-title"><span class="pill">${esc(label)}</span><strong>${esc(event.actor_id || "系统")}</strong></div>
      <div class="event-content">${esc(content)}</div>
      <details><summary>查看安全公开载荷</summary><pre>${esc(JSON.stringify(payload, null, 2))}</pre></details>
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

function renderLLMConfigs(configs) {
  const entries = Object.entries(configs);
  $("llmConfigs").innerHTML = entries.length ? entries.map(([pid, cfg]) => `<div class="config-card">
    <strong>${esc(pid)}</strong>
    <dl>
      <dt>模型</dt><dd>${esc(cfg.model)}</dd>
      <dt>Base URL</dt><dd>${esc(cfg.base_url)}</dd>
      <dt>来源</dt><dd>${esc(cfg.source)}</dd>
      <dt>Profile</dt><dd>${esc(cfg.profile || "-")}</dd>
      <dt>JSON</dt><dd>${cfg.json_mode ? "on" : "off"}</dd>
    </dl>
  </div>`).join("") : "<div class='muted'>规则 Agent 模式，或 LLM Agent 尚未初始化。</div>";
}

async function pollPending(pid) {
  const data = await fetchJson(`/api/pending?player_id=${encodeURIComponent(pid)}`);
  const obs = data.pending;
  if (!obs) {
    $("pendingBadge").textContent = "等待";
    $("pending").innerHTML = `当前没有等待 ${esc(pid)} 的行动。`;
    lastPendingKey = "";
    return;
  }
  $("pendingBadge").textContent = "需要操作";
  const key = `${obs.player_id}|${obs.phase}|${obs.round_index}|${obs.day_index}|${obs.night_index}`;
  if (key === lastPendingKey) return;
  lastPendingKey = key;

  const options = [];
  (obs.available_actions || []).forEach((spec) => {
    const targets = spec.target_options || [];
    if (!targets.length) options.push({ action: spec.action_type, target: "" });
    else targets.forEach((target) => options.push({ action: spec.action_type, target: target.player_id }));
  });
  const actionTypes = [...new Set(options.map((o) => o.action))];
  $("pending").innerHTML = `<div class="form-grid">
    <div><strong>${esc(obs.player_id)}</strong>：${esc(obs.current_task)}</div>
    <label class="field-label">动作</label><select id="actionType">${actionTypes.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}</select>
    <label class="field-label">目标</label><select id="targetPlayer"></select>
    <label class="field-label">发言 / 备注</label><textarea id="actionContent" placeholder="白天发言时填写；技能或投票可以留空"></textarea>
    <button class="button" id="submitActionButton">提交行动</button>
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
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());
  if (!res.ok) alert(res.error);
  else {
    $("pending").innerHTML = "已提交，等待下一步。";
    lastPendingKey = "";
    poll();
  }
}

$("godToggle").onchange = poll;
$("humanSelect").onchange = () => { lastPendingKey = ""; poll(); };
$("eventSearch").oninput = () => { lastEventsFingerprint = ""; poll(); };
$("eventFilter").onchange = () => { lastEventsFingerprint = ""; poll(); };
$("refreshButton").onclick = poll;
setInterval(poll, 1000);
poll();
