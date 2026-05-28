from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def save_batch_html_report(leaderboard: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    overall = leaderboard.get("overall", {})
    version_rows = []
    for version, stats in leaderboard.get("by_version", {}).items():
        version_rows.append(
            f"<tr><td>{html.escape(str(version))}</td><td>{stats.get('total_games')}</td>"
            f"<td>{_pct(stats.get('good_win_rate'))}</td><td>{_pct(stats.get('wolves_win_rate'))}</td>"
            f"<td>{stats.get('avg_rounds')}</td><td>{stats.get('avg_fallback_count')}</td>"
            f"<td>{stats.get('avg_llm_action_count')}</td><td>{stats.get('avg_llm_rule_fallback_count')}</td></tr>"
        )
    role_rows = []
    for role, info in sorted(leaderboard.get("role_survival", {}).items()):
        role_rows.append(f"<tr><td>{html.escape(role)}</td><td>{info['appearances']}</td><td>{info['survived']}</td><td>{_pct(info['survival_rate'])}</td></tr>")
    role_win_rows = []
    for role, info in sorted(leaderboard.get("role_win_rate", {}).items()):
        role_win_rows.append(f"<tr><td>{html.escape(role)}</td><td>{info['appearances']}</td><td>{info['wins']}</td><td>{_pct(info['win_rate'])}</td></tr>")
    game_rows = []
    for game in leaderboard.get("games", []):
        game_rows.append(
            f"<tr><td>{html.escape(str(game.get('game_id')))}</td><td>{html.escape(str(game.get('version_label')))}</td>"
            f"<td>{html.escape(str(game.get('winner')))}</td><td>{html.escape(str(game.get('rounds')))}</td>"
            f"<td>{html.escape(str(game.get('summary')))}</td></tr>"
        )
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>AI Werewolf Leaderboard</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 32px; background: #f7f7f8; color: #202124; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0 24px; }}
.card {{ background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
.value {{ font-size: 28px; font-weight: 700; margin-top: 6px; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 24px; }}
th, td {{ border-bottom: 1px solid #eee; padding: 10px; vertical-align: top; text-align: left; }}
th {{ background: #eceff3; }}
</style>
</head>
<body>
<h1>AI 狼人杀 v2.0 批量评测 Leaderboard</h1>
<div class="grid">
  <div class="card">总局数<div class="value">{leaderboard.get('total_games', 0)}</div></div>
  <div class="card">好人胜率<div class="value">{_pct(overall.get('good_win_rate'))}</div></div>
  <div class="card">狼人胜率<div class="value">{_pct(overall.get('wolves_win_rate'))}</div></div>
  <div class="card">平均轮数<div class="value">{html.escape(str(overall.get('avg_rounds')))}</div></div>
  <div class="card">平均 fallback<div class="value">{html.escape(str(overall.get('avg_fallback_count')))}</div></div>
  <div class="card">平均 LLM 行动<div class="value">{html.escape(str(overall.get('avg_llm_action_count')))}</div></div>
  <div class="card">平均 LLM 回退<div class="value">{html.escape(str(overall.get('avg_llm_rule_fallback_count')))}</div></div>
</div>
<h2>按版本统计</h2>
<table><thead><tr><th>版本</th><th>局数</th><th>好人胜率</th><th>狼人胜率</th><th>平均轮数</th><th>平均 fallback</th><th>平均 LLM 行动</th><th>平均 LLM 回退</th></tr></thead><tbody>{''.join(version_rows)}</tbody></table>
<h2>角色存活统计</h2>
<table><thead><tr><th>角色</th><th>出场数</th><th>存活数</th><th>存活率</th></tr></thead><tbody>{''.join(role_rows)}</tbody></table>
<h2>角色胜率</h2>
<table><thead><tr><th>角色</th><th>出场数</th><th>获胜数</th><th>胜率</th></tr></thead><tbody>{''.join(role_win_rows)}</tbody></table>
<h2>对局摘要</h2>
<table><thead><tr><th>Game ID</th><th>版本</th><th>胜者</th><th>轮数</th><th>摘要</th></tr></thead><tbody>{''.join(game_rows)}</tbody></table>
</body>
</html>"""
    path.write_text(content, encoding="utf-8")


def _pct(value: Any) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.1f}%"
