"""Tests for the setup_heartbeat.py script.

Verifies that the setup script correctly creates GOALS.md, JOURNAL.md,
and PRIMARY.md (with hash + read-only permissions) in a target workspace.
"""

import importlib.util
import stat
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "setup_heartbeat.py"
SPEC = importlib.util.spec_from_file_location("setup_heartbeat", MODULE_PATH)
setup_heartbeat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup_heartbeat)

# Also load primary_guard for verification
GUARD_PATH = Path(__file__).resolve().parent.parent / "scripts" / "primary_guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("primary_guard", GUARD_PATH)
primary_guard = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(primary_guard)


def test_fill_template_replaces_all_placeholders(tmp_path):
    """fill_template replaces every {PLACEHOLDER} token."""
    template = tmp_path / "test.txt"
    template.write_text("Hello {NAME}, your workspace is {WORKSPACE}.")
    result = setup_heartbeat.fill_template(
        template, {"NAME": "IO", "WORKSPACE": "/workspace"}
    )
    assert result == "Hello IO, your workspace is /workspace."
    assert "{" not in result


def test_fill_template_leaves_unmatched_placeholders(tmp_path):
    """Unmatched {PLACEHOLDER} tokens are left as-is."""
    template = tmp_path / "test.txt"
    template.write_text("Hello {NAME}, {UNKNOWN} stays.")
    result = setup_heartbeat.fill_template(template, {"NAME": "IO"})
    assert "{UNKNOWN}" in result


def test_setup_creates_goals_journal_and_primary(tmp_path, monkeypatch):
    """The full setup flow (with --skip-cron) creates all three files."""
    # Simulate: python3 scripts/setup_heartbeat.py --workspace <tmp> --skip-cron \
    #   --human-email test@example.com --agent-email agent@inbox.com
    monkeypatch.setattr(
        sys, "argv",
        [
            "setup_heartbeat.py",
            "--workspace", str(tmp_path),
            "--skip-cron",
            "--human-email", "test@example.com",
            "--agent-email", "agent@inbox.com",
            "--agent-name", "TestAgent",
            "--human-name", "TestHuman",
            "--projects", "Project A, Project B",
        ],
    )
    setup_heartbeat.main()

    goals = tmp_path / "GOALS.md"
    journal = tmp_path / "JOURNAL.md"
    primary = tmp_path / "PRIMARY.md"
    hash_file = tmp_path / "PRIMARY.sha256"

    assert goals.exists(), "GOALS.md was not created"
    assert journal.exists(), "JOURNAL.md was not created"
    assert primary.exists(), "PRIMARY.md was not created"
    assert hash_file.exists(), "PRIMARY.sha256 was not created"

    goals_content = goals.read_text()
    assert "TestAgent" in goals_content
    assert "TestHuman" in goals_content
    assert "{AGENT_NAME}" not in goals_content
    assert "{HUMAN_NAME}" not in goals_content

    journal_content = journal.read_text()
    assert "TestAgent" in journal_content
    assert "TestHuman" in journal_content

    primary_content = primary.read_text()
    assert "TestAgent" in primary_content
    assert "TestHuman" in primary_content
    assert "{AGENT_NAME}" not in primary_content
    assert "{HUMAN_NAME}" not in primary_content


def test_setup_makes_primary_read_only(tmp_path, monkeypatch):
    """PRIMARY.md is set to read-only (0o444) after setup."""
    monkeypatch.setattr(
        sys, "argv",
        [
            "setup_heartbeat.py",
            "--workspace", str(tmp_path),
            "--skip-cron",
            "--human-email", "test@example.com",
            "--agent-email", "agent@inbox.com",
        ],
    )
    setup_heartbeat.main()

    mode = stat.S_IMODE((tmp_path / "PRIMARY.md").stat().st_mode)
    assert mode == 0o444, f"PRIMARY.md should be 0o444, got {oct(mode)}"


def test_setup_primary_hash_is_valid(tmp_path, monkeypatch):
    """The hash file matches PRIMARY.md after setup."""
    monkeypatch.setattr(
        sys, "argv",
        [
            "setup_heartbeat.py",
            "--workspace", str(tmp_path),
            "--skip-cron",
            "--human-email", "test@example.com",
            "--agent-email", "agent@inbox.com",
        ],
    )
    setup_heartbeat.main()

    result = primary_guard.check_primary(str(tmp_path))
    assert result["valid"] is True
    assert result["hash"] == result["expected"]


def test_setup_skips_existing_files(tmp_path, monkeypatch, capsys):
    """Setup does not overwrite existing GOALS.md or JOURNAL.md."""
    # Pre-create GOALS.md with custom content
    (tmp_path / "GOALS.md").write_text("# My Custom Goals")

    monkeypatch.setattr(
        sys, "argv",
        [
            "setup_heartbeat.py",
            "--workspace", str(tmp_path),
            "--skip-cron",
            "--human-email", "test@example.com",
            "--agent-email", "agent@inbox.com",
        ],
    )
    setup_heartbeat.main()

    # GOALS.md should still have the custom content
    assert (tmp_path / "GOALS.md").read_text() == "# My Custom Goals"
    # JOURNAL.md and PRIMARY.md should be created
    assert (tmp_path / "JOURNAL.md").exists()
    assert (tmp_path / "PRIMARY.md").exists()


def test_setup_preserves_primary_if_exists(tmp_path, monkeypatch):
    """Setup does not overwrite existing PRIMARY.md."""
    # Pre-create PRIMARY.md
    primary_path = tmp_path / "PRIMARY.md"
    primary_path.write_text("# Custom Primary")
    hash_path = tmp_path / "PRIMARY.sha256"
    hash_path.write_text(primary_guard.compute_hash(str(primary_path)) + "\n")

    monkeypatch.setattr(
        sys, "argv",
        [
            "setup_heartbeat.py",
            "--workspace", str(tmp_path),
            "--skip-cron",
            "--human-email", "test@example.com",
            "--agent-email", "agent@inbox.com",
        ],
    )
    setup_heartbeat.main()

    # PRIMARY.md should still have the custom content
    assert primary_path.read_text() == "# Custom Primary"
    # GOALS.md and JOURNAL.md should be created
    assert (tmp_path / "GOALS.md").exists()
    assert (tmp_path / "JOURNAL.md").exists()