"""Standalone memory graph payload builder for agent-heartbeat.

Builds a graph payload from local workspace files with zero Hermes dependencies.
Supported sources:
- journal.db journal entries
- GOALS.md
- MEMORY.md / USER.md / SOUL.md
- skills directories containing SKILL.md
- wiki directories containing entities/concepts/comparisons/queries
- docs directories containing markdown files
- codebase directories summarized into single nodes
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EXCLUDED_SKILL_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
_JOURNAL_CLUSTER_ID = "journal-chain"
_JOURNAL_CLUSTER_COLOR = "#10b981"
_JOURNAL_STOP_WORDS = {
    "about", "after", "again", "agent", "agents", "also", "been", "being", "both",
    "clean", "created", "create", "could", "daily", "deep", "did", "does", "doing",
    "down", "each", "entry", "ever", "every", "file", "files", "first", "from",
    "have", "into", "just", "journal", "keep", "left", "like", "made", "make",
    "memory", "more", "most", "next", "nightly", "open", "other", "over", "pick",
    "room", "same", "session", "sessions", "should", "some", "something", "start",
    "started", "still", "system", "than", "that", "their", "them", "then", "there",
    "these", "they", "this", "thread", "threads", "time", "today", "want", "what",
    "when", "where", "which", "will", "with", "work", "workspace", "would", "your",
}


def _memory_graph_top_level_category(
    skill_md: Path, search_dirs: list[Path], local_skills_dir: Path | None
) -> str:
    """Return a clustering key for a skill path, never None."""
    for search_dir in search_dirs:
        try:
            rel_parts = skill_md.relative_to(search_dir).parts
        except ValueError:
            continue
        if len(rel_parts) >= 2:
            return rel_parts[0]
        if local_skills_dir is not None and search_dir != local_skills_dir:
            return search_dir.name
        return "uncategorized"
    return "uncategorized"


def _memory_graph_normalize_name(value: str) -> str:
    return re.sub(r"[-_\s]+", "", str(value or "").lower())


def _memory_graph_classify_entry(text: str) -> str:
    keyword_clusters = (
        ("identity", ("identity", "who i am", "name is", "my role", "i am a")),
        ("preferences", ("prefer", "favorite", "dislike", "style", "tone")),
        ("workflows", ("workflow", "process", "procedure", "step-by-step", "steps to")),
        ("invariants", ("always ", "never ", "must ", "invariant", "rule:")),
        ("deployment", ("deploy", "production", "release", "docker", "server")),
        ("troubleshooting", ("bug", "error", "fix", "issue", "debug", "troubleshoot")),
        ("trade-system", ("trade", "trading", "position", "strategy", "order book", "market")),
    )
    lowered = text.lower()
    for cluster_id, keywords in keyword_clusters:
        if any(keyword in lowered for keyword in keywords):
            return cluster_id
    return "general"


def _memory_graph_cluster_label(cluster_id: str) -> str:
    if cluster_id == "user-profile":
        return "User Profile"
    if cluster_id == "soul":
        return "Soul"
    if cluster_id == "goals":
        return "Goals"
    if cluster_id == "codebases":
        return "Codebases"
    if cluster_id.startswith("skill-cat:") or cluster_id.startswith("memory-cat:"):
        return cluster_id.split(":", 1)[1]
    if cluster_id.startswith("doc-cat:"):
        return f"Docs: {cluster_id.split(':', 1)[1]}"
    if cluster_id.startswith("wiki-type:"):
        return f"Wiki: {cluster_id.split(':', 1)[1]}"
    return cluster_id


def _memory_graph_hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    s = saturation / 100.0
    l = lightness / 100.0
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((hue / 60.0) % 2 - 1))
    m = l - c / 2
    if hue < 60:
        r, g, b = c, x, 0.0
    elif hue < 120:
        r, g, b = x, c, 0.0
    elif hue < 180:
        r, g, b = 0.0, c, x
    elif hue < 240:
        r, g, b = 0.0, x, c
    elif hue < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    r, g, b = (round((v + m) * 255) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _parse_frontmatter_standalone(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Uses PyYAML if available, falls back to a simple parser.
    """
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm_text = parts[1].strip()
    try:
        import yaml  # type: ignore

        fm = yaml.safe_load(fm_text) or {}
    except ImportError:
        fm = _simple_frontmatter_parse(fm_text)
    except Exception:
        fm = {}
    return fm if isinstance(fm, dict) else {}, parts[2]


