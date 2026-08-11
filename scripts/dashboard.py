#!/usr/bin/env python3
"""Панель аналитики WNDR: читает SQLite бота, кладёт рядом самодостаточный HTML.

Ничего не публикует и никуда не ходит: данные сообщества — ники, фразы — остаются
на машине, как и весь остальной runtime бота. Файл открывается двойным щелчком.

    ./.venv/bin/python scripts/dashboard.py [--open]
"""
from __future__ import annotations

import argparse
import html
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill.wndr_stickers.src.config import get_settings  # noqa: E402

# --- Палитра ---------------------------------------------------------------
# Слот 1 — фирменный акцент WNDR, остальные подобраны из семейства вывесок
# 1970-х и проверены валидатором палитр: диапазон светлоты, порог хромы,
# различимость при протанопии и дейтеранопии, контраст к поверхности.
# Проверять глазами тут нечего — обе строки прошли все шесть проверок.
LIGHT = ["#CC3D11", "#4A5FA5", "#00907F", "#A8730B", "#7B3F8F"]
DARK = ["#E8663A", "#7B8FD4", "#199E8A", "#BA8710", "#AE6BC2"]

#: День, с которого бот начал писать тип чата и длительность генерации.
TELEMETRY_FROM = "2026-08-11"


def q(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[tuple]:
    return conn.execute(sql, args).fetchall()


# --- Сбор метрик -----------------------------------------------------------
def collect(conn: sqlite3.Connection, bot_id: int | None) -> dict:
    today = date.today()
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]

    # Бот однажды записал заявку на себя — след старого бага кнопки «Ещё
    # вариант», когда автором считался отправитель сообщения, а им был он сам.
    # В метрику людей он попадать не должен: иначе MAU показывает на одного
    # «человека» больше, чем их есть.
    not_bot = "" if bot_id is None else f" AND user_id != {int(bot_id)}"

    per_day = dict(
        q(conn, "SELECT date(created_at), COUNT(*) FROM requests "
                f"WHERE status='ok'{not_bot} GROUP BY 1")
    )
    dau = dict(
        q(conn, "SELECT date(created_at), COUNT(DISTINCT user_id) FROM requests "
                f"WHERE 1=1{not_bot} GROUP BY 1")
    )

    # MAU на каждый день — уникальные люди за скользящие 30 дней.
    mau = {}
    for d in days:
        start = (d - timedelta(days=29)).isoformat()
        mau[d.isoformat()] = q(
            conn,
            "SELECT COUNT(DISTINCT user_id) FROM requests "
            f"WHERE date(created_at) BETWEEN ? AND ?{not_bot}",
            (start, d.isoformat()),
        )[0][0]

    statuses = dict(q(conn, "SELECT status, COUNT(*) FROM requests GROUP BY 1"))
    ok = statuses.get("ok", 0)
    total_requests = sum(statuses.values())

    people = q(
        conn,
        "SELECT COALESCE(u.username, 'id' || r.user_id) AS who, "
        "  SUM(r.status='ok'), SUM(r.status='rejected'), SUM(r.status='failed'), "
        "  COUNT(*) "
        "FROM requests r LEFT JOIN users u ON u.user_id=r.user_id "
        f"WHERE 1=1{not_bot.replace('user_id', 'r.user_id')} "
        "GROUP BY who ORDER BY 5 DESC",
    )

    in_pack = q(conn, "SELECT COUNT(*) FROM stickers WHERE in_pack=1")[0][0]
    core = q(conn, "SELECT COUNT(*) FROM stickers WHERE is_core=1")[0][0]

    # Главная метрика. Автор сам решает, достаточно ли хорош его стикер, чтобы
    # отдать сообществу — это оценка качества генерации его голосом, а не нашим.
    # Импорт исключаем: те стикеры никто не генерировал и не выбирал.
    sticker_not_bot = "" if bot_id is None else f" AND user_id != {int(bot_id)}"
    made = q(
        conn, "SELECT COUNT(*) FROM stickers WHERE provider!='telegram-import'"
              f"{sticker_not_bot}"
    )[0][0]
    put = q(
        conn, "SELECT COUNT(*) FROM stickers WHERE provider!='telegram-import' "
              f"AND ever_in_pack=1{sticker_not_bot}"
    )[0][0]

    # Вернулся ли человек за вторым стикером. Один — любопытство, второй — привычка.
    per_person = q(
        conn, f"SELECT COUNT(*) FROM requests WHERE status='ok'{not_bot} GROUP BY user_id"
    )
    once = sum(1 for (n,) in per_person if n == 1)
    repeat = sum(1 for (n,) in per_person if n > 1)

    # Сколько прошло от знакомства с ботом до первого удачного стикера.
    activation = [
        row[0] for row in q(
            conn,
            "SELECT CAST((julianday(MIN(r.created_at)) - julianday(u.first_seen)) "
            "* 86400 AS INTEGER) FROM users u "
            "JOIN requests r ON r.user_id=u.user_id AND r.status='ok' "
            f"WHERE 1=1{not_bot.replace('user_id', 'u.user_id')} GROUP BY u.user_id",
        )
        if row[0] is not None and row[0] >= 0
    ]

    return {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "days": [d.isoformat() for d in days],
        "per_day": per_day,
        "dau": dau,
        "mau": mau,
        "statuses": statuses,
        "ok": ok,
        "total_requests": total_requests,
        "people": people,
        "in_pack": in_pack,
        "core": core,
        "made": made,
        "put": put,
        "once": once,
        "repeat": repeat,
        "activation": sorted(activation),
        # Кто больше всех нагенерил. Считаем стикеры, а не заявки: отказы и
        # сбои в зачёт не идут, иначе «лидером» станет тот, у кого не выходило.
        "leaderboard": q(
            conn,
            "SELECT COALESCE(u.username, 'id' || s.user_id) AS who, COUNT(*) n, "
            "  SUM(s.ever_in_pack) put "
            "FROM stickers s LEFT JOIN users u ON u.user_id=s.user_id "
            f"WHERE s.provider!='telegram-import'{sticker_not_bot.replace('user_id', 's.user_id')} "
            "GROUP BY who ORDER BY n DESC, put DESC",
        ),
        "buttons": q(
            conn,
            "SELECT name, COUNT(*) FROM ui_events GROUP BY 1 ORDER BY 2 DESC",
        ),
        "buttons_people": q(
            conn, "SELECT COUNT(DISTINCT user_id) FROM ui_events"
        )[0][0],
        "rejections": q(
            conn,
            "SELECT COALESCE(detail,'без причины'), COUNT(*) FROM requests "
            f"WHERE status='rejected'{not_bot} GROUP BY 1 ORDER BY 2 DESC",
        ),
        "stickers_total": q(conn, "SELECT COUNT(*) FROM stickers")[0][0],
        "users_total": q(
            conn, f"SELECT COUNT(*) FROM users WHERE 1=1{not_bot}"
        )[0][0],
        "providers": q(
            conn, "SELECT COALESCE(provider,'?'), COUNT(*) FROM stickers "
                  "GROUP BY 1 ORDER BY 2 DESC"
        ),
        "shapes": q(
            conn, "SELECT COALESCE(shape,'?'), COUNT(*) FROM stickers "
                  "GROUP BY 1 ORDER BY 2 DESC LIMIT 8"
        ),
        "hours": dict(
            q(conn, "SELECT CAST(strftime('%H', created_at) AS INTEGER), COUNT(*) "
                    "FROM requests WHERE status='ok' GROUP BY 1")
        ),
        "chat_types": q(
            conn, "SELECT chat_type, COUNT(*) FROM requests "
                  "WHERE chat_type IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        ),
        "variants": q(
            conn, "SELECT version, COUNT(*) FROM stickers GROUP BY 1 ORDER BY 1"
        ),
        "multi_variant_slugs": q(
            conn, "SELECT COUNT(*) FROM (SELECT slug FROM stickers "
                  "GROUP BY slug HAVING COUNT(*) > 1)"
        )[0][0],
        "durations": [
            r[0] for r in q(
                conn, "SELECT seconds FROM stickers WHERE seconds IS NOT NULL "
                      "ORDER BY seconds"
            )
        ],
        "recent": q(
            conn,
            "SELECT s.created_at, COALESCE(u.username,'участник'), s.phrase, "
            "  s.provider, s.in_pack "
            "FROM stickers s LEFT JOIN users u ON u.user_id=s.user_id "
            "ORDER BY s.id DESC LIMIT 12",
        ),
    }


# --- Кирпичики разметки ----------------------------------------------------
def esc(value) -> str:
    return html.escape(str(value))


def card(title: str, body: str, *, note: str = "", wide: bool = False) -> str:
    note_html = f'<p class="note">{esc(note)}</p>' if note else ""
    return (
        f'<section class="card{" wide" if wide else ""}">'
        f'<h2>{esc(title)}</h2>{note_html}{body}</section>'
    )


def empty(message: str) -> str:
    return f'<p class="empty">{esc(message)}</p>'


def bars(rows: list[tuple[str, float]], *, unit: str = "", slot: int = 0) -> str:
    """Горизонтальные полосы. Одна серия — один цвет: длина уже кодирует величину."""
    if not rows:
        return empty("Пока нет данных.")
    top = max(v for _, v in rows) or 1
    out = ['<ul class="bars">']
    for label, value in rows:
        pct = value / top * 100
        shown = f"{value:g}{unit}"
        out.append(
            f'<li><span class="bar-label">{esc(label)}</span>'
            f'<span class="bar-track"><span class="bar-fill c{slot}" '
            f'style="width:{pct:.1f}%"></span></span>'
            f'<span class="bar-value">{esc(shown)}</span></li>'
        )
    out.append("</ul>")
    return "".join(out)


def sparkbars(days: list[str], values: dict, *, label: str, slot: int = 0) -> str:
    """Столбики по дням. Подпись только у ненулевых — числа на каждом дне не нужны."""
    top = max([values.get(d, 0) for d in days] + [1])
    cells = []
    for d in days:
        v = values.get(d, 0)
        h = (v / top * 100) if v else 0
        human = datetime.fromisoformat(d).strftime("%d.%m")
        cells.append(
            f'<div class="day" data-tip="{esc(human)}: {v} {esc(label)}">'
            f'<div class="day-bar c{slot}" style="height:{h:.1f}%"></div>'
            f'<span class="day-tick">{esc(human[:2])}</span></div>'
        )
    return f'<div class="days">{"".join(cells)}</div>'


def lines(days: list[str], series: list[tuple[str, dict, int]]) -> str:
    """Две серии на одной шкале — DAU и MAU считают одно и то же, людей."""
    width, height, pad = 720, 190, 26
    top = max([v for _, data, _ in series for v in data.values()] + [1])
    inner_w, inner_h = width - pad * 2, height - pad * 2
    step = inner_w / max(len(days) - 1, 1)

    paths, dots, legend = [], [], []
    for name, data, slot in series:
        pts = []
        for i, d in enumerate(days):
            x = pad + i * step
            y = pad + inner_h - (data.get(d, 0) / top) * inner_h
            pts.append((x, y))
        paths.append(
            f'<path class="line c{slot}s" d="M'
            + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            + '"/>'
        )
        for (x, y), d in zip(pts, days, strict=False):
            value = data.get(d, 0)
            if value:
                human = datetime.fromisoformat(d).strftime("%d.%m")
                dots.append(
                    f'<circle class="dot c{slot}f" cx="{x:.1f}" cy="{y:.1f}" r="4.5">'
                    f"<title>{esc(human)} · {esc(name)}: {value}</title></circle>"
                )
        legend.append(
            f'<span class="key"><i class="c{slot}f"></i>{esc(name)}</span>'
        )

    grid = "".join(
        f'<line class="grid" x1="{pad}" x2="{width - pad}" '
        f'y1="{pad + inner_h * f:.1f}" y2="{pad + inner_h * f:.1f}"/>'
        for f in (0, 0.5, 1)
    )
    return (
        f'<div class="legend">{"".join(legend)}</div>'
        f'<svg class="chart" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img">'
        f"{grid}{''.join(paths)}{''.join(dots)}"
        f'<text class="axis" x="{pad}" y="{pad - 8}">{top}</text>'
        f"</svg>"
    )


def table(headers: list[str], rows: list[list]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _human_time(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}с"
    if seconds < 5400:
        return f"{seconds / 60:.0f}мин"
    if seconds < 172800:
        return f"{seconds / 3600:.0f}ч"
    return f"{seconds / 86400:.0f}д"


def _button_label(name: str) -> str:
    """Имя кнопки человеческим языком; `rm:*` разложены по правам нажавшего."""
    known = {
        "again": "🎲 ещё вариант",
        "pack": "➕ в пак",
        "redo": "🔁 ещё раз / всё равно",
        "rm:author": "✕ убрал свой",
        "rm:owner": "✕ убрала владелец",
        "rm:vote": "🙋 просьба убрать чужой",
        "rm:core": "✕ по основе (отказ)",
    }
    return known.get(name, name)


def _short_reason(detail: str) -> str:
    """Причина отказа коротко: полные тексты — это фразы для человека, не метки."""
    text = (detail or "").strip()
    known = {
        "duplicate": "повтор",
        "Ссылки и упоминания на стикер не ставим.": "ссылка",
        "Похоже на набор символов — попробуй осмысленную фразу.": "набор символов",
        "Слишком коротко — напиши фразу целиком.": "слишком коротко",
        "Такую фразу в общий пак не отдам.": "стоп-слово",
    }
    if text in known:
        return known[text]
    if text.startswith("Слишком длинно"):
        return "слишком длинно"
    if text.startswith("Больше") and "слов" in text:
        return "больше 8 слов"
    if text.startswith("Эти символы"):
        return "чужие символы"
    if text.startswith("Звёздочки"):
        return "непарная звёздочка"
    return text[:28]


def stat(value, caption: str, *, accent: bool = False) -> str:
    return (
        f'<div class="stat{" accent" if accent else ""}">'
        f'<b>{esc(value)}</b><span>{esc(caption)}</span></div>'
    )


# --- Сборка страницы -------------------------------------------------------
def render(d: dict) -> str:
    ok, total = d["ok"], d["total_requests"]
    success = f"{ok / total * 100:.0f}%" if total else "—"

    today = d["days"][-1]
    dau_today = d["dau"].get(today, 0)
    mau_today = d["mau"].get(today, 0)

    # North star — две цифры слева. Всё остальное объясняет их движение.
    pack_rate = f"{d['put'] / d['made'] * 100:.0f}%" if d["made"] else "—"
    people_made = d["once"] + d["repeat"]
    retention = f"{d['repeat'] / people_made * 100:.0f}%" if people_made else "—"

    hero = "".join([
        stat(pack_rate, "сделанного ушло в пак", accent=True),
        stat(retention, "вернулись за вторым", accent=True),
        stat(d["in_pack"], "в паке сейчас"),
        stat(success, "запросов дошло до стикера"),
        stat(dau_today, "DAU сегодня"),
        stat(mau_today, "MAU за 30 дней"),
    ])

    cards = []

    cards.append(card(
        "Люди: DAU и MAU",
        lines(d["days"], [("DAU", d["dau"], 0), ("MAU (30 дней)", d["mau"], 1)]),
        note="DAU — уникальные люди за день, MAU — за скользящие 30 дней.",
        wide=True,
    ))

    cards.append(card(
        "Стикеры по дням",
        sparkbars(d["days"], d["per_day"], label="стикеров", slot=0),
        note="Только удачные генерации, последние 30 дней.",
        wide=True,
    ))

    board = d["leaderboard"]
    medals = ["🥇", "🥈", "🥉"]
    cards.append(card(
        "Кто больше всех нагенерил",
        bars(
            [
                (f"{medals[i] if i < 3 else '  '} {who}", n)
                for i, (who, n, _put) in enumerate(board)
            ],
            slot=0,
        )
        + table(
            ["место", "кто", "стикеров", "из них в паке"],
            [[i + 1, who, n, put or 0] for i, (who, n, put) in enumerate(board)],
        ),
        note="Считаем сделанные стикеры, а не попытки: отказы и сбои в зачёт не "
             "идут, иначе в лидеры выходит тот, у кого не получалось. Импорт "
             "исходного пака тоже не в счёт — его никто не генерировал.",
        wide=True,
    ))

    cards.append(card(
        "Кто сколько запрашивал",
        bars([(p[0], p[1]) for p in d["people"]], slot=1)
        + table(
            ["кто", "стикеров", "отклонено", "сбоев"],
            [list(p[:4]) for p in d["people"]],
        ),
        note="Полосы — удачные генерации; в таблице видно и отказы.",
    ))

    if d["buttons"]:
        cards.append(card(
            "Кнопки: что нажимают",
            bars([(_button_label(n), c) for n, c in d["buttons"]], slot=4)
            + f'<p class="note">Разных людей нажимали: {d["buttons_people"]}</p>',
            note="Раньше в базу попадало только то, чем дело кончилось, а какой "
                 "дорогой человек туда пришёл — терялось.",
        ))
    else:
        cards.append(card(
            "Кнопки: что нажимают",
            empty("Копится с 12 августа — раньше нажатия не записывались."),
        ))

    cards.append(card(
        "Ушло ли в пак",
        "".join([
            '<div class="stats inline">',
            stat(d["made"], "сгенерировано"),
            stat(d["put"], "отдано сообществу"),
            stat(pack_rate, "доля", accent=True),
            "</div>",
        ]),
        note="Автор сам решает, достаточно ли хорош стикер, чтобы положить его "
             "в общий пак. Просядет — значит поехало качество генерации, и это "
             "видно раньше любых жалоб. Импорт не считаем: его никто не выбирал.",
    ))

    cards.append(card(
        "Вернулись за вторым",
        "".join([
            '<div class="stats inline">',
            stat(d["once"], "сделали один раз"),
            stat(d["repeat"], "сделали ещё"),
            stat(retention, "доля", accent=True),
            "</div>",
        ]),
        note="Один стикер — любопытство, второй — привычка. Главное число, "
             "когда в чате много людей: сотня разовых визитов не спасёт пак.",
    ))

    reject_total = sum(n for _, n in d["rejections"])
    funnel_note = (
        "Отказы — это люди, которые хотели сделать стикер и получили «нет» "
        "по формальному правилу. Их видно первыми при росте чата."
    )
    cards.append(card(
        "Воронка: где отваливаются",
        bars(
            [(k, v) for k, v in sorted(d["statuses"].items(), key=lambda kv: -kv[1])],
            slot=2,
        )
        + (
            f'<p class="note">Причины отказов ({reject_total}):</p>'
            + bars([(_short_reason(r), n) for r, n in d["rejections"]], slot=3)
            if d["rejections"] else ""
        ),
        note=funnel_note,
    ))

    if d["activation"]:
        s = d["activation"]
        med = s[len(s) // 2]
        cards.append(card(
            "Сколько до первого стикера",
            "".join([
                '<div class="stats inline">',
                stat(_human_time(med), "медиана"),
                stat(len(s), "человек дошли"),
                "</div>",
            ]),
            note="От знакомства с ботом до первого удачного стикера. Длинный "
                 "путь означает, что человек ушёл, ничего не получив.",
        ))

    cards.append(card(
        "Провайдеры картинок",
        bars([(p[0], p[1]) for p in d["providers"]], slot=1),
        note="telegram-import — стикеры, залитые из исходного пака, а не "
             "сгенерированные.",
    ))

    # «Час суток» и «формы плашек» убраны намеренно: цифры красивые, но ни одно
    # решение от них не менялось. Данные никуда не делись — если понадобятся,
    # запрос вернуть на место дешевле, чем каждый раз пролистывать лишнее.

    if d["chat_types"]:
        chat_body = bars(
            [("личка" if t == "private" else t, n) for t, n in d["chat_types"]],
            slot=1,
        )
    else:
        chat_body = empty("Копится с 11 августа — раньше бот это не записывал.")
    cards.append(card(
        "Личка или общий чат",
        chat_body,
        note=f"Данные с {TELEMETRY_FROM}. Всё, что было раньше, не размечено.",
    ))

    if d["durations"]:
        s = d["durations"]
        med = s[len(s) // 2]
        p90 = s[int(len(s) * 0.9)] if len(s) > 1 else s[0]
        dur_body = "".join([
            '<div class="stats inline">',
            stat(f"{med:.0f}с", "медиана"),
            stat(f"{p90:.0f}с", "90-й перцентиль"),
            stat(len(s), "замеров"),
            "</div>",
        ])
    else:
        dur_body = empty("Копится с 11 августа — раньше время не записывалось.")
    cards.append(card(
        "Сколько ждать стикер",
        dur_body,
        note=f"Данные с {TELEMETRY_FROM}.",
    ))

    variants = d["variants"]
    if d["multi_variant_slugs"]:
        var_body = bars([(f"вариант {v}", n) for v, n in variants], slot=4)
    else:
        counter = stat(d["multi_variant_slugs"], "фраз с несколькими вариантами")
        var_body = (
            f'<div class="stats inline">{counter}</div>'
            + empty("Пока каждую фразу делали по одному разу — кнопкой «Ещё вариант» "
                    "ещё не пользовались.")
        )
    cards.append(card("Варианты одной фразы", var_body))

    cards.append(card(
        "Последние стикеры",
        table(
            ["когда", "кто", "фраза", "провайдер", "в паке"],
            [
                [r[0][:16], r[1], r[2], r[3] or "—", "да" if r[4] else "нет"]
                for r in d["recent"]
            ],
        ),
        wide=True,
    ))

    return PAGE.format(
        generated=esc(d["generated_at"]),
        hero=hero,
        cards="".join(cards),
        core=d["core"],
    )


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WNDR Community — аналитика</title>
<style>
:root {{
  --paper:#F2E2C8; --card:#F7F3EA; --ink:#0D0D0D; --accent:#CC3D11;
  --muted:#6B6257; --rule:#0D0D0D22;
  --c0:#CC3D11; --c1:#4A5FA5; --c2:#00907F; --c3:#A8730B; --c4:#7B3F8F;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper:#12110E; --card:#1C1A16; --ink:#F2E2C8; --accent:#E8663A;
    --muted:#9A9082; --rule:#F2E2C822;
    --c0:#E8663A; --c1:#7B8FD4; --c2:#199E8A; --c3:#BA8710; --c4:#AE6BC2;
  }}
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; padding:28px 20px 64px; background:var(--paper); color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}}
.display {{
  font-family:Haettenschweiler,"Arial Narrow",Impact,sans-serif;
  font-weight:700; letter-spacing:.01em; text-transform:uppercase;
}}
header {{ max-width:1180px; margin:0 auto 26px; }}
h1 {{ font-size:clamp(38px,7vw,68px); line-height:.92; margin:0; }}
h1 em {{ font-style:normal; color:var(--accent); }}
.sub {{ color:var(--muted); margin:10px 0 0; font-size:14px; }}
.wrap {{ max-width:1180px; margin:0 auto; }}
.stats {{
  display:grid; gap:12px; margin-bottom:24px;
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
}}
/* Внутри карточки числа мельче и их до трёх — иначе тройка ломается на 2+1. */
.stats.inline {{
  margin:0; gap:8px;
  grid-template-columns:repeat(auto-fit,minmax(92px,1fr));
}}
.stats.inline .stat {{ padding:12px 14px; box-shadow:2px 2px 0 var(--ink); }}
.stats.inline .stat b {{ font-size:clamp(24px,3vw,32px); }}
.stat {{
  background:var(--card); border:2px solid var(--ink); border-radius:14px;
  padding:16px 18px; box-shadow:3px 3px 0 var(--ink);
}}
.stat b {{
  display:block; font-size:clamp(30px,4vw,44px); line-height:1;
  font-family:Haettenschweiler,"Arial Narrow",Impact,sans-serif; font-weight:700;
}}
.stat.accent b {{ color:var(--accent); }}
.stat span {{ display:block; margin-top:6px; color:var(--muted); font-size:13px; }}
.grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(330px,1fr)); }}
.card {{
  background:var(--card); border:2px solid var(--ink); border-radius:16px;
  padding:18px 20px 20px; box-shadow:4px 4px 0 var(--ink); min-width:0;
}}
.card.wide {{ grid-column:1/-1; }}
.card h2 {{
  margin:0 0 4px; font-size:19px;
  font-family:Haettenschweiler,"Arial Narrow",Impact,sans-serif;
  font-weight:700; text-transform:uppercase; letter-spacing:.02em;
}}
.note {{ margin:0 0 14px; color:var(--muted); font-size:12.5px; }}
.empty {{ color:var(--muted); font-size:13.5px; font-style:italic; margin:10px 0 0; }}
.bars {{ list-style:none; margin:0 0 12px; padding:0; }}
.bars li {{
  display:grid; grid-template-columns:minmax(78px,26%) 1fr auto;
  gap:10px; align-items:center; padding:4px 0;
}}
.bar-label {{ font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.bar-track {{ background:var(--rule); border-radius:4px; height:14px; overflow:hidden; }}
.bar-fill {{ display:block; height:100%; border-radius:0 4px 4px 0; min-width:3px; }}
.bar-value {{ font-size:13px; color:var(--muted); font-variant-numeric:tabular-nums; }}
.days {{ display:flex; align-items:flex-end; gap:2px; height:130px; }}
.day {{
  flex:1; display:flex; flex-direction:column; justify-content:flex-end;
  align-items:center; height:100%; position:relative; min-width:0;
}}
.day-bar {{ width:100%; border-radius:4px 4px 0 0; min-height:2px; }}
.day-tick {{ font-size:9px; color:var(--muted); margin-top:4px; }}
.day:hover::after {{
  content:attr(data-tip); position:absolute; bottom:100%; left:50%;
  transform:translateX(-50%); background:var(--ink); color:var(--paper);
  padding:5px 8px; border-radius:6px; font-size:11px; white-space:nowrap; z-index:5;
}}
.chart {{ width:100%; height:auto; overflow:visible; }}
.grid-line, .grid {{ stroke:var(--rule); stroke-width:1; }}
.line {{ fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }}
.dot {{ stroke:var(--card); stroke-width:2; }}
.axis {{ fill:var(--muted); font-size:11px; }}
.legend {{ display:flex; gap:16px; margin-bottom:8px; flex-wrap:wrap; }}
.key {{ display:flex; align-items:center; gap:6px; font-size:12.5px; color:var(--muted); }}
.key i {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
table {{
  width:100%; border-collapse:collapse; margin-top:12px; font-size:12.5px;
  display:block; overflow-x:auto;
}}
th, td {{
  text-align:left; padding:6px 10px 6px 0;
  border-bottom:1px solid var(--rule); white-space:nowrap;
}}
th {{ color:var(--muted); font-weight:600; }}
td:nth-child(3) {{ white-space:normal; min-width:150px; }}
.c0 {{ background:var(--c0); }} .c1 {{ background:var(--c1); }} .c2 {{ background:var(--c2); }}
.c3 {{ background:var(--c3); }} .c4 {{ background:var(--c4); }}
.c0f {{ fill:var(--c0); }} .c1f {{ fill:var(--c1); }}
.c0s {{ stroke:var(--c0); }} .c1s {{ stroke:var(--c1); }}
.key i.c0f {{ background:var(--c0); }} .key i.c1f {{ background:var(--c1); }}
footer {{ max-width:1180px; margin:30px auto 0; color:var(--muted); font-size:12px; }}
</style></head>
<body>
<header>
  <h1 class="display">WNDR <em>Community</em><br>аналитика</h1>
  <p class="sub">Срез на {generated} · ядро пака: {core} стикеров ·
     данные не покидают эту машину</p>
</header>
<div class="wrap">
  <div class="stats">{hero}</div>
  <div class="grid">{cards}</div>
</div>
<footer>Пересобрать: <code>./.venv/bin/python scripts/dashboard.py</code></footer>
</body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="открыть в браузере")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.db_path.exists():
        raise SystemExit(f"Нет базы: {settings.db_path}")

    out = args.out or settings.output_dir / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    # id бота — это префикс его же токена, так что угадывать по нику не нужно.
    token = settings.telegram_bot_token
    bot_id = int(token.split(":", 1)[0]) if ":" in token else None

    with sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True) as conn:
        page = render(collect(conn, bot_id))

    out.write_text(page, encoding="utf-8")
    out.chmod(0o600)
    print(f"готово: {out}")
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
