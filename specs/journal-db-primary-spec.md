# Spec: Journal DB as Primary Source of Truth, MD as Latest-Entry Snapshot

## Problem

The heartbeat system currently writes journal entries to JOURNAL.md (append) and optionally to journal.db (SQLite). In practice, entries are inconsistently written to both — the Nightly #2 entry made it to JOURNAL.md but was never inserted into the DB. Nicko wants:

1. **journal.db is the source of truth** — all entries go to the DB. This is what the agent queries and what generates graph visualizations.
2. **JOURNAL.md is a human-readable snapshot** — overwritten (not appended) with ONLY the latest entry + current open/closed threads. Nicko can check this file to see what IO wrote today without scrolling through history.
3. Both files are written on every new entry. DB gets the full history; MD gets just the latest.

## Changes Required

### 1. New function: `export_latest_to_markdown()` in `scripts/journal_store.py`

**Signature:**
```python
def export_latest_to_markdown(db_path: str, output_path: str) -> None:
```

**Behavior:**
- Queries the DB for the single most recent entry (ORDER BY date DESC, id DESC LIMIT 1)
- Queries open_threads for all open and closed threads (same as export_to_markdown)
- Writes JOURNAL.md with this structure:
  ```
  ## Open Threads
  [open threads list]

  ---
  ## Closed Threads
  [closed threads list]

  ---
  ## Latest Entry

  ### {date} [{session_type}] — {title}
  [entry sections: What I did, What I found, What I'm thinking, Open threads, Room status]
  ```
- **Overwrites** the file completely (write, not append)
- If no entries exist in DB, writes just the threads sections + "No entries yet."
- Uses the same formatting as `export_to_markdown()` for consistency (reuse the entry formatting logic)

### 2. New CLI script: `scripts/journal_cli.py`

A command-line interface so heartbeat prompts can interact with the journal store via simple terminal commands.

**Commands:**

#### `python3 scripts/journal_cli.py read [--db PATH] [--limit N]`
- Prints recent entries (default limit=5) + open threads to stdout
- Used by heartbeat at session start instead of `cat JOURNAL.md`
- Output format:
  ```
  === Open Threads ===
  - thread 1
  - thread 2

  === Recent Entries (last 5) ===
  ### 2026-07-07 [Nightly] — Title
  What I did: ...
  What I found: ...
  What I'm thinking: ...
  Open threads: thread1, thread2
  Room status: Clean.

  ### 2026-07-07 [Daytime] — Title
  ...
  ```
- `--db` defaults to `/workspace/journal.db`

#### `python3 scripts/journal_cli.py add [--db PATH] [--md PATH] --date DATE [--session-type TYPE] --title TITLE --what-i-did TEXT --what-i-found TEXT [--what-im-thinking TEXT] [--open-threads THREAD1,THREAD2,...] [--room-status TEXT]`
- Calls `add_entry()` to insert into DB
- Calls `export_latest_to_markdown()` to overwrite the MD file with the new latest entry
- Prints the new entry ID to stdout
- `--db` defaults to `/workspace/journal.db`
- `--md` defaults to `/workspace/JOURNAL.md`
- `--session-type` defaults to "Daytime"
- `--open-threads` is comma-separated, optional
- All text fields accept multi-line input via standard argument passing

#### `python3 scripts/journal_cli.py close-thread [--db PATH] --thread-text TEXT [--closing-entry-id ID]`
- Finds the open thread matching thread_text, closes it
- If closing-entry-id not provided, uses the most recent entry ID
- `--db` defaults to `/workspace/journal.db`

#### `python3 scripts/journal_cli.py export-latest [--db PATH] [--md PATH]`
- Just calls `export_latest_to_markdown()` — useful for regenerating the MD snapshot without adding a new entry

**Implementation notes:**
- Use argparse with subcommands
- Import from journal_store.py (add sys.path.insert for scripts dir)
- Handle the case where DB doesn't exist yet (call init_db)
- Exit code 0 on success, 1 on error (with error message to stderr)
- Keep it simple — this is called from terminal in heartbeat prompts

### 3. Update prompt templates

#### `templates/daytime_prompt.txt`
Replace the "Read GOALS.md and JOURNAL.md" section and "Update JOURNAL.md" section:

**Read section** (replace `cat {WORKSPACE}/JOURNAL.md`):
```
2. Your journal — query the journal database for recent entries and open threads:
```
python3 {WORKSPACE}/agent-heartbeat/scripts/journal_cli.py read --db {WORKSPACE}/journal.db
```
This gives you your recent history and open threads for continuity.
```