def _simple_frontmatter_parse(text: str) -> dict:
    """Minimal YAML-like parser for frontmatter when PyYAML is unavailable.

    Handles:
    - Simple key: value pairs
    - Bracketed lists: key: [item, item]
    - Indented list items: key:\\n  - item
    - One level of nested dict: key:\\n  subkey: value

    For deeper nesting (metadata.hermes.tags), install PyYAML:
        pip install pyyaml
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level key
        if not raw_line.startswith((" ", "\t")) and ":" in raw_line:
            key, _, val = raw_line.strip().partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                # Could be nested dict or list — collect indented lines
                nested: dict[str, Any] = {}
                nested_list: list[str] = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if not next_line.strip():
                        j += 1
                        continue
                    if not next_line.startswith((" ", "\t")):
                        break  # back to top level
                    stripped = next_line.strip()
                    if stripped.startswith("- "):
                        nested_list.append(stripped[2:].strip().strip('"').strip("'"))
                        j += 1
                        continue
                    # Nested key: value (one level deep)
                    if ":" in stripped:
                        nkey, _, nval = stripped.partition(":")
                        nkey = nkey.strip()
                        nval = nval.strip()
                        if nval.startswith("[") and nval.endswith("]"):
                            inner = nval[1:-1].strip()
                            nested[nkey] = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()] if inner else []
                        elif nval.lower() in {"true", "false"}:
                            nested[nkey] = nval.lower() == "true"
                        elif nval:
                            nested[nkey] = nval.strip('"').strip("'")
                        else:
                            # No value — try collecting list items below
                            sub_list: list[str] = []
                            k = j + 1
                            while k < len(lines):
                                if not lines[k].strip():
                                    k += 1
                                    continue
                                if not lines[k].startswith((" ", "\t")):
                                    break
                                # Only collect items that are more indented than nkey's line
                                if lines[k].strip().startswith("- "):
                                    sub_list.append(lines[k].strip()[2:].strip().strip('"').strip("'"))
                                    k += 1
                                else:
                                    break
                            nested[nkey] = sub_list if sub_list else {}
                        j += 1
                if nested:
                    result[key] = nested
                elif nested_list:
                    result[key] = nested_list
                else:
                    result[key] = []
                i = j
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                result[key] = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()] if inner else []
                i += 1
            elif val.lower() in {"true", "false"}:
                result[key] = val.lower() == "true"
                i += 1
            else:
                result[key] = val.strip('"').strip("'")
                i += 1
        else:
            i += 1
    return result


def _parse_tags_standalone(value: Any) -> list[str]:
    """Parse tags from frontmatter — accepts list or comma-separated string."""
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        return [t.strip().strip('"').strip("'") for t in stripped.split(",") if t.strip()]
    return []


def _iter_skill_files(skills_dir: str | Path, max_depth: int = 5):
    """Walk a directory for SKILL.md files."""
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return
    for skill_md in skills_dir.rglob("SKILL.md"):
        if any(part in _EXCLUDED_SKILL_DIRS for part in skill_md.parts):
            continue
        try:
            rel = skill_md.relative_to(skills_dir)
        except ValueError:
            continue
        if len(rel.parts) - 1 > max_depth:
            continue
        yield skill_md


def _skill_category_from_path_standalone(skill_md: Path, skills_dir: Path) -> str:
    """Determine skill category from directory structure."""
    try:
        rel = skill_md.relative_to(skills_dir)
        if len(rel.parts) > 1:
            return rel.parts[0]
    except ValueError:
        pass
    return "general"


def _skill_top_category(skill_md: Path, skills_dir: Path) -> str:
    """Determine top-level category for clustering."""
    try:
        rel = skill_md.relative_to(skills_dir)
        if len(rel.parts) > 2:
            return rel.parts[0] + "/" + rel.parts[1]
        elif len(rel.parts) > 1:
            return rel.parts[0]
    except ValueError:
        pass
    return "general"


def _truncate_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _extract_significant_words(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text.lower()):
        normalized = word.strip("_-")
        if len(normalized) < 4 or normalized in _JOURNAL_STOP_WORDS:
            continue
        words.add(normalized)
    return words


def _parse_open_threads(entry_body: str) -> list[str]:
    lines = entry_body.splitlines()
    collected: list[str] = []
    collecting = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if collecting:
                continue
            continue

        heading_match = re.match(r"^(?:\*\*)?Open threads[^:]*:(?:\*\*)?\s*(.*)$", line, re.IGNORECASE)
        if heading_match:
            collecting = True
            inline = heading_match.group(1).strip()
            if inline:
                collected.append(inline.lstrip("-*• ").strip())
            continue

        if collecting and (line.startswith("**") or line.startswith("###") or line == "---"):
            break

        if collecting:
            collected.append(line.lstrip("-*• ").strip())

    return [item for item in collected if item]


def _detect_journal_session_type(heading_session_type: str | None, entry_text: str) -> str:
    if heading_session_type in {"Daytime", "Nightly"}:
        return heading_session_type
    if re.search(r"\[Nightly\]", entry_text, re.IGNORECASE):
        return "Nightly"
    if re.search(r"\[Daytime\]", entry_text, re.IGNORECASE):
        return "Daytime"
    return "Daytime"


def build_journal_graph_data_from_db(
    db_path: str, honcho_conclusions: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Read journal.db entries into graph nodes, chain edges, and a cluster."""
    result: dict[str, Any] = {
        "nodes": [],
        "edges": [],
        "clusters": [],
        "stats": {
            "journalEntryCount": 0,
            "journalChainEdges": 0,
        },
        "entries": [],
    }

    path = Path(db_path)
    if not path.exists():
        return result

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM journal_entries
            ORDER BY date ASC, id ASC
            """
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Failed to read journal db %s: %s", db_path, e)
        return result
    finally:
        if conn is not None:
            conn.close()

    parsed_entries: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for sort_index, row in enumerate(rows):
        row_data = dict(row)
        row_id = row_data.get("id")
        if row_id is None:
            continue

        title = str(row_data.get("title") or "").strip()
        what_i_did = str(row_data.get("what_i_did") or "").strip()
        what_i_found = str(row_data.get("what_i_found") or "").strip()
        what_im_thinking = str(row_data.get("what_im_thinking") or "").strip()
        date = str(row_data.get("date") or "").strip()
        session_type = str(row_data.get("session_type") or "Daytime").strip() or "Daytime"
        raw_open_threads = row_data.get("open_threads") or "[]"
        if isinstance(raw_open_threads, bytes):
            raw_open_threads = raw_open_threads.decode("utf-8", errors="replace")
        try:
            parsed_open_threads = json.loads(raw_open_threads)
        except (TypeError, json.JSONDecodeError):
            parsed_open_threads = []
        open_threads = [str(item).strip() for item in parsed_open_threads if str(item).strip()]
        entry_text = " ".join(filter(None, [title, what_i_did, what_i_found, what_im_thinking]))
        node_id = f"journal:entry:{row_id}"

        nodes.append(
            {
                "id": node_id,
                "type": "journal-entry",
                "label": _truncate_text(f"{date} — {title or 'Untitled'}", 50),
                "preview": entry_text[:500],
                "clusterId": _JOURNAL_CLUSTER_ID,
                "session_type": session_type,
                "date": date,
                "open_threads": open_threads,
            }
        )
        parsed_entries.append(
            {
                "id": node_id,
                "date": date,
                "session_type": session_type,
                "text": entry_text,
                "keywords": _extract_significant_words(entry_text),
                "sort_index": sort_index,
            }
        )

    parsed_entries.sort(key=lambda entry: (entry["date"], entry["sort_index"]))

    for earlier, later in zip(parsed_entries, parsed_entries[1:]):
        edges.append(
            {
                "source": earlier["id"],
                "target": later["id"],
                "type": "journal:chain",
                "weight": 3,
            }
        )

    if honcho_conclusions:
        edges.extend(build_journal_reference_edges(parsed_entries, honcho_conclusions))

    clusters = []
    if nodes:
        clusters.append(
            {
                "id": _JOURNAL_CLUSTER_ID,
                "label": "IO Journal",
                "color": _JOURNAL_CLUSTER_COLOR,
                "nodeIds": [node["id"] for node in nodes],
            }
        )

    result["nodes"] = nodes
    result["edges"] = edges
    result["clusters"] = clusters
    result["entries"] = parsed_entries
    result["stats"] = {
        "journalEntryCount": len(nodes),
        "journalChainEdges": sum(1 for edge in edges if edge.get("type") == "journal:chain"),
    }
    return result


def build_journal_reference_edges(
    journal_entries: list[dict[str, Any]], conclusion_nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build lightweight journal → conclusion reference edges via word overlap."""
    _MIN_OVERLAP = 5
    _MAX_EDGES_PER_ENTRY = 3

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    conclusion_keywords: list[tuple[str, set[str]]] = []
    for node in conclusion_nodes:
        node_id = str(node.get("id") or "")
        content = str(node.get("preview") or node.get("label") or "")
        if not node_id or not content:
            continue
        keywords = _extract_significant_words(content)
        if keywords:
            conclusion_keywords.append((node_id, keywords))

    for entry in journal_entries:
        source = str(entry.get("id") or "")
        entry_keywords = set(entry.get("keywords") or ())
        if not source or not entry_keywords:
            continue
        scored: list[tuple[int, str]] = []
        for target, target_keywords in conclusion_keywords:
            overlap = entry_keywords & target_keywords
            if len(overlap) < _MIN_OVERLAP:
                continue
            scored.append((len(overlap), target))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        for _, target in scored[:_MAX_EDGES_PER_ENTRY]:
            key = (source, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "type": "journal:references",
                    "weight": 1,
                }
            )

    return edges


