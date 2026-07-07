"""SQLite-backed journal store for agent-heartbeat."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent.parent / "journal.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    session_type TEXT NOT NULL DEFAULT 'Daytime',
    title TEXT,
    what_i_did TEXT,
    what_i_found TEXT,
    what_im_thinking TEXT,
    open_threads TEXT,
    room_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS open_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_entry_id INTEGER,
    closed_entry_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT,
    FOREIGN KEY (created_entry_id) REFERENCES journal_entries(id),
    FOREIGN KEY (closed_entry_id) REFERENCES journal_entries(id)
);
"""

ENTRY_PATTERN = re.compile(
    r"^###\s+(?P<date>\d{4}-\d{2}-\d{2})(?:\s+\[(?P<session_type>[^\]]+)\])?\s+—\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)
SECTION_LABEL_PATTERN = re.compile(r"^\*\*(?P<label>[^*]+):\*\*\s*(?P<value>.*)$")


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _normalize_session_type(session_type: str | None) -> str:
    if not session_type:
        return "Daytime"
    normalized = session_type.strip()
    return normalized or "Daytime"


def _normalize_threads(open_threads: list[str] | None) -> list[str]:
    if not open_threads:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for thread in open_threads:
        if thread is None:
            continue
        text = str(thread).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw_threads = data.get("open_threads") or "[]"
    try:
        data["open_threads"] = json.loads(raw_threads)
    except json.JSONDecodeError:
        data["open_threads"] = []
    return data


def add_entry(
    db_path: str,
    date: str,
    session_type: str | None,
    title: str | None,
    what_i_did: str | None,
    what_i_found: str | None,
    what_im_thinking: str | None,
    open_threads: list[str],
    room_status: str | None,
) -> int:
    init_db(db_path)
    normalized_session_type = _normalize_session_type(session_type)
    normalized_threads = _normalize_threads(open_threads)

    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO journal_entries (
                date, session_type, title, what_i_did, what_i_found,
                what_im_thinking, open_threads, room_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date,
                normalized_session_type,
                title,
                what_i_did,
                what_i_found,
                what_im_thinking,
                json.dumps(normalized_threads),
                room_status,
            ),
        )
        entry_id = int(cursor.lastrowid)

        existing_open = {
            row["thread_text"]
            for row in conn.execute(
                "SELECT thread_text FROM open_threads WHERE status = 'open'"
            ).fetchall()
        }
        for thread_text in normalized_threads:
            if thread_text in existing_open:
                continue
            conn.execute(
                """
                INSERT INTO open_threads (thread_text, status, created_entry_id)
                VALUES (?, 'open', ?)
                """,
                (thread_text, entry_id),
            )
            existing_open.add(thread_text)

        conn.commit()
        return entry_id


def get_recent_entries(db_path: str, limit: int = 5) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM journal_entries
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_entry(row) for row in rows]


def get_open_threads(db_path: str) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM open_threads
            WHERE status = 'open'
            ORDER BY id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def close_thread(db_path: str, thread_id: int, closing_entry_id: int) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE open_threads
            SET status = 'closed',
                closed_entry_id = ?,
                closed_at = datetime('now')
            WHERE id = ?
            """,
            (closing_entry_id, thread_id),
        )
        conn.commit()


def get_entries_by_date_range(
    db_path: str, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM journal_entries
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC, id ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return [_row_to_entry(row) for row in rows]


def get_entries_by_session_type(
    db_path: str, session_type: str, limit: int | None = None
) -> list[dict[str, Any]]:
    """Return entries matching a session type ('Daytime' or 'Nightly').

    Matching is case-insensitive, so callers can pass 'nightly', 'Nightly',
    'DAYTIME', etc. Results are newest-first to match get_recent_entries.
    """
    normalized = _normalize_session_type(session_type)
    init_db(db_path)
    sql = (
        "SELECT * FROM journal_entries WHERE session_type = ? COLLATE NOCASE "
        "ORDER BY date DESC, id DESC"
    )
    params: list = [normalized]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_entry(row) for row in rows]


def get_entry_by_id(db_path: str, entry_id: int) -> dict[str, Any] | None:
    """Return a single entry by its primary key, or None if not found."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (int(entry_id),)
        ).fetchone()
    return _row_to_entry(row) if row else None


