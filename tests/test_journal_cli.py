"""Tests for the journal_cli command-line interface."""

import subprocess
import sys
from pathlib import Path

CLI = str(Path(__file__).resolve().parent.parent / "scripts" / "journal_cli.py")


def _run_cli(db_path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, CLI, *args, "--db", db_path],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seed(db_path: str) -> int:
    """Add one entry via the CLI and return the entry ID printed to stdout."""
    result = _run_cli(
        db_path,
        "add",
        "--md", str(Path(db_path).parent / "JOURNAL.md"),
        "--date", "2026-07-07",
        "--session-type", "Daytime",
        "--title", "CLI Test Entry",
        "--what-i-did", "Ran a CLI test.",
        "--what-i-found", "It works.",
        "--what-im-thinking", "Good enough.",
        "--open-threads", "test thread alpha,test thread beta",
        "--room-status", "Clean.",
    )
    assert result.returncode == 0, f"add failed: {result.stderr}"
    return int(result.stdout.strip())


def test_cli_add_inserts_into_db_and_prints_id(tmp_path):
    db_path = str(tmp_path / "journal.db")
    entry_id = _seed(db_path)
    assert entry_id >= 1

    # Verify DB has the entry
    import sqlite3
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT title FROM journal_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    conn.close()
    assert row[0] == "CLI Test Entry"


def test_cli_add_overwrites_md_with_latest_entry_only(tmp_path):
    db_path = str(tmp_path / "journal.db")
    md_path = tmp_path / "JOURNAL.md"

    # Add first entry
    _run_cli(
        db_path, "add",
        "--md", str(md_path),
        "--date", "2026-07-01",
        "--title", "First",
        "--what-i-did", "first thing",
        "--what-i-found", "first find",
        "--open-threads", "alpha",
    )
    # Add second entry
    _run_cli(
        db_path, "add",
        "--md", str(md_path),
        "--date", "2026-07-02",
        "--title", "Second",
        "--what-i-did", "second thing",
        "--what-i-found", "second find",
        "--open-threads", "beta",
    )

    content = md_path.read_text()
    assert "### 2026-07-02 [Daytime] — Second" in content
    # First entry should NOT be in the latest snapshot
    assert "First" not in content
    assert "first thing" not in content


def test_cli_read_prints_entries_and_open_threads(tmp_path):
    db_path = str(tmp_path / "journal.db")
    _seed(db_path)

    result = _run_cli(db_path, "read", "--limit", "5")
    assert result.returncode == 0
    assert "=== Open Threads ===" in result.stdout
    assert "test thread alpha" in result.stdout
    assert "=== Recent Entries" in result.stdout
    assert "CLI Test Entry" in result.stdout


def test_cli_close_thread_closes_matching_thread(tmp_path):
    db_path = str(tmp_path / "journal.db")
    _seed(db_path)

    result = _run_cli(db_path, "close-thread", "--thread-text", "alpha")
    assert result.returncode == 0
    assert "Closed thread" in result.stdout

    # Verify it's closed in the DB
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status FROM open_threads WHERE thread_text LIKE '%alpha%'"
    ).fetchone()
    conn.close()
    assert row["status"] == "closed"


def test_cli_close_thread_returns_error_for_no_match(tmp_path):
    db_path = str(tmp_path / "journal.db")
    _seed(db_path)

    result = _run_cli(db_path, "close-thread", "--thread-text", "nonexistent")
    assert result.returncode == 1
    assert "No open thread" in result.stderr


def test_cli_export_latest_regenerates_md(tmp_path):
    db_path = str(tmp_path / "journal.db")
    md_path = tmp_path / "JOURNAL.md"
    _seed(db_path)

    # Delete the MD file, then regenerate
    if md_path.exists():
        md_path.unlink()

    result = _run_cli(
        db_path, "export-latest", "--md", str(md_path)
    )
    assert result.returncode == 0
    assert md_path.exists()
    content = md_path.read_text()
    assert "## Latest Entry" in content
    assert "CLI Test Entry" in content