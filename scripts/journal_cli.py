#!/usr/bin/env python3
"""CLI for the agent-heartbeat SQLite journal store."""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from journal_store import (  # noqa: E402
    add_entry,
    close_thread_by_text,
    export_latest_to_markdown,
    get_open_threads,
    get_recent_entries,
    init_db,
)

DEFAULT_DB = os.path.join(os.getcwd(), "journal.db")
DEFAULT_MD = os.path.join(os.getcwd(), "JOURNAL.md")


def _parse_threads(raw: str | None) -> list[str]:
    if not raw:
        return []
    # Split on newlines, not commas. Thread texts legitimately contain commas
    # (e.g. "AlphaVantage keys exhausted, reported 0 events on TRV day"). A
    # comma delimiter shattered ~33-50% of real journal threads into fragments.
    # Pre-2026-07-19 this split on "," — see CHANGELOG.md.
    return [part.strip() for part in raw.split("\n") if part.strip()]

def cmd_read(args: argparse.Namespace) -> int:
    init_db(args.db)
    open_threads = get_open_threads(args.db)
    recent_entries = get_recent_entries(args.db, limit=args.limit)

    print("=== Open Threads ===")
    if open_threads:
        for thread in open_threads:
            print(f"- {thread['thread_text']}")
    else:
        print("- (none)")

    print()
    print(f"=== Recent Entries (last {args.limit}) ===")
    if not recent_entries:
        print("No entries yet.")
        return 0

    for index, entry in enumerate(recent_entries):
        title = entry.get("title") or "Untitled"
        print(f"### {entry['date']} [{entry['session_type']}] — {title}")
        if entry.get("what_i_did"):
            print(f"What I did: {entry['what_i_did']}")
        if entry.get("what_i_found"):
            print(f"What I found: {entry['what_i_found']}")
        if entry.get("what_im_thinking"):
            print(f"What I'm thinking: {entry['what_im_thinking']}")
        open_threads_text = ", ".join(entry.get("open_threads") or []) or "(none)"
        print(f"Open threads: {open_threads_text}")
        if entry.get("room_status"):
            print(f"Room status: {entry['room_status']}")
        if index != len(recent_entries) - 1:
            print()

    return 0


def cmd_add(args: argparse.Namespace) -> int:
    init_db(args.db)
    entry_id = add_entry(
        db_path=args.db,
        date=args.date,
        session_type=args.session_type,
        title=args.title,
        what_i_did=args.what_i_did,
        what_i_found=args.what_i_found,
        what_im_thinking=args.what_im_thinking,
        open_threads=_parse_threads(args.open_threads),
        room_status=args.room_status,
    )
    export_latest_to_markdown(args.db, args.md)
    print(entry_id)
    return 0


def cmd_close_thread(args: argparse.Namespace) -> int:
    init_db(args.db)
    closed = close_thread_by_text(
        args.db, args.thread_text, closing_entry_id=args.closing_entry_id
    )
    if not closed:
        print(f"No open thread matched: {args.thread_text}", file=sys.stderr)
        return 1
    print(f"Closed thread matching: {args.thread_text}")
    return 0


def cmd_export_latest(args: argparse.Namespace) -> int:
    init_db(args.db)
    export_latest_to_markdown(args.db, args.md)
    print(args.md)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Journal CLI for agent-heartbeat")
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser("read", help="Print recent entries and open threads")
    read_parser.add_argument("--db", default=DEFAULT_DB, help="Path to journal.db")
    read_parser.add_argument("--limit", type=int, default=5, help="Recent entry limit")
    read_parser.set_defaults(func=cmd_read)

    add_parser = subparsers.add_parser("add", help="Add an entry and refresh JOURNAL.md")
    add_parser.add_argument("--db", default=DEFAULT_DB, help="Path to journal.db")
    add_parser.add_argument("--md", default=DEFAULT_MD, help="Path to JOURNAL.md snapshot")
    add_parser.add_argument("--date", required=True, help="Entry date (YYYY-MM-DD)")
    add_parser.add_argument(
        "--session-type", default="Daytime", help="Session type (Daytime or Nightly)"
    )
    add_parser.add_argument("--title", required=True, help="Entry title")
    add_parser.add_argument("--what-i-did", required=True, help="What I did")
    add_parser.add_argument("--what-i-found", required=True, help="What I found")
    add_parser.add_argument("--what-im-thinking", default=None, help="What I'm thinking")
    add_parser.add_argument(
        "--open-threads", default="", help="Newline-separated open threads"
    )
    add_parser.add_argument("--room-status", default=None, help="Room status")
    add_parser.set_defaults(func=cmd_add)

    close_parser = subparsers.add_parser(
        "close-thread", help="Close an open thread by text match"
    )
    close_parser.add_argument("--db", default=DEFAULT_DB, help="Path to journal.db")
    close_parser.add_argument("--thread-text", required=True, help="Thread text matcher")
    close_parser.add_argument(
        "--closing-entry-id",
        type=int,
        default=None,
        help="Entry ID that resolved the thread (defaults to latest entry)",
    )
    close_parser.set_defaults(func=cmd_close_thread)

    export_parser = subparsers.add_parser(
        "export-latest", help="Regenerate the markdown snapshot"
    )
    export_parser.add_argument("--db", default=DEFAULT_DB, help="Path to journal.db")
    export_parser.add_argument("--md", default=DEFAULT_MD, help="Path to JOURNAL.md snapshot")
    export_parser.set_defaults(func=cmd_export_latest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
