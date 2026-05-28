# AI 狼人杀 — 多智能体协作与博弈 Agent Team 系统 v2.1

这是一个可直接运行的 AI 狼人杀多 Agent 项目。当前 v2.1 已实现完整对局引擎、多角色 Agent、严格信息隔离、结构化日志、自动复盘、批量评测 Leaderboard、HTML 回放、本地浏览器观战 / 人机混战 UI，并新增**真实 LLM API 接口**。

项目支持两种 AI 运行模式：

- `rule`：本地规则 Agent，无需网络和 API Key，适合验收、测试、批量跑分。
- `llm`：真实 LLM Agent，通过 OpenAI-compatible `/v1/chat/completions` API 调用模型，适合展示多 Agent 大模型博弈能力。

进阶方向选择并实现：**② 评测+复盘**。

---

## 1. 已实现功能总览

### 核心功能

- 多 Agent 自主对局。
- 每个 Agent 按身份拥有独立目标、策略和动作空间。
- 狼人阵营夜间私密协商与击杀投票。
- 角色支持：狼人、预言家、女巫、猎人、守卫、平民。
- 完整回合流转：夜晚行动、白天发言、投票放逐、猎人开枪、胜负裁决。
- 严格信息隔离：Agent 只能接收 `AgentObservation`，不能访问完整 `GameState`。
- 结构化 JSONL 事件日志，全程可观测。
- 自动复盘 JSON。
- 单局 HTML 回放。
- 批量 Leaderboard：JSON / Markdown / HTML。
- 本地浏览器观战 UI，支持纯 AI 对战或人机混战。
- OpenAI-compatible LLM API Provider。
- LLM 调用失败或输出非法时可自动回退到规则 Agent。

### 评测+复盘

- 结果评测：阵营胜率、角色存活率、角色胜率、平均轮数。
- 过程评测：投票准确率、狼刀命中、预言家查验、女巫用药、守卫守护、猎人开枪、fallback 率。
- LLM 评测：LLM 行动次数、LLM 错误次数、LLM 规则回退次数、平均延迟。
- 自动复盘：关键转折、死亡记录、玩家行为摘要。
- Leaderboard：支持不同版本 / 不同模型 Agent 的同台比较。

---

## 2. 环境要求

- Python 3.10+
- 默认规则 Agent 无强制第三方依赖
- LLM 模式需要可访问 OpenAI-compatible Chat Completions API

在项目根目录运行：

```bash
python -m ai_werewolf boards
```

---

## 3. 可用板子

```bash
python -m ai_werewolf boards
```

| 预设 | 角色配置 |
|---|---|
| `6p` | 2 狼人 + 1 预言家 + 1 女巫 + 2 平民 |
| `8p-simple` | 3 狼人 + 1 预言家 + 1 女巫 + 3 平民 |
| `10p-standard` | 3 狼人 + 1 预言家 + 1 女巫 + 1 猎人 + 1 守卫 + 3 平民 |

---

## 4. 运行规则 Agent 纯 AI 对战

运行一局 6 人局：

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 6p --out logs/demo
```

运行一局 10 人标准局：

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 10p-standard --out logs/demo_10p
```

批量运行并生成 Leaderboard：

```bash
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --out logs/batch_10p
```

输出文件：

```text
logs/batch_10p/
├── game_001_seed_100.jsonl
├── game_001_seed_100_review.json
├── game_001_seed_100_replay.html
├── ...
├── batch_summary.json
├── leaderboard.json
├── leaderboard.md
└── leaderboard.html
```

---

## 5. 运行真实 LLM Agent

### 5.1 使用环境变量

PowerShell：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="gpt-4o-mini"
python -m ai_werewolf run --games 1 --seed 42 --preset 6p --agent-mode llm --out logs/llm_demo --version-label openai_gpt4o_mini
```

也支持项目专用变量：

```powershell
$env:AI_WEREWOLF_LLM_API_KEY="你的 API Key"
$env:AI_WEREWOLF_LLM_MODEL="gpt-4o-mini"
$env:AI_WEREWOLF_LLM_BASE_URL="https://api.openai.com/v1"
python -m ai_werewolf run --games 1 --preset 6p --agent-mode llm --out logs/llm_demo
```

### 5.2 直接通过命令行传参

```bash
python -m ai_werewolf run \
  --games 1 \
  --seed 42 \
  --preset 6p \
  --agent-mode llm \
  --llm-api-key YOUR_API_KEY \
  --llm-base-url https://api.openai.com/v1 \
  --llm-model gpt-4o-mini \
  --llm-temperature 0.2 \
  --llm-max-tokens 700 \
  --out logs/llm_demo \
  --version-label openai_gpt4o_mini
```

### 5.3 接本地或代理 OpenAI-compatible 服务

只要服务暴露 `/v1/chat/completions`，即可替换 `base_url`：

```bash
python -m ai_werewolf run \
  --games 1 \
  --preset 6p \
  --agent-mode llm \
  --llm-api-key local-key \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --llm-model local-model \
  --out logs/local_llm
```

### 5.4 JSON Mode

部分 OpenAI-compatible 服务支持 JSON mode。支持时可加：

```bash
--llm-json-mode
```

如果本地兼容服务不支持 `response_format`，不要加该参数。

### 5.5 LLM 失败回退

默认情况下，LLM 调用失败、输出无法解析或动作非法时，系统会尽量回退，保证对局不中断：

- LLM 调用 / JSON 解析失败：`LLMAgent` 回退到 `RuleBasedAgent`。
- LLM 返回非法游戏动作：`GameEngine` 使用合法 fallback 动作。

如果希望严格暴露错误，可使用：

```bash
--no-llm-rule-fallback
```

---

## 6. 运行命令行人机混战

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 10p-standard --human P1 --out logs/human_console
```

