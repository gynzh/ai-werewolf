# AI Werewolf

AI Werewolf 是一个可本地运行的多智能体狼人杀项目。它包含完整的对局引擎、规则 Agent、真实 LLM Agent、Web 观战界面、事件日志、自动复盘和批量评测能力。

项目适合两类场景：

- **演示 / 观战**：在浏览器中观看多个 AI Agent 自动完成狼人杀对局，也可以指定某些席位由人类操作。
- **评测 / 复盘**：批量运行不同 Agent 或不同模型配置，生成 JSONL 事件日志、review、HTML replay 和 leaderboard。

---

## 环境要求

- Python 3.10+
- Windows、macOS、Linux 均可运行；下方命令以 Windows PowerShell 为主。
- 规则 Agent 不需要 API Key。
- LLM Agent 需要 OpenAI-compatible `/v1/chat/completions` 接口。

安装：

```powershell
pip install -e .
```

运行测试：

```powershell
python -m unittest discover tests
```

---

## 快速开始

### 1. 浏览器观战规则 Agent

```powershell
python -m ai_werewolf serve --preset 6p --human= --seed 42 --out logs/web
```

`serve` 默认使用 `--port 0` 自动分配端口，避免 Windows 上旧进程占用固定端口。请打开终端输出的完整地址，例如：

```text
AI 狼人杀 Web 服务已启动：http://127.0.0.1:51234/game/ab12cd34ef
```

### 2. 浏览器观战 LLM Agent

先在项目根目录创建 `.env`：

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
python -m ai_werewolf serve --preset 6p --human= --agent-mode llm --seed 42 --out logs/web
```

### 3. 浏览器人机混战

让 `P1` 由浏览器操作，其余玩家由 AI 控制：

```powershell
python -m ai_werewolf serve --preset 6p --human P1 --agent-mode llm --seed 42 --out logs/web
```

---

## Web UI

Web UI 是本地静态前端 + Python 后端 API。当前界面只保留常用操作：

- 创建 / 切换 Session
- 查看当前局状态、胜负、玩家席位
- 查看公开事件时间线
- 指定人类席位并提交行动
- 打开 `events.jsonl`、`review.json`、`replay.html`
- 查看 LLM Agent 的模型配置摘要

每一局都有独立 URL：

```text
/game/<session_id>
```

每一局也有独立输出目录：

```text
logs/web/session_<session_id>/
├── events.jsonl
├── review.json
└── replay.html
```

这可以避免同一端口、同一 seed、同一输出目录下误看旧对局。

---

## LLM 配置

### 统一配置

可通过 `.env`、环境变量或命令行参数配置共享 LLM：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human= `
  --agent-mode llm `
  --llm-model gpt-4o-mini `
  --out logs/web
```

支持的主要变量：

```env
AI_WEREWOLF_LLM_API_KEY=...
AI_WEREWOLF_LLM_BASE_URL=https://api.openai.com/v1
AI_WEREWOLF_LLM_MODEL=gpt-4o-mini
AI_WEREWOLF_LLM_TEMPERATURE=0.2
AI_WEREWOLF_LLM_MAX_TOKENS=700
AI_WEREWOLF_LLM_TIMEOUT=60
AI_WEREWOLF_LLM_JSON_MODE=false
```

### 每个 Agent 独立配置

复制示例：

```powershell
Copy-Item docs\llm_agents.example.json llm_agents.local.json
```

运行：

```powershell
python -m ai_werewolf serve `
  --preset 6p `
  --human= `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --seed 42 `
  --out logs/web
```

也可以用玩家级环境变量覆盖单个玩家：

```env
AI_WEREWOLF_LLM_P1_MODEL=gpt-4o
AI_WEREWOLF_LLM_P2_BASE_URL=http://127.0.0.1:8000/v1
AI_WEREWOLF_LLM_P2_API_KEY=local-key
```

优先级：玩家环境变量 > `agents.Px` > profile > default profile > config default > 全局 CLI / 环境变量。

---

## 命令行批量评测

规则 Agent：

```powershell
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --out logs/rule_10p
```

LLM Agent：

```powershell
python -m ai_werewolf run `
  --games 20 `
  --seed 100 `
  --preset 10p-standard `
  --agent-mode llm `
  --llm-agent-config llm_agents.local.json `
  --out logs/llm_10p
```

生成 leaderboard：

```powershell
python -m ai_werewolf leaderboard logs/rule_10p logs/llm_10p `
  --out logs/compare/leaderboard.json `
  --markdown logs/compare/leaderboard.md `
  --html logs/compare/leaderboard.html
```

---

## 常用命令

查看可用板子：

```powershell
python -m ai_werewolf boards
```

运行单局并生成 replay：

```powershell
python -m ai_werewolf run --games 1 --seed 42 --preset 6p --out logs/demo
```

自定义角色：

```powershell
python -m ai_werewolf run --games 1 --seed 7 --roles werewolf,werewolf,seer,witch,hunter,guard,villager,villager --out logs/custom
```

---

## 目录结构

```text
ai_werewolf/
├── agents/       # RuleBasedAgent、LLMAgent、HumanAgent
├── configs/      # 角色板子
├── engine/       # 对局引擎
├── eval/         # review、replay、leaderboard
├── llm/          # LLM provider、prompt、parser、agent config
├── logging/      # JSONL event store
├── models/       # schema、action、event、observation
├── rules/        # 角色、动作合法性、胜负规则
├── visibility/   # Agent 可见信息隔离
└── web/          # 本地 Web API 与静态前端
docs/
└── llm_agents.example.json
tests/
```

---

## 信息隔离与安全

- Agent 只能接收经过过滤的 `AgentObservation`，不能直接访问完整 `GameState`。
- 公开事件会自动移除 `reasoning_summary`、raw prompt、raw response、私密技能结果等字段。
- `.env`、`llm_agents.local.json`、`logs/`、IDE 文件和运行产物不应提交到仓库。

---

## 仓库维护建议

提交前确认以下内容没有被跟踪：

```powershell
git status --ignored
```

如果历史上已经提交过运行产物或 IDE 文件，可执行：

```powershell
git rm -r --cached logs .idea 2>$null
git rm --cached .gitingore FINAL_REVIEW.md 2>$null
```

然后再提交源码、测试和必要文档。
