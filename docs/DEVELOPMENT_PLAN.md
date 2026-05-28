# AI 狼人杀多 Agent 系统开发方案（v2.1 实现版）

本文档与当前 v2.1 代码保持一致。项目已经实现题目主体功能，并补齐真实 LLM API 接口。当前系统包含完整对局引擎、多角色 Agent、信息隔离、结构化日志、自动复盘、批量 Leaderboard、HTML 回放、本地浏览器观战 UI、人机混战入口，以及 OpenAI-compatible LLM Provider。

---

## 1. 项目目标

本项目面向“AI 狼人杀 — 多智能体协作与博弈的 Agent Team 实战”任务，目标是构建一个能够自主完成信息不对称博弈的狼人杀 Agent Team 系统。

系统重点体现：

1. 多 Agent 协作与对抗。
2. 独立角色目标、策略和动作空间。
3. 严格信息隔离。
4. 完整对局状态机。
5. 结构化可观测日志。
6. 自动复盘和量化评测。
7. 纯 AI 对战与人机混战。
8. 前端观战 UI。
9. 真实 LLM API 接入。

进阶方向选择 **② 评测+复盘**：构建结果评测、过程评测、多维量化指标、复盘归因和不同 Agent 版本对比 Leaderboard。

---

## 2. 当前 v2.1 完成范围

### 2.1 对局引擎

已实现完整状态机：

```text
ROLE_ASSIGNMENT
  ↓
NIGHT_START
  ↓
GUARD_ACTION
  ↓
WEREWOLF_DISCUSSION
  ↓
WEREWOLF_KILL
  ↓
SEER_CHECK
  ↓
WITCH_ACTION
  ↓
NIGHT_RESOLUTION
  ↓
HUNTER_SHOOT（条件触发）
  ↓
DAY_ANNOUNCEMENT
  ↓
DAY_DISCUSSION
  ↓
DAY_VOTE
  ↓
EXILE_RESOLUTION
  ↓
HUNTER_SHOOT（条件触发）
  ↓
WIN_CHECK
  ↓
NEXT_ROUND or GAME_END
```

### 2.2 角色系统

| 角色 | 阵营 | 行动空间 |
|---|---|---|
| 狼人 | 狼人阵营 | 夜间协商、夜间击杀、白天伪装发言、投票 |
| 预言家 | 好人阵营 | 夜间查验、白天公开或隐藏信息、投票 |
| 女巫 | 好人阵营 | 解药、毒药、白天发言、投票 |
| 猎人 | 好人阵营 | 死亡后开枪或跳过、白天发言、投票 |
| 守卫 | 好人阵营 | 夜间守护，不能连续两晚守同一人 |
| 平民 | 好人阵营 | 白天发言、投票 |

### 2.3 板子配置

```text
6p: 2 狼人 + 1 预言家 + 1 女巫 + 2 平民
8p-simple: 3 狼人 + 1 预言家 + 1 女巫 + 3 平民
10p-standard: 3 狼人 + 1 预言家 + 1 女巫 + 1 猎人 + 1 守卫 + 3 平民
```

同时支持 `--roles` 自定义角色列表。

### 2.4 Agent 类型

1. `RuleBasedAgent`
   - 本地规则 Agent。
   - 不依赖外部 API。
   - 用于稳定验收和批量基准测试。

2. `LLMAgent`
   - 真实 LLM Agent。
   - 通过 `ModelProvider` 调用模型。
   - 当前内置 `OpenAICompatibleProvider`。
   - 只接收 `AgentObservation`，不接收 `GameState`。
   - 可配置失败回退。

3. `ConsoleHumanAgent`
   - 命令行人机混战。

4. `BrowserHumanAgent`
   - Web UI 人机混战。

---

## 3. 系统架构

```text
CLI / Web UI
   ↓
GameEngine
   ├─ GameState                # 完整系统真相，仅引擎可访问
   ├─ Phase State Machine      # 对局阶段流转
   ├─ VisibilityManager        # 信息隔离，生成 AgentObservation
   ├─ ActionValidator          # 动作合法性校验
   ├─ Agent Runtime            # RuleBased / LLM / Human
   ├─ LLM Provider             # OpenAI-compatible /v1/chat/completions
   ├─ EventStore               # JSONL 结构化日志
   ├─ Review Builder           # 单局复盘
   ├─ HTML Replay              # 单局回放
   └─ Leaderboard Builder      # 批量评测
```

核心调用链：

```text
GameState + EventStore
        ↓
VisibilityManager.build_observation(player_id)
        ↓
AgentObservation
        ↓
RuleBasedAgent 或 LLMAgent
        ↓
Action
        ↓
ActionValidator.validate(state, action)
        ↓
GameEngine 结算状态变化
        ↓
EventStore.append(GameEvent)
```

