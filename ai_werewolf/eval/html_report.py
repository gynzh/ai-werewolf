from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from ai_werewolf.logging.event_store import EventStore


def save_html_replay(review: dict[str, Any], store: EventStore, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    public_events = [e for e in store.events if e.visibility == "public"]
    rows = []
    for e in public_events:
        payload = html.escape(json.dumps(e.payload, ensure_ascii=False, indent=2))
        rows.append(
            f"<tr><td>{e.round_index}</td><td>{html.escape(e.phase)}</td>"
            f"<td>{html.escape(e.event_type)}</td><td>{html.escape(str(e.actor_id or '系统'))}</td>"
            f"<td><pre>{payload}</pre></td></tr>"
        )
    roles = review.get("roles", {})
    role_cards = []
    for pid, info in roles.items():
        status = "存活" if info.get("alive") else f"死亡：{info.get('death_reason')}"
        role_cards.append(
            f"<div class='card'><b>{html.escape(pid)} · {html.escape(info.get('name',''))}</b>"
            f"<br>身份：{html.escape(info.get('role_cn',''))}"
            f"<br>阵营：{html.escape(info.get('faction_cn') or info.get('faction',''))}"
            f"<br>状态：{html.escape(status)}</div>"
        )
    metrics = review.get("metrics", {})
    player_rows = []
    for pid, info in metrics.get("player_reports", {}).items():
        player_rows.append(
            f"<tr><td>{html.escape(pid)}</td><td>{html.escape(info.get('role_cn',''))}</td>"
            f"<td>{'是' if info.get('alive') else '否'}</td><td>{info.get('speeches')}</td>"
            f"<td>{info.get('votes_cast')}</td><td>{info.get('votes_received')}</td>"
            f"<td>{info.get('votes_to_wolves')}</td><td>{info.get('votes_to_good')}</td></tr>"
        )
    turning_rows = []
    for item in review.get("turning_points", []):
        turning_rows.append(
            f"<tr><td>{html.escape(str(item.get('round')))}</td><td>{html.escape(item.get('impact',''))}</td>"
            f"<td>{html.escape(item.get('description',''))}</td></tr>"
        )
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>AI Werewolf Replay - {html.escape(review.get('game_id',''))}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 32px; background: #f7f7f8; color: #202124; }}
h1, h2 {{ margin-bottom: 8px; }}
.summary {{ padding: 16px; background: white; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; line-height: 1.8; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
.card {{ background: white; border-radius: 12px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.08); line-height: 1.7; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }}
th, td {{ border-bottom: 1px solid #eee; padding: 10px; vertical-align: top; text-align: left; }}
th {{ background: #eceff3; }}
pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eceff3; margin-right: 8px; }}
</style>
</head>
<body>
<h1>AI 狼人杀 v2.0 对局回放</h1>
<div class="summary">
<b>Game ID：</b>{html.escape(review.get('game_id',''))}<br>
<b>胜利阵营：</b>{html.escape(review.get('winner_cn',''))}<br>
<b>胜负原因：</b>{html.escape(review.get('win_reason',''))}<br>
<b>复盘摘要：</b>{html.escape(review.get('summary',''))}<br>
<span class="badge">总事件 {metrics.get('total_events')}</span>
<span class="badge">公开事件 {metrics.get('public_events')}</span>
<span class="badge">好人投狼率 {_pct(metrics.get('vote_accuracy_good_to_wolf'))}</span>
<span class="badge">狼人投好人率 {_pct(metrics.get('vote_accuracy_wolf_to_good'))}</span>
<span class="badge">fallback {metrics.get('process_metrics', {}).get('fallback_count')}</span>
</div>
<h2>身份与状态</h2>
<div class="grid">{''.join(role_cards)}</div>
<h2>玩家表现摘要</h2>
<table>
<thead><tr><th>玩家</th><th>身份</th><th>存活</th><th>发言</th><th>投票</th><th>被投</th><th>投狼</th><th>投好人</th></tr></thead>
<tbody>{''.join(player_rows)}</tbody>
</table>
<h2>关键转折</h2>
<table><thead><tr><th>轮次</th><th>影响</th><th>说明</th></tr></thead><tbody>{''.join(turning_rows)}</tbody></table>
<h2>公开事件时间线</h2>
<table>
<thead><tr><th>轮次</th><th>阶段</th><th>事件</th><th>角色</th><th>内容</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body>
</html>"""
    path.write_text(content, encoding="utf-8")


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"
