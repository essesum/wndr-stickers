#!/usr/bin/env python3
"""Публичная страница сезона WNDR — то, чем можно поделиться с клубом.

Это НЕ админка. Здесь нет ников, фраз и того, кто сколько сделал: страница
уходит на GitHub Pages, а Pages публичны всегда, независимо от приватности
репозитория. Персональные цифры остаются в локальной панели (dashboard.py).

    ./.venv/bin/python scripts/site.py [--open]
"""
from __future__ import annotations

import argparse
import html
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dashboard import collect  # noqa: E402

from skill.wndr_stickers.src.config import get_settings  # noqa: E402

PACK_URL = "https://t.me/addstickers/wndr_club_by_WNDR_stickers_bot"
BOT_URL = "https://t.me/WNDR_stickers_bot"
SEASON = "season 3"


def esc(value) -> str:
    return html.escape(str(value))


def month(day: str) -> str:
    return datetime.fromisoformat(day).strftime("%d.%m")


def day_bars(days: list[str], values: dict) -> str:
    """Столбики по дням. На узком экране показываем только последние две недели."""
    top = max([values.get(d, 0) for d in days] + [1])
    cells = []
    for index, d in enumerate(days):
        v = values.get(d, 0)
        height = (v / top * 100) if v else 0
        late = "" if index >= len(days) - 14 else " early"
        cells.append(
            f'<div class="day{late}">'
            f'<div class="day-bar" style="height:{height:.1f}%"></div>'
            f'<span class="day-tick">{esc(month(d)[:2])}</span>'
            f'<span class="day-tip">{esc(month(d))}: {v}</span>'
            f"</div>"
        )
    return (
        '<div class="days" role="img" aria-label="Стикеры по дням за 30 дней">'
        f'{"".join(cells)}</div>'
    )


def hour_bars(hours: dict) -> str:
    top = max(list(hours.values()) + [1])
    cells = []
    for h in range(24):
        v = hours.get(h, 0)
        height = (v / top * 100) if v else 0
        cells.append(
            f'<div class="hour">'
            f'<div class="hour-bar" style="height:{height:.1f}%"></div>'
            f'<span class="hour-tick">{h:02d}</span>'
            f'<span class="day-tip">{h:02d}:00 — {v}</span>'
            f"</div>"
        )
    return (
        '<div class="hours" role="img" aria-label="Активность по часам суток">'
        f'{"".join(cells)}</div>'
    )


def shape_rows(shapes: list[tuple[str, int]]) -> str:
    if not shapes:
        return '<p class="empty">Пока пусто.</p>'
    top = max(n for _, n in shapes) or 1
    rows = []
    for name, n in shapes[:6]:
        rows.append(
            f'<li><span class="shape-name">{esc(name)}</span>'
            f'<span class="shape-track"><span class="shape-fill" '
            f'style="width:{n / top * 100:.0f}%"></span></span>'
            f'<span class="shape-n">{n}</span></li>'
        )
    return f'<ul class="shapes">{"".join(rows)}</ul>'


def render(d: dict, in_pack: int) -> str:
    days = d["days"]
    made_30d = sum(d["per_day"].get(x, 0) for x in days)
    active = d["mau"].get(days[-1], 0)

    table_rows = "".join(
        f"<tr><td>{esc(month(x))}</td><td>{d['per_day'].get(x, 0)}</td>"
        f"<td>{d['dau'].get(x, 0)}</td></tr>"
        for x in days
        if d["per_day"].get(x, 0) or d["dau"].get(x, 0)
    ) or '<tr><td colspan="3">Пока пусто</td></tr>'

    return PAGE.format(
        season=esc(SEASON),
        pack_url=PACK_URL,
        bot_url=BOT_URL,
        in_pack=in_pack,
        made_30d=made_30d,
        active=active,
        total_made=d["stickers_total"],
        day_bars=day_bars(days, d["per_day"]),
        hour_bars=hour_bars(d["hours"]),
        shapes=shape_rows(d["shapes"]),
        table_rows=table_rows,
        updated=esc(datetime.now().strftime("%d.%m.%Y %H:%M")),
    )


PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>WNDR community pack — {season}</title>
<meta name="description" content="Стикерпак WNDR собирает само сообщество.
  Пульс сезона: сколько сделано, когда клуб активен, из чего собран пак.">