多个人类玩家：

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 10p-standard --human P1,P3 --out logs/human_console
```

人类 + LLM 混战：

```bash
python -m ai_werewolf run --games 1 --preset 6p --human P1 --agent-mode llm --out logs/human_llm
```

注意：命令行人机混战一次只支持一局。

---

## 7. 启动浏览器观战 / 人机混战 UI

规则 Agent 观战：

```bash
python -m ai_werewolf serve --preset 10p-standard --human "" --seed 42 --out logs/web_ai
```

人机混战：

```bash
python -m ai_werewolf serve --preset 10p-standard --human P1 --seed 42 --out logs/web_human
```

LLM Agent 浏览器观战：

```bash
python -m ai_werewolf serve --preset 6p --human "" --agent-mode llm --seed 42 --out logs/web_llm
```

打开：

```text
http://127.0.0.1:8765
```

Web UI 能显示：

- 当前阶段、轮次、胜负状态。
- 玩家座位与存活状态。
- 上帝视角身份开关。
- 公开事件时间线。
- 人类玩家行动面板。
- 对局结束后保存 JSONL、review、HTML replay。

---

## 8. 自定义角色

```bash
python -m ai_werewolf run --games 1 --seed 7 --roles werewolf,werewolf,seer,witch,hunter,guard,villager,villager --out logs/custom
```

合法角色：

```text
werewolf, seer, witch, hunter, guard, villager
```

---

## 9. 重新生成 Leaderboard

```bash
python -m ai_werewolf leaderboard logs/batch_10p --out logs/batch_10p/rebuilt_leaderboard.json --markdown logs/batch_10p/rebuilt_leaderboard.md --html logs/batch_10p/rebuilt_leaderboard.html
```

比较规则 Agent 与 LLM Agent：

```bash
python -m ai_werewolf run --games 20 --seed 1 --preset 10p-standard --version-label rule_based_v2_1 --out logs/rule_v2_1
python -m ai_werewolf run --games 20 --seed 1 --preset 10p-standard --agent-mode llm --version-label llm_model_v1 --out logs/llm_v1
python -m ai_werewolf leaderboard logs/rule_v2_1 logs/llm_v1 --out logs/compare/leaderboard.json --markdown logs/compare/leaderboard.md --html logs/compare/leaderboard.html
```

---

## 10. 测试

```bash
python -m unittest discover tests
```

当前 v2.1 验证结果：

```text
Ran 10 tests
OK
```

测试覆盖：

- 6 人局完整闭环。
- 10 人标准局完整闭环。
- 猎人、守卫角色支持。
- 信息隔离检查。
- 自定义角色与人类玩家解析。
- 猎人死亡后开枪动作合法性。
- Leaderboard 生成。
- LLM Agent Prompt / JSON Parser。
- OpenAI-compatible Provider 本地 HTTP mock 测试。
- Web 会话纯 AI 对战完成与产物保存。

---

## 11. 目录结构

```text
ai-werewolf-mvp/
├── ai_werewolf/
│   ├── agents/          # RuleBasedAgent / LLMAgent / HumanAgent
│   ├── configs/         # 板子配置
│   ├── engine/          # GameEngine 对局引擎
│   ├── eval/            # review / replay / leaderboard
│   ├── llm/             # provider / prompt builder / parser
│   ├── logging/         # EventStore JSONL
│   ├── models/          # GameState / Action / Event / Observation
│   ├── rules/           # 角色与动作合法性
│   ├── visibility/      # 信息隔离
│   ├── web/             # 本地浏览器观战与人机混战服务
│   ├── cli.py
│   └── __main__.py
├── docs/
│   └── DEVELOPMENT_PLAN.md
├── tests/
│   └── test_mvp.py
├── logs/
├── pyproject.toml
└── README.md
```

---

## 12. LLM 接口实现文件

```text
ai_werewolf/llm/provider_base.py
ai_werewolf/llm/openai_compatible_provider.py
ai_werewolf/llm/prompt_builder.py
ai_werewolf/llm/output_parser.py
ai_werewolf/agents/llm_agent.py
```

核心调用链：

```text
GameEngine
  ↓ VisibilityManager
AgentObservation
  ↓ PromptBuilder
LLMAgent
  ↓ OpenAICompatibleProvider
/v1/chat/completions
  ↓ OutputParser
Action
  ↓ ActionValidator
GameEngine 结算
```

---

## 13. 核心设计原则

### 13.1 GameState 与 AgentObservation 隔离

`GameState` 是完整系统真相，只由 `GameEngine` 持有。Agent 永远只接收经过过滤的 `AgentObservation`。

### 13.2 LLM 也不能越权

LLM Prompt 只包含当前玩家可见信息。即使接入真实大模型，也不会把完整身份表、其他玩家私有技能结果、狼队私密信息泄露给无权限 Agent。

### 13.3 日志可复盘

所有关键行为都写入 `GameEvent`。LLM 模式下还记录：

- provider
- model
- latency
- LLM 错误
- LLM 回退次数
- engine fallback 次数

---

## 14. 当前边界

v2.1 已完成题目主体与进阶方向 ② 的可运行交付。仍可继续扩展：

- Azure OpenAI 专用 Provider。
- Ollama 原生 Provider。
- React + WebSocket 高级前端。
- 更多角色和复杂板子。
- 自进化 Agent。

当前版本已经具备完整本地运行、真实 LLM 接入、观战、复盘、评测和人机混战能力。
