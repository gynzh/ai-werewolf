# Web 架构说明

当前 Web UI 已从“单局全局状态”升级为“服务实例 + 多 Session”结构。

## 后端对象

- `WebSessionManager`：管理多个 `WebGameSession`，提供 Session 列表、默认 Session 和浏览器创建新局能力。
- `WebGameSession`：一局游戏的完整隔离单元，包含 `GameEngine`、`EventStore`、人类行动等待队列、输出目录和复盘产物。
- `BrowserHumanAgent`：浏览器人类玩家 Agent，通过 `/api/sessions/{id}/pending` 与 `/api/sessions/{id}/action` 交互。

## 路由

- `GET /`：Web 应用首页。
- `GET /game/{session_id}`：进入指定游戏 Session。
- `GET /api/sessions`：Session Center 列表。
- `POST /api/sessions`：从浏览器创建新局。
- `GET /api/sessions/{id}/state?god=1`：读取状态。
- `GET /api/sessions/{id}/stream?god=1`：SSE 实时事件流。
- `GET /api/sessions/{id}/pending?player_id=P1`：读取人类玩家待办动作。
- `POST /api/sessions/{id}/action`：提交浏览器人类动作。
- `GET /artifacts/{id}/log|review|html`：打开该 Session 的产物。

## 输出目录

Web 模式不再用 `web_game_seed_42.*` 这类容易覆盖的文件名。每局使用独立目录：

```text
logs/web/
└── session_<session_id>/
    ├── events.jsonl
    ├── review.json
    └── replay.html
```

## Windows 注意事项

`serve` 默认 `--port 0`，会让 Windows 自动分配一个可用端口，避免旧进程占用 `8765` 导致浏览器打开旧 Session。终端会打印完整 URL，例如：

```powershell
AI 狼人杀 Web 服务已启动：http://127.0.0.1:51234/game/ab12cd34ef
```
