"""Локальная память фраз сообщества.

SQLite бота — единственное хранилище. Векторы считаются внутри процесса
детерминированным char-ngram алгоритмом; сеть и shared services не используются.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import numpy as np

log = logging.getLogger(__name__)

VECTOR_DIMENSIONS = 768
DUPLICATE_THRESHOLD = 0.82

_PUNCT_RE = re.compile(r"[*«»\"'`]+")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Similar:
    phrase: str
    score: float
    slug: str
    version: int
    sticker_id: int


def normalise(phrase: str) -> str:
    text = unicodedata.normalize("NFC", phrase)
    text = _PUNCT_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip().lower()


def same_phrase(a: str, b: str) -> bool:
    return normalise(a) == normalise(b)


def decide_duplicate(matches: list[Similar], *, threshold: float = DUPLICATE_THRESHOLD):
    if not matches:
        return None
    best = max(matches, key=lambda match: match.score)
    return best if best.score >= threshold else None


async def embed(text: str) -> list[float] | None:
    """Локальный char-ngram vector: без модели, сети и shared services."""
    value = normalise(text)
    if not value:
        return None
    padded = f"  {value}  "
    vector = np.zeros(VECTOR_DIMENSIONS, dtype=np.float32)
    for size in (2, 3, 4):
        for offset in range(len(padded) - size + 1):
            gram = padded[offset : offset + size].encode("utf-8")
            digest = hashlib.blake2b(gram, digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
    norm = float(np.linalg.norm(vector))
    return (vector / norm).tolist() if norm else None


def _cosine(left: list[float], right: list[float]) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    if a.shape != b.shape or not a.size:
        return 0.0
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


async def remember(
    db_path: Path,
    phrase: str,
    *,
    sticker_id: int,
    slug: str,
    version: int,
    status: str = "created",
) -> bool:
    vector = await embed(normalise(phrase))
    if vector is None:
        return False
    try:
        async with aiosqlite.connect(db_path) as database:
            await database.execute(
                "INSERT OR REPLACE INTO community_vectors"
                "(sticker_id, phrase, normalised, slug, version, status, vector_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    sticker_id,
                    phrase,
                    normalise(phrase),
                    slug,
                    version,
                    status,
                    json.dumps(vector, separators=(",", ":")),
                ),
            )
            await database.commit()
        return True
    except Exception:
        log.warning("не записал локальный индекс фраз", exc_info=True)
        return False


async def find_similar(db_path: Path, phrase: str, *, limit: int = 3) -> list[Similar]:
    try:
        async with aiosqlite.connect(db_path) as database:
            cursor = await database.execute(
                "SELECT sticker_id, phrase, normalised, slug, version, vector_json "
                "FROM community_vectors"
            )
            rows = await cursor.fetchall()
    except Exception:
        log.warning("локальный индекс фраз недоступен", exc_info=True)
        return []

    if not rows:
        return []

    wanted = normalise(phrase)
    for sticker_id, saved_phrase, saved_normalised, slug, version, _vector in rows:
        if saved_normalised == wanted:
            return [Similar(saved_phrase, 1.0, slug, int(version), int(sticker_id))]

    query_vector = await embed(wanted)
    if query_vector is None:
        return []

    matches = [
        Similar(
            phrase=saved_phrase,
            score=_cosine(query_vector, json.loads(vector_json)),
            slug=slug,
            version=int(version),
            sticker_id=int(sticker_id),
        )
        for sticker_id, saved_phrase, _normalised, slug, version, vector_json in rows
    ]
    return sorted(matches, key=lambda match: match.score, reverse=True)[:limit]


async def rebuild_from_db(db_path: Path) -> int:
    """Пересобрать локальные vectors из канонической таблицы stickers."""
    async with aiosqlite.connect(db_path) as database:
        cursor = await database.execute("SELECT id, phrase, slug, version FROM stickers")
        rows = await cursor.fetchall()
        await database.execute("DELETE FROM community_vectors")
        await database.commit()
    indexed = 0
    for sticker_id, phrase, slug, version in rows:
        if phrase and await remember(
            db_path,
            phrase,
            sticker_id=int(sticker_id),
            slug=slug,
            version=int(version),
            status="rebuilt",
        ):
            indexed += 1
    return indexed
