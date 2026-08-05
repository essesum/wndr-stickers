---
name: wndr-stickers
description: Стикеры для сообщества WNDR. Использовать, когда Катя делает или правит стикеры WNDR, спрашивает про стикерпак, стиль пака, или когда что-то не так с ботом @wndr-стикеров. Не для других стикерпаков.
zone: work
owner: Катя
proactive: false
version: 0.1.0
---

# wndr-stickers

Hermes-скилл к самостоятельному Telegram-боту, который делает стикеры для
сообщества WNDR в утверждённом стиле пака.

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
- Считает квоты: бот открыт сообществу, а картинки платные

## Чего не делает

- Не перезаписывает утверждённые версии — новые решения уходят в `-v2`, `-v3`
- Не ставит стрелки: свежий хендофф их запретил, хотя на старом листе они есть
  (переключается флагом `ALLOW_ARROW_SHAPES`)
- Не занимается другими стикерпаками

## Точки входа

- `skill.wndr_stickers.src.pipeline.make_sticker(phrase, settings) -> StickerResult`
- `skill.wndr_stickers.src.pipeline.make_illustration(motif, settings)` — стикер без текста
- `skill.wndr_stickers.src.pipeline.rebuild_from_raw(raw_png, phrase, settings)` —
  переверстать текст на уже готовой плашке, без повторного вызова модели и без трат
- `skill.wndr_stickers.src.pipeline.preview_layout(phrase, settings)` — посмотреть
  разбивку строк вообще без сети

## Стиль

Палитра ровно три цвета плюс кант: `#CC3D11`, `#0D0D0D`, `#F2E2C8`, обводка `#F7F3EA`.
Типографика доминирует, иллюстрация только усиливает смысл. Формы: скруглённый
прямоугольник, волнистое облако, взрыв-звезда, молния, овал, марка, облако.

Акцентное слово помечается звёздочками: `Это не *тантра*` — слово станет оранжевым.

## Провайдеры картинок

Цепочка в `.env`, слева направо с автоматическим fallback:

- `openrouter_gpt` — GPT image через OpenRouter, модель `openai/gpt-5-image`
- `openai` — прямой `api.openai.com`, Responses API с инструментом `image_generation`
- `gemini` — `gemini-3-pro-image-preview`, работает и на бесплатном ключе

Подписка ChatGPT в `~/.codex/auth.json` картинок через API НЕ даёт — там OAuth,
`OPENAI_API_KEY: null`. Для провайдера `openai` нужен отдельный боевой ключ.

## Проверки, когда что-то не так

```bash
cd ~/dev/wndr-stickers
launchctl list | grep -i wndr
tail -80 ~/.ai-system/logs/wndr-stickers.err.log

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

sqlite3 ~/katya-ai/state/wndr-stickers/stickers.db \
  "select status, count(*) from requests group by status;"
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
