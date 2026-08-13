# WNDR Visual Reference Integration Plan

> **For Hermes:** Execute directly with regression tests, then independent SYSTEM review.

**Goal:** Довести начатый visual WIP: classic использует flat reference, expressive/illustration — retro reference, а кириллица печатается repo-local Golos Text Black.

**Architecture:** Сохранить существующие два режима и pipeline; менять только reference/font/style contract. Выбор режима остаётся автоматическим. Никаких новых UX-кнопок и generation-session в этом scope.

**Tech Stack:** Python 3.11+, Pillow, pytest, aiogram.

---

### Task 1: Закрепить новый visual contract тестами

**Files:**
- Modify: `tests/test_config.py`
- Modify: `tests/test_style_modes.py`
- Modify: `tests/test_style_contract.py`
- Modify: `tests/test_plate_and_cutout.py`

Проверить repo-relative пути, выбор flat/retro reference, новый classic bank и off-fill gate.

### Task 2: Завершить pipeline integration

**Files:**
- Modify: `skill/wndr_stickers/src/config.py`
- Modify: `skill/wndr_stickers/src/pipeline.py`
- Modify: `skill/wndr_stickers/src/plate.py`
- Modify: `skill/wndr_stickers/src/style.py`
- Modify: `scripts/preflight.py`

Использовать `reference_for(mode.look)`, `font_file`, проверять оба reference sheet и шрифт в preflight. Illustration использует retro reference.

### Task 3: Синхронизировать operator contract

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `skill/wndr_stickers/SKILL.md`
- Modify: `CHANGELOG.md`

Указать два reference sheet, Golos Text Black и актуальную необратимую политику удаления.

### Task 4: Verify and deliver

Run:
- `./.venv/bin/python -m pytest -q`
- `./.venv/bin/ruff check .`
- `WNDR_RUNTIME_SANDBOX=1 ./.venv/bin/python scripts/preflight.py`
- offline `preview_layout` artifact
- independent review and verifier
- secret scan
- selective commit/push
- restart `com.katya.wndr-stickers` and verify current log/runtime
