#!/usr/bin/env python3
"""
session_context.py — Cross-session context for autonomous agent heartbeats.

Queries a session database for recent interactive sessions and outputs
a structured summary that heartbeat sessions can use to gain awareness
of what happened in interactive chats since the last heartbeat.

Platform-neutral: auto-detects a Hermes-Agent-style schema (sessions +
messages tables) and falls back gracefully when the schema does not match.
Stdlib only — no third-party dependencies.

Usage:
    python3 session_context.py --db /path/to/state.db --since 24h \\
        --include-messages --min-messages 3
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

def parse_since(since_str):
    """Parse a --since value into a Unix timestamp (float).

    Accepts:
      - Relative shorthand: "24h", "30m", "1d", "3600s"
      - ISO 8601 datetime: "2025-07-20T12:00:00" (with optional Z/+offset)
      - Raw Unix timestamp: "1721472000"

    Returns the cutoff timestamp in seconds since epoch (UTC).
    Exits with an error message if the value cannot be parsed.
    """
    match = re.match(r'^(\d+)([hmds])$', since_str)
    if match:
        value, unit = int(match.group(1)), match.group(2)
        deltas = {
            'h': 'hours', 'm': 'minutes',
            'd': 'days', 's': 'seconds',
        }
        return (datetime.now(timezone.utc) -
                timedelta(**{deltas[unit]: value})).timestamp()
    # ISO 8601
    try:
        dt = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        pass
    # Raw Unix timestamp
    try:
        return float(since_str)
    except ValueError:
        print(f"Error: invalid --since value: {since_str}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def detect_schema(conn):
    """Detect the database schema type.

    Returns one of:
      - 'hermes'  : Hermes-Agent-style schema (sessions + messages with
                    the expected columns)
      - 'generic' : A table containing 'session' in its name exists, but
                    the full Hermes schema is not present
      - None      : No recognizable session schema found
    """
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in c.fetchall()}
    if 'sessions' in tables and 'messages' in tables:
        c.execute("PRAGMA table_info(sessions)")
        cols = {col[1] for col in c.fetchall()}
        if {'id', 'source', 'title', 'started_at', 'message_count'}.issubset(cols):
            return 'hermes'
    if any('session' in t.lower() for t in tables):
        return 'generic'
    return None


# ---------------------------------------------------------------------------
# Message cleaning
# ---------------------------------------------------------------------------

def strip_message_content(content, max_len=200):
    """Clean and truncate a message body for summary display.

    Removes:
      - Square-bracket tool-call blocks: [...]
      - HTML/XML tags: <...>
      - Reasoning blocks: <reasoning>...</reasoning>
    Collapses whitespace and truncates to *max_len* characters, appending
    '...' when truncated. Returns an empty string for falsy input.
    """
    if not content:
        return ""
    # Remove <reasoning>...</reasoning> first (before generic tag strip)
    content = re.sub(r'<reasoning>.*?</reasoning>', '', content, flags=re.DOTALL)
    # Remove [tool_call ...] style blocks
    content = re.sub(r'\[.*?\]', '', content, flags=re.DOTALL)
    # Remove remaining HTML/XML tags
    content = re.sub(r'<[^>]+>', '', content)
    # Collapse whitespace
    content = ' '.join(content.split())
    if len(content) > max_len:
        content = content[:max_len - 3] + '...'
    return content.strip()


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def query_hermes_sessions(conn, since_ts, sources, min_messages,
                          include_messages, message_trunc):
    """Query interactive sessions from a Hermes-Agent-style schema.

    Excludes autonomous sources (cron, delegate, subagent). Applies
    time-window, source, and minimum-message-count filters. When
    *include_messages* is True, retrieves the first and last user messages
    for each session.

    Returns a list of session dicts (newest first).
    """
    c = conn.cursor()
    excluded = ('cron', 'delegate', 'subagent')
    query = (
        "SELECT id, source, title, started_at, ended_at, message_count "
        "FROM sessions "
        "WHERE source NOT IN (?, ?, ?) "
        "AND message_count >= ? "
        "AND started_at >= ?"
    )
    params = list(excluded) + [min_messages, since_ts]
    if sources:
        placeholders = ','.join('?' * len(sources))
        query += f" AND source IN ({placeholders})"
        params.extend(sources)
    query += " ORDER BY started_at DESC"

    c.execute(query, params)
    sessions = []
    for row in c.fetchall():
        sid, source, title, started_at, ended_at, msg_count = row
        session = {
            'session_id': sid,
            'source': source,
            'title': title or '(no title)',
            'started_at': (
                datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
                if started_at else None
            ),
            'ended_at': (
                datetime.fromtimestamp(ended_at, tz=timezone.utc).isoformat()
                if ended_at else None
            ),
            'message_count': int(msg_count or 0),
            'first_user_message': None,
            'last_user_message': None,
        }
        if include_messages:
            c.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'user' "
                "ORDER BY id ASC LIMIT 1",
                (sid,),
            )
            first = c.fetchone()
            if first:
                session['first_user_message'] = strip_message_content(
                    first[0], message_trunc)
            c.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'user' "
                "ORDER BY id DESC LIMIT 1",
                (sid,),
            )
            last = c.fetchone()
            if last:
                session['last_user_message'] = strip_message_content(
                    last[0], message_trunc)
        sessions.append(session)
    return sessions


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_human(sessions, since_str):
    """Render sessions as a human-readable text summary."""
    total_messages = sum(s['message_count'] for s in sessions)
    source_set = sorted({s['source'] for s in sessions})
    now = datetime.now(timezone.utc).isoformat()

    lines = []
    lines.append("=" * 60)
    lines.append("Cross-Session Context — Recent Interactive Sessions")
    lines.append("=" * 60)
    lines.append(f"Generated:    {now}")
    lines.append(f"Window:       since {since_str}")
    lines.append(f"Total sessions: {len(sessions)}")
    lines.append(f"Total messages: {total_messages}")
    if source_set:
        lines.append(f"Sources:      {', '.join(source_set)}")
    lines.append("")

    if not sessions:
        lines.append("No interactive sessions found in this window.")
        return "\n".join(lines)

    for i, s in enumerate(sessions, 1):
        lines.append("-" * 60)
        lines.append(f"[{i}] {s['started_at']} | {s['source']} | "
                     f"{s['message_count']} msgs")
        lines.append(f"    Title: {s['title']}")
        if s['first_user_message']:
            lines.append(f"    First user msg: {s['first_user_message']}")
        if s['last_user_message']:
            lines.append(f"    Last user msg:  {s['last_user_message']}")
    lines.append("-" * 60)
    return "\n".join(lines)


def format_json(sessions, since_str):
    """Render sessions as a JSON document."""
    total_messages = sum(s['message_count'] for s in sessions)
    source_set = sorted({s['source'] for s in sessions})
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'since': since_str,
        'total_sessions': len(sessions),
        'total_messages': total_messages,
        'sources': source_set,
        'sessions': sessions,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Summarize recent interactive sessions for heartbeat context."
    )
    parser.add_argument('--db', required=True,
                        help='Path to the SQLite session database')
    parser.add_argument('--since', default='24h',
                        help='Time window: "24h", "12h", "1d", "30m", '
                             '"3600s", ISO 8601, or Unix timestamp '
                             '(default: 24h)')
    parser.add_argument('--source', default=None,
                        help='Filter by source (comma-separated, '
                             'e.g. webui,telegram)')
    parser.add_argument('--min-messages', type=int, default=3,
                        help='Minimum message count threshold (default: 3)')
    parser.add_argument('--include-messages', action='store_true',
                        help='Include first/last user messages per session')
    parser.add_argument('--message-trunc', type=int, default=200,
                        help='Max chars per message (default: 200)')
    parser.add_argument('--format', choices=['human', 'json'], default='human',
                        help='Output format (default: human)')
    parser.add_argument('--output', default=None,
                        help='Write output to file instead of stdout')
    args = parser.parse_args()

    # Graceful handling: DB does not exist
    if not os.path.exists(args.db):
        msg = (f"Session database not found: {args.db}\n"
               "No interactive session context available. "
               "Skipping cross-session context step.")
        if args.format == 'json':
            payload = {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'since': args.since,
                'total_sessions': 0,
                'total_messages': 0,
                'sources': [],
                'sessions': [],
                'error': f'database not found: {args.db}',
            }
            output = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            output = msg
        _write_output(output, args.output)
        return

    since_ts = parse_since(args.since)
    sources = None
    if args.source:
        sources = [s.strip() for s in args.source.split(',') if s.strip()]

    try:
        conn = sqlite3.connect(args.db)
    except sqlite3.Error as e:
        print(f"Error opening database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        schema = detect_schema(conn)
        if schema == 'hermes':
            sessions = query_hermes_sessions(
                conn, since_ts, sources, args.min_messages,
                args.include_messages, args.message_trunc)
        elif schema == 'generic':
            print("Warning: generic session schema detected — "
                  "Hermes-style columns not found. No sessions queried.",
                  file=sys.stderr)
            sessions = []
        else:
            print("Warning: no recognizable session schema found in "
                  f"{args.db}. No sessions queried.", file=sys.stderr)
            sessions = []
    finally:
        conn.close()

    if args.format == 'json':
        output = format_json(sessions, args.since)
    else:
        output = format_human(sessions, args.since)

    _write_output(output, args.output)


def _write_output(output, output_path):
    """Write *output* to stdout or to *output_path* if given."""
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)
            if not output.endswith('\n'):
                f.write('\n')
    else:
        print(output)


if __name__ == "__main__":
    main()