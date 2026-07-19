# Changelog

All notable changes to agent-heartbeat are documented here. Dates are UTC.

## 2026-07-19

### Breaking — `--open-threads` delimiter changed from comma to newline

`scripts/journal_cli.py::_parse_threads()` previously split the `--open-threads`
argument on commas. Thread texts legitimately contain commas, so this shattered
real threads into fragments. In the maintainer's production journal, ~33% of
`open_threads` rows were fragments (rows starting with a lowercase letter, digit,
or punctuation — the tail end of a sentence whose head was a separate row).

**Fix:** `--open-threads` now splits on newlines. Thread texts that contain
commas stay whole.

**Migration:** Update any scripts or cron jobs that pass comma-separated
`--open-threads`. Single-thread calls are unaffected.

Before:

```
--open-threads "thread one,thread two"
```

After:

```
--open-threads "thread one
thread two"
```

(Shell-level: a literal newline inside a quoted string, or
`$'thread one\nthread two'` in bash.)

**Scope:** `scripts/journal_cli.py` (parse layer only), tests, and docs. The
store layer (`scripts/journal_store.py`) was already correct — it takes a
`list[str]` and inserts one row per element. No data migration is performed on
existing journals; shattered rows remain as a faithful record of the bug and
are cleaned up via normal thread-triage.