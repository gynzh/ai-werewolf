# AI Werewolf — 多智能体狼人杀系统

这是一个可直接运行的 AI 狼人杀多 Agent 项目，支持规则 Agent、真实 LLM Agent、批量评测、自动复盘、本地 Web 观战和浏览器人机混战。

当前版本重点完善了 Web 产品化能力：多 Session 隔离、SSE 实时同步、前后端分离静态 UI、每个 LLM Agent 独立配置、公开事件脱敏、Replay / Session Center，以及 Windows 友好的启动方式。

---

## 环境要求

- Windows / macOS / Linux 均可运行，当前文档命令以 Windows PowerShell 为主。
- Python 3.10+
- 规则 Agent 不需要 API Key。
- LLM 模式需要可访问 OpenAI-compatible `/v1/chat/completions` API。

安装本项目：

```powershell
pip install -e .
```

运行测试：

```powershell
python -m unittest discover tests
```

---

## 快速开始：Web 多 Agent 观战

规则 Agent 纯 AI 观战：

```powershell
python -m ai_werewolf serve --preset 6p --human= --seed 42 --out logs/web
```

LLM Agent 纯 AI 观战：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human= `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --seed 42 `
  --out logs/web
```

`serve` 默认使用 `--port 0`，Windows 会自动分配可用端口，避免旧的 `8765` 进程或旧浏览器 Session 混淆。启动后请以终端输出的 URL 为准：

```text
AI 狼人杀 Web 服务已启动：http://127.0.0.1:51234/game/ab12cd34ef
```

如果你想固定端口：

```powershell
python -m ai_werewolf serve --port 8765 --preset 6p --human= --out logs/web
```

---

## Web UI 能力

Web UI 已经从单局页面升级为多 Session 应用：

- 每局有独立 `session_id`，URL 形如 `/game/<session_id>`。
- 同一个 Web 服务中可以创建多局，互不污染。
- SSE 实时事件流：页面不再依赖旧的单纯轮询。
- Session Center：查看历史 Session、状态、模式、seed、输出目录。
- 创建新局面板：可直接在浏览器选择 preset、seed、human、rule/llm、LLM config、输出目录。
- Replay Center：每个 Session 提供 `events.jsonl`、`review.json`、`replay.html` 打开入口。
- 上帝视角：可切换显示身份和阵营。
- 公开事件时间线：支持搜索、发言/投票/系统事件过滤。
- 人类行动面板：当指定人类席位轮到行动时可在浏览器提交动作。

Web 路由：

```text
GET  /
GET  /game/<session_id>
GET  /api/sessions
POST /api/sessions
GET  /api/sessions/<session_id>/state?god=1
GET  /api/sessions/<session_id>/stream?god=1
GET  /api/sessions/<session_id>/pending?player_id=P1
POST /api/sessions/<session_id>/action
GET  /artifacts/<session_id>/log
GET  /artifacts/<session_id>/review
GET  /artifacts/<session_id>/html
```

---

## Web 输出目录

Web 模式不再覆盖固定文件名。每局都会保存到独立目录：

```text
logs/web/
└── session_<session_id>/
    ├── events.jsonl
    ├── review.json
    └── replay.html
```

这解决了同一 seed、同一 out 目录下看起来像“打开旧日志”的问题。

---

## LLM 配置

### 1. 统一配置

在项目根目录创建 `.env`：

```env
AI_WEREWOLF_LLM_API_KEY=你的_API_KEY
AI_WEREWOLF_LLM_MODEL=gpt-4o-mini
AI_WEREWOLF_LLM_BASE_URL=https://api.openai.com/v1
AI_WEREWOLF_LLM_TEMPERATURE=0.2
AI_WEREWOLF_LLM_MAX_TOKENS=700
AI_WEREWOLF_LLM_TIMEOUT=60
AI_WEREWOLF_LLM_JSON_MODE=false
```

然后运行：

```powershell
python -m ai_werewolf serve --preset 6p --human= --agent-mode llm --out logs/web
```

### 2. 每个 Agent 独立配置

复制示例文件：

```powershell
Copy-Item docs\llm_agents.example.json llm_agents.local.json
```

示例结构：

```json
{
  "default_profile": "fast",
  "default": {
    "api_key_env": "AI_WEREWOLF_LLM_API_KEY",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini"
  },
  "profiles": {
    "fast": { "model": "gpt-4o-mini", "temperature": 0.2 },
    "strong": { "model": "gpt-4o", "temperature": 0.15 }
  },
  "agents": {
    "P1": { "profile": "strong" },
    "P2": { "profile": "fast" },
    "P3": {
      "api_key_env": "P3_LLM_API_KEY",
      "base_url": "http://127.0.0.1:8000/v1",
      "model": "local-model"
    }
  }
}
```

运行：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human= `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --out logs/web
```

也支持玩家级环境变量：

```env
AI_WEREWOLF_LLM_P1_MODEL=gpt-4o
AI_WEREWOLF_LLM_P2_BASE_URL=http://127.0.0.1:8000/v1
AI_WEREWOLF_LLM_P2_API_KEY=local-key
```

配置优先级：玩家环境变量 > `agents.Px` > profile > default profile > config default > 全局 CLI / 环境变量。

---

## 命令行批量评测

运行规则 Agent：

```powershell
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --out logs/rule_10p
```

运行 LLM Agent：

```powershell
python -m ai_werewolf run `
  --games 20 `
  --seed 100 `
  --preset 10p-standard `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --out logs/llm_10p
