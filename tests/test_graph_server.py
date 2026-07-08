import http.client
import json
import socket
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

import scripts.graph_server as graph_server
from scripts.graph_server import GraphHTTPHandler


@pytest.fixture
def server_workspace(tmp_path):
    (tmp_path / "GOALS.md").write_text("# Goals\n\nShip graph server.")
    db_path = tmp_path / "journal.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE journal_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, session_type TEXT, title TEXT,
        what_i_did TEXT, what_i_found TEXT, what_im_thinking TEXT,
        open_threads TEXT DEFAULT '[]', room_status TEXT
    )"""
    )
    conn.execute(
        "INSERT INTO journal_entries (date, session_type, title, what_i_did, what_i_found, what_im_thinking, open_threads, room_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-07-08",
            "Daytime",
            "Server Entry",
            "Served data",
            "Found endpoints",
            "Thinking about tests",
            '["thread1"]',
            "Clean",
        ),
    )
    conn.commit()
    conn.close()
    return tmp_path


def _find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _ServerContext:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.port = _find_free_port()
        GraphHTTPHandler.workspace = workspace
        GraphHTTPHandler.skills_dir = None
        GraphHTTPHandler.wiki_path = None
        GraphHTTPHandler.docs_path = None
        GraphHTTPHandler.codebase_paths = None
        GraphHTTPHandler.journal_db = str(workspace / "journal.db")
        self.httpd = graph_server.http.server.HTTPServer(("127.0.0.1", self.port), GraphHTTPHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def request(self, path: str):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            conn.close()


def test_root_serves_graph_html(server_workspace):
    with _ServerContext(server_workspace) as server:
        status, headers, body = server.request("/")
    text = body.decode("utf-8")
    assert status == 200
    assert "text/html" in headers["Content-Type"]
    assert "Agent Heartbeat" in text
    assert "memoryGraphCanvas" in text


def test_api_memory_graph_returns_json(server_workspace):
    with _ServerContext(server_workspace) as server:
        status, headers, body = server.request("/api/memory-graph")
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert {"nodes", "edges", "clusters", "stats"} <= set(payload)
    assert any(node["type"] == "goals" for node in payload["nodes"])


def test_vendor_d3_serves_javascript(server_workspace):
    with _ServerContext(server_workspace) as server:
        status, headers, body = server.request("/vendor/d3/d3.v7.min.js")
    assert status == 200
    assert "application/javascript" in headers["Content-Type"]
    assert len(body) > 1000


def test_nonexistent_returns_404(server_workspace):
    with _ServerContext(server_workspace) as server:
        status, _headers, _body = server.request("/nonexistent")
    assert status == 404


def test_api_returns_500_on_builder_error(server_workspace, monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(graph_server, "build_graph_payload", boom)
    with _ServerContext(server_workspace) as server:
        status, headers, body = server.request("/api/memory-graph")
    payload = json.loads(body.decode("utf-8"))
    assert status == 500
    assert headers["Content-Type"] == "application/json"
    assert payload["error"] == "boom"
