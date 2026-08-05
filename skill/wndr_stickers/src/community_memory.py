"""Память сообщества: что уже было и что повторяется.

Отдельная коллекция Qdrant `wndr_community` — рядом с `katya_memory`, но не
внутри неё. Это память сообщества, а не Кати: фразы посторонних людей не должны
становиться её фактами.

Слои по контракту системы: SQLite — истина, коллекция — перестраиваемый индекс
поверх неё. Потеряли коллекцию — пересобрали из базы, ничего не потеряно.

Персональных данных здесь нет: ни Telegram-ID, ни авторства. Они живут только
в SQLite в `state/`.

Все вызовы best-effort: недоступный Qdrant или Ollama не должен ронять бота —
он лишь лишает его подсказки про повторы.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

COLLECTION = "wndr_community"
DIMS = 768
DISTANCE = "Cosine"

QDRANT_URL = "http://127.0.0.1:6333"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "embeddinggemma:300m"
TIMEOUT = 10.0

#: Порог косинусной близости, за которым фраза считается повтором.
#: Замер на живых фразах пака: перефразировки одной мысли дают 0.83–0.93
#: («Пусть расцветают все цветы» -> 0.93, «Со мной всё окей» -> 0.83),
#: посторонние фразы — 0.40–0.63. Порог поставлен в этот зазор.
DUPLICATE_THRESHOLD = 0.82

#: Пространство имён для стабильных id точек: переиндексация не плодит дубли.
_NAMESPACE = uuid.UUID("8f1d4c2a-6b3e-4f7a-9c1d-2e5b8a0f3d64")

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
    """Регистр, лишние пробелы и звёздочки акцента не делают фразу другой.

    А вот «ё» против «е» и вопросительный знак — делают: это разные стикеры,
    и правила пака на этот счёт однозначны.
    """
    text = unicodedata.normalize("NFC", phrase)
    text = _PUNCT_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip().lower()
    return text


def same_phrase(a: str, b: str) -> bool:
    """Точный повтор — ловим строкой, не тратя вызов эмбеддера."""
    return normalise(a) == normalise(b)


def point_id(sticker_id: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"sticker:{sticker_id}"))


def build_payload(
    *, phrase: str, sticker_id: int, slug: str, version: int, status: str
) -> dict:
    """Только то, что нужно для поиска повторов. Никаких персональных данных."""
    return {
        "phrase": phrase,
        "normalised": normalise(phrase),
        "sticker_id": sticker_id,
        "slug": slug,
        "version": version,
        "status": status,
    }


def decide_duplicate(matches: list[Similar], *, threshold: float = DUPLICATE_THRESHOLD):
    """Ближайшее совпадение, если оно достаточно близко."""
    if not matches:
        return None
    best = max(matches, key=lambda m: m.score)
    return best if best.score >= threshold else None


# --- сетевые адаптеры (best-effort) ------------------------------------------

async def ensure_collection() -> bool:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            existing = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}")
            if existing.status_code == 200:
                return True
            created = await client.put(
                f"{QDRANT_URL}/collections/{COLLECTION}",
                json={"vectors": {"size": DIMS, "distance": DISTANCE}},
            )
            return created.status_code < 300
    except Exception:
        log.warning("память сообщества недоступна: не создал коллекцию", exc_info=True)
        return False


async def embed(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": text}
            )
            resp.raise_for_status()
            data = resp.json()
        vectors = data.get("embeddings") or ([data["embedding"]] if "embedding" in data else [])
        return vectors[0] if vectors else None
    except Exception:
        log.warning("не смог посчитать эмбеддинг", exc_info=True)
        return None


async def remember(
    phrase: str, *, sticker_id: int, slug: str, version: int, status: str = "created"
) -> bool:
    vector = await embed(normalise(phrase))
    if vector is None or not await ensure_collection():
        return False
    payload = build_payload(
        phrase=phrase, sticker_id=sticker_id, slug=slug, version=version, status=status
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.put(
                f"{QDRANT_URL}/collections/{COLLECTION}/points",
                params={"wait": "true"},
                json={
                    "points": [
                        {"id": point_id(sticker_id), "vector": vector, "payload": payload}
                    ]
                },
            )
        return resp.status_code < 300
    except Exception:
        log.warning("не записал фразу в память сообщества", exc_info=True)
        return False


async def find_similar(phrase: str, *, limit: int = 3) -> list[Similar]:
    vector = await embed(normalise(phrase))
    if vector is None:
        return []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
                json={"vector": vector, "limit": limit, "with_payload": True},
            )
            if resp.status_code != 200:
                return []
            hits = resp.json().get("result", [])
    except Exception:
        log.warning("поиск по памяти сообщества не удался", exc_info=True)
        return []

    out = []
    for hit in hits:
        p = hit.get("payload") or {}
        out.append(
            Similar(
                phrase=p.get("phrase", ""),
                score=float(hit.get("score", 0.0)),
                slug=p.get("slug", ""),
                version=int(p.get("version", 0)),
                sticker_id=int(p.get("sticker_id", 0)),
            )
        )
    return out


async def rebuild_from_db(db_path: Path) -> int:
    """Коллекция — проекция. Пересобираем её из SQLite, который и есть истина."""
    import aiosqlite

    if not await ensure_collection():
        return 0
    indexed = 0
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT id, phrase, slug, version FROM stickers")
        rows = await cur.fetchall()
    for sticker_id, phrase, slug, version in rows:
        if phrase and await remember(
            phrase, sticker_id=sticker_id, slug=slug, version=version, status="rebuilt"
        ):
            indexed += 1
    return indexed
