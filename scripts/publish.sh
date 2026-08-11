#!/bin/bash
# Пересобрать страницу сезона из базы бота и выложить на GitHub Pages.
#
#     ./scripts/publish.sh
#
# Данные берутся из локальной SQLite, поэтому запускать надо на той машине,
# где живёт бот. На странице только агрегаты: ников, фраз и «кто сколько
# сделал» там нет — Pages публичны, эти цифры остаются в локальной панели.
set -euo pipefail

cd "$(dirname "$0")/.."

./.venv/bin/python scripts/site.py

if git diff --quiet -- docs/index.html; then
  echo "Страница не изменилась — публиковать нечего."
  exit 0
fi

# Страховка: персональные данные не должны попасть в публичный коммит.
if grep -qiE "ekaterinasum|/Users/" docs/index.html; then
  echo "ОТМЕНА: на странице нашлись личные данные или домашний путь." >&2
  exit 1
fi

git add docs/index.html
git commit -q -m "site: обновление статистики сезона $(date +%Y-%m-%d)"
git push -q origin HEAD
echo "Опубликовано: https://essesum.github.io/wndr-stickers/"