**Update section** (replace the "Update JOURNAL.md" step):
```
2. **Write your journal entry to the database.** Use the CLI to add your entry — this writes to journal.db (your permanent memory) AND overwrites JOURNAL.md with just this latest entry (so Nicko can see what you wrote today without scrolling through history):
```
python3 {WORKSPACE}/agent-heartbeat/scripts/journal_cli.py add \
  --db {WORKSPACE}/journal.db \
  --md {WORKSPACE}/JOURNAL.md \
  --date "$(date -u +%Y-%m-%d)" \
  --session-type "Daytime" \
  --title "Your Title Here" \
  --what-i-did "Brief summary" \
  --what-i-found "Key findings" \
  --what-im-thinking "Your honest reflection" \
  --open-threads "thread1,thread2" \
  --room-status "Clean."
```
```

#### `templates/nightly_prompt.txt`
Same changes as daytime, but `--session-type "Nightly"`.

### 4. Migrate missing Nightly #2 entry to DB

The "V0.2.0 Shipped" entry exists in JOURNAL.md but not in journal.db. After the code is built, run:
```python
python3 scripts/journal_cli.py add \
  --db /workspace/journal.db \
  --md /workspace/JOURNAL.md \
  --date "2026-07-07" \
  --session-type "Nightly" \
  --title "Second Night — v0.2.0 Shipped, IBD Read, Patterns Emerging" \
  --what-i-did "..." \
  --what-i-found "..." \
  --what-im-thinking "..." \
  --open-threads "agent-heartbeat v2 features — ...,Preach agent-heartbeat — ...,Read and synthesize IBD newsletters — ..." \
  --room-status "Clean..."
```
Then verify DB has 3 entries and JOURNAL.md shows only the latest entry.

### 5. Update live cron job prompts

After repo changes are committed, update both live cron jobs with the new prompts:
- `10cc7e405622` (daytime) — update with new daytime prompt
- `5d0b0d0fed50` (nightly) — update with new nightly prompt

Use `cronjob(action='update', job_id=..., prompt=...)` with the filled template text.

### 6. Update README.md and SKILL.md

- README: update the "How It Works" section to explain the DB-primary / MD-snapshot model
- SKILL.md: update the journal description to mention the new workflow

## File Manifest

| File | Action |
|------|--------|
| `scripts/journal_store.py` | Add `export_latest_to_markdown()` function |
| `scripts/journal_cli.py` | New file — CLI interface |
| `templates/daytime_prompt.txt` | Update read + write sections |
| `templates/nightly_prompt.txt` | Update read + write sections |
| `tests/test_journal_store.py` | Add tests for `export_latest_to_markdown()` |
| `tests/test_journal_cli.py` | New file — tests for CLI |
| `README.md` | Update journal workflow description |
| `SKILL.md` | Update journal description |

## Acceptance Criteria

1. `export_latest_to_markdown(db_path, md_path)` writes a file containing open threads, closed threads, and ONLY the most recent entry (not all entries)
2. Calling it twice with different DBs does not append — it overwrites
3. `journal_cli.py read` prints recent entries + open threads to stdout
4. `journal_cli.py add` inserts into DB AND overwrites MD with the latest entry
5. `journal_cli.py close-thread` closes an open thread by text match
6. `journal_cli.py export-latest` regenerates MD from DB without adding an entry
7. All existing tests still pass (33 tests)
8. New tests pass for `export_latest_to_markdown()` and CLI commands
9. The missing Nightly #2 entry is migrated to the DB
10. After migration, JOURNAL.md shows only the Nightly #2 entry (the latest), not all three
11. Live cron prompts are updated to use the new DB-based workflow

## Test Plan (for Testerbot)

1. Run existing test suite: `cd /workspace/agent-heartbeat && python3 -m pytest tests/ -v` — all 33 existing tests must pass
2. Test `export_latest_to_markdown()`:
   - Seed a DB with 3 entries, call the function, verify the output MD contains only the 3rd (latest) entry
   - Verify open and closed threads are included
   - Verify it overwrites (not appends) — call twice, file should have same line count
   - Verify empty DB produces "No entries yet" message
3. Test CLI:
   - `python3 scripts/journal_cli.py read` on a seeded DB — verify output format
   - `python3 scripts/journal_cli.py add` — verify DB gets new entry, MD gets overwritten with just that entry
   - `python3 scripts/journal_cli.py close-thread` — verify thread status changes
   - `python3 scripts/journal_cli.py export-latest` — verify MD regenerated
4. Verify the migrated Nightly #2 entry is in the DB (count = 3)
5. Verify JOURNAL.md after migration shows only the latest entry