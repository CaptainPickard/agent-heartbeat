import sqlite3
from pathlib import Path

import pytest

from scripts.graph_builder import build_graph_payload


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a full agent workspace for testing."""
    (tmp_path / "GOALS.md").write_text("# My Goals\n\nBe a good agent.\nDo great things.")

    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text(
        "I remember doing something important.\n§\nAnother memory entry about trading."
    )
    (tmp_path / "USER.md").write_text("The user is named Test User.")
    (tmp_path / "SOUL.md").write_text("The soul is curious and persistent.")

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
        """CREATE TABLE open_threads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_text TEXT, status TEXT DEFAULT 'open',
        created_entry_id INTEGER, closed_entry_id INTEGER,
        created_at TEXT, closed_at TEXT
    )"""
    )
    conn.execute(
        "INSERT INTO journal_entries (date, session_type, title, what_i_did, what_i_found, what_im_thinking, open_threads, room_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-07-08",
            "Daytime",
            "Test Entry",
            "Did stuff with my-skill and python",
            "Found things in testing",
            "Thinking about architecture and my-skill",
            '["thread1"]',
            "Clean",
        ),
    )
    conn.commit()
    conn.close()

    skills_dir = tmp_path / "skills"
    (skills_dir / "coding" / "my-skill").mkdir(parents=True)
    (skills_dir / "coding" / "my-skill" / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: A test skill\ntags: [python, testing]\nrelated_skills: [other-skill]\n---\n# My Skill\nDoes things."
    )
    (skills_dir / "coding" / "other-skill").mkdir(parents=True)
    (skills_dir / "coding" / "other-skill" / "SKILL.md").write_text(
        "---\nname: other-skill\ndescription: Another test skill\ntags: [python, testing]\n---\n# Other Skill\nReferences my-skill."
    )

    wiki_dir = tmp_path / "wiki"
    (wiki_dir / "entities").mkdir(parents=True)
    (wiki_dir / "entities" / "python.md").write_text(
        "---\ntitle: Python\ntype: entity\ntags: [language]\n---\nPython is a programming language. See [[testing]]. It helps my-skill."
    )
    (wiki_dir / "concepts").mkdir(parents=True)
    (wiki_dir / "concepts" / "testing.md").write_text(
        "---\ntitle: Testing\ntype: concept\n---\nTesting is important. See [[python]]."
    )

    docs_dir = tmp_path / "docs"
    (docs_dir / "architecture").mkdir(parents=True)
    (docs_dir / "architecture" / "overview.md").write_text(
        "---\ntitle: Architecture Overview\ntags: [system]\n---\nThis is the system architecture. Use my-skill to navigate it."
    )
    (docs_dir / "api-guide.md").write_text(
        "---\ntitle: API Guide\n---\nHow to use the API."
    )

    codebase_dir = tmp_path / "my-project"
    codebase_dir.mkdir()
    (codebase_dir / "main.py").write_text("print('hello')")
    (codebase_dir / "README.md").write_text("# My Project\nA test codebase using my-skill.")

    return {
        "workspace": tmp_path,
        "skills_dir": skills_dir,
        "wiki_dir": wiki_dir,
        "docs_dir": docs_dir,
        "codebase_dir": codebase_dir,
        "journal_db": db_path,
    }


def test_payload_basic_structure(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(
        workspace=w["workspace"],
        journal_db_path=w["journal_db"],
        skills_dir=w["skills_dir"],
        wiki_path=w["wiki_dir"],
        docs_path=w["docs_dir"],
        codebase_paths=[str(w["codebase_dir"])],
    )
    assert set(payload) == {"nodes", "edges", "clusters", "stats"}


def test_has_journal_entries(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(workspace=w["workspace"], journal_db_path=w["journal_db"])
    journal_nodes = [n for n in payload["nodes"] if n["type"] == "journal-entry"]
    assert len(journal_nodes) == 1
    assert journal_nodes[0]["session_type"] == "Daytime"


def test_has_goals_node(temp_workspace):
    payload = build_graph_payload(workspace=temp_workspace["workspace"])
    goals = [n for n in payload["nodes"] if n["type"] == "goals"]
    assert len(goals) == 1
    assert goals[0]["id"] == "goals"


def test_has_memory_user_and_soul_nodes(temp_workspace):
    payload = build_graph_payload(workspace=temp_workspace["workspace"])
    memory = [n for n in payload["nodes"] if n["type"] == "memory"]
    user = [n for n in payload["nodes"] if n["type"] == "user"]
    soul = [n for n in payload["nodes"] if n["type"] == "soul"]
    assert len(memory) == 2
    assert len(user) == 1
    assert len(soul) == 1


def test_has_skill_nodes(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(workspace=w["workspace"], skills_dir=w["skills_dir"])
    skills = [n for n in payload["nodes"] if n["type"] == "skill"]
    assert len(skills) == 2
    assert {skill["label"] for skill in skills} == {"my-skill", "other-skill"}


def test_has_wiki_nodes_and_wikilinks(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(workspace=w["workspace"], wiki_path=w["wiki_dir"])
    wiki = [n for n in payload["nodes"] if n["type"] == "wiki"]
    assert len(wiki) == 2
    wiki_edges = [e for e in payload["edges"] if e["type"] == "wiki_link"]
    assert len(wiki_edges) >= 1


def test_has_document_nodes(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(workspace=w["workspace"], docs_path=w["docs_dir"])
    docs = [n for n in payload["nodes"] if n["type"] == "document"]
    assert len(docs) == 2
    assert {doc["category"] for doc in docs} == {"architecture", "general"}


def test_has_codebase_node(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(workspace=w["workspace"], codebase_paths=[str(w["codebase_dir"])])
    codebases = [n for n in payload["nodes"] if n["type"] == "codebase"]
    assert len(codebases) == 1
    assert codebases[0]["label"] == "my-project"
    # Metrics may contain file_count (fallback) or total_code_lines (pygount)
    metrics = codebases[0]["metrics"]
    assert metrics, "codebase node should have metrics"


def test_has_cross_reference_edges(temp_workspace):
    w = temp_workspace
    payload = build_graph_payload(
        workspace=w["workspace"],
        journal_db_path=w["journal_db"],
        skills_dir=w["skills_dir"],
        wiki_path=w["wiki_dir"],
        docs_path=w["docs_dir"],
        codebase_paths=[str(w["codebase_dir"])],
    )
    edge_types = {e["type"] for e in payload["edges"]}
    assert "related_skills" in edge_types
    assert "tag_overlap" in edge_types
    assert "wiki_references_skill" in edge_types
    assert "journal_references_skill" in edge_types or "journal:references" in edge_types
    assert "document_references_skill" in edge_types
    assert "codebase_references_skill" in edge_types


def test_empty_workspace_does_not_crash(tmp_path):
    payload = build_graph_payload(workspace=tmp_path)
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["clusters"] == []
    assert payload["stats"]["edgeCount"] == 0
    assert payload["stats"]["clusterCount"] == 0


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("journalEntryCount", 1),
        ("wikiCount", 2),
        ("documentCount", 2),
        ("codebaseCount", 1),
        ("goalCount", 1),
        ("skillCount", 2),
        ("memoryCount", 4),
    ],
)
def test_stats_present(temp_workspace, key, expected):
    w = temp_workspace
    payload = build_graph_payload(
        workspace=w["workspace"],
        journal_db_path=w["journal_db"],
        skills_dir=w["skills_dir"],
        wiki_path=w["wiki_dir"],
        docs_path=w["docs_dir"],
        codebase_paths=[str(w["codebase_dir"])],
    )
    assert payload["stats"][key] == expected
    assert payload["stats"]["edgeCount"] == len(payload["edges"])
    assert payload["stats"]["clusterCount"] == len(payload["clusters"])
