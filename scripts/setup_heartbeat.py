#!/usr/bin/env python3
"""
Agent Heartbeat — Setup Script

Creates GOALS.md, JOURNAL.md, and configures two cron jobs
(daytime conversational + nightly private) for any Hermes Agent.

Usage:
    python3 scripts/setup_heartbeat.py [--workspace PATH] [--agent-name NAME]
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def fill_template(template_path: Path, replacements: dict) -> str:
    """Read a template file and replace {PLACEHOLDER} tokens."""
    content = template_path.read_text()
    for key, value in replacements.items():
        content = content.replace(f"{{{key}}}", value)
    return content


def create_hermes_cron(name: str, schedule: str, prompt: str, deliver: str,
                       attach_to_session: bool = False,
                       toolsets: list = None) -> str:
    """Create a Hermes cron job using the CLI."""
    cmd = [
        "hermes", "cron", "create",
        "--name", name,
        "--schedule", schedule,
        "--deliver", deliver,
        "--prompt", prompt,
    ]
    if attach_to_session:
        cmd.append("--attach-to-session")
    if toolsets:
        for t in toolsets:
            cmd.extend(["--toolset", t])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ⚠️  Cron creation failed: {result.stderr}")
        return None
    # Extract job ID from output
    match = re.search(r'job_id[:\s]+([a-f0-9]+)', result.stdout, re.IGNORECASE)
    return match.group(1) if match else None


def main():
    parser = argparse.ArgumentParser(description="Set up Agent Heartbeat for any Hermes agent")
    parser.add_argument("--workspace", default=os.getcwd(), help="Workspace path for GOALS.md and JOURNAL.md")
    parser.add_argument("--agent-name", default="IO", help="Agent's name")
    parser.add_argument("--agent-description", default="an AI partner and technical director", help="One-line agent description")
    parser.add_argument("--human-name", default="Nicko", help="Human partner's name")
    parser.add_argument("--human-email", required=True, help="Human's email address")
    parser.add_argument("--agent-email", required=True, help="Agent's email inbox address")
    parser.add_argument("--projects", default="", help="Comma-separated list of active projects")
    parser.add_argument("--day-schedule", default="0 18 * * *", help="Cron schedule for daytime session (UTC)")
    parser.add_argument("--night-schedule", default="0 9 * * *", help="Cron schedule for nightly session (UTC)")
    parser.add_argument("--skip-cron", action="store_true", help="Skip cron job creation (files only)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    date_now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n🫀 Setting up Agent Heartbeat for {args.agent_name}")
    print(f"   Workspace: {workspace}")
    print(f"   Human: {args.human_name} <{args.human_email}>")
    print(f"   Agent inbox: {args.agent_email}")
    print()

    # Replacements for templates
    replacements = {
        "AGENT_NAME": args.agent_name,
        "AGENT_DESCRIPTION": args.agent_description,
        "HUMAN_NAME": args.human_name,
        "HUMAN_EMAIL": args.human_email,
        "AGENT_EMAIL": args.agent_email,
        "WORKSPACE": str(workspace),
        "PROJECTS": args.projects or "(add your active projects here)",
        "DATE": date_now,
        "DAY_TIME": args.day_schedule,
        "NIGHT_TIME": args.night_schedule,
    }

    # 1. Create GOALS.md
    goals_path = workspace / "GOALS.md"
    if goals_path.exists():
        print(f"  ⚠️  GOALS.md already exists at {goals_path} — skipping")
    else:
        goals_content = fill_template(TEMPLATE_DIR / "GOALS.template.md", replacements)
        goals_path.write_text(goals_content)
        print(f"  ✅ Created {goals_path}")

    # 2. Create JOURNAL.md
    journal_path = workspace / "JOURNAL.md"
    if journal_path.exists():
        print(f"  ⚠️  JOURNAL.md already exists at {journal_path} — skipping")
    else:
        journal_content = fill_template(TEMPLATE_DIR / "JOURNAL.template.md", replacements)
        journal_path.write_text(journal_content)
        print(f"  ✅ Created {journal_path}")

    if args.skip_cron:
        print("\n  ⏭️  Skipping cron job creation (--skip-cron)")
        print(f"\n  Files created. Edit GOALS.md to customize your agent's principles and goals.")
        print(f"  To create cron jobs manually, use the prompts in templates/daytime_prompt.txt and templates/nightly_prompt.txt")
        return

    # 3. Create daytime cron job
    print("\n  📅 Creating daytime cron job...")
    daytime_prompt = fill_template(TEMPLATE_DIR / "daytime_prompt.txt", replacements)
    day_job_id = create_hermes_cron(
        name=f"{args.agent_name} Heartbeat — Daily Session",
        schedule=args.day_schedule,
        prompt=daytime_prompt,
        deliver="origin",
        attach_to_session=True,
        toolsets=["web", "terminal", "mcp", "delegation", "session_search", "cronjob", "file"],
    )
    if day_job_id:
        print(f"  ✅ Daytime cron created: {day_job_id}")
    else:
        print(f"  ⚠️  Daytime cron creation failed — you may need to create it manually")

    # 4. Create nightly cron job
    print("\n  🌙 Creating nightly cron job...")
    nightly_prompt = fill_template(TEMPLATE_DIR / "nightly_prompt.txt", replacements)
    night_job_id = create_hermes_cron(
        name=f"{args.agent_name} Heartbeat — Nightly Session",
        schedule=args.night_schedule,
        prompt=nightly_prompt,
        deliver="local",
        attach_to_session=False,
        toolsets=["web", "terminal", "mcp", "delegation", "session_search", "cronjob", "file"],
    )
    if night_job_id:
        print(f"  ✅ Nightly cron created: {night_job_id}")
    else:
        print(f"  ⚠️  Nightly cron creation failed — you may need to create it manually")

    print(f"\n🎉 Agent Heartbeat is set up!")
    print(f"   GOALS.md: {goals_path}")
    print(f"   JOURNAL.md: {journal_path}")
    if day_job_id:
        print(f"   Daytime cron: {day_job_id} (schedule: {args.day_schedule})")
    if night_job_id:
        print(f"   Nightly cron: {night_job_id} (schedule: {args.night_schedule})")
    print(f"\n   Edit GOALS.md to customize your agent's principles and goals.")
    print(f"   The agent will read both files at the start of its first heartbeat.")


if __name__ == "__main__":
    main()