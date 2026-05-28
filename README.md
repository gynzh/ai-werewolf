# AI 狼人杀 — 多智能体协作与博弈系统

这是一个可直接运行的 AI 狼人杀多 Agent 项目，支持规则 Agent、真实 LLM Agent、批量评测、结构化日志、自动复盘、HTML 回放，以及前后端分离的本地 Web 观战 / 人机混战界面。

## 核心能力

- 多 Agent 自主对局：狼人、预言家、女巫、猎人、守卫、平民。
- 信息隔离：Agent 只能读取自己的 `AgentObservation`。
- 真实 LLM 接入：OpenAI-compatible `/v1/chat/completions`。
- 每个 LLM Agent 可独立配置 API Key、Base URL、模型、温度、JSON mode 等。
- Web UI 前后端分离：Python 后端只提供 API 和静态文件服务，前端位于 `ai_werewolf/web/static/`。
- 安全公开事件：公开事件会自动移除 `reasoning_summary` 等私密推理字段，避免身份泄漏污染对局。
- 评测与复盘：JSONL 事件日志、review JSON、单局 HTML replay、Leaderboard。

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

查看可用板子：

```bash
python -m ai_werewolf boards
```

## 快速运行

规则 Agent 离线跑一局：

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 6p --out logs/demo
```

规则 Agent 浏览器观战：

```powershell
python -m ai_werewolf serve --preset 6p --human --seed 42 --out logs/web_rule
```

打开：

```text
http://127.0.0.1:8765
```

## LLM Agent：统一默认配置

在项目根目录创建 `.env`：

```env
AI_WEREWOLF_LLM_API_KEY=你的_API_KEY
AI_WEREWOLF_LLM_BASE_URL=https://api.openai.com/v1
AI_WEREWOLF_LLM_MODEL=gpt-4o-mini
AI_WEREWOLF_LLM_TEMPERATURE=0.2
AI_WEREWOLF_LLM_MAX_TOKENS=900
AI_WEREWOLF_LLM_TIMEOUT=60
AI_WEREWOLF_LLM_JSON_MODE=false
```

启动纯 AI 多 Agent LLM 观战：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human `
  --agent-mode llm `
  --seed 42 `
  --out logs/web_llm
```

`--human` 表示没有浏览器人类玩家，所有席位都由 AI Agent 控制。如果写 `--human P1`，则 P1 会在浏览器行动面板中等待你操作。

## LLM Agent：每个 Agent 独立配置

你可以用两种方式给不同玩家设置不同模型或 API。

### 方式一：按玩家写环境变量

```env
AI_WEREWOLF_LLM_API_KEY=默认_KEY
AI_WEREWOLF_LLM_MODEL=gpt-4o-mini
AI_WEREWOLF_LLM_BASE_URL=https://api.openai.com/v1

AI_WEREWOLF_LLM_P1_MODEL=gpt-4o-mini
AI_WEREWOLF_LLM_P1_TEMPERATURE=0.15

AI_WEREWOLF_LLM_P2_API_KEY=另一个_KEY
AI_WEREWOLF_LLM_P2_BASE_URL=https://api.deepseek.com/v1
AI_WEREWOLF_LLM_P2_MODEL=deepseek-chat
AI_WEREWOLF_LLM_P2_TEMPERATURE=0.65
```

支持的玩家专属变量格式：

```text
AI_WEREWOLF_LLM_P1_API_KEY
AI_WEREWOLF_LLM_P1_API_KEY_ENV
AI_WEREWOLF_LLM_P1_BASE_URL
AI_WEREWOLF_LLM_P1_MODEL
AI_WEREWOLF_LLM_P1_TEMPERATURE
AI_WEREWOLF_LLM_P1_MAX_TOKENS
AI_WEREWOLF_LLM_P1_TIMEOUT
AI_WEREWOLF_LLM_P1_JSON_MODE
AI_WEREWOLF_LLM_P1_ORGANIZATION
```

`P1` 可替换成 `P2`、`P3` 等。

### 方式二：使用 JSON 配置文件

复制示例文件：

```powershell
Copy-Item docs/llm_agents.example.json llm_agents.local.json
```

然后运行：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --seed 42 `
  --out logs/web_llm_multi
```

配置结构：

```json
{
  "default_profile": "balanced",
  "default": {
    "api_key_env": "AI_WEREWOLF_LLM_API_KEY",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "temperature": 0.2,
    "max_tokens": 900,
    "timeout": 60,
    "json_mode": false
  },
  "profiles": {
    "wolf_aggressive": {
      "api_key_env": "DEEPSEEK_API_KEY",
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-chat",
      "temperature": 0.65
    }
  },
  "agents": {
    "P2": { "profile": "wolf_aggressive" },
    "P3": { "model": "gpt-4o-mini", "temperature": 0.25 }
  }
}
```

不建议把真实 API Key 直接写进 JSON 文件。推荐写 `api_key_env`，再在 `.env` 中放真实密钥。

配置优先级从高到低：

```text
玩家专属环境变量 > agents.Px > profile > default > 命令行共享参数 > 全局环境变量
```

## Web 前后端分离结构

```text
ai_werewolf/web/server.py        # 后端：HTTP API、会话、静态文件服务
ai_werewolf/web/static/index.html
ai_werewolf/web/static/styles.css
ai_werewolf/web/static/app.js    # 前端：状态轮询、席位面板、时间线、人类行动面板
```

后端 API：

```text
GET  /api/state?god=0|1
GET  /api/pending?player_id=P1
GET  /api/review
POST /api/action
```

浏览器 UI 会展示：

- 当前阶段、轮次、胜负状态。
- 玩家席位、存活状态、上帝视角身份信息。
- 公开事件时间线、事件搜索与过滤。
- LLM Agent 配置概览，不展示 API Key。
- 人类玩家行动面板。

## 输出文件

`run` 和 `serve` 都会把运行产物保存到 `--out`：

```text
*.jsonl              # 结构化事件日志
*_review.json        # 自动复盘
*_replay.html        # 单局 HTML 回放
leaderboard.*        # 批量评测时生成
batch_summary.json   # 批量运行摘要
```

这些都是运行产物，默认已在 `.gitignore` 中忽略，不建议提交到仓库。

## 信息泄漏防护

公开事件会自动移除以下私密字段：

```text
reasoning_summary
action_reasoning_summary
private_reasoning_summary
chain_of_thought
raw_prompt
raw_response
private_history
```

这保证 `AgentObservation.public_history` 和 Web UI 时间线不会把“我是狼人”“我作为女巫已救人”等隐藏信息暴露给其他 Agent。私密事件和 system 事件仍保留完整信息用于复盘和调试。

运行测试：

```bash
pytest
```

其中 `tests/test_public_event_redaction.py` 会检查公开事件不会写入私密 reasoning。

## 批量评测与 Leaderboard

```bash
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --out logs/rule_10p
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --agent-mode llm --out logs/llm_10p
python -m ai_werewolf leaderboard logs/rule_10p logs/llm_10p --out logs/compare/leaderboard.json --markdown logs/compare/leaderboard.md --html logs/compare/leaderboard.html
```

## 仓库清理建议

不要提交以下内容：

```text
logs/
.idea/
__pycache__/
.env
*.jsonl
*_review.json
*_replay.html
```

如果这些内容已经被 Git 跟踪，可以执行：

```powershell
git rm -r --cached logs .idea
Get-ChildItem -Recurse -Directory -Filter __pycache__ | ForEach-Object { git rm -r --cached $_.FullName }
git add .gitignore
git commit -m "Clean runtime artifacts from repository"
```
