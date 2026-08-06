"""Именование файлов: латиница, kebab-case, версии. Утверждённое не перезаписывается."""
from __future__ import annotations

import re
from pathlib import Path

# Транслитерация под смысловые имена файлов, а не под ГОСТ.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_VERSION_RE = re.compile(r"^(?P<slug>.+?)-v(?P<num>\d+)$")


def translit(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(_TRANSLIT.get(ch, ch))
    return "".join(out)


def slugify(phrase: str) -> str:
    """«Я приношу весь свой объем» -> 'ya-prinoshu-ves-svoy-obem'."""
    s = translit(phrase)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "sticker"


def next_version(slug: str, directory: Path) -> int:
    """Следующая свободная версия. Существующие файлы никогда не трогаем."""
    if not directory.exists():
        return 1
    highest = 0
    for path in directory.glob(f"{slug}-v*.webp"):
        m = _VERSION_RE.match(path.stem)
        if m and m.group("slug") == slug:
            highest = max(highest, int(m.group("num")))
    return highest + 1


def versioned_name(slug: str, version: int, suffix: str = ".webp") -> str:
    return f"{slug}-v{version}{suffix}"


def allocate(phrase: str, directory: Path, suffix: str = ".webp") -> tuple[str, int, str]:
    """Возвращает (slug, version, filename) для новой генерации."""
    slug = slugify(phrase)
    version = next_version(slug, directory)
    return slug, version, versioned_name(slug, version, suffix)


def reserve(phrase: str, directory: Path, suffix: str = ".webp") -> tuple[str, int, str]:
    """Атомарно занять имя файла; безопасно для параллельных генераций."""
    directory.mkdir(parents=True, exist_ok=True)
    slug = slugify(phrase)
    version = 1
    while True:
        filename = versioned_name(slug, version, suffix)
        try:
            (directory / filename).touch(exist_ok=False)
            return slug, version, filename
        except FileExistsError:
            version += 1