<meta name="robots" content="noindex">
<meta property="og:title" content="WNDR community pack — {season}">
<meta property="og:description"
  content="Пак собирает само сообщество. Пришли фразу боту — получишь стикер.">
<meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#F2E2C8; --card:#F7F3EA; --ink:#0D0D0D; --accent:#CC3D11;
  --muted:#6B6257; --rule:#0D0D0D1F; --shadow:#0D0D0D;
  --gap:16px; --radius:16px;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper:#12110E; --card:#1C1A16; --ink:#F2E2C8; --accent:#E8663A;
    --muted:#9A9082; --rule:#F2E2C81F; --shadow:#000;
  }}
}}
* {{ box-sizing:border-box; }}
html {{ -webkit-text-size-adjust:100%; }}
body {{
  margin:0; background:var(--paper); color:var(--ink);
  padding:clamp(16px,4vw,40px) clamp(14px,4vw,32px) 64px;
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  overflow-x:hidden;
}}
.display {{ font-family:Anton,Haettenschweiler,"Arial Narrow",Impact,sans-serif;
  font-weight:400; text-transform:uppercase; letter-spacing:.005em; }}
.wrap {{ max-width:1080px; margin:0 auto; }}

h1 {{ font-size:clamp(40px,11vw,86px); line-height:.9; margin:0 0 14px; }}
h1 em {{ font-style:normal; color:var(--accent); display:block; }}
.lede {{ font-size:clamp(16px,2.4vw,19px); max-width:52ch; margin:0 0 22px; color:var(--ink); }}
.muted {{ color:var(--muted); }}