def get_entry_count(db_path: str) -> int:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM journal_entries").fetchone()
    return int(row["count"])


def _format_entry_block(entry: dict[str, Any]) -> list[str]:
    """Render a single journal entry as markdown lines (header + sections)."""
    title = entry.get("title") or "Untitled"
    session_type = _normalize_session_type(entry.get("session_type"))
    lines = [f"### {entry['date']} [{session_type}] — {title}", ""]

    if entry.get("what_i_did"):
        lines.append(f"**What I did:** {entry['what_i_did']}")
        lines.append("")
    if entry.get("what_i_found"):
        lines.append(f"**What I found:** {entry['what_i_found']}")
        lines.append("")
    if entry.get("what_im_thinking"):
        lines.append(f"**What I'm thinking:** {entry['what_im_thinking']}")
        lines.append("")
    if entry.get("open_threads"):
        lines.append("**Open threads:**")
        for thread_text in entry["open_threads"]:
            lines.append(f"- {thread_text}")
        lines.append("")
    if entry.get("room_status"):
        lines.append(f"**Room status:** {entry['room_status']}")
        lines.append("")
    return lines


def _format_threads_sections(
    open_rows: list[sqlite3.Row], closed_rows: list[sqlite3.Row]
) -> list[str]:
    """Render the Open/Closed Threads header sections used by both exporters."""
    lines = [
        "## Open Threads",
        "",
        "*Threads I'm actively pursuing. When I pick one up, I continue from where I left off. When I resolve one, I move it to the closed section.*",
        "",
    ]
    if open_rows:
        lines.extend(f"- {row['thread_text']}" for row in open_rows)
    else:
        lines.append("- **(none yet)**")

    lines.extend(
        [
            "",
            "---",
            "",
            "## Closed Threads",
            "",
            "*Threads I've resolved or abandoned. Kept for reference, moved here to keep the open list clean.*",
            "",
        ]
    )
    if closed_rows:
        lines.extend(f"- {row['thread_text']}" for row in closed_rows)
    else:
        lines.append("- **(none yet)**")
    return lines


def export_to_markdown(db_path: str, output_path: str) -> None:
    """Export the full journal (all entries + threads) to a markdown file."""
    init_db(db_path)
    with _connect(db_path) as conn:
        open_rows = conn.execute(
            "SELECT thread_text FROM open_threads WHERE status = 'open' ORDER BY id ASC"
        ).fetchall()
        closed_rows = conn.execute(
            "SELECT thread_text FROM open_threads WHERE status = 'closed' ORDER BY id ASC"
        ).fetchall()
        entry_rows = conn.execute(
            "SELECT * FROM journal_entries ORDER BY date ASC, id ASC"
        ).fetchall()

    lines = _format_threads_sections(open_rows, closed_rows)
    lines.extend(["", "---", "", "## Entries", ""])

    for index, row in enumerate(entry_rows):
        entry = _row_to_entry(row)
        lines.extend(_format_entry_block(entry))
        if index != len(entry_rows) - 1:
            lines.extend(["---", ""])

    Path(output_path).write_text("\n".join(lines).rstrip() + "\n")


def export_latest_to_markdown(db_path: str, output_path: str) -> None:
    """Overwrite output_path with open/closed threads + ONLY the latest entry.

    The database is the source of truth (full history). This produces a
    human-readable snapshot so a human can see what the agent wrote today
    without scrolling through the entire journal.
    """
    init_db(db_path)
    with _connect(db_path) as conn:
        open_rows = conn.execute(
            "SELECT thread_text FROM open_threads WHERE status = 'open' ORDER BY id ASC"
        ).fetchall()
        closed_rows = conn.execute(
            "SELECT thread_text FROM open_threads WHERE status = 'closed' ORDER BY id ASC"
        ).fetchall()
        latest_row = conn.execute(
            "SELECT * FROM journal_entries ORDER BY date DESC, id DESC LIMIT 1"
        ).fetchone()

    lines = _format_threads_sections(open_rows, closed_rows)
    lines.extend(["", "---", "", "## Latest Entry", ""])

    if latest_row is not None:
        entry = _row_to_entry(latest_row)
        lines.extend(_format_entry_block(entry))
    else:
        lines.append("No entries yet.")
        lines.append("")

    Path(output_path).write_text("\n".join(lines).rstrip() + "\n")