LLM 调用链：

```text
AgentObservation
  ↓ PromptBuilder
Prompt
  ↓ OpenAICompatibleProvider
/v1/chat/completions
  ↓ OutputParser
Action
```

---

## 4. 代码结构

```text
ai-werewolf-mvp/
├── ai_werewolf/
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── human_agent.py
│   │   ├── llm_agent.py
│   │   └── rule_based_agent.py
│   ├── configs/
│   │   └── boards.py
│   ├── engine/
│   │   └── game_engine.py
│   ├── eval/
│   │   ├── batch_report.py
│   │   ├── html_report.py
│   │   ├── leaderboard.py
│   │   └── review.py
│   ├── llm/
│   │   ├── openai_compatible_provider.py
│   │   ├── output_parser.py
│   │   ├── prompt_builder.py
│   │   └── provider_base.py
│   ├── logging/
│   │   └── event_store.py
│   ├── models/
│   │   └── schema.py
│   ├── rules/
│   │   ├── actions.py
│   │   └── roles.py
│   ├── visibility/
│   │   └── visibility_manager.py
│   ├── web/
│   │   ├── __init__.py
│   │   └── server.py
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

## 5. LLM API 设计与实现

### 5.1 Provider 抽象

`ModelProvider` 是最小模型接口：

```python
class ModelProvider(ABC):
    provider_name: str = "base"
    model_name: str = "unknown"

    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError
```

### 5.2 OpenAI-compatible Provider

`OpenAICompatibleProvider` 使用 Python 标准库 `urllib` 调用：

```text
POST {base_url}/chat/completions
```

请求包含：

- `model`
- `messages`
- `temperature`
- `max_tokens`
- 可选 `response_format={"type":"json_object"}`

支持环境变量：

```text
AI_WEREWOLF_LLM_API_KEY / WEREWOLF_LLM_API_KEY / OPENAI_API_KEY
AI_WEREWOLF_LLM_MODEL / WEREWOLF_LLM_MODEL / OPENAI_MODEL
AI_WEREWOLF_LLM_BASE_URL / WEREWOLF_LLM_BASE_URL / OPENAI_BASE_URL
AI_WEREWOLF_LLM_TEMPERATURE / WEREWOLF_LLM_TEMPERATURE
AI_WEREWOLF_LLM_MAX_TOKENS / WEREWOLF_LLM_MAX_TOKENS
AI_WEREWOLF_LLM_TIMEOUT / WEREWOLF_LLM_TIMEOUT
AI_WEREWOLF_LLM_JSON_MODE / WEREWOLF_LLM_JSON_MODE
```

### 5.3 CLI 参数

```text
--agent-mode rule|llm
--llm-provider openai-compatible
--llm-api-key
--llm-base-url
--llm-model
--llm-temperature
--llm-max-tokens
--llm-timeout
--llm-json-mode
--no-llm-rule-fallback
```

### 5.4 LLM 失败处理

两级容错：

1. `LLMAgent` 层：API 调用失败或 JSON 解析失败时，可回退到 `RuleBasedAgent`。
2. `GameEngine` 层：Agent 返回非法动作时，使用当前阶段合法 fallback 动作。

这样可以保证 LLM 行为不稳定时，对局仍能完整结束。

---

## 6. 信息隔离设计

系统将信息分为四类：

| 类型 | 可见范围 | 示例 |
|---|---|---|
| `public` | 所有玩家 | 发言、投票、白天公告、游戏结束身份揭示 |
| `private` | 单个玩家 | 身份分配、预言家查验结果、女巫夜间刀口、守卫行动 |
| `faction` | 阵营内 | 狼队讨论、狼队击杀票 |
| `system` | 系统与复盘 | 夜间真实结算、fallback 错误、LLM 调用元数据 |

约束：

1. Agent 不接收 `GameState`。
2. Agent 只能接收 `AgentObservation`。
3. LLM Prompt 只包含过滤后的 `AgentObservation`。
4. `LeakChecker` 检查明显隐藏身份泄露。
5. 对局结束前公开事件默认不暴露身份。
6. `game_ended` 才公开完整身份，便于复盘。

---

## 7. 胜负规则

默认 `kill_side`：

- 好人胜利：所有狼人死亡。
- 狼人胜利：所有平民死亡，或所有神职死亡。

也保留 `kill_all` 配置接口。

---

## 8. 评测与复盘体系

### 8.1 单局 review JSON

每局生成：

```text
*_review.json
```

包含：

- 胜利阵营。
- 胜负原因。
- 角色与阵营。
- 死亡记录。
- 投票准确率。
- 预言家查验记录。
- 女巫行动记录。
- 守卫行动记录。
- 猎人开枪记录。
- 狼人刀口记录。
- 放逐记录。
- 玩家行为摘要。
- 过程指标。
- LLM 指标。
- 关键转折。
- 中文复盘摘要。

### 8.2 过程指标

当前指标：

- `fallback_count`
- `fallback_rate_per_event`
- `agent_action_count`
- `agent_action_received_count`
- `llm_action_count`
- `llm_rule_fallback_count`
- `llm_error_count`
- `llm_avg_latency_seconds`
- `wolf_kill_good_rate`
- `wolf_kill_god_rate`
- `seer_found_wolf_count`
- `witch_poison_count`
- `guard_protect_count`
- `guard_successful_save_count`
- `hunter_shot_count`
- `good_vote_to_wolf_rate`
- `wolf_vote_to_good_rate`

### 8.3 Leaderboard

批量评测输出：

```text
leaderboard.json
leaderboard.md
leaderboard.html
```

统计：

- 总局数。
- 好人胜率。
- 狼人胜率。
- 平均轮数。
- 平均 fallback。
- 平均 LLM 行动数。
- 平均 LLM 回退数。
- 平均 LLM 错误数。
- 按 `version_label` 聚合。
- 角色存活率。
- 角色胜率。
- 每局摘要。

---

## 9. 前端观战与人机混战

启动：

```bash
python -m ai_werewolf serve --preset 10p-standard --human P1 --seed 42 --out logs/web
```

浏览器打开：

```text
http://127.0.0.1:8765
```

LLM 观战：

```bash
python -m ai_werewolf serve --preset 6p --human "" --agent-mode llm --seed 42 --out logs/web_llm
```

能力：

1. 纯 AI 实时观战。
2. 人机混战。
3. LLM Agent 对战。
4. 上帝视角开关。
5. 玩家状态面板。
6. 公开事件时间线。
7. 人类行动表单。
8. 对局结束后自动保存 JSONL、review、HTML replay。

---

## 10. 运行与验收

### 查看板子

```bash
python -m ai_werewolf boards
```

### 规则 Agent 纯 AI 对战

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 10p-standard --out logs/demo_10p
```