.cta {{ display:flex; flex-wrap:wrap; gap:10px; margin:0 0 34px; }}
.btn {{
  display:inline-flex; align-items:center; justify-content:center;
  min-height:48px; padding:0 22px; border-radius:999px; text-decoration:none;
  border:2px solid var(--ink); font-weight:600; font-size:15px;
  background:var(--card); color:var(--ink); box-shadow:3px 3px 0 var(--shadow);
  transition:transform .15s ease, box-shadow .15s ease;
}}
.btn.primary {{ background:var(--accent); color:#F7F3EA; border-color:var(--ink); }}
.btn:hover {{ transform:translate(-1px,-1px); box-shadow:4px 4px 0 var(--shadow); }}
.btn:active {{ transform:translate(2px,2px); box-shadow:1px 1px 0 var(--shadow); }}
.btn:focus-visible {{ outline:3px solid var(--accent); outline-offset:3px; }}

.stats {{ display:grid; gap:var(--gap); margin:0 0 var(--gap);
  grid-template-columns:repeat(2,minmax(0,1fr)); }}
.card {{
  background:var(--card); border:2px solid var(--ink); border-radius:var(--radius);
  padding:16px 18px; box-shadow:4px 4px 0 var(--shadow); min-width:0;
}}
.stat b {{ display:block; font-size:clamp(34px,8vw,52px); line-height:1;
  font-family:Anton,Impact,sans-serif; font-weight:400; }}
.stat.hi b {{ color:var(--accent); }}
.stat span {{ display:block; margin-top:6px; font-size:13px; color:var(--muted); }}

section.card {{ margin-bottom:var(--gap); }}
h2 {{ font-size:clamp(17px,3.4vw,21px); margin:0 0 4px; }}
.note {{ margin:0 0 16px; font-size:13px; color:var(--muted); }}

.days, .hours {{ display:flex; align-items:flex-end; gap:2px; height:120px; }}
.day, .hour {{ position:relative; flex:1; min-width:0; height:100%;
  display:flex; flex-direction:column; justify-content:flex-end; align-items:center; }}
.day-bar, .hour-bar {{ width:100%; background:var(--accent);
  border-radius:3px 3px 0 0; min-height:2px; }}
.hour-bar {{ background:var(--ink); }}
.day-tick, .hour-tick {{ font-size:9px; color:var(--muted); margin-top:5px; }}
.day-tip {{
  position:absolute; bottom:100%; left:50%; transform:translateX(-50%);
  background:var(--ink); color:var(--paper); padding:5px 9px; border-radius:7px;
  font-size:12px; white-space:nowrap; opacity:0; pointer-events:none;
  transition:opacity .15s ease; z-index:5;
}}
.day:hover .day-tip, .hour:hover .day-tip,
.day:focus-within .day-tip, .hour:focus-within .day-tip {{ opacity:1; }}

.shapes {{ list-style:none; margin:0; padding:0; }}
.shapes li {{ display:grid; grid-template-columns:minmax(72px,32%) 1fr auto;
  gap:10px; align-items:center; padding:5px 0; }}
.shape-name {{ font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.shape-track {{ background:var(--rule); border-radius:4px; height:14px; overflow:hidden; }}
.shape-fill {{ display:block; height:100%; background:var(--accent); border-radius:0 4px 4px 0; }}
.shape-n {{ font-size:14px; color:var(--muted); font-variant-numeric:tabular-nums; }}

details {{ margin-top:14px; }}
summary {{ cursor:pointer; font-size:14px; color:var(--muted); min-height:44px;
  display:flex; align-items:center; }}
summary:focus-visible {{ outline:3px solid var(--accent); outline-offset:2px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:8px; }}
th, td {{ text-align:left; padding:7px 10px 7px 0; border-bottom:1px solid var(--rule);
  font-variant-numeric:tabular-nums; }}
th {{ color:var(--muted); font-weight:600; }}
.empty {{ color:var(--muted); font-style:italic; }}

footer {{ margin-top:30px; font-size:13px; color:var(--muted); }}
footer a {{ color:inherit; }}

/* Планшет */
@media (min-width:768px) {{
  .stats {{ grid-template-columns:repeat(4,minmax(0,1fr)); }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:var(--gap); }}
  .grid2 > section {{ margin-bottom:0; }}
  .grid2 {{ margin-bottom:var(--gap); }}
  .days, .hours {{ height:150px; }}
}}
/* Узкий телефон: 30 столбиков не читаются — показываем две недели */
@media (max-width:520px) {{
  .day.early {{ display:none; }}
  .hour-tick {{ font-size:8px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition:none !important; animation:none !important; }}
}}
</style></head>
<body>
<div class="wrap">
<header>
  <h1 class="display">WNDR community pack<em>{season}</em></h1>
  <p class="lede">Пак собирает само сообщество. Пришли фразу боту — он вернёт
  готовый стикер в стиле WNDR, и ты сам решаешь, класть его в общий пак или нет.
  Сезон начался с чистого листа: в паке только то, что сделали участники.</p>
  <div class="cta">
    <a class="btn primary" href="{bot_url}">Сделать стикер</a>
    <a class="btn" href="{pack_url}">Добавить пак</a>
  </div>
</header>

<div class="stats">
  <div class="card stat hi"><b>{in_pack}</b><span>в паке сейчас</span></div>
  <div class="card stat"><b>{made_30d}</b><span>сделано за 30 дней</span></div>
  <div class="card stat"><b>{active}</b><span>участников в деле</span></div>
  <div class="card stat"><b>{total_made}</b><span>стикеров за всё время</span></div>
</div>

<section class="card">
  <h2 class="display">Пульс сезона</h2>
  <p class="note">Сколько стикеров рождалось каждый день. Последние 30 дней;
  на телефоне — две недели.</p>
  {day_bars}
  <details>
    <summary>Показать таблицей</summary>
    <table><thead><tr><th>день</th><th>стикеров</th><th>участников</th></tr></thead>
    <tbody>{table_rows}</tbody></table>
  </details>
</section>

<div class="grid2">
  <section class="card">
    <h2 class="display">Когда клуб в ударе</h2>
    <p class="note">Час суток, в который рождаются стикеры.</p>
    {hour_bars}
  </section>

  <section class="card">
    <h2 class="display">Из чего собран пак</h2>
    <p class="note">Форму плашки бот выбирает сам из канонических для WNDR.</p>
    {shapes}
  </section>
</div>

<footer>
  Обновлено {updated} · страница собирается из данных бота ·
  <a href="{pack_url}">пак в Telegram</a>
</footer>
</div>
</body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "site" / "index.html")
    args = parser.parse_args()

    settings = get_settings()
    token = settings.telegram_bot_token
    bot_id = int(token.split(":", 1)[0]) if ":" in token else None

    with sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True) as conn:
        data = collect(conn, bot_id)
        in_pack = data["in_pack"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(data, in_pack), encoding="utf-8")
    print(f"готово: {args.out}")
    if args.open:
        subprocess.run(["open", str(args.out)], check=False)


if __name__ == "__main__":
    main()
