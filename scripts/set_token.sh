#!/bin/bash
# Записывает токен бота в .env, не показывая его на экране и не оставляя
# в истории команд. Запускать: ~/dev/wndr-stickers/scripts/set_token.sh
set -euo pipefail

ENV_FILE="$HOME/dev/wndr-stickers/.env"
[ -f "$ENV_FILE" ] || cp "$HOME/dev/wndr-stickers/.env.example" "$ENV_FILE"

read -rsp "Токен от @BotFather: " TOKEN
echo

TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
if [ -z "$TOKEN" ]; then
  echo "Пусто — ничего не записал." >&2
  exit 1
fi
if ! printf '%s' "$TOKEN" | grep -qE '^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$'; then
  echo "Не похоже на токен Telegram (ожидается 123456789:AA...). Ничего не записал." >&2
  exit 1
fi

TOKEN="$TOKEN" python3 - "$ENV_FILE" <<'PY'
import os, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
token = os.environ["TOKEN"]
line = f"TELEGRAM_BOT_TOKEN={token}"
if re.search(r"^TELEGRAM_BOT_TOKEN=.*$", text, flags=re.M):
    text = re.sub(r"^TELEGRAM_BOT_TOKEN=.*$", line, text, count=1, flags=re.M)
else:
    text = text.rstrip("\n") + "\n" + line + "\n"
path.write_text(text)
print(f"Записан токен длиной {len(token)} символов в {path}")
PY

chmod 600 "$ENV_FILE"
echo "Готово. Дальше: ./.venv/bin/python scripts/preflight.py"
