# Web Architecture

Web 模式由一个本地 Python HTTP 服务和静态前端组成。后端负责创建和推进游戏 Session，前端通过 API / SSE 展示状态。

## 核心对象

- `WebSessionManager`：管理多个游戏 Session。
- `WebGameSession`：单局游戏的隔离单元，拥有独立引擎、日志、复盘和回放文件。
- `BrowserHumanAgent`：浏览器人类玩家代理，轮到人类行动时等待 `/action` 提交。

## 主要路由

```text
GET  /                              静态前端
GET  /game/<session_id>             指定 Session 页面
GET  /api/sessions                  Session 列表
POST /api/sessions                  创建新 Session
GET  /api/sessions/<id>/state       当前状态
GET  /api/sessions/<id>/stream      SSE 状态流
GET  /api/sessions/<id>/pending     人类玩家待办动作
POST /api/sessions/<id>/action      提交人类动作
GET  /artifacts/<id>/log            events.jsonl
GET  /artifacts/<id>/review         review.json
GET  /artifacts/<id>/html           replay.html
```

## 输出目录

```text
logs/web/session_<session_id>/
├── events.jsonl
├── review.json
└── replay.html
```

每局独立目录，避免固定文件名覆盖或浏览器误看旧局。

## Windows 说明

`serve` 默认使用 `--port 0`，由系统自动分配可用端口。启动后以终端打印的 URL 为准，不要手动假设端口一定是 `8765`。
