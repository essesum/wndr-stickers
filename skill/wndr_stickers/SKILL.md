---
name: wndr-stickers
description: Стикеры для сообщества WNDR. Использовать, когда Катя делает или правит стикеры WNDR, спрашивает про стикерпак, стиль пака, или когда что-то не так с ботом @wndr-стикеров. Не для других стикерпаков.
zone: community
owner: Катя
proactive: false
version: 0.2.0
---

# wndr-stickers

Hermes-скилл к самостоятельному Telegram-боту, который делает стикеры для
сообщества WNDR в утверждённом стиле пака.

## Что такое WNDR Club

WNDR Club — место, где мы вместе продвигаемся в важных областях жизни и
поддерживаем друг друга на пути.

В основе клуба — meta-skill действия: движение вперёд, даже когда нет всех
ответов. Не ждать идеальных условий, а делать шаги и собирать результаты.

Стикерпак — не просто визуальный мерч, а язык этого движения: он поддерживает
действие, взаимную опору и право двигаться через неопределённость.

## Главное про подход

Модель НЕ пишет текст. Она рисует только плашку с пустой серединой, а кириллицу
впечатывает код настоящим шрифтом. Так снят главный источник брака: на кириллице
генеративные модели стабильно теряют «ъ», путают «е»/«ё» и дорисовывают знаки,
которых в исходной фразе нет.

Из этого следует правило: **если текст на стикере разошёлся с запрошенным —
это баг в нашем коде, а не каприз модели.** Чинить в `typeset.py`, не
перегенерацией.

## Что делает

- Принимает фразу в Telegram, возвращает WebP 512×512, готовый для стикерпака
- Держит стиль по картинке-референсу `assets/reference/wndr-reference-sheet.png`,
  которая прикладывается к каждому запросу
- Ведёт общий стикерпак в Telegram (владелец набора — Катя) и общий ZIP
- Работает без премодерации: участники сами добавляют, убирают и возвращают
  стикеры; удаление обратимо и записывается в прозрачную историю
- Публичные duplicate memory и ZIP видят только активный общий пак, не черновики
- Считает квоты: бот открыт сообществу, а картинки платные

## Чего не делает

- Не загружает Hermes, Катину память, WORK/PERSONAL-контекст или Vault
- Не подключается к общему Qdrant/Memory API: фразы и vectors живут в своей SQLite
- Не перезаписывает утверждённые версии — новые решения уходят в `-v2`, `-v3`
- Не применяет неканонические запреты на стрелки: стрелка/указатель входит в canonical v0.1 формы
- Не занимается другими стикерпаками

## Точки входа

- `skill.wndr_stickers.src.pipeline.make_sticker(phrase, settings) -> StickerResult`
- `skill.wndr_stickers.src.pipeline.make_illustration(motif, settings)` — стикер без текста
- `skill.wndr_stickers.src.pipeline.rebuild_from_raw(raw_png, phrase, settings)` —
  переверстать текст на уже готовой плашке, без повторного вызова модели и без трат
- `skill.wndr_stickers.src.pipeline.preview_layout(phrase, settings)` — посмотреть
  разбивку строк вообще без сети

## Стиль

Source of truth: `docs/reference/WNDR-Sticker-Agent-v0.1.pdf` sections 2/8/9 and `docs/reference/wndr-style-contract.v0.1.json`. Палитра ровно: `#CC3D11`, `#0D0D0D`, `#F2E2C8`, обводка `#F7F3EA`. Ровно два базовых цвета плюс акцент на 1–3 словах. Обводка 8–12px при 512px. Типографика: плотный тяжёлый ретро-гротеск, центр, 1–3 строки, без light-шрифтов. Формы: скруглённый прямоугольник, wavy blob, starburst, молния/резаный параллелограмм, декоративный овал, стрелка/указатель, stamp/зубчатый край.

Акцентное слово помечается звёздочками: `Это не *тантра*` — слово станет оранжевым.

## Провайдеры картинок

Цепочка в `.env`, слева направо с автоматическим fallback:

- `codex` — GPT image по подписке ChatGPT; в launchd наследует outer Seatbelt (`WNDR_RUNTIME_SANDBOX=1`) и не запускает вложенный sandbox-exec, при ручном запуске включает standalone sandbox; всегда одноразовый HOME/CODEX_HOME и env allowlist
- `openrouter_gpt` — GPT image через OpenRouter, модель `openai/gpt-5-image`
- `openai` — прямой `api.openai.com`, Responses API с инструментом `image_generation`
- `gemini` — `gemini-3-pro-image-preview`, работает и на бесплатном ключе

Подписка ChatGPT не даёт прямой image API, но Codex CLI использует built-in
`image_gen`. В subprocess копируется только auth-файл; user config, rules,
sessions и настоящий home недоступны. Для `openai` нужен отдельный боевой ключ.

## Проверки, когда что-то не так

```bash
cd ~/dev/wndr-stickers
launchctl list | grep -i wndr
tail -80 ~/.wndr-stickers/logs/bot.err.log

# квоты провайдеров — самая частая причина «бот молчит»
./.venv/bin/python - <<'PY'
from skill.wndr_stickers.src.config import get_settings
from skill.wndr_stickers.src import imagegen
s = get_settings()
try:
    img = imagegen.generate("test plate, no text", s.reference_sheet_path, s)
    print("OK", img.provider, img.model, len(img.data), "B")
except Exception as e:
    print("FAIL", e)
PY

sqlite3 ~/.wndr-stickers/state/stickers.db \
  "select status, count(*) from requests group by status;"

# Публичный ZIP должен совпадать с активным общим паком, а не со всеми черновиками.
./.venv/bin/python - <<'PY'
import asyncio, zipfile
from pathlib import Path
from skill.wndr_stickers.src.config import get_settings
from skill.wndr_stickers.src import db
async def main():
    s = get_settings()
    rows = await db.pack_stickers(s.db_path)
    active = sorted(Path(r.path).name for r in rows if Path(r.path).is_file())
    zipped = sorted(zipfile.ZipFile(s.zip_path).namelist()) if s.zip_path.exists() else []
    print('active_db=', active)
    print('zip=', zipped)
    print('match=', active == zipped)
asyncio.run(main())
PY
```

`402` от OpenRouter — кончились кредиты, пополнять на openrouter.ai.
`429` от Gemini — исчерпана бесплатная квота, ждать суточного сброса.

## Вёрстка без сети

Если надо быстро посмотреть, как ляжет фраза, модель дёргать не нужно:

```bash
./.venv/bin/python -c "
from skill.wndr_stickers.src.config import get_settings
from skill.wndr_stickers.src import pipeline
pipeline.preview_layout('Пусть все цветы расцветут', get_settings()).save('/tmp/preview.png')
"
```
