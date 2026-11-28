## Knowledge Graph Navigation (Graphify)

This repository maintains a pre-built architectural knowledge graph in `graphify-out/`.

- **Start here first:** Before running broad `grep`/`glob` searches or reading multiple files to understand architecture, dependencies, or data flows, read `graphify-out/GRAPH_REPORT.md` (specifically the **God Nodes** and **Community** sections) to locate relevant modules.
- **Querying the graph:** Use CLI commands via bash tool for targeted structural lookups instead of full-file reads:
  - `graphify query "<question>"` — traverse relationships and find context around a topic.
  - `graphify explain "<NodeName>"` — inspect a specific class, function, or module and its direct neighbors.
  - `graphify path "<NodeA>" "<NodeB>"` — trace how two components connect.
- **Freshness check:** If `graphify-out/needs_update` exists (meaning docs or images changed since the last semantic build), notify the user or run `/graphify . --update` if documentation context is critical for the current task.
- **Ignore build artifacts:** Do not manually read or edit `graphify-out/graph.json` directly (it is large and auto-managed by git hooks); rely on `GRAPH_REPORT.md` and the `graphify` CLI commands above.

<!-- agents:start -->

## Subagents (portable)

Canonical bodies live in `agents/` and are the single source of truth:

- [architect](agents/architect.md) — read-only analysis and step-by-step plans (`tier: strong`).
- [coder](agents/coder.md) — implementation and tests after an approved plan (`tier: fast`).
- [reviewer](agents/reviewer.md) — read-only audit and verdict (`tier: strong`).

Shared guardrails: [skills/stormlab-dev.md](skills/stormlab-dev.md).
Model mapping: [agents/models.json](agents/models.json) (Claude: opus/sonnet; OpenCode: placeholders to be filled).

Workflow: **architect → coder → reviewer**. The architect must finish and get the plan approved before the coder writes code; the coder commits only after tests pass; the reviewer audits the diff and returns APPROVE or REQUEST CHANGES.

Regenerate the platform adapters with `python scripts/sync_agents.py` after editing any file in `agents/`. Do not edit `.claude/agents/*.md` or `.opencode/agent/*.md` by hand.
<!-- agents:end -->