def close_thread_by_text(
    db_path: str, thread_text: str, closing_entry_id: int | None = None
) -> bool:
    """Close an open thread by text match (substring, case-insensitive).

    If closing_entry_id is None, uses the most recent entry ID.
    Returns True if a thread was closed, False if no match found.
    """
    init_db(db_path)
    with _connect(db_path) as conn:
        if closing_entry_id is None:
            row = conn.execute(
                "SELECT id FROM journal_entries ORDER BY date DESC, id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            closing_entry_id = int(row["id"])

        # Find the first open thread containing the search text (case-insensitive)
        match = conn.execute(
            "SELECT id FROM open_threads WHERE status = 'open' "
            "AND thread_text LIKE ? COLLATE NOCASE ORDER BY id ASC LIMIT 1",
            (f"%{thread_text}%",),
        ).fetchone()
        if match is None:
            return False

        conn.execute(
            "UPDATE open_threads SET status = 'closed', closed_entry_id = ?, "
            "closed_at = datetime('now') WHERE id = ?",
            (closing_entry_id, int(match["id"])),
        )
        conn.commit()
        return True


def _extract_section(lines: list[str], labels: list[str]) -> str | None:
    collected: list[str] = []
    active = False
    label_set = set(labels)

    for line in lines:
        match = SECTION_LABEL_PATTERN.match(line)
        if match:
            current_label = match.group("label").strip()
            if current_label in label_set:
                active = True
                value = match.group("value").strip()
                if value:
                    collected.append(value)
                continue
            if active:
                break
        elif active:
            collected.append(line)

    text = "\n".join(part.rstrip() for part in collected).strip()
    return text or None


def _extract_open_threads(lines: list[str]) -> list[str]:
    threads: list[str] = []
    capture = False
    valid_labels = {"Open threads started", "Open threads"}

    for line in lines:
        match = SECTION_LABEL_PATTERN.match(line)
        if match:
            label = match.group("label").strip()
            capture = label in valid_labels
            inline = match.group("value").strip()
            if capture and inline:
                threads.append(inline.lstrip("- ").strip())
            continue
        if capture:
            stripped = line.strip()
            if stripped.startswith("**"):
                capture = False
            elif stripped.startswith("- "):
                thread = stripped[2:].strip()
                if thread:
                    threads.append(thread)
            elif stripped == "":
                continue
            else:
                capture = False
    return _normalize_threads(threads)


def _parse_markdown_entries(md_text: str) -> list[dict[str, Any]]:
    matches = list(ENTRY_PATTERN.finditer(md_text))
    entries: list[dict[str, Any]] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(md_text)
        block = md_text[start:end].strip()
        block_lines = [line.rstrip() for line in block.splitlines()]

        what_i_did = _extract_section(block_lines, ["What happened", "What I did"])
        what_i_found = _extract_section(block_lines, ["What I found"])
        thinking_parts = [
            _extract_section(block_lines, ["What I'm thinking"]),
            _extract_section(block_lines, ["What I want to explore"]),
        ]
        what_im_thinking = "\n\n".join(part for part in thinking_parts if part)
        room_status = _extract_section(block_lines, ["Room status"])
        threads = _extract_open_threads(block_lines)

        entries.append(
            {
                "date": match.group("date"),
                "session_type": _normalize_session_type(match.group("session_type")),
                "title": match.group("title").strip(),
                "what_i_did": what_i_did,
                "what_i_found": what_i_found,
                "what_im_thinking": what_im_thinking or None,
                "open_threads": threads,
                "room_status": room_status,
            }
        )

    return entries


def migrate_from_markdown(db_path: str, md_path: str) -> int:
    init_db(db_path)
    md_text = Path(md_path).read_text()
    parsed_entries = _parse_markdown_entries(md_text)
    count = 0
    for entry in parsed_entries:
        add_entry(
            db_path=db_path,
            date=entry["date"],
            session_type=entry["session_type"],
            title=entry["title"],
            what_i_did=entry["what_i_did"],
            what_i_found=entry["what_i_found"],
            what_im_thinking=entry["what_im_thinking"],
            open_threads=entry["open_threads"],
            room_status=entry["room_status"],
        )
        count += 1
    return count
