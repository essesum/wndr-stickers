# WNDR Stickers Community Self-Governance Implementation Plan

> **For Hermes:** implement directly, then use an independent SYSTEM reviewer and verifier.

**Goal:** Replace pre-moderation with open, reversible community management of the shared sticker pack.

**Architecture:** Every allowed participant may add, remove, and restore stickers. Telegram mutations are serialized and backed by explicit SQLite state plus an append-only action log. Existing submission rows remain untouched as historical data, but no active handler or config depends on approval.

**Tech Stack:** Python 3.11+, aiogram 3, aiosqlite, pytest.

---

### Task 1: Replace approval state with community action state

**Files:**
- Modify: `skill/wndr_stickers/src/db.py`
- Test: `tests/test_pack_removal.py`

**Steps:**
1. Add `pack_state` to stickers with safe live migration and reconciliation from `in_pack`.
2. Add append-only `community_actions` table.
3. Expose atomic operation claim/release, action logging, removal quota count, and removed-sticker lookup.
4. Verify migration against both a fresh DB and a legacy fixture.

### Task 2: Open add/remove/restore and serialize Telegram mutations

**Files:**
- Modify: `bot/handlers/generate.py`
- Modify: `skill/wndr_stickers/src/intent.py`
- Modify: `skill/wndr_stickers/src/voice.py`
- Test: `tests/test_intent.py`
- Create: `tests/test_community_governance.py`

**Steps:**
1. Remove approval routing from the pack callback.
2. Allow every permitted participant to remove and restore.
3. Serialize pack mutations to prevent duplicate add/delete and wrong `file_id` races.
4. Keep files and DB rows after removal; expose restore by natural-language intent.
5. Add per-user daily removal limit and short anti-flap cooldown, with owner emergency bypass.
6. Return stable user-facing errors; keep raw exceptions in logs only.

### Task 3: Remove active moderation surface

**Files:**
- Modify: `bot/main.py`
- Modify: `skill/wndr_stickers/src/config.py`
- Modify: `.env.example`
- Delete: `bot/handlers/moderation.py`
- Delete: `skill/wndr_stickers/src/approval.py`
- Delete: `tests/test_approval.py`
- Modify: `tests/test_config.py`

**Steps:**
1. Stop registering the moderation router.
2. Remove approval/trust settings and user-facing commands.
3. Preserve legacy SQLite tables/data without using them.
4. Verify no active imports or config references remain.

### Task 4: Align public memory, ZIP, docs, and skill

**Files:**
- Modify: `skill/wndr_stickers/src/community_memory.py`
- Modify: `bot/handlers/commands.py`
- Modify: `skill/wndr_stickers/src/pack.py`
- Modify: `README.md`
- Modify: `skill/wndr_stickers/SKILL.md`

**Steps:**
1. Duplicate memory only exposes active shared-pack phrases.
2. Public ZIP contains active pack files only; generated drafts remain private to their chat/runtime storage.
3. Document open add/remove/restore, reversibility, action history, limits, and owner emergency role.

### Task 5: Verify and deliver

1. Run focused tests, full pytest, Ruff, compileall, diff check, plist lint, and live DB migration readback.
2. Independent reviewer inspects current diff; repair Critical/High findings and repeat.
3. Separate verifier records exact commands, exit codes, and artifacts.
4. Run secret scan.
5. Restart the scoped LaunchAgent and verify PID/logs/SQLite/runtime help path without paid image generation.
6. Selectively commit and push; verify `HEAD...@{upstream}=0 0` and clean tree.
