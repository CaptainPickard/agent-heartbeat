import hashlib
import importlib.util
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest


MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "primary_guard.py"
SPEC = importlib.util.spec_from_file_location("primary_guard", MODULE_PATH)
primary_guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(primary_guard)


@pytest.fixture
def temp_file(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("hello world", encoding="utf-8")
    return path


def test_compute_hash_produces_correct_sha256(temp_file):
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert primary_guard.compute_hash(str(temp_file)) == expected


def test_write_hash_creates_sha256_file_with_correct_hash(tmp_path, temp_file):
    hash_path = tmp_path / "sample.sha256"
    primary_guard.write_hash(str(temp_file), str(hash_path))

    expected = hashlib.sha256(b"hello world").hexdigest()
    assert hash_path.read_text(encoding="utf-8").strip() == expected


def test_verify_hash_returns_true_for_unmodified_file(tmp_path, temp_file):
    hash_path = tmp_path / "sample.sha256"
    primary_guard.write_hash(str(temp_file), str(hash_path))

    assert primary_guard.verify_hash(str(temp_file), str(hash_path)) is True


def test_verify_hash_returns_false_for_tampered_file(tmp_path, temp_file):
    hash_path = tmp_path / "sample.sha256"
    primary_guard.write_hash(str(temp_file), str(hash_path))
    temp_file.write_text("tampered", encoding="utf-8")

    assert primary_guard.verify_hash(str(temp_file), str(hash_path)) is False


def test_lock_file_makes_file_read_only(tmp_path):
    path = tmp_path / "locked.txt"
    path.write_text("locked", encoding="utf-8")
    primary_guard.lock_file(str(path))

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o444

    if os.geteuid() == 0:
        # When running as root we can't prove the 0o444 lock blocks writes
        # directly (root bypasses file permissions), so we drop to a non-root
        # uid and try to write via a subprocess. The interpreter we spawn must
        # itself be executable by that uid — sys.executable may live under a
        # root-only path (e.g. a venv inside /root), so we probe candidate
        # interpreters as uid 65534 and use the first one that actually starts.
        candidates = [sys.executable]
        fallback = shutil.which("python3")
        if fallback and fallback != sys.executable:
            candidates.append(fallback)

        interpreter = None
        for cand in candidates:
            try:
                probe = subprocess.run(
                    [cand, "-c", "pass"],
                    capture_output=True,
                    text=True,
                    preexec_fn=lambda: (os.setgid(65534), os.setuid(65534)),
                )
            except (PermissionError, OSError):
                continue
            if probe.returncode == 0:
                interpreter = cand
                break

        if interpreter is None:
            # No usable interpreter for the dropped uid — the mode==0o444
            # assertion above already proves the lock applied correctly.
            return

        script = (
            "from pathlib import Path; "
            "Path(__import__('sys').argv[1]).write_text('should fail', encoding='utf-8')"
        )
        try:
            result = subprocess.run(
                [interpreter, "-c", script, str(path)],
                capture_output=True,
                text=True,
                preexec_fn=lambda: (os.setgid(65534), os.setuid(65534)),
            )
        except (PermissionError, OSError):
            # Interpreter became inaccessible between probe and run — the
            # mode==0o444 assertion above already proves the lock applied.
            return
        assert result.returncode != 0
        assert (
            "PermissionError" in result.stderr
            or "Permission denied" in result.stderr
            or "Errno 13" in result.stderr
        )
        return

    with pytest.raises((PermissionError, OSError)):
        path.write_text("should fail", encoding="utf-8")


def test_unlock_file_restores_writability(tmp_path):
    path = tmp_path / "unlocked.txt"
    path.write_text("content", encoding="utf-8")
    primary_guard.lock_file(str(path))
    primary_guard.unlock_file(str(path))

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o644
    path.write_text("updated", encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "updated"


def test_setup_primary_creates_primary_and_hash_with_correct_content(tmp_path):
    primary_guard.setup_primary(str(tmp_path), human_name="Human", agent_name="Agent")

    primary_path = tmp_path / "PRIMARY.md"
    hash_path = tmp_path / "PRIMARY.sha256"

    assert primary_path.exists()
    assert hash_path.exists()

    content = primary_path.read_text(encoding="utf-8")
    assert "# Agent — Primary Directives (Immutable)" in content
    assert "set by Human" in content
    assert f"*Hash: See {tmp_path}/PRIMARY.sha256*" in content
    assert "{AGENT_NAME}" not in content
    assert "{HUMAN_NAME}" not in content
    assert hash_path.read_text(encoding="utf-8").strip() == primary_guard.compute_hash(str(primary_path))


def test_setup_primary_sets_primary_read_only(tmp_path):
    primary_guard.setup_primary(str(tmp_path), human_name="Human", agent_name="Agent")

    mode = stat.S_IMODE((tmp_path / "PRIMARY.md").stat().st_mode)
    assert mode == 0o444


def test_check_primary_returns_valid_true_for_correct_setup(tmp_path):
    primary_guard.setup_primary(str(tmp_path), human_name="Human", agent_name="Agent")

    result = primary_guard.check_primary(str(tmp_path))

    assert result["valid"] is True
    assert result["path"] == str(tmp_path / "PRIMARY.md")
    assert result["hash"] == result["expected"]


def test_check_primary_returns_valid_false_after_tampering(tmp_path):
    primary_guard.setup_primary(str(tmp_path), human_name="Human", agent_name="Agent")

    primary_path = tmp_path / "PRIMARY.md"
    primary_guard.unlock_file(str(primary_path))
    primary_path.write_text("tampered", encoding="utf-8")

    result = primary_guard.check_primary(str(tmp_path))

    assert result["valid"] is False
    assert result["hash"] != result["expected"]
