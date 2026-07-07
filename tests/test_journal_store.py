import json
import sqlite3
from pathlib import Path

import pytest

from scripts.journal_store import (
    add_entry,
    close_thread,
    export_to_markdown,
    get_entries_by_date_range,
    get_entry_count,
    get_open_threads,
    get_recent_entries,
    init_db,
    migrate_from_markdown,
)


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "journal.db")


@pytest.fixture()
def seeded_db(db_path):
    init_db(db_path)
    first_id = add_entry(
        db_path=db_path,
        date="2026-07-07",
        session_type="Daytime",
        title="First Entry",
        what_i_did="Did first thing.",
        what_i_found="Found first thing.",
        what_im_thinking="Thinking first thought.",
        open_threads=["thread a", "thread b"],
        room_status="Clean.",
    )
    second_id = add_entry(
        db_path=db_path,
        date="2026-07-08",
        session_type="Nightly",
        title="Second Entry",
        what_i_did="Did second thing.",
        what_i_found="Found second thing.",
        what_im_thinking="Thinking second thought.",
        open_threads=["thread b", "thread c"],
        room_status="Still clean.",
    )
    return db_path, first_id, second_id


def test_init_db_creates_tables(db_path):
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "journal_entries" in names
    assert "open_threads" in names


def test_add_entry_inserts_all_fields_and_defaults_session_type(db_path):
    init_db(db_path)

    entry_id = add_entry(
        db_path=db_path,
        date="2026-07-09",
        session_type=None,
        title="Default Session",
        what_i_did="Built the feature.",
        what_i_found="It works.",
        what_im_thinking="Need to harden it.",
        open_threads=["ship feature"],
        room_status="Clean room.",
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row["date"] == "2026-07-09"
    assert row["session_type"] == "Daytime"
    assert row["title"] == "Default Session"
    assert row["what_i_did"] == "Built the feature."
    assert row["what_i_found"] == "It works."
    assert row["what_im_thinking"] == "Need to harden it."
    assert json.loads(row["open_threads"]) == ["ship feature"]
    assert row["room_status"] == "Clean room."


def test_get_recent_entries_returns_limit_in_reverse_order(seeded_db):
    db_path, _, _ = seeded_db

    recent = get_recent_entries(db_path, limit=1)

    assert len(recent) == 1
    assert recent[0]["title"] == "Second Entry"
    assert recent[0]["date"] == "2026-07-08"


def test_get_open_threads_returns_only_open_threads(seeded_db):
    db_path, first_id, second_id = seeded_db
    threads = get_open_threads(db_path)
    thread_ids = {thread["thread_text"]: thread["id"] for thread in threads}

    close_thread(db_path, thread_ids["thread a"], second_id)

    remaining = get_open_threads(db_path)
    remaining_texts = {thread["thread_text"] for thread in remaining}

    assert remaining_texts == {"thread b", "thread c"}
    assert "thread a" not in remaining_texts


def test_close_thread_marks_closed_and_sets_closed_at(seeded_db):
    db_path, _, second_id = seeded_db
    thread = next(t for t in get_open_threads(db_path) if t["thread_text"] == "thread a")

    close_thread(db_path, thread["id"], second_id)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM open_threads WHERE id = ?", (thread["id"],)
        ).fetchone()
    finally:
        conn.close()

    assert row["status"] == "closed"
    assert row["closed_entry_id"] == second_id
    assert row["closed_at"] is not None


def test_get_entries_by_date_range_filters_correctly(seeded_db):
    db_path, _, _ = seeded_db

    entries = get_entries_by_date_range(db_path, "2026-07-08", "2026-07-08")

    assert [entry["title"] for entry in entries] == ["Second Entry"]


def test_get_entry_count_returns_total_rows(seeded_db):
    db_path, _, _ = seeded_db
    assert get_entry_count(db_path) == 2


def test_export_to_markdown_produces_expected_journal_format(seeded_db, tmp_path):
    db_path, _, second_id = seeded_db
    thread = next(t for t in get_open_threads(db_path) if t["thread_text"] == "thread a")
    close_thread(db_path, thread["id"], second_id)

    output_path = tmp_path / "JOURNAL.md"
    export_to_markdown(db_path, str(output_path))

    content = output_path.read_text()

    assert "## Open Threads" in content
    assert "## Closed Threads" in content
    assert "## Entries" in content
    assert "### 2026-07-07 [Daytime] — First Entry" in content
    assert "### 2026-07-08 [Nightly] — Second Entry" in content
    assert "**What I did:** Did first thing." in content
    assert "**What I found:** Found second thing." in content
    assert "**What I'm thinking:** Thinking second thought." in content
    assert "- thread b" in content
    assert "- thread a" in content
    assert "**Room status:** Still clean." in content


def test_migrate_from_markdown_parses_existing_journal_entries(db_path):
    source_md = "/workspace/JOURNAL.md"
    init_db(db_path)

    migrated = migrate_from_markdown(db_path, source_md)
    entries = get_recent_entries(db_path, limit=10)

    assert migrated >= 1
    assert get_entry_count(db_path) == migrated
    assert any(entry["title"] == "Journal Created" for entry in entries)
    created = next(entry for entry in entries if entry["title"] == "Journal Created")
    assert created["date"] == "2026-07-07"
    assert created["session_type"] == "Daytime"
    assert "Nicko and I set up the autonomous heartbeat system" in created["what_i_did"]
    assert "most significant thing" in created["what_im_thinking"]
    assert any(
        "First heartbeat decision — what do I pick?" in thread
        for thread in created["open_threads"]
    )


def test_open_threads_are_stored_as_json_and_retrieved_correctly(seeded_db):
    db_path, _, _ = seeded_db
    entries = get_recent_entries(db_path, limit=2)
    first_entry = next(entry for entry in entries if entry["title"] == "First Entry")

    assert isinstance(first_entry["open_threads"], list)
    assert first_entry["open_threads"] == ["thread a", "thread b"]