def _scan_wiki_pages(wiki_path: Path) -> tuple[list[dict], list[dict], dict]:
    """Scan a wiki directory for .md pages with frontmatter."""
    wiki_type_dirs = {
        "entities": "entity",
        "concepts": "concept",
        "comparisons": "comparison",
        "queries": "query",
    }
    nodes = []
    edges = []
    meta: dict[str, dict[str, Any]] = {}

    if not wiki_path.exists():
        return nodes, edges, meta

    for dir_name, default_type in wiki_type_dirs.items():
        type_dir = wiki_path / dir_name
        if not type_dir.exists():
            continue
        for md_file in sorted(type_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")[:4000]
                frontmatter, body = _parse_frontmatter_standalone(content)
            except Exception:
                continue
            slug = md_file.stem.lower().replace(" ", "-")
            title = str(frontmatter.get("title", md_file.stem))
            wiki_type = str(frontmatter.get("type", default_type))
            tags = _parse_tags_standalone(frontmatter.get("tags", ""))
            preview = body.strip()[:300]

            cluster_id = f"wiki-type:{wiki_type}"
            nodes.append(
                {
                    "id": f"wiki:{slug}",
                    "type": "wiki",
                    "label": title[:50],
                    "preview": preview,
                    "clusterId": cluster_id,
                    "wiki_type": wiki_type,
                    "tags": tags,
                }
            )
            meta[slug] = {
                "type": wiki_type,
                "tags": tags,
                "title": title,
                "body": body,
            }

    for slug, info in meta.items():
        body = str(info.get("body") or "")
        for match in re.finditer(r"\[\[([^\]]+)\]\]", body):
            target_slug = match.group(1).strip().lower().replace(" ", "-")
            if target_slug in meta and target_slug != slug:
                edges.append(
                    {
                        "source": f"wiki:{slug}",
                        "target": f"wiki:{target_slug}",
                        "type": "wiki_link",
                        "weight": 2,
                    }
                )

    return nodes, edges, meta


def _scan_documents(docs_path: Path) -> list[dict]:
    """Scan a docs directory for .md files as document nodes."""
    nodes = []
    if not docs_path.exists():
        return nodes

    for md_file in sorted(docs_path.rglob("*.md")):
        if any(part in _EXCLUDED_SKILL_DIRS for part in md_file.parts):
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")[:4000]
            frontmatter, body = _parse_frontmatter_standalone(content)
        except Exception:
            continue

        title = str(frontmatter.get("title", md_file.stem))
        try:
            rel = md_file.relative_to(docs_path)
            category = rel.parts[0] if len(rel.parts) > 1 else "general"
        except ValueError:
            category = "general"

        slug = str(rel if 'rel' in locals() else md_file.name).replace(os.sep, "-").lower().replace(" ", "-")
        tags = _parse_tags_standalone(frontmatter.get("tags", ""))
        preview = body.strip()[:300]

        nodes.append(
            {
                "id": f"doc:{slug}",
                "type": "document",
                "label": title[:50],
                "preview": preview,
                "clusterId": f"doc-cat:{category}",
                "tags": tags,
                "category": category,
            }
        )

    return nodes


def _scan_codebase(codebase_path: Path, name: str | None = None) -> dict | None:
    """Scan a codebase directory and create a single summary node."""
    if not codebase_path.exists() or not codebase_path.is_dir():
        return None

    name = name or codebase_path.name
    metrics: dict[str, Any] = {}

    try:
        result = subprocess.run(
            ["pygount", "--format=json", str(codebase_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PATH": os.environ.get("PATH", "")},
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            total_code = 0
            languages: list[str] = []
            for entry in data:
                lang = entry.get("language", "")
                code = entry.get("code", 0)
                total_code += code
                if lang not in {"__empty__", "__binary__", "__generated__", "__duplicate__", "__unknown__"}:
                    languages.append(f"{lang} ({code})")
            metrics = {
                "total_code_lines": total_code,
                "top_languages": languages[:5],
            }
    except Exception:
        pass

    if not metrics:
        file_count = sum(
            1
            for path in codebase_path.rglob("*")
            if path.is_file() and not any(part in _EXCLUDED_SKILL_DIRS for part in path.parts)
        )
        metrics = {"file_count": file_count}

    readme_preview = ""
    for readme_name in ("README.md", "README.rst", "README.txt", "README"):
        readme_path = codebase_path / readme_name
        if readme_path.exists():
            readme_preview = readme_path.read_text(encoding="utf-8", errors="replace")[:500]
            break

    return {
        "id": f"codebase:{name}",
        "type": "codebase",
        "label": name,
        "preview": readme_preview,
        "clusterId": "codebases",
        "metrics": metrics,
        "path": str(codebase_path),
    }


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _add_cluster(clusters: list[dict], cluster_id: str, label: str, color: str, node_ids: list[str]) -> None:
    if not node_ids:
        return
    for cluster in clusters:
        if cluster["id"] == cluster_id:
            existing = list(cluster.get("nodeIds", []))
            merged = list(dict.fromkeys(existing + node_ids))
            cluster["nodeIds"] = merged
            if label:
                cluster["label"] = label
            if color:
                cluster["color"] = color
            return
    clusters.append({"id": cluster_id, "label": label, "color": color, "nodeIds": node_ids})


def _add_memory_nodes(workspace: Path, nodes: list[dict], clusters: list[dict], stats: dict) -> dict[str, str]:
    """Add MEMORY.md / USER.md / SOUL.md nodes if present."""
    mem_dir = workspace / "memories"
    mem_file = _first_existing(mem_dir / "MEMORY.md", workspace / "MEMORY.md")
    user_file = _first_existing(workspace / "USER.md", mem_dir / "USER.md")
    soul_file = _first_existing(workspace / "SOUL.md", mem_dir / "SOUL.md")

    texts: dict[str, str] = {}
    memory_family_count = 0
    memory_cluster_members: dict[str, list[str]] = defaultdict(list)

    memory_text = mem_file.read_text(encoding="utf-8", errors="replace") if mem_file else ""
    raw_entries = re.split(r"\n\s*§\s*\n", memory_text) if memory_text.strip() else []
    entries = [entry.strip() for entry in raw_entries if entry.strip()]
    for idx, entry in enumerate(entries):
        cluster_id = f"memory-cat:{_memory_graph_classify_entry(entry)}"
        memory_id = f"memory:{idx}"
        nodes.append(
            {
                "id": memory_id,
                "type": "memory",
                "label": entry[:50].strip(),
                "preview": entry[:500],
                "clusterId": cluster_id,
            }
        )
        texts[memory_id] = entry
        memory_family_count += 1
        memory_cluster_members[cluster_id].append(memory_id)

    if user_file and user_file.read_text(encoding="utf-8", errors="replace").strip():
        user_text = user_file.read_text(encoding="utf-8", errors="replace")
        nodes.append(
            {
                "id": "memory:user",
                "type": "user",
                "label": (user_text[:50].strip() or "User Profile"),
                "preview": user_text[:500],
                "clusterId": "user-profile",
            }
        )
        texts["memory:user"] = user_text
        memory_family_count += 1
        _add_cluster(clusters, "user-profile", "User Profile", "#f59e0b", ["memory:user"])

    if soul_file and soul_file.read_text(encoding="utf-8", errors="replace").strip():
        soul_text = soul_file.read_text(encoding="utf-8", errors="replace")
        nodes.append(
            {
                "id": "memory:soul",
                "type": "soul",
                "label": (soul_text[:50].strip() or "Soul"),
                "preview": soul_text[:500],
                "clusterId": "soul",
            }
        )
        texts["memory:soul"] = soul_text
        memory_family_count += 1
        _add_cluster(clusters, "soul", "Soul", "#f97316", ["memory:soul"])

    for idx, cluster_id in enumerate(sorted(memory_cluster_members)):
        color = _memory_graph_hsl_to_hex(360.0 * idx / max(1, len(memory_cluster_members)), 60.0, 50.0)
        _add_cluster(
            clusters,
            cluster_id,
            _memory_graph_cluster_label(cluster_id),
            color,
            memory_cluster_members[cluster_id],
        )

    stats["memoryCount"] = memory_family_count
    return texts


def _add_skill_nodes(skills_dir: Path, nodes: list[dict], clusters: list[dict], stats: dict) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Scan skills directory and add skill nodes/clusters."""
    if not skills_dir.exists():
        stats["skillCount"] = 0
        return {}, {}

    search_dirs = [skills_dir]
    disabled: set[str] = set()
    skill_meta: dict[str, dict[str, Any]] = {}
    skill_texts: dict[str, str] = {}
    category_members: dict[str, list[str]] = defaultdict(list)
    seen_names: set[str] = set()

    for skill_md in _iter_skill_files(skills_dir):
        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")[:6000]
            frontmatter, body = _parse_frontmatter_standalone(content)
        except Exception:
            continue
        name = str(frontmatter.get("name", skill_md.parent.name))[:64]
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        description = str(frontmatter.get("description", "") or "")
        category = _skill_category_from_path_standalone(skill_md, skills_dir)
        top_category = _memory_graph_top_level_category(skill_md, search_dirs, skills_dir)
        metadata = frontmatter.get("metadata")
        hermes_meta = metadata.get("hermes", {}) if isinstance(metadata, dict) else {}
        tags = _parse_tags_standalone(hermes_meta.get("tags") or frontmatter.get("tags", ""))
        related_skills = _parse_tags_standalone(
            hermes_meta.get("related_skills") or frontmatter.get("related_skills", "")
        )

        node = {
            "id": f"skill:{name}",
            "type": "skill",
            "label": name,
            "preview": (description or body.strip())[:300],
            "category": category,
            "tags": tags,
            "clusterId": f"skill-cat:{top_category}",
            "disabled": name in disabled,
        }
        nodes.append(node)
        skill_meta[name] = {"tags": tags, "related_skills": related_skills, "body": body, "description": description}
        skill_texts[f"skill:{name}"] = f"{name}\n{description}\n{body}".strip()
        category_members[top_category].append(name)

    total_clusters = len(category_members) or 1
    for idx, top_category in enumerate(sorted(category_members)):
        _add_cluster(
            clusters,
            f"skill-cat:{top_category}",
            _memory_graph_cluster_label(f"skill-cat:{top_category}"),
            _memory_graph_hsl_to_hex(360.0 * idx / total_clusters, 60.0, 50.0),
            [f"skill:{name}" for name in category_members[top_category]],
        )

    stats["skillCount"] = len(skill_meta)
    return skill_meta, skill_texts


def _build_cross_references(nodes: list[dict], edges: list[dict], skill_meta: dict[str, dict[str, Any]] | None = None) -> None:
    """Build cross-reference edges across node types.

    - related skill edges from frontmatter
    - skill tag overlap/category affinity
    - content mentions from memory/wiki/journal/goals/docs/codebase → skills
    """
    skill_meta = skill_meta or {}
    edge_seen = {(edge.get("type"), frozenset((edge.get("source"), edge.get("target")))) for edge in edges}

    def add_edge(source: str, target: str, edge_type: str, weight: int) -> None:
        if source == target:
            return
        key = (edge_type, frozenset((source, target)))
        if key in edge_seen:
            return
        edge_seen.add(key)
        edges.append({"source": source, "target": target, "type": edge_type, "weight": weight})

    skill_nodes = [node for node in nodes if node.get("type") == "skill"]
    normalized_to_name = {
        _memory_graph_normalize_name(node["label"]): node["label"]
        for node in skill_nodes
        if node.get("label")
    }

    def resolve_skill_name(raw: str) -> str | None:
        norm = _memory_graph_normalize_name(raw)
        if not norm:
            return None
        if norm in normalized_to_name:
            return normalized_to_name[norm]
        candidates = [
            candidate_name
            for candidate_norm, candidate_name in normalized_to_name.items()
            if norm in candidate_norm or candidate_norm in norm
        ]
        if not candidates:
            return None
        return min(candidates, key=len)

    for skill_name, meta in skill_meta.items():
        for raw_related in meta.get("related_skills", []):
            resolved = resolve_skill_name(str(raw_related))
            if resolved:
                add_edge(f"skill:{skill_name}", f"skill:{resolved}", "related_skills", 3)

    skill_names = [node["label"] for node in skill_nodes if node.get("label")]
    for i in range(len(skill_names)):
        for j in range(i + 1, len(skill_names)):
            name_a, name_b = skill_names[i], skill_names[j]
            shared_tags = set(skill_meta.get(name_a, {}).get("tags", [])) & set(skill_meta.get(name_b, {}).get("tags", []))
            if len(shared_tags) >= 2:
                add_edge(f"skill:{name_a}", f"skill:{name_b}", "tag_overlap", len(shared_tags))

    category_members: dict[str, list[str]] = defaultdict(list)
    for node in skill_nodes:
        category_members[node["clusterId"]].append(node["label"])
    for members in category_members.values():
        if not (2 <= len(members) <= 10):
            continue
        added = 0
        for i in range(len(members)):
            if added >= 10:
                break
            for j in range(i + 1, len(members)):
                if added >= 10:
                    break
                add_edge(f"skill:{members[i]}", f"skill:{members[j]}", "category", 1)
                added += 1

    skill_name_patterns = [
        (skill_name, re.compile(r"\b" + re.escape(skill_name) + r"\b", re.IGNORECASE))
        for skill_name in skill_names
    ]

    for node in nodes:
        node_type = node.get("type")
        if node_type == "skill":
            continue
        text = str(node.get("preview") or node.get("label") or "")
        if not text:
            continue
        for skill_name, pattern in skill_name_patterns:
            if pattern.search(text):
                edge_type = {
                    "memory": "memory_reference",
                    "user": "memory_reference",
                    "soul": "memory_reference",
                    "wiki": "wiki_references_skill",
                    "journal-entry": "journal_references_skill",
                    "document": "document_references_skill",
                    "codebase": "codebase_references_skill",
                    "goals": "goals_references_skill",
                }.get(node_type, "references_skill")
                weight = 2 if node_type in {"memory", "user", "soul", "journal-entry", "goals"} else 1
                add_edge(node["id"], f"skill:{skill_name}", edge_type, weight)

    content_nodes = [node for node in nodes if node.get("type") in {"journal-entry", "document", "goals", "wiki"}]
    journal_nodes = [node for node in content_nodes if node.get("type") == "journal-entry"]
    for journal_node in journal_nodes:
        journal_words = _extract_significant_words(str(journal_node.get("preview") or ""))
        if not journal_words:
            continue
        for target in content_nodes:
            if target["id"] == journal_node["id"]:
                continue
            target_words = _extract_significant_words(str(target.get("preview") or target.get("label") or ""))
            overlap = journal_words & target_words
            if len(overlap) >= 5:
                add_edge(journal_node["id"], target["id"], "journal:references", min(len(overlap), 3))


def build_graph_payload(
    workspace: str | Path,
    skills_dir: str | Path | None = None,
    wiki_path: str | Path | None = None,
    docs_path: str | Path | None = None,
    codebase_paths: list[str] | None = None,
    journal_db_path: str | Path | None = None,
) -> dict:
    """Build the complete graph payload from local files."""
    workspace = Path(workspace)
    nodes: list[dict] = []
    edges: list[dict] = []
    clusters: list[dict] = []
    stats: dict[str, Any] = {
        "skillCount": 0,
        "memoryCount": 0,
        "wikiCount": 0,
        "documentCount": 0,
        "codebaseCount": 0,
        "journalEntryCount": 0,
        "journalChainEdges": 0,
        "goalCount": 0,
    }

    if journal_db_path:
        journal_data = build_journal_graph_data_from_db(str(journal_db_path))
        nodes.extend(journal_data["nodes"])
        edges.extend(journal_data["edges"])
        clusters.extend(journal_data["clusters"])
        stats.update(journal_data["stats"])

    goals_file = workspace / "GOALS.md"
    if goals_file.exists():
        goals_text = goals_file.read_text(encoding="utf-8", errors="replace")
        nodes.append(
            {
                "id": "goals",
                "type": "goals",
                "label": "GOALS.md",
                "preview": goals_text[:500],
                "clusterId": "goals",
            }
        )
        _add_cluster(clusters, "goals", "Goals", "#fbbf24", ["goals"])
        stats["goalCount"] = 1

    _add_memory_nodes(workspace, nodes, clusters, stats)
    skill_meta: dict[str, dict[str, Any]] = {}
    if skills_dir:
        skill_meta, _skill_texts = _add_skill_nodes(Path(skills_dir), nodes, clusters, stats)

    if wiki_path:
        wiki_nodes, wiki_edges, _wiki_meta = _scan_wiki_pages(Path(wiki_path))
        nodes.extend(wiki_nodes)
        edges.extend(wiki_edges)
        wiki_types = sorted({n["wiki_type"] for n in wiki_nodes})
        wiki_colors = {"entity": "#2dd4bf", "concept": "#f472b6", "comparison": "#fbbf24", "query": "#a78bfa"}
        for wt in wiki_types:
            wt_node_ids = [n["id"] for n in wiki_nodes if n["wiki_type"] == wt]
            _add_cluster(clusters, f"wiki-type:{wt}", f"Wiki: {wt}", wiki_colors.get(wt, "#2dd4bf"), wt_node_ids)
        stats["wikiCount"] = len(wiki_nodes)

    if docs_path:
        doc_nodes = _scan_documents(Path(docs_path))
        nodes.extend(doc_nodes)
        doc_cats = sorted({n["category"] for n in doc_nodes})
        for cat in doc_cats:
            cat_ids = [n["id"] for n in doc_nodes if n["category"] == cat]
            _add_cluster(clusters, f"doc-cat:{cat}", f"Docs: {cat}", "#3b82f6", cat_ids)
        stats["documentCount"] = len(doc_nodes)

    if codebase_paths:
        cb_nodes = []
        for cb_path in codebase_paths:
            node = _scan_codebase(Path(cb_path))
            if node:
                cb_nodes.append(node)
        nodes.extend(cb_nodes)
        if cb_nodes:
            _add_cluster(clusters, "codebases", "Codebases", "#a855f7", [n["id"] for n in cb_nodes])
        stats["codebaseCount"] = len(cb_nodes)

    _build_cross_references(nodes, edges, skill_meta=skill_meta)

    stats["edgeCount"] = len(edges)
    stats["clusterCount"] = len(clusters)

    return {
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "stats": stats,
    }


__all__ = [
    "build_graph_payload",
    "build_journal_graph_data_from_db",
    "build_journal_reference_edges",
    "_parse_frontmatter_standalone",
    "_simple_frontmatter_parse",
    "_scan_wiki_pages",
    "_scan_documents",
    "_scan_codebase",
]
