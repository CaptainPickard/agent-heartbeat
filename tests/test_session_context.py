"""Tests for session_context.py.

Covers schema detection, session filtering, message extraction,
time parsing, and both output formats.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session_context.py"
SPEC = importlib.util.spec_from_file_location("session_context", MODULE_PATH)
session_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session_context)

parse_since = session_context.parse_since
detect_schema = session_context.detect_schema
strip_message_content = session_context.strip_message_content
query_hermes_sessions = session_context.query_hermes_sessions
format_human = session_context.format_human
format_json = session_context.format_json


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_hermes_db(tmp_path, sessions_data=None, messages_data=None):
    """Build a temporary Hermes-schema SQLite DB.

    sessions_data: list of dicts with keys
        id, source, title, started_at, ended_at, message_count
    messages_data: list of dicts with keys
        id, session_id, role, content, timestamp
    """
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        source TEXT,
        title TEXT,
        started_at REAL,
        ended_at REAL,
        message_count INTEGER
    )""")
    c.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT,
        content TEXT,
        timestamp REAL
    )""")
    for s in sessions_data or []:
        c.execute(
            "INSERT INTO sessions (id, source, title, started_at, "
            "ended_at, message_count) VALUES (?, ?, ?, ?, ?, ?)",
            (s['id'], s.get('source'), s.get('title'),
             s.get('started_at'), s.get('ended_at'),
             s.get('message_count', 0)),
        )
    for m in messages_data or []:
        c.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (m['session_id'], m['role'], m['content'], m.get('timestamp')),
        )
    conn.commit()
    conn.close()
    return db_path


def now_ts():
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# 1. Schema detection
# ---------------------------------------------------------------------------

class TestSchemaDetection:
    def test_hermes_schema_detected(self, tmp_path):
        db = make_hermes_db(tmp_path)
        conn = sqlite3.connect(str(db))
        assert detect_schema(conn) == 'hermes'
        conn.close()

    def test_generic_fallback(self, tmp_path):
        db = tmp_path / "g.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE session_log (id INTEGER, data TEXT)")
        conn.commit()
        assert detect_schema(conn) == 'generic'
        conn.close()

    def test_no_session_schema(self, tmp_path):
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE other (id INTEGER)")
        conn.commit()
        assert detect_schema(conn) is None
        conn.close()

    def test_missing_db_handled(self, tmp_path, capsys):
        # Running main() against a non-existent DB should not crash.
        missing = str(tmp_path / "nope.db")
        sys.argv = ["session_context.py", "--db", missing, "--since", "24h"]
        session_context.main()
        out = capsys.readouterr().out
        assert "not found" in out or "No interactive" in out


# ---------------------------------------------------------------------------
# 2. Session filtering
# ---------------------------------------------------------------------------

class TestSessionFiltering:
    def _base_sessions(self):
        ts = now_ts()
        return [
            {'id': 's1', 'source': 'webui', 'title': 'Chat 1',
             'started_at': ts - 3600, 'ended_at': ts - 3500,
             'message_count': 10},
            {'id': 's2', 'source': 'cron', 'title': 'Cron run',
             'started_at': ts - 3000, 'ended_at': ts - 2900,
             'message_count': 5},
            {'id': 's3', 'source': 'delegate', 'title': 'Delegated',
             'started_at': ts - 2000, 'ended_at': ts - 1900,
             'message_count': 4},
            {'id': 's4', 'source': 'telegram', 'title': 'TG chat',
             'started_at': ts - 7200, 'ended_at': ts - 7100,
             'message_count': 2},
            {'id': 's5', 'source': 'webui', 'title': 'Old chat',
             'started_at': ts - 90000, 'ended_at': ts - 89000,
             'message_count': 8},
        ]

    def test_excludes_autonomous_sources(self, tmp_path):
        db = make_hermes_db(tmp_path, sessions_data=self._base_sessions())
        conn = sqlite3.connect(str(db))
        sessions = query_hermes_sessions(conn, since_ts=0, sources=None,
                                         min_messages=0,
                                         include_messages=False,
                                         message_trunc=200)
        sources = {s['source'] for s in sessions}
        assert 'cron' not in sources
        assert 'delegate' not in sources
        assert 'subagent' not in sources
        conn.close()

    def test_respects_min_messages(self, tmp_path):
        db = make_hermes_db(tmp_path, sessions_data=self._base_sessions())
        conn = sqlite3.connect(str(db))
        sessions = query_hermes_sessions(conn, since_ts=0, sources=None,
                                         min_messages=5,
                                         include_messages=False,
                                         message_trunc=200)
        assert all(s['message_count'] >= 5 for s in sessions)
        conn.close()

    def test_respects_since(self, tmp_path):
        db = make_hermes_db(tmp_path, sessions_data=self._base_sessions())
        conn = sqlite3.connect(str(db))
        cutoff = now_ts() - 50000  # ~13.8h ago
        sessions = query_hermes_sessions(conn, since_ts=cutoff, sources=None,
                                         min_messages=0,
                                         include_messages=False,
                                         message_trunc=200)
        # 's5' (90s ago) should be excluded
        ids = {s['session_id'] for s in sessions}
        assert 's5' not in ids
        conn.close()

    def test_respects_source_filter(self, tmp_path):
        db = make_hermes_db(tmp_path, sessions_data=self._base_sessions())
        conn = sqlite3.connect(str(db))
        sessions = query_hermes_sessions(conn, since_ts=0,
                                         sources=['webui'],
                                         min_messages=0,
                                         include_messages=False,
                                         message_trunc=200)
        assert all(s['source'] == 'webui' for s in sessions)
        conn.close()


# ---------------------------------------------------------------------------
# 3. Message extraction
# ---------------------------------------------------------------------------

class TestMessageExtraction:
    def test_first_and_last_user_messages(self, tmp_path):
        ts = now_ts()
        sessions = [{'id': 'sx', 'source': 'webui', 'title': 'T',
                     'started_at': ts - 100, 'ended_at': ts - 50,
                     'message_count': 4}]
        messages = [
            {'session_id': 'sx', 'role': 'user',
             'content': 'Hello there', 'timestamp': ts - 100},
            {'session_id': 'sx', 'role': 'assistant',
             'content': 'Hi!', 'timestamp': ts - 90},
            {'session_id': 'sx', 'role': 'user',
             'content': 'Do something', 'timestamp': ts - 60},
            {'session_id': 'sx', 'role': 'user',
             'content': 'Final request', 'timestamp': ts - 55},
        ]
        db = make_hermes_db(tmp_path, sessions, messages)
        conn = sqlite3.connect(str(db))
        result = query_hermes_sessions(conn, since_ts=0, sources=None,
                                       min_messages=0,
                                       include_messages=True,
                                       message_trunc=200)
        assert len(result) == 1
        assert result[0]['first_user_message'] == 'Hello there'
        assert result[0]['last_user_message'] == 'Final request'
        conn.close()

    def test_content_stripping(self):
        raw = 'Hello <reasoning>secret thoughts</reasoning> [tool_call: foo] world <b>bold</b>'
        cleaned = strip_message_content(raw, max_len=500)
        assert 'reasoning' not in cleaned
        assert 'tool_call' not in cleaned
        assert '<' not in cleaned
        assert 'Hello' in cleaned and 'world' in cleaned

    def test_truncation(self):
        long_text = 'x' * 300
        result = strip_message_content(long_text, max_len=50)
        assert len(result) <= 50
        assert result.endswith('...')

    def test_empty_messages_skipped(self, tmp_path):
        ts = now_ts()
        sessions = [{'id': 'sempty', 'source': 'webui', 'title': 'No msgs',
                     'started_at': ts - 100, 'ended_at': ts - 50,
                     'message_count': 0}]
        db = make_hermes_db(tmp_path, sessions, [])
        conn = sqlite3.connect(str(db))
        result = query_hermes_sessions(conn, since_ts=0, sources=None,
                                       min_messages=0,
                                       include_messages=True,
                                       message_trunc=200)
        # session present but no user messages
        assert result[0]['first_user_message'] is None
        assert result[0]['last_user_message'] is None
        conn.close()


# ---------------------------------------------------------------------------
# 4. Time parsing
# ---------------------------------------------------------------------------

class TestTimeParsing:
    def test_24h(self):
        ts = parse_since('24h')
        expected = (datetime.now(timezone.utc) -
                    timedelta(hours=24)).timestamp()
        assert abs(ts - expected) < 5

    def test_30m(self):
        ts = parse_since('30m')
        expected = (datetime.now(timezone.utc) -
                    timedelta(minutes=30)).timestamp()
        assert abs(ts - expected) < 5

    def test_1d(self):
        ts = parse_since('1d')
        expected = (datetime.now(timezone.utc) -
                    timedelta(days=1)).timestamp()
        assert abs(ts - expected) < 5

    def test_iso_8601(self):
        ts = parse_since('2025-07-20T12:00:00Z')
        expected = datetime(2025, 7, 20, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        assert abs(ts - expected) < 5

    def test_unix_timestamp(self):
        ts = parse_since('1721472000')
        assert abs(ts - 1721472000.0) < 0.01

    def test_invalid_exits(self):
        with pytest.raises(SystemExit):
            parse_since('not-a-time')


# ---------------------------------------------------------------------------
# 5. Output formats
# ---------------------------------------------------------------------------

class TestOutputFormats:
    def _sample_sessions(self):
        return [
            {'session_id': 'a', 'source': 'webui', 'title': 'Chat A',
             'started_at': '2025-07-20T10:00:00+00:00',
             'ended_at': '2025-07-20T10:30:00+00:00',
             'message_count': 5,
             'first_user_message': 'Hi', 'last_user_message': 'Bye'},
        ]

    def test_human_has_counts(self):
        out = format_human(self._sample_sessions(), '24h')
        assert 'Total sessions: 1' in out
        assert 'Total messages: 5' in out
        assert 'Chat A' in out

    def test_json_has_all_fields(self):
        out = format_json(self._sample_sessions(), '24h')
        data = json.loads(out)
        for key in ('generated_at', 'since', 'total_sessions',
                    'total_messages', 'sources', 'sessions'):
            assert key in data
        assert data['total_sessions'] == 1
        assert data['sessions'][0]['session_id'] == 'a'

    def test_output_writes_to_file(self, tmp_path):
        out_file = tmp_path / "out.txt"
        sys.argv = ["session_context.py", "--db", str(tmp_path / "x.db"),
                    "--since", "24h", "--output", str(out_file)]
        session_context.main()
        assert out_file.exists()
        content = out_file.read_text()
        assert "not found" in content or "No interactive" in content

    def test_empty_graceful_message(self):
        out = format_human([], '24h')
        assert 'No interactive sessions found' in out