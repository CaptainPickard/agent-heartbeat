# agent-heartbeat Examples

This directory contains example scripts and configurations for running an
agent heartbeat. Each example is self-contained and demonstrates a different
aspect of the heartbeat workflow.

## Examples

### `sample_heartbeat.py`

A minimal, self-contained Python script that demonstrates the core heartbeat
lifecycle:

1. **Read goals** — load a GOALS.md file for orientation
2. **Read journal** — query the SQLite journal database for open threads and
   recent entries to recover continuity
3. **Do work** — in this example, a simple placeholder. In a real deployment,
   this is where your LLM agent does its work (research, coding, reflection)
4. **Write journal entry** — persist the session's output to the journal database
5. **Export to markdown** — write the latest entry to JOURNAL.md for human inspection
6. **Clean up** — delete temp files, leave the room clean

```bash
# Run the sample heartbeat
python examples/sample_heartbeat.py \
  --db journal.db \
  --md JOURNAL.md \
  --goals GOALS.md
```

Run it twice and you'll see continuity in action — the second run sees the
open threads and journal entry from the first run.

## How to Use These Examples

1. **Copy the template files** from `templates/` to your working directory:
   ```bash
   cp templates/GOALS.template.md GOALS.md
   cp templates/JOURNAL.template.md JOURNAL.md
   ```

2. **Run the setup script** to initialize the journal database:
   ```bash
   python scripts/setup_heartbeat.py
   ```

3. **Run the sample heartbeat** to see the lifecycle in action:
   ```bash
   python examples/sample_heartbeat.py
   ```

4. **Schedule it** with cron, systemd timers, or any scheduler:
   ```bash
   # Run every hour
   0 * * * * cd /path/to/your/heartbeat && python examples/sample_heartbeat.py
   ```

5. **Replace `do_heartbeat_work()`** with your actual agent logic. This is
   where you call your LLM, use tools, do research, etc. The journal entry
   fields (`title`, `what_i_did`, `what_i_found`, `what_im_thinking`,
   `open_threads`, `room_status`) are the interface between your agent's
   work and its persistent memory.

## The Heartbeat Pattern

The heartbeat pattern is simple but powerful:

- **Goals** are the compass — they orient the agent but don't dictate actions
- **Journal** is the memory — it provides continuity across sessions
- **Open threads** are the todo list — they track ongoing work across sessions
- **The heartbeat** is the rhythm — it creates regular cycles of work and reflection

An agent without a heartbeat is stateless — it starts fresh every time.
An agent with a heartbeat has continuity, memory, and the ability to pursue
long-term goals across many sessions. That's the difference between a tool
and a partner.

## Next Steps

- Read the [main README](../README.md) for the full documentation
- Read [SECURITY.md](../templates/SECURITY.md) before deploying autonomously
- Read the [prompt templates](../templates/) for examples of how to instruct
  an LLM agent to run a heartbeat session
- Check the [specs](../specs/) directory for design documents