### LLM Agent 对战

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 6p --agent-mode llm --llm-api-key YOUR_API_KEY --llm-base-url https://api.openai.com/v1 --llm-model gpt-4o-mini --out logs/llm_demo
```

### 批量评测

```bash
python -m ai_werewolf run --games 20 --seed 100 --preset 10p-standard --out logs/batch_10p
```

### 人机混战

```bash
python -m ai_werewolf run --games 1 --seed 42 --preset 10p-standard --human P1 --out logs/human_console
```

### 浏览器观战

```bash
python -m ai_werewolf serve --preset 10p-standard --human P1 --seed 42 --out logs/web
```

### 测试

```bash
python -m unittest discover tests
```

当前测试：

```text
Ran 10 tests
OK
```

---

## 11. 完成度审查

| 目标 | 完成状态 | 对应实现 |
|---|---|---|
| 多 Agent 自主博弈 | 已完成 | `RuleBasedAgent` / `LLMAgent` + `GameEngine` |
| 独立角色目标与动作空间 | 已完成 | `rules/actions.py`、`agents/*` |
| 狼人协作与好人对抗 | 已完成 | wolf faction events、白天发言投票 |
| 严格信息隔离 | 已完成 | `VisibilityManager`、`LeakChecker` |
| 完整对局引擎 | 已完成 | `engine/game_engine.py` |
| 胜负裁决 | 已完成 | `GameEngine._check_win_and_emit_if_finished` |
| 结构化日志 | 已完成 | `EventStore` JSONL |
| 全程可观测 | 已完成 | JSONL、review、HTML replay、Web UI |
| 前端观战 UI | 已完成 | `web/server.py` |
| 纯 AI 对战 | 已完成 | `run` / `serve --human ""` |
| 人机混战 | 已完成 | `--human` console + browser UI |
| LLM API 接口 | 已完成 | `OpenAICompatibleProvider` |
| LLM Agent | 已完成 | `LLMAgent` |
| LLM 失败回退 | 已完成 | `LLMAgent` + `GameEngine` fallback |
| 评测+复盘 | 已完成 | `eval/review.py`、`eval/leaderboard.py` |
| Leaderboard | 已完成 | JSON / MD / HTML |
| 自动测试 | 已完成 | 10 个 unittest |

---

## 12. 当前边界

当前系统已经完成题目主体与进阶方向 ② 的可运行交付。未包含但可继续扩展：

1. Azure OpenAI 专用 Provider。
2. Ollama 原生 Provider。
3. React + WebSocket 高级前端。
4. 更多角色和复杂规则。
5. 自进化 Agent。

这些不是当前题目交付的必要闭环。v2.1 已具备完整本地运行、真实 LLM 接入、观战、复盘、评测和人机混战能力。
