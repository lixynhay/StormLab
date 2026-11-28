#!/usr/bin/env python3
"""Generate platform-specific subagent definitions from portable canonical files.

Canonical sources: agents/{architect,coder,reviewer}.md (frontmatter: role + access only).
Outputs:
  .claude/agents/*.md    (Claude Code)
  .opencode/agent/*.md   (OpenCode)
  AGENTS.md              (section between <!-- agents:start --> / <!-- agents:end -->)

Model selection is intentionally not configured here: the provider/router on the
API side resolves it. No generated frontmatter contains a `model` field.

The canonical BODY is copied verbatim into every output; only frontmatter differs.
Run twice: the second run must leave the working tree unchanged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "agents"
AGENTS_MD = ROOT / "AGENTS.md"
START = "<!-- agents:start -->"
END = "<!-- agents:end -->"

# role, access, description (platform frontmatter metadata, not part of the body)
ROLES = [
    (
        "architect",
        "read-only",
        "Read-only software architect and technical planner for StormLab. Use BEFORE writing any code to explore the codebase via graphify, analyze impact, and produce a strict step-by-step PLAN.md.",
    ),
    (
        "coder",
        "write",
        "Implementation engineer for StormLab. Use AFTER a plan is approved to write clean code, update tests, and run verification checks.",
    ),
    (
        "reviewer",
        "read-only",
        "Strict code reviewer and QA critic for StormLab. Use AFTER implementation to audit git diff against SPC formula pins, async/render safety, security rules, and test coverage.",
    ),
]

CLAUDE_TOOLS = {
    "read-only": "Read, Glob, Grep, Bash",
    "write": "Read, Edit, Write, Glob, Grep, Bash",
}

OPENCODE_PERMISSIONS = {
    "read-only": (
        "tools:\n"
        "  write: false\n"
        "  edit: false\n"
        "permission:\n"
        "  edit: deny\n"
        "  bash: ask"
    ),
    "write": (
        "tools:\n"
        "  write: true\n"
        "  edit: true\n"
        "  bash: true\n"
        "permission:\n"
        "  edit: allow\n"
        "  bash: allow"
    ),
}


def canonical_body(role: str) -> str:
    """Return the canonical body exactly as stored (frontmatter stripped)."""
    path = AGENTS_DIR / f"{role}.md"
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path.relative_to(ROOT)}: missing canonical frontmatter")
    return text[match.end():]


def claude_document(role: str, access: str, description: str, body: str) -> str:
    frontmatter = (
        "---\n"
        f"name: {role}\n"
        f"description: {description}\n"
        f"tools: {CLAUDE_TOOLS[access]}\n"
        "---\n"
    )
    return frontmatter + body


def opencode_document(role: str, access: str, description: str, body: str) -> str:
    frontmatter = (
        "---\n"
        f"description: {description}\n"
        "mode: subagent\n"
        f"{OPENCODE_PERMISSIONS[access]}\n"
        "---\n"
    )
    return frontmatter + body


def agents_section() -> str:
    lines = [
        START,
        "",
        "## Subagents (portable)",
        "",
        "Canonical bodies live in `agents/` and are the single source of truth:",
        "",
        "- [architect](agents/architect.md) — read-only analysis and step-by-step plans.",
        "- [coder](agents/coder.md) — implementation and tests after an approved plan.",
        "- [reviewer](agents/reviewer.md) — read-only audit and verdict.",
        "",
        "Shared guardrails: [skills/stormlab-dev.md](skills/stormlab-dev.md).",
        "Model selection is delegated to the provider/router on the API side — there is no `model` field and no models.json.",
        "",
        "Workflow: **architect → coder → reviewer**. The architect must finish and get the plan approved before the coder writes code; the coder commits only after tests pass; the reviewer audits the diff and returns APPROVE or REQUEST CHANGES.",
        "",
        "Regenerate the platform adapters with `python scripts/sync_agents.py` after editing any file in `agents/`. Do not edit `.claude/agents/*.md` or `.opencode/agent/*.md` by hand.",
        END,
    ]
    return "\n".join(lines)


def write_if_changed(path: Path, content: str, check_only: bool) -> bool:
    """Return True if content differed (or would differ in --check mode)."""
    relative = path.relative_to(ROOT).as_posix()
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == content:
        print(f"  unchanged  {relative}")
        return False
    if check_only:
        print(f"  OUT OF DATE  {relative}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"  written    {relative}")
    return True


def sync_agents_md(section: str, check_only: bool) -> bool:
    text = AGENTS_MD.read_text(encoding="utf-8")
    if START in text and END in text:
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        updated = before + section + after
    else:
        updated = text.rstrip("\n") + "\n\n" + section + "\n"
    return write_if_changed(AGENTS_MD, updated, check_only)


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    if len(sys.argv) > 2 or (check_only and len(sys.argv) != 2):
        print("usage: python scripts/sync_agents.py [--check]", file=sys.stderr)
        return 2

    changed = False
    print("Generating platform adapters from agents/*.md ...")
    for role, access, description in ROLES:
        body = canonical_body(role)
        changed |= write_if_changed(
            ROOT / ".claude" / "agents" / f"{role}.md",
            claude_document(role, access, description, body),
            check_only,
        )
        changed |= write_if_changed(
            ROOT / ".opencode" / "agent" / f"{role}.md",
            opencode_document(role, access, description, body),
            check_only,
        )
    changed |= sync_agents_md(agents_section(), check_only)

    if check_only:
        print("CHECK: adapters are up to date" if not changed else "CHECK: adapters are stale")
        return 1 if changed else 0
    print("Done. Re-run to verify idempotency; body is identical in all outputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
