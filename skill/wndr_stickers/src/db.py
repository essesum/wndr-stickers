"""Состояние бота: кто что просил, что сгенерировано, что уехало в пак."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    banned      INTEGER NOT NULL DEFAULT 0,
    trusted     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    phrase      TEXT NOT NULL,
    status      TEXT NOT NULL,               -- ok | rejected | failed
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_requests_user_time ON requests(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_requests_time ON requests(created_at);

CREATE TABLE IF NOT EXISTS stickers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER REFERENCES requests(id),
    user_id     INTEGER NOT NULL,
    slug        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    phrase      TEXT NOT NULL,
    path        TEXT NOT NULL,
    raw_path    TEXT,
    provider    TEXT,
    model       TEXT,
    shape       TEXT,
    in_pack     INTEGER NOT NULL DEFAULT 0,
    emoji       TEXT,
    pack_name   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(slug, version)
);

-- Апрув: что попадает в ОБЩИЙ пак, решают модераторы, а не автор стикера.
CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sticker_id    INTEGER NOT NULL REFERENCES stickers(id),
    submitted_by  INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    decided_by    INTEGER,
    decided_at    TEXT,
    reason        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(sticker_id)
);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status, created_at);
"""

#: Колонки, добавленные после первого релиза. Ставим по одной, молча пропуская
#: уже существующие — так база из ранней версии доезжает без ручной миграции.
_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE stickers ADD COLUMN pack_name TEXT",
)


@dataclass
class StickerRow:
    id: int
    slug: str
    version: int
    phrase: str
    path: str
    in_pack: bool


@dataclass
class Submission:
    id: int
    sticker_id: int
    submitted_by: int
    status: str
    decided_by: int | None
    decided_at: str | None
    reason: str | None
    created_at: str
    phrase: str = ""
    path: str = ""


async def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        for statement in _MIGRATIONS:
            # Колонка уже есть — это норма, база просто новее.
            with contextlib.suppress(Exception):
                await db.execute(statement)
        await db.commit()


async def touch_user(path: Path, user_id: int, username: str | None) -> bool:
    """Регистрируем пользователя. Возвращаем False, если он забанен."""
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO users(user_id, username) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
            (user_id, username),
        )
        await db.commit()
        cur = await db.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
    return not (row and row[0])


async def log_request(
    path: Path, user_id: int, phrase: str, status: str, detail: str | None = None
) -> int:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "INSERT INTO requests(user_id, phrase, status, detail) VALUES(?,?,?,?)",
            (user_id, phrase, status, detail),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def count_requests(path: Path, *, user_id: int | None, hours: int) -> int:
    """Сколько удачных генераций за последние N часов."""
    window = f"-{hours} hours"
    async with aiosqlite.connect(path) as db:
        if user_id is None:
            cur = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE status='ok' "
                "AND created_at >= datetime('now', ?)",
                (window,),
            )
        else:
            cur = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE status='ok' AND user_id=? "
                "AND created_at >= datetime('now', ?)",
                (user_id, window),
            )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def save_sticker(path: Path, *, request_id: int, user_id: int, result) -> int:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "INSERT OR REPLACE INTO stickers"
            "(request_id, user_id, slug, version, phrase, path, raw_path, provider, model, shape)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                request_id,
                user_id,
                result.slug,
                result.version,
                result.phrase,
                str(result.path),
                str(result.raw_path),
                result.provider,
                result.model,
                result.shape,
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def mark_in_pack(
    path: Path, sticker_id: int, emoji: str, pack: str | None = None
) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE stickers SET in_pack=1, emoji=?, pack_name=? WHERE id=?",
            (emoji, pack, sticker_id),
        )
        await db.commit()


async def get_sticker(path: Path, sticker_id: int) -> StickerRow | None:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT id, slug, version, phrase, path, in_pack FROM stickers WHERE id=?",
            (sticker_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return StickerRow(row[0], row[1], row[2], row[3], row[4], bool(row[5]))


async def pack_stickers(path: Path) -> list[StickerRow]:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT id, slug, version, phrase, path, in_pack FROM stickers "
            "WHERE in_pack=1 ORDER BY created_at"
        )
        rows = await cur.fetchall()
    return [StickerRow(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in rows]


# --- апрув -------------------------------------------------------------------

_SUBMISSION_COLUMNS = (
    "s.id, s.sticker_id, s.submitted_by, s.status, s.decided_by, s.decided_at, "
    "s.reason, s.created_at, k.phrase, k.path"
)


def _submission(row) -> Submission:
    return Submission(*row)


async def create_submission(path: Path, sticker_id: int, submitted_by: int) -> int:
    """Заявка на попадание в общий пак. Повторная на тот же стикер вернёт первую."""
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO submissions(sticker_id, submitted_by) VALUES(?, ?)",
            (sticker_id, submitted_by),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id FROM submissions WHERE sticker_id=?", (sticker_id,)
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def get_submission(path: Path, submission_id: int) -> Submission | None:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            f"SELECT {_SUBMISSION_COLUMNS} FROM submissions s "
            "JOIN stickers k ON k.id = s.sticker_id WHERE s.id=?",
            (submission_id,),
        )
        row = await cur.fetchone()
    return _submission(row) if row else None


async def decide_submission(
    path: Path,
    submission_id: int,
    *,
    approved: bool,
    decided_by: int,
    reason: str | None = None,
) -> bool:
    """Решение принимается один раз. Если кто-то уже решил — вернём False.

    Условие status='pending' прямо в UPDATE закрывает гонку двух модераторов,
    нажавших кнопку одновременно.
    """
    status = "approved" if approved else "rejected"
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "UPDATE submissions SET status=?, decided_by=?, reason=?, "
            "decided_at=datetime('now') WHERE id=? AND status='pending'",
            (status, decided_by, reason, submission_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def pending_submissions(path: Path, limit: int = 20) -> list[Submission]:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            f"SELECT {_SUBMISSION_COLUMNS} FROM submissions s "
            "JOIN stickers k ON k.id = s.sticker_id "
            "WHERE s.status='pending' ORDER BY s.created_at LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [_submission(r) for r in rows]


async def approved_count(path: Path, user_id: int) -> int:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM submissions WHERE submitted_by=? AND status='approved'",
            (user_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def is_trusted(path: Path, user_id: int) -> bool:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT trusted FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
    return bool(row and row[0])


async def set_trusted(path: Path, user_id: int, trusted: bool) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO users(user_id, trusted) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET trusted=excluded.trusted",
            (user_id, int(trusted)),
        )
        await db.commit()


async def count_in_pack(path: Path, pack: str) -> int:
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM stickers WHERE in_pack=1 AND pack_name=?", (pack,)
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def set_banned(path: Path, user_id: int, banned: bool) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO users(user_id, banned) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET banned=excluded.banned",
            (user_id, int(banned)),
        )
        await db.commit()


async def stats(path: Path) -> dict:
    async with aiosqlite.connect(path) as db:
        out = {}
        for key, sql in {
            "users": "SELECT COUNT(*) FROM users",
            "stickers": "SELECT COUNT(*) FROM stickers",
            "in_pack": "SELECT COUNT(*) FROM stickers WHERE in_pack=1",
            "today": "SELECT COUNT(*) FROM requests WHERE status='ok' "
            "AND created_at >= datetime('now','-24 hours')",
        }.items():
            cur = await db.execute(sql)
            row = await cur.fetchone()
            out[key] = int(row[0]) if row else 0
    return out
