# Honcho Memory Integration (Optional)

The memory graph supports Honcho as an optional data source. Honcho is a
memory/reasoning server that stores conclusions, peers, and sessions. If you
run Honcho alongside your agent, you can add its data to the graph.

## What Honcho Adds

- **Conclusions** (small circles, amber) — persistent facts Honcho has saved
  about peers. These appear as individual nodes, colored by workspace.
- **Peers** (diamonds, purple) — hub nodes for each peer (user, AI, etc.)
- **Sessions** (squares, cyan) — Honcho session nodes
- **Observation edges** — amber-tinted edges showing which peer observed which
  conclusion
- **Cross-reference edges** — dashed blue lines connecting Honcho conclusions
  to skills they reference

## How to Add Honcho to the Graph

The core `graph_builder.py` and `graph_server.py` do not include Honcho
support. To add it:

### 1. Copy the Honcho graph module

Copy `build_honcho_graph_data()` and its helpers from the Hermes WebUI's
`api/honcho_graph.py` into a new file `scripts/honcho_graph.py` in your
agent-heartbeat installation.

### 2. Create a custom graph server wrapper

```python
#!/usr/bin/env python3
"""Custom graph server with Honcho support."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_builder import build_graph_payload
from honcho_graph import build_honcho_graph_data  # your copy

# Call build_graph_payload() as normal, then merge Honcho data:
def build_payload_with_honcho(workspace, honcho_url, honcho_workspaces, **kwargs):
    payload = build_graph_payload(workspace=workspace, **kwargs)

    honcho_data = build_honcho_graph_data(honcho_url, honcho_workspaces)
    payload["nodes"].extend(honcho_data["nodes"])
    payload["edges"].extend(honcho_data["edges"])
    payload["clusters"].extend(honcho_data["clusters"])

    # Update stats
    payload["stats"]["honchoConclusionCount"] = len(honcho_data.get("conclusions", []))
    payload["stats"]["honchoPeerCount"] = len(honcho_data.get("peers", []))

    return payload
```

### 3. Use Honcho-specific node rendering

The graph frontend already supports Honcho node types:
- `honcho-conclusion` — small amber circle
- `honcho-peer` — purple diamond
- `honcho-session` — cyan square

No frontend changes are needed — the rendering code already handles these
types. Just include them in the JSON payload and they'll appear.

### 4. Honcho API details

Honcho uses `POST` for all list endpoints with `Content-Type: application/json`
and body `{}`. Pagination via `?size=100&page=N` query params.

Key endpoints:
- `POST /v3/workspaces/{workspace}/conclusions/list`
- `POST /v3/workspaces/{workspace}/peers/list`
- `POST /v3/workspaces/{workspace}/sessions/list`

The `build_honcho_graph_data()` function handles pagination, caching, and
cross-reference edge building automatically.

### 5. Configuration

Read `honcho.json` from your Hermes home directory to get the `baseUrl` and
workspace name. Or pass them directly:

```python
honcho_data = build_honcho_graph_data(
    base_url="http://localhost:8000",
    workspaces=["my-workspace"],
)
```

## Why Honcho is Optional

Not every agent-heartbeat user runs Honcho. The core graph works perfectly
with just journal.db + GOALS.md + optional skills/wiki/docs/codebases. Honcho
adds a layer of peer-aware memory for agents that need it. Keeping it out of
the core means the graph server has zero external service dependencies —
it reads local files only.

If you don't use Honcho, you don't need to do anything. The graph works
without it.
