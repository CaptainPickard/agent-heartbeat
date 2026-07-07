"""Tests for export_latest_to_markdown() and close_thread_by_text()."""

from pathlib import Path

from scripts.journal_store import (
    add_entry,
    close_thread_by_text,
    export_latest_to_markdown,
    get_open_threads,
    init_db,
)


def _seed_three(db_path: str) -> list[int]:
    """Seed a DB with 3 entries and return their IDs."""
    init_db(db_path)
    ids = []
    for i in range(1, 4):
        eid = add_entry(
            db_path=db_path,
            date=f"2026-07-0{i}",
            session_type="Daytime" if i % 2 else "Nightly",
            title=f"Entry {i}",
            what_i_did=f"Did thing {i}.",
            what_i_found=f"Found thing {i}.",
            what_im_thinking=f"Thinking thought {i}.",
            open_threads=[f"thread {i}"],
            room_status=f"Clean {i}.",
        )
        ids.append(eid)
    return ids


def test_export_latest_writes_only_most_recent_entry(tmp_path):
    db_path = str(tmp_path / "journal.db")
    _seed_three(db_path)

    out = tmp_path / "JOURNAL.md"
    export_latest_to_markdown(db_path, str(out))

    content = out.read_text()

    assert "## Open Threads" in content
    assert "## Closed Threads" in content
    assert "## Latest Entry" in content
    assert "### 2026-07-03 [Daytime] — Entry 3" in content
    # Earlier entries must NOT appear
    assert "Entry 1" not in content
    assert "Entry 2" not in content
    assert "Did thing 1." not in content


def test_export_latest_overwrites_not_appends(tmp_path):
    db_path = str(tmp_path / "journal.db")
    _seed_three(db_path)

    out = tmp_path / "JOURNAL.md"
    export_latest_to_markdown(db_path, str(out))
    first_lines = len(out.read_text().splitlines())

    # Call again — should overwrite, not append
    export_latest_to_markdown(db_path, str(out))
    second_lines = len(out.read_text().splitlines())

    assert first_lines == second_lines


def test_export_latest_empty_db_writes_no_entries_message(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_db(db_path)

    out = tmp_path / "JOURNAL.md"
    export_latest_to_markdown(db_path, str(out))

    content = out.read_text()
    assert "## Open Threads" in content
    assert "No entries yet." in content


def test_export_latest_includes_open_and_closed_threads(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_db(db_path)
    add_entry(
        db_path=db_path,
        date="2026-07-01",
        session_type="Daytime",
        title="Test",
        what_i_did="x",
        what_i_found="y",
        what_im_thinking=None,
        open_threads=["alpha thread", "beta thread"],
        room_status="clean",
    )
    # Close one
    close_thread_by_text(db_path, "alpha")

    out = tmp_path / "JOURNAL.md"
    export_latest_to_markdown(db_path, str(out))
    content = out.read_text()

    assert "- beta thread" in content  # still open
    assert "- alpha thread" in content  # now closed


def test_close_thread_by_text_substring_case_insensitive(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_db(db_path)
    add_entry(
        db_path=db_path,
        date="2026-07-01",
        session_type="Daytime",
        title="T",
        what_i_did="x",
        what_i_found="y",
        what_im_thinking=None,
        open_threads=["Build examples directory for contributors"],
        room_status="clean",
    )

    result = close_thread_by_text(db_path, "examples directory")
    assert result is True

    remaining = get_open_threads(db_path)
    assert len(remaining) == 0


def test_close_thread_by_text_returns_false_for_no_match(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_db(db_path)
    add_entry(
        db_path=db_path,
        date="2026-07-01",
        session_type="Daytime",
        title="T",
        what_i_did="x",
        what_i_found="y",
        what_im_thinking=None,
        open_threads=["unrelated thread"],
        room_status="clean",
    )

    result = close_thread_by_text(db_path, "nonexistent")
    assert result is False

    remaining = get_open_threads(db_path)
    assert len(remaining) == 1


def test_close_thread_by_text_uses_latest_entry_id_when_none_given(tmp_path):
    db_path = str(tmp_path / "journal.db")
    ids = _seed_three(db_path)

    # Close a thread from the third entry without specifying closing_entry_id
    result = close_thread_by_text(db_path, "thread 3")
    assert result is True

    # The closing_entry_id should be the latest entry (ids[2])
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT closed_entry_id FROM open_threads WHERE thread_text = 'thread 3'"
    ).fetchone()
    conn.close()
    assert row["closed_entry_id"] == ids[2]