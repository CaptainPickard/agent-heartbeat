"""Independent validation tests for the DB-primary journal workflow."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts import journal_store

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "journal_cli.py"
DAYTIME_TEMPLATE = REPO_ROOT / "templates" / "daytime_prompt.txt"
NIGHTLY_TEMPLATE = REPO_ROOT / "templates" / "nightly_prompt.txt"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _add_entry(
    db_path: Path,
    *,
    date: str,
    title: str,
    session_type: str = "Daytime",
    what_i_did: str = "did",
    what_i_found: str = "found",
    what_im_thinking: str | None = "thinking",
    open_threads: list[str] | None = None,
    room_status: str | None = "Clean.",
) -> int:
    return journal_store.add_entry(
        str(db_path),
        date,
        session_type,
        title,
        what_i_did,
        what_i_found,
        what_im_thinking,
        open_threads or [],
        room_status,
    )


def test_export_latest_snapshot_overwrites_existing_file_and_keeps_only_latest_entry(tmp_path):
    db_path = tmp_path / "journal.db"
    md_path = tmp_path / "JOURNAL.md"

    _add_entry(db_path, date="2026-07-07", title="Older entry", open_threads=["thread a"])
    _add_entry(db_path, date="2026-07-08", title="Newest entry", open_threads=["thread b"])

    md_path.write_text("STALE HEADER\n### definitely old content\n")
    journal_store.export_latest_to_markdown(str(db_path), str(md_path))

    content = md_path.read_text()
    assert "STALE HEADER" not in content
    assert "Older entry" not in content
    assert "Newest entry" in content
    assert content.count("### ") == 1
    assert content.rstrip().endswith("**Room status:** Clean.")


def test_export_latest_empty_db_writes_no_entries_message_and_thread_sections(tmp_path):
    db_path = tmp_path / "journal.db"
    md_path = tmp_path / "JOURNAL.md"

    journal_store.export_latest_to_markdown(str(db_path), str(md_path))

    content = md_path.read_text()
    assert "## Open Threads" in content
    assert "## Closed Threads" in content
    assert "## Latest Entry" in content
    assert "No entries yet." in content
    assert content.count("### ") == 0


def test_cli_add_updates_db_and_replaces_markdown_snapshot_on_second_add(tmp_path):
    db_path = tmp_path / "journal.db"
    md_path = tmp_path / "JOURNAL.md"

    first = _run_cli(
        "add",
        "--db",
        str(db_path),
        "--md",
        str(md_path),
        "--date",
        "2026-07-07",
        "--session-type",
        "Daytime",
        "--title",
        "First title",
        "--what-i-did",
        "first did",
        "--what-i-found",
        "first found",
        "--open-threads",
        "Alpha thread",
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip().isdigit()

    md_path.write_text("manually corrupted snapshot\n")

    second = _run_cli(
        "add",
        "--db",
        str(db_path),
        "--md",
        str(md_path),
        "--date",
        "2026-07-08",
        "--session-type",
        "Nightly",
        "--title",
        "Second title",
        "--what-i-did",
        "second did\nwith newline",
        "--what-i-found",
        "second found",
        "--what-im-thinking",
        "second think",
        "--open-threads",
        "Beta thread,Gamma thread",
        "--room-status",
        "Tidy.",
    )
    assert second.returncode == 0, second.stderr

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
        latest = conn.execute(
            "SELECT session_type, title, what_i_did FROM journal_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert count == 2
    assert latest == ("Nightly", "Second title", "second did\nwith newline")

    content = md_path.read_text()
    assert "manually corrupted snapshot" not in content
    assert "First title" not in content
    assert "Second title" in content
    assert "second did\nwith newline" in content
    assert content.count("### ") == 1


def test_cli_read_prints_open_threads_and_recent_entries_in_expected_order(tmp_path):
    db_path = tmp_path / "journal.db"
    md_path = tmp_path / "JOURNAL.md"

    _run_cli(
        "add",
        "--db",
        str(db_path),
        "--md",
        str(md_path),
        "--date",
        "2026-07-07",
        "--title",
        "Older",
        "--what-i-did",
        "older did",
        "--what-i-found",
        "older found",
        "--open-threads",
        "alpha",
    )
    _run_cli(
        "add",
        "--db",
        str(db_path),
        "--md",
        str(md_path),
        "--date",
        "2026-07-08",
        "--session-type",
        "Nightly",
        "--title",
        "Newer",
        "--what-i-did",
        "newer did",
        "--what-i-found",
        "newer found",
        "--what-im-thinking",
        "newer think",
        "--open-threads",
        "beta",
        "--room-status",
        "Organized.",
    )

    result = _run_cli("read", "--db", str(db_path), "--limit", "2")
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert output.startswith("=== Open Threads ===\n")
    assert "- alpha" in output
    assert "- beta" in output
    assert "=== Recent Entries (last 2) ===" in output
    assert output.index("### 2026-07-08 [Nightly] — Newer") < output.index(
        "### 2026-07-07 [Daytime] — Older"
    )
    assert "Open threads: beta" in output
    assert "Room status: Organized." in output


def test_cli_close_thread_and_export_latest_regenerate_snapshot(tmp_path):
    db_path = tmp_path / "journal.db"
    md_path = tmp_path / "JOURNAL.md"

    _add_entry(db_path, date="2026-07-07", title="Seed", open_threads=["Important Thread"])
    md_path.write_text("obsolete snapshot\n")

    close_result = _run_cli(
        "close-thread",
        "--db",
        str(db_path),
        "--thread-text",
        "important",
    )
    assert close_result.returncode == 0, close_result.stderr

    with sqlite3.connect(db_path) as conn:
        closed = conn.execute(
            "SELECT status, closed_entry_id FROM open_threads WHERE thread_text = ?",
            ("Important Thread",),
        ).fetchone()
    assert closed[0] == "closed"
    assert closed[1] == 1

    export_result = _run_cli(
        "export-latest",
        "--db",
        str(db_path),
        "--md",
        str(md_path),
    )
    assert export_result.returncode == 0, export_result.stderr
    content = md_path.read_text()
    assert "obsolete snapshot" not in content
    assert "## Closed Threads" in content
    assert "Important Thread" in content
    assert export_result.stdout.strip() == str(md_path)


def test_close_thread_by_text_is_case_insensitive_substring_and_closes_first_match_only(tmp_path):
    db_path = tmp_path / "journal.db"
    closing_entry_id = _add_entry(
        db_path,
        date="2026-07-07",
        title="Seed",
        open_threads=["Alpha planning", "alpha follow-up", "Unrelated"],
    )

    closed = journal_store.close_thread_by_text(
        str(db_path), "ALPHA", closing_entry_id=closing_entry_id
    )
    assert closed is True

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT thread_text, status FROM open_threads ORDER BY id ASC"
        ).fetchall()
    assert rows == [
        ("Alpha planning", "closed"),
        ("alpha follow-up", "open"),
        ("Unrelated", "open"),
    ]


def test_close_thread_by_text_returns_false_when_no_match_or_no_entries_exist(tmp_path):
    db_path = tmp_path / "journal.db"

    assert journal_store.close_thread_by_text(str(db_path), "missing") is False

    _add_entry(db_path, date="2026-07-07", title="Seed", open_threads=["Thread one"])
    assert journal_store.close_thread_by_text(str(db_path), "does-not-match") is False


def test_close_thread_by_text_with_empty_search_does_not_close_anything(tmp_path):
    db_path = tmp_path / "journal.db"
    _add_entry(db_path, date="2026-07-07", title="Seed", open_threads=["Thread one", "Thread two"])

    closed = journal_store.close_thread_by_text(str(db_path), "")
    assert closed is False

    with sqlite3.connect(db_path) as conn:
        statuses = conn.execute(
            "SELECT status FROM open_threads ORDER BY id ASC"
        ).fetchall()
    assert statuses == [("open",), ("open",)]


def test_templates_use_journal_cli_commands_and_do_not_tell_agent_to_read_journal_md_directly():
    expected_add_block = (
        'scripts/journal_cli.py add \\\n'
        '  --db {WORKSPACE}/journal.db \\\n'
        '  --md {WORKSPACE}/JOURNAL.md'
    )

    for template_path in (DAYTIME_TEMPLATE, NIGHTLY_TEMPLATE):
        text = template_path.read_text()
        assert "scripts/journal_cli.py read --db {WORKSPACE}/journal.db" in text
        assert expected_add_block in text
        assert "cat {WORKSPACE}/JOURNAL.md" not in text
        assert "Read GOALS.md and JOURNAL.md first" not in text
        assert "Check JOURNAL.md" not in text
