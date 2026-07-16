#!/usr/bin/env python3
"""
Sample heartbeat script for agent-heartbeat.

This is a minimal, self-contained example of how to run an agent heartbeat
using the agent-heartbeat toolkit. It demonstrates the core workflow:

1. Read the goals file (GOALS.md) for orientation
2. Read the journal database for continuity (open threads + recent entries)
3. Do something productive — research, reflection, project work
4. Write a journal entry to the database
5. Clean up

This script is designed to be called by a cron scheduler. It does not
require an LLM — it's a simple Python script that demonstrates the
journal lifecycle. In a real deployment, you would replace the "do work"
section with your agent's actual logic (LLM calls, tool use, etc.).

Usage:
    python examples/sample_heartbeat.py --db journal.db --md JOURNAL.md --goals GOALS.md

The script will:
- Initialize the journal database if it doesn't exist
- Print open threads and recent entries for context
- Simulate a heartbeat cycle (read → think → write)
- Write a new journal entry
- Export the latest entry to markdown

This is intentionally simple. Real heartbeats are complex — they read
emails, check systems, do research, form opinions, and write rich journal
entries. But the skeleton is always the same: read context, do work, write
entry, clean up. That skeleton is what this example demonstrates.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add the scripts directory to the path so we can import journal_store
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from journal_store import (  # noqa: E402
    add_entry,
    export_latest_to_markdown,
    get_open_threads,
    get_recent_entries,
    init_db,
)


def read_goals(goals_path: str) -> str | None:
    """Read the goals file for orientation."""
    try:
        with open(goals_path) as f:
            return f.read()
    except FileNotFoundError:
        print(f"[warn] No goals file found at {goals_path}")
        return None


def print_context(db_path: str, limit: int = 5) -> None:
    """Print open threads and recent entries for continuity."""
    print("\n=== Open Threads ===")
    threads = get_open_threads(db_path)
    if threads:
        for t in threads:
            print(f"  - {t['thread_text']}")
    else:
        print("  (none)")

    print(f"\n=== Recent Entries (last {limit}) ===")
    entries = get_recent_entries(db_path, limit=limit)
    if not entries:
        print("  No entries yet.")
        return

    for entry in entries:
        title = entry.get("title", "Untitled")
        print(f"  {entry['date']} [{entry['session_type']}] — {title}")


def do_heartbeat_work(goals: str | None, threads: list[dict]) -> dict:
    """
    This is where your agent does its actual work.

    In this example, we just return a simple summary. In a real deployment,
    this is where you'd:
    - Call your LLM with the goals + journal context
    - Let the agent use tools (web search, file read/write, code execution)
    - Collect the agent's output and reflections

    The return value is a dict with the same fields as a journal entry:
    title, what_i_did, what_i_found, what_im_thinking, open_threads, room_status
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # In a real heartbeat, the agent would decide what to work on based on
    # the goals and open threads. Here we just demonstrate the structure.
    thread_summary = ", ".join(t["thread_text"] for t in threads[:3]) if threads else "none"

    return {
        "date": date_str,
        "session_type": "Heartbeat",
        "title": f"Sample heartbeat — {date_str}",
        "what_i_did": f"Ran the sample heartbeat script. Read goals ({'yes' if goals else 'no'}) "
                       f"and {len(threads)} open threads. This is a demonstration — replace "
                       f"this with your agent's actual work.",
        "what_i_found": f"Open threads: {thread_summary}. The journal lifecycle works: "
                         f"read context, do work, write entry, clean up.",
        "what_im_thinking": "This is the skeleton of a heartbeat. The real magic happens when "
                            "you replace do_heartbeat_work() with an LLM agent that can think, "
                            "explore, and form opinions. The journal is the memory. The goals "
                            "are the compass. The heartbeat is the rhythm.",
        "open_threads": ["sample-thread-1", "sample-thread-2"],
        "room_status": "Clean.",
    }


def run_heartbeat(db_path: str, md_path: str, goals_path: str, limit: int) -> int:
    """Run a single heartbeat cycle."""
    # Step 1: Initialize the journal database
    init_db(db_path)
    print(f"[init] Journal database: {db_path}")

    # Step 2: Read goals for orientation
    goals = read_goals(goals_path)
    if goals:
        print(f"[goals] Read {len(goals)} characters from {goals_path}")

    # Step 3: Read journal for continuity
    print_context(db_path, limit=limit)
    threads = get_open_threads(db_path)

    # Step 4: Do the actual work
    print("\n[work] Running heartbeat cycle...")
    entry_data = do_heartbeat_work(goals, threads)

    # Step 5: Write the journal entry
    entry_id = add_entry(
        db_path=db_path,
        date=entry_data["date"],
        session_type=entry_data["session_type"],
        title=entry_data["title"],
        what_i_did=entry_data["what_i_did"],
        what_i_found=entry_data["what_i_found"],
        what_im_thinking=entry_data["what_im_thinking"],
        open_threads=entry_data["open_threads"],
        room_status=entry_data["room_status"],
    )
    print(f"[journal] Wrote entry #{entry_id}: {entry_data['title']}")

    # Step 6: Export latest entry to markdown
    export_latest_to_markdown(db_path, md_path)
    print(f"[export] Latest entry exported to {md_path}")

    # Step 7: Clean up (in a real heartbeat, you'd delete temp files here)
    print("[clean] Room status: Clean.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a sample agent-heartbeat cycle."
    )
    parser.add_argument(
        "--db",
        default=os.path.join(os.getcwd(), "journal.db"),
        help="Path to journal.db (default: ./journal.db)",
    )
    parser.add_argument(
        "--md",
        default=os.path.join(os.getcwd(), "JOURNAL.md"),
        help="Path to JOURNAL.md snapshot (default: ./JOURNAL.md)",
    )
    parser.add_argument(
        "--goals",
        default=os.path.join(os.getcwd(), "GOALS.md"),
        help="Path to GOALS.md (default: ./GOALS.md)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of recent entries to show (default: 5)",
    )
    args = parser.parse_args()
    return run_heartbeat(args.db, args.md, args.goals, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())