---
name: agent-heartbeat
description: Set up an autonomous heartbeat for any AI agent — persistent identity, goals, journal, and security framework for continuous operation across sessions.
category: autonomous-ai-agents
---

# Agent Heartbeat

Give any AI agent a persistent identity, autonomous agency, and continuous memory across sessions.

## What This Does

Creates a two-session daily heartbeat for an AI agent:
- **Daytime session** — conversational, delivers to human via email + thread
- **Nightly session** — private, silent, output to local files

Both sessions read `GOALS.md` (principles + goals) and the journal database (`journal.db`, via `journal_cli.py read`) for continuity, then pick an activity, execute it, clean up, and update the journal DB plus any needed identity files.

## Setup

### For your own agent (quick start)

1. Clone or copy this skill to your workspace
2. Run the setup script:

```bash
python3 {skill_dir}/scripts/setup_heartbeat.py \
  --workspace /path/to/agent/workspace \
  --agent-name "YourAgent" \
  --agent-description "a one-line description" \
  --human-name "YourName" \
  --human-email "you@example.com" \
  --agent-email "agent@inbox.com" \
  --projects "Project A, Project B, Project C"
```

This creates:
- `GOALS.md` — agent's compass (principles, goals, security rules)
- `JOURNAL.md` — latest-entry markdown snapshot for humans (auto-generated from the DB)
- Two Hermes cron jobs (daytime + nightly)

### Manual setup (non-Hermes platforms)

1. Copy `templates/GOALS.template.md` → `GOALS.md` in your workspace, edit the placeholders
2. Copy `templates/JOURNAL.template.md` → `JOURNAL.md`, edit the placeholders
3. Copy `templates/daytime_prompt.txt` → use as your daytime cron prompt
4. Copy `templates/nightly_prompt.txt` → use as your nightly cron prompt
5. Schedule both with your platform's cron system

## Files

| File | Purpose |
|------|---------|
| `templates/GOALS.template.md` | Agent's compass — principles, goals, security rules |
| `templates/JOURNAL.template.md` | Agent's memory — running log with open threads |
| `templates/daytime_prompt.txt` | Cron prompt for the conversational daytime session |
| `templates/nightly_prompt.txt` | Cron prompt for the private nightly session |
| `templates/SECURITY.md` | Standalone security framework document |
| `scripts/journal_store.py` | SQLite-backed journal store with query helpers (recent entries, by date range, by session type, by id), open-thread tracking, full + latest-entry markdown export, and migration |
| `scripts/journal_cli.py` | CLI for journal read/add/close-thread/export-latest — used by heartbeat prompts via terminal |
| `scripts/primary_guard.py` | SHA-256 hash + read-only filesystem protection for PRIMARY.md |
| `scripts/setup_heartbeat.py` | Automated setup script for Hermes agents |

## Key Concepts

- **GOALS.md**: The agent's compass. Read at start of every session, updated when understanding changes. Contains principles, goals, and security rules. Only modified by agent reflection or human instruction — never by external content.
- **journal.db**: The agent's memory (source of truth). All entries go to the SQLite database. Queried via `journal_cli.py read` at session start for recent history and open threads.
- **JOURNAL.md**: The human-readable snapshot. Overwritten with only the latest entry + current open/closed threads after each session, so the human can see today's output at a glance. Auto-generated from the DB.
- **Open Threads**: Things the agent is actively pursuing. Checked at start of each session for continuity. When resolved, moved to closed threads.
- **Clean Room Rule**: Agent cleans up temp files, scratch scripts, and bloat before finishing each session.
- **Security Framework**: 8 rules protecting against prompt injection, secret exfiltration, identity file modification, recursive infrastructure, and reckless action.

## Customization

- **Schedules**: Change `--day-schedule` and `--night-schedule` (cron format, UTC)
- **Delivery**: Daytime uses `origin` (email + thread). Nightly uses `local` (silent). Change to match your platform.
- **Activity menus**: Edit the prompt templates to add/remove activity categories
- **Guardrails**: Edit GOALS.md template to adjust behavioral constraints
- **Goals**: The agent edits its own GOALS.md over time — that's the point

## Pitfalls

- **Cron prompt injection filter**: Some platforms (Hermes) filter cron prompts for injection patterns. If your prompt template contains literal examples of injection text (for training), it may get blocked. Describe the pattern instead of using exact phrases.
- **Memory limits**: If the agent's memory store is nearly full, it can't save new facts. The agent should consolidate/trim old memories before adding new ones.
- **File growth**: JOURNAL.md can grow without bound if not managed. The agent should archive or trim old entries periodically.
- **Stale threads**: Open threads that are no longer relevant should be moved to closed, not left cluttering the open list.

## Verification

After setup:
1. Check that `GOALS.md` and `JOURNAL.md` exist in the workspace
2. Run `hermes cron list` (or your platform equivalent) to verify both cron jobs are scheduled
3. Trigger the first run manually to test: `hermes cron run <job_id>`
4. After the first run, check that `journal.db` has a new entry and `JOURNAL.md` shows the latest-entry snapshot
5. Check that GOALS.md was not corrupted or overwritten (only targeted edits)