```

生成 Leaderboard：

```powershell
python -m ai_werewolf leaderboard logs/rule_10p logs/llm_10p `
  --out logs/compare/leaderboard.json `
  --markdown logs/compare/leaderboard.md `
  --html logs/compare/leaderboard.html
```

---

## 可用板子

查看板子：

```powershell
python -m ai_werewolf boards
```

内置 preset：

| Preset | 角色配置 |
|---|---|
| `6p` | 2 狼人 + 1 预言家 + 1 女巫 + 2 平民 |
| `8p-simple` | 3 狼人 + 1 预言家 + 1 女巫 + 3 平民 |
| `10p-standard` | 3 狼人 + 1 预言家 + 1 女巫 + 1 猎人 + 1 守卫 + 3 平民 |

自定义角色：

```powershell
python -m ai_werewolf run --games 1 --seed 7 --roles werewolf,werewolf,seer,witch,hunter,guard,villager,villager --out logs/custom
```

合法角色：

```text
werewolf, seer, witch, hunter, guard, villager
```

---

## 信息隔离与公开事件脱敏

`GameState` 是系统真相，只由 `GameEngine` 持有。Agent 只能通过 `AgentObservation` 接收可见信息。

公开事件会在 `EventStore` 边界被脱敏，避免把 LLM 的私密推理、隐藏身份、raw prompt、raw response 或 fallback 错误暴露给其他 Agent 或 Web UI。

公开事件会移除这些字段：

```text
reasoning_summary, action_reasoning_summary, private_reasoning_summary,
chain_of_thought, raw_prompt, raw_response, messages, system_prompt,
private_history, llm_error
```

私密事件仍保留完整 payload，用于 review 和调试。

---

## 项目结构

```text
ai_werewolf/
├── agents/          # RuleBasedAgent / LLMAgent / HumanAgent
├── configs/         # 板子配置
├── engine/          # GameEngine 对局引擎
├── eval/            # review / replay / leaderboard
├── llm/             # provider / prompt builder / parser / per-agent config
├── logging/         # EventStore JSONL + public redaction
├── models/          # GameState / Action / Event / Observation
├── rules/           # 角色与动作合法性
├── visibility/      # 信息隔离
├── web/             # 本地 Web 后端 + static 前端
│   ├── server.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── styles.css
├── cli.py
└── __main__.py
```

更多 Web 架构说明见：`docs/WEB_ARCHITECTURE.md`。

---

## 仓库清理要求

运行产物、IDE 配置、缓存和本地密钥不应提交：

```text
logs/
.idea/
__pycache__/
*.pyc
.env
llm_agents.local.json
```

如果这些内容已经被 Git 跟踪，请在 PowerShell 中清理索引：

```powershell
git rm -r --cached logs .idea 2>$null
git rm --cached .gitingore FINAL_REVIEW.md 2>$null
git add .gitignore README.md ai_werewolf docs tests pyproject.toml
git status
```

---

## 常见问题

### PowerShell 中纯 AI 怎么写？

推荐：

```powershell
--human=
```

也可以在新 Web UI 的创建表单里把“人类席位”留空。

### 为什么不再默认打开 8765？

固定端口容易遇到旧 Python 进程或旧浏览器标签页，导致页面看起来像旧日志。现在默认 `--port 0`，终端会打印真实 URL。

### 这是真正前后端分离吗？

当前是轻量前后端分离：后端提供 JSON/SSE API，前端是 `web/static/` 中的独立 HTML/CSS/JS。没有引入 Node/Vite/React 构建链，保持 Windows 本地运行简单。后续如果需要大型 UI，可以在此 API 上迁移到 React/Vue。
