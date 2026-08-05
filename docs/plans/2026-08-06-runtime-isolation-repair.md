# WNDR Stickers Runtime Isolation Repair Plan

> **For Hermes:** implement directly, then use an independent `katya-qa` reviewer and a separate machine verifier.

**Goal:** Restore end-to-end sticker generation while making the community bot unable to read Katya AI, WORK, PERSONAL, Hermes, Vault, or shared memory.

**Architecture:** Keep the bot as a standalone aiogram/launchd service, not a Hermes profile. SQLite remains the only durable store; duplicate vectors move from shared Qdrant into the bot's own SQLite. Codex runs as an ephemeral subprocess with a temporary HOME/CODEX_HOME. Under launchd it inherits the outer macOS sandbox (`WNDR_RUNTIME_SANDBOX=1`) instead of applying a forbidden nested sandbox; standalone/manual runs still apply a dedicated sandbox that denies the real home. A file lock guarantees one Telegram poller.

**Tech Stack:** Python 3.14, aiogram, SQLite/aiosqlite, Ollama embeddings, Codex CLI, macOS sandbox-exec + launchd, pytest.

---

### Task 1: Lock the bug contracts

**Files:**
- Modify: `tests/test_codex_provider.py`
- Create: `tests/test_instance_lock.py`
- Modify: `tests/test_community_memory.py`

1. Keep the failing assertion that the Codex command carries the prompt.
2. Add assertions for ephemeral/ignore-user-config flags, temporary HOME/CODEX_HOME, and home-denying sandbox profile.
3. Add a two-holder lock test proving the second bot instance fails closed.
4. Add a SQLite-local vector-store test and assert that no Qdrant endpoint exists in the module.
5. Run focused tests and confirm failures before implementation.

### Task 2: Fix Codex and isolate the model subprocess

**Files:**
- Modify: `skill/wndr_stickers/src/imagegen.py`

1. Pass the full prompt as the final Codex argument.
2. Copy only `~/.codex/auth.json` into a per-call temporary CODEX_HOME with mode 0600.
3. Copy the reference image into the temporary workdir.
4. Run Codex with a sanitized environment, `--ephemeral`, `--ignore-user-config`, and `--ignore-rules`. If `WNDR_RUNTIME_SANDBOX=1` is absent, wrap Codex in standalone sandbox-exec denying the real home; if present, rely on the already-active outer runtime Seatbelt to avoid `sandbox_apply: Operation not permitted`.
5. Read generated artifacts only from the temporary directory.

### Task 3: Remove shared-memory coupling

**Files:**
- Modify: `skill/wndr_stickers/src/db.py`
- Replace: `skill/wndr_stickers/src/community_memory.py`
- Modify: `bot/handlers/generate.py`
- Modify: `scripts/preflight.py`

1. Add a `community_vectors` table to the bot SQLite schema.
2. Store embeddings as JSON in SQLite; scan and cosine-rank locally.
3. Keep Ollama only as a stateless embedding service.
4. Pass `settings.db_path` explicitly to find/remember operations.
5. Remove every Qdrant/Memory API reference from runtime code and preflight.

### Task 4: Enforce one runtime and detach state/logs

**Files:**
- Create: `skill/wndr_stickers/src/instance_lock.py`
- Modify: `bot/main.py`
- Modify: `skill/wndr_stickers/src/config.py`
- Modify: `.env.example`
- Modify: `deploy/com.katya.wndr-stickers.plist`
- Modify live `.env` and LaunchAgent without exposing secrets.

1. Acquire a non-blocking lock under the bot's state directory before Telegram polling.
2. Move defaults and live state/output/logs to `~/.wndr-stickers/`.
3. Copy the current SQLite as a reversible migration; do not delete the old source.
4. Stop the unmanaged poller, reload launchd, and verify exactly one process.

### Task 5: Verification and delivery

1. Run focused tests, full pytest, ruff, py_compile, plist lint.
2. Run a real Codex image smoke and verify PNG bytes/artifact dimensions.
3. Restart launchd; verify one PID, Telegram polling connected, and no fresh conflict errors.
4. Run independent SYSTEM review; repair Critical/High findings and repeat.
5. Run secret scan, selectively commit/push, update README/context/skill, and verify clean state.
