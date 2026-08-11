"""Состояние бота: кто что просил, что сгенерировано, что уехало в пак."""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

#: Каждый вызов открывает своё соединение, а генерации идут параллельно
#: (max_concurrent_generations) вместе с действиями сообщества. В journal_mode
#: DELETE писатель блокирует читателей целиком, и достаточно одной длинной
#: записи, чтобы соседний запрос упал в «database is locked». WAL разводит
#: читателей и писателя, а timeout даёт пережить короткое пересечение писателей.
BUSY_TIMEOUT_SECONDS = 15.0


def connect(path: Path) -> aiosqlite.Connection:
    """Единая точка подключения: одинаковый busy timeout у всех запросов."""
    return aiosqlite.connect(path, timeout=BUSY_TIMEOUT_SECONDS)


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
    ever_in_pack INTEGER NOT NULL DEFAULT 0,
    pack_state  TEXT NOT NULL DEFAULT 'out', -- out | adding | in | removing | restoring
    emoji       TEXT,
    pack_name   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(slug, version)
);

-- Историческая таблица старого approval-flow. Сохраняется только ради данных
-- существующей SQLite; активный бот её не читает и не пишет.
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

-- Локальный семантический индекс фраз сообщества. Никаких Telegram-ID/авторства.
CREATE TABLE IF NOT EXISTS community_vectors (
    sticker_id   INTEGER PRIMARY KEY REFERENCES stickers(id) ON DELETE CASCADE,
    phrase       TEXT NOT NULL,
    normalised   TEXT NOT NULL,
    slug         TEXT NOT NULL,
    version      INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'created',
    vector_json  TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_community_vectors_normalised
    ON community_vectors(normalised);

-- Прозрачная история самоуправления сообщества. Ничего не удаляем из истории:
-- Telegram-пак можно восстановить из файлов и этого журнала.
CREATE TABLE IF NOT EXISTS community_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sticker_id  INTEGER NOT NULL REFERENCES stickers(id),
    user_id     INTEGER NOT NULL,
    action      TEXT NOT NULL, -- added | removed | restored
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_community_actions_user_time
    ON community_actions(user_id, action, created_at);
CREATE INDEX IF NOT EXISTS idx_community_actions_sticker_time
    ON community_actions(sticker_id, created_at);
"""

#: Колонки, добавленные после первого релиза. Ставим по одной, молча пропуская
#: уже существующие — так база из ранней версии доезжает без ручной миграции.
_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN trusted INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE stickers ADD COLUMN pack_name TEXT",
    # Telegram адресует стикер в наборе по file_id — без него удалить нечем.
    "ALTER TABLE stickers ADD COLUMN file_id TEXT",
    "ALTER TABLE stickers ADD COLUMN ever_in_pack INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE stickers ADD COLUMN pack_state TEXT NOT NULL DEFAULT 'out'",
    # Ядро пака: стикеры, зафиксированные до открытия бота сообществу. Их не
    # убирает никто, кроме владельца. Флаг проставляется один раз отдельным
    # скриптом, а НЕ при старте: иначе каждый новый стикер становился бы
    # неприкосновенным после ближайшего перезапуска.
    "ALTER TABLE stickers ADD COLUMN is_core INTEGER NOT NULL DEFAULT 0",
    # Аналитика. Раньше не писалось вообще, поэтому по старым строкам обе
    # колонки останутся пустыми — это честная дыра в истории, а не потеря.
    "ALTER TABLE requests ADD COLUMN chat_type TEXT",
    "ALTER TABLE stickers ADD COLUMN seconds REAL",
)


@dataclass
class StickerRow:
    id: int
    user_id: int
    slug: str
    version: int
    phrase: str
    path: str
    in_pack: bool
    pack_state: str = "out"
    file_id: str | None = None
    pack_name: str | None = None
    #: Часть замороженного ядра — убрать может только владелец.
    is_core: bool = False


@dataclass(frozen=True)
class CommunityAction:
    id: int
    sticker_id: int
    phrase: str
    user_id: int
    username: str | None
    action: str
    detail: str | None
    created_at: str


async def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with connect(path) as db:
        # WAL — свойство самого файла, ставится один раз и переживает рестарты.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.executescript(SCHEMA)
        for statement in _MIGRATIONS:
            # Колонка уже есть — это норма, база просто новее.
            with contextlib.suppress(Exception):
                await db.execute(statement)
        # Старые строки знают только in_pack. Миграция не требует ручной
        # правки живой SQLite и не трогает уже начатые операции.
        await db.execute(
            "UPDATE stickers SET pack_state='in' WHERE in_pack=1 AND pack_state='out'"
        )
        await db.execute("UPDATE stickers SET ever_in_pack=1 WHERE in_pack=1")
        await db.commit()


async def touch_user(path: Path, user_id: int, username: str | None) -> bool:
    """Регистрируем пользователя. Возвращаем False, если он забанен."""
    async with connect(path) as db:
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
    path: Path,
    user_id: int,
    phrase: str,
    status: str,
    detail: str | None = None,
    chat_type: str | None = None,
) -> int:
    async with connect(path) as db:
        cur = await db.execute(
            "INSERT INTO requests(user_id, phrase, status, detail, chat_type) "
            "VALUES(?,?,?,?,?)",
            (user_id, phrase, status, detail, chat_type),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def update_request(
    path: Path, request_id: int, status: str, detail: str | None = None
) -> None:
    async with connect(path) as database:
        await database.execute(
            "UPDATE requests SET status=?, detail=? WHERE id=?",
            (status, detail, request_id),
        )
        await database.commit()


async def count_requests(path: Path, *, user_id: int | None, hours: int) -> int:
    """Сколько удачных генераций за последние N часов."""
    window = f"-{hours} hours"
    async with connect(path) as db:
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


async def count_quota_requests(path: Path, *, user_id: int | None, hours: int) -> int:
    """Успешные + свежие reservations; зависшие pending протухают через 15 минут."""
    window = f"-{hours} hours"
    sql = (
        "SELECT COUNT(*) FROM requests WHERE "
        "((status='ok' AND created_at >= datetime('now', ?)) "
        "OR (status='pending' AND created_at >= datetime('now', '-15 minutes')))"
    )
    params: tuple = (window,)
    if user_id is not None:
        sql += " AND user_id=?"
        params = (window, user_id)
    async with connect(path) as database:
        cur = await database.execute(sql, params)
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def save_sticker(path: Path, *, request_id: int, user_id: int, result) -> int:
    async with connect(path) as db:
        cur = await db.execute(
            "INSERT OR REPLACE INTO stickers"
            "(request_id, user_id, slug, version, phrase, path, raw_path, provider, "
            "model, shape, seconds)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
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
                getattr(result, "seconds", None),
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


_STICKER_COLUMNS = (
    "id, user_id, slug, version, phrase, path, in_pack, pack_state, file_id, "
    "pack_name, is_core"
)


def _sticker(row) -> StickerRow:
    return StickerRow(
        row[0], row[1], row[2], row[3], row[4], row[5], bool(row[6]), row[7], row[8],
        row[9], bool(row[10]),
    )


async def mark_in_pack(
    path: Path,
    sticker_id: int,
    emoji: str,
    pack: str | None = None,
    file_id: str | None = None,
) -> None:
    async with connect(path) as db:
        await db.execute(
            "UPDATE stickers SET in_pack=1, ever_in_pack=1, pack_state='in', "
            "emoji=?, pack_name=?, file_id=? "
            "WHERE id=?",
            (emoji, pack, file_id, sticker_id),
        )
        await db.commit()


async def clear_core(path: Path, sticker_id: int) -> None:
    """Снять неприкосновенность. Нужно якорю: он защищён лишь пока пак пуст."""
    async with connect(path) as db:
        await db.execute("UPDATE stickers SET is_core=0 WHERE id=?", (sticker_id,))
        await db.commit()


async def mark_removed_from_pack(path: Path, sticker_id: int) -> None:
    """Стикер убран из набора. Файл на диске остаётся — можно вернуть обратно."""
    async with connect(path) as db:
        await db.execute(
            "UPDATE stickers SET in_pack=0, pack_state='out', file_id=NULL WHERE id=?",
            (sticker_id,),
        )
        await db.commit()


async def find_in_pack(path: Path, phrase: str) -> StickerRow | None:
    """Ищем по фразе среди тех, что реально лежат в паке.

    Регистр и лишние пробелы не считаются различием: человек пишет «удали
    я так чувствую», а в базе «Я так чувствую». Если версий несколько, берём
    последнюю добавленную — именно она сейчас в наборе.
    """
    needle = " ".join(phrase.split()).casefold()
    if not needle:
        return None
    async with connect(path) as db:
        cur = await db.execute(
            f"SELECT {_STICKER_COLUMNS} FROM stickers WHERE in_pack=1 "
            "ORDER BY created_at DESC, id DESC"
        )
        rows = await cur.fetchall()
    for row in rows:
        if " ".join((row[4] or "").split()).casefold() == needle:
            return _sticker(row)
    return None


async def find_removed(path: Path, phrase: str) -> StickerRow | None:
    """Последняя удалённая версия фразы, которую можно вернуть в общий пак."""
    needle = " ".join(phrase.split()).casefold()
    if not needle:
        return None
    async with connect(path) as database:
        cur = await database.execute(
            f"SELECT {_STICKER_COLUMNS} FROM stickers WHERE in_pack=0 AND ever_in_pack=1 "
            "AND pack_state='out' "
            "ORDER BY created_at DESC, id DESC"
        )
        rows = await cur.fetchall()
    for row in rows:
        if " ".join((row[4] or "").split()).casefold() == needle:
            return _sticker(row)
    return None


async def claim_pack_operation(path: Path, sticker_id: int, operation: str) -> bool:
    """Атомарно захватить внешнюю Telegram-операцию над одним стикером."""
    transitions = {
        "adding": (0, "out"),
        "restoring": (0, "out"),
        "removing": (1, "in"),
    }
    if operation not in transitions:
        raise ValueError(f"unknown pack operation: {operation}")
    expected_in_pack, expected_state = transitions[operation]
    async with connect(path) as database:
        cur = await database.execute(
            "UPDATE stickers SET pack_state=? WHERE id=? AND in_pack=? AND pack_state=?",
            (operation, sticker_id, expected_in_pack, expected_state),
        )
        await database.commit()
        return cur.rowcount > 0


async def release_pack_operation(path: Path, sticker_id: int, operation: str) -> None:
    """Откатить claim после ошибки Telegram, не меняя фактическое членство."""
    async with connect(path) as database:
        await database.execute(
            "UPDATE stickers SET pack_state=CASE WHEN in_pack=1 THEN 'in' ELSE 'out' END "
            "WHERE id=? AND pack_state=?",
            (sticker_id, operation),
        )
        await database.commit()


async def log_community_action(
    path: Path,
    sticker_id: int,
    user_id: int,
    action: str,
    detail: str | None = None,
) -> int:
    async with connect(path) as database:
        cur = await database.execute(
            "INSERT INTO community_actions(sticker_id, user_id, action, detail) VALUES(?,?,?,?)",
            (sticker_id, user_id, action, detail),
        )
        await database.commit()
        return int(cur.lastrowid or 0)


async def count_community_actions(
    path: Path, *, user_id: int, action: str, hours: int
) -> int:
    window = f"-{hours} hours"
    async with connect(path) as database:
        cur = await database.execute(
            "SELECT COUNT(*) FROM community_actions WHERE user_id=? AND action=? "
            "AND created_at >= datetime('now', ?)",
            (user_id, action, window),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def seconds_since_last_community_action(path: Path, sticker_id: int) -> int | None:
    async with connect(path) as database:
        cur = await database.execute(
            "SELECT CAST((julianday('now') - julianday(created_at)) * 86400 AS INTEGER) "
            "FROM community_actions WHERE sticker_id=? ORDER BY id DESC LIMIT 1",
            (sticker_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def recent_community_actions(path: Path, limit: int = 15) -> list[CommunityAction]:
    async with connect(path) as database:
        cur = await database.execute(
            "SELECT a.id, a.sticker_id, s.phrase, a.user_id, u.username, a.action, "
            "a.detail, a.created_at FROM community_actions a "
            "JOIN stickers s ON s.id=a.sticker_id "
            "LEFT JOIN users u ON u.user_id=a.user_id ORDER BY a.id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [CommunityAction(*row) for row in rows]


async def get_sticker(path: Path, sticker_id: int) -> StickerRow | None:
    async with connect(path) as db:
        cur = await db.execute(
            f"SELECT {_STICKER_COLUMNS} FROM stickers WHERE id=?", (sticker_id,)
        )
        row = await cur.fetchone()
    return _sticker(row) if row else None


async def pack_stickers(path: Path) -> list[StickerRow]:
    async with connect(path) as db:
        cur = await db.execute(
            f"SELECT {_STICKER_COLUMNS} FROM stickers WHERE in_pack=1 ORDER BY created_at"
        )
        rows = await cur.fetchall()
    return [_sticker(r) for r in rows]


async def count_in_pack(path: Path, pack: str) -> int:
    async with connect(path) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM stickers WHERE in_pack=1 AND pack_name=?", (pack,)
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def set_banned(path: Path, user_id: int, banned: bool) -> None:
    async with connect(path) as db:
        await db.execute(
            "INSERT INTO users(user_id, banned) VALUES(?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET banned=excluded.banned",
            (user_id, int(banned)),
        )
        await db.commit()


async def stats(path: Path) -> dict:
    async with connect(path) as db:
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
