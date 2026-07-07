import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "PRIMARY.template.md"
PRIMARY_FILENAME = "PRIMARY.md"
HASH_FILENAME = "PRIMARY.sha256"


def compute_hash(file_path: str) -> str:
    """Compute the SHA-256 hash of a file."""
    digest = hashlib.sha256()
    path = Path(file_path)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_hash(file_path: str, hash_path: str) -> None:
    """Write the SHA-256 hash of file_path to hash_path."""
    digest = compute_hash(file_path)
    Path(hash_path).write_text(digest + "\n", encoding="utf-8")


def verify_hash(file_path: str, hash_path: str) -> bool:
    """Verify that a file matches its stored SHA-256 hash."""
    expected = Path(hash_path).read_text(encoding="utf-8").strip()
    return compute_hash(file_path) == expected


def lock_file(file_path: str) -> None:
    """Set file permissions to read-only for all users."""
    os.chmod(file_path, 0o444)


def unlock_file(file_path: str) -> None:
    """Set file permissions to owner-writable, world-readable."""
    os.chmod(file_path, 0o644)


def setup_primary(workspace: str, human_name: str, agent_name: str) -> None:
    """Create PRIMARY.md and PRIMARY.sha256 in the target workspace and lock PRIMARY.md."""
    workspace_path = Path(workspace)
    workspace_path.mkdir(parents=True, exist_ok=True)

    created_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{AGENT_NAME}": agent_name,
        "{HUMAN_NAME}": human_name,
        "{DATE}": created_date,
        "{WORKSPACE}": str(workspace_path),
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    primary_path = workspace_path / PRIMARY_FILENAME
    hash_path = workspace_path / HASH_FILENAME

    primary_path.write_text(content, encoding="utf-8")
    write_hash(str(primary_path), str(hash_path))
    lock_file(str(primary_path))


def check_primary(workspace: str) -> dict:
    """Validate PRIMARY.md against PRIMARY.sha256 and report status."""
    workspace_path = Path(workspace)
    primary_path = workspace_path / PRIMARY_FILENAME
    hash_path = workspace_path / HASH_FILENAME

    actual_hash = compute_hash(str(primary_path))
    expected_hash = hash_path.read_text(encoding="utf-8").strip()
    return {
        "valid": actual_hash == expected_hash,
        "path": str(primary_path),
        "hash": actual_hash,
        "expected": expected_hash,
    }
