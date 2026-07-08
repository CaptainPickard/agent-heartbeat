#!/usr/bin/env python3
"""Standalone memory graph server for agent-heartbeat.

Serves:
  GET /                 -> graph.html
  GET /api/memory-graph -> JSON graph payload
  GET /vendor/*         -> vendored JS libraries (d3)
"""

from __future__ import annotations

import argparse
import http.server
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from graph_builder import build_graph_payload

GRAPH_DIR = Path(__file__).resolve().parent.parent / "graph"


class GraphHTTPHandler(http.server.SimpleHTTPRequestHandler):
    workspace: Path | None = None
    skills_dir: Path | None = None
    wiki_path: Path | None = None
    docs_path: Path | None = None
    codebase_paths: list[str] | None = None
    journal_db: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/graph.html"):
            self._serve_file(GRAPH_DIR / "graph.html", "text/html; charset=utf-8")
        elif parsed.path == "/api/memory-graph":
            self._serve_graph_api(parsed)
        elif parsed.path.startswith("/vendor/"):
            file_path = GRAPH_DIR / parsed.path.lstrip("/")
            content_type = "application/javascript; charset=utf-8"
            if file_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            self._serve_file(file_path, content_type)
        elif parsed.path == "/favicon.ico":
            self.send_error(404)
        else:
            self.send_error(404)

    def _serve_graph_api(self, parsed):
        _qs = parse_qs(parsed.query)
        try:
            if self.workspace is None:
                raise RuntimeError("workspace is not configured")
            payload = build_graph_payload(
                workspace=self.workspace,
                skills_dir=self.skills_dir,
                wiki_path=self.wiki_path,
                docs_path=self.docs_path,
                codebase_paths=self.codebase_paths,
                journal_db_path=self.journal_db,
            )
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # pragma: no cover - validated via HTTP test
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists() or not path.is_file():
            self.send_error(404, f"File not found: {path}")
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory graph server for agent-heartbeat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Minimal (journal + goals)
  %(prog)s --workspace .

  # Full (all data sources)
  %(prog)s --workspace . --skills-dir ~/skills --wiki-path ~/wiki \
    --docs-path ~/docs --codebase-paths ~/project-a,~/project-b

  # Custom port
  %(prog)s --workspace . --port 8888

Honcho (optional):
  See docs/honcho-integration.md for adding Honcho memory data.
  Not included in the core server — add via a custom build_graph_payload
  wrapper that calls build_honcho_graph_data() and merges the result.
""",
    )
    parser.add_argument("--workspace", required=True, help="Path to agent workspace")
    parser.add_argument("--skills-dir", default=None, help="Path to skills directory (SKILL.md files)")
    parser.add_argument("--wiki-path", default=None, help="Path to wiki directory (entities/, concepts/, etc.)")
    parser.add_argument("--docs-path", default=None, help="Path to documents directory (.md files)")
    parser.add_argument("--codebase-paths", default=None, help="Comma-separated paths to codebase directories")
    parser.add_argument("--journal-db", default=None, help="Path to journal.db (default: workspace/journal.db)")
    parser.add_argument("--port", type=int, default=8790, help="Port to serve on (default: 8790)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    journal_db = args.journal_db or str(workspace / "journal.db")
    skills_dir = Path(args.skills_dir).resolve() if args.skills_dir else None
    wiki_path = Path(args.wiki_path).resolve() if args.wiki_path else None
    docs_path = Path(args.docs_path).resolve() if args.docs_path else None
    codebase_paths = [str(Path(p.strip()).resolve()) for p in args.codebase_paths.split(",") if p.strip()] if args.codebase_paths else None

    GraphHTTPHandler.workspace = workspace
    GraphHTTPHandler.skills_dir = skills_dir
    GraphHTTPHandler.wiki_path = wiki_path
    GraphHTTPHandler.docs_path = docs_path
    GraphHTTPHandler.codebase_paths = codebase_paths
    GraphHTTPHandler.journal_db = journal_db

    server = http.server.HTTPServer((args.host, args.port), GraphHTTPHandler)
    print(f"Memory graph server running at http://localhost:{args.port}")
    print(f"  Workspace:   {workspace}")
    print(f"  Journal DB:  {journal_db}")
    print(f"  Skills:      {skills_dir or '(not configured)'}")
    print(f"  Wiki:        {wiki_path or '(not configured)'}")
    print(f"  Documents:   {docs_path or '(not configured)'}")
    print(f"  Codebases:   {codebase_paths or '(not configured)'}")
    print("  Honcho:      (optional — see docs/honcho-integration.md)")
    print(f"\n  Open http://localhost:{args.port} in your browser")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
