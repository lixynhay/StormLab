## Knowledge Graph Navigation (Graphify)

This repository maintains a pre-built architectural knowledge graph in `graphify-out/`.

- **Start here first:** Before running broad `grep`/`glob` searches or reading multiple files to understand architecture, dependencies, or data flows, read `graphify-out/GRAPH_REPORT.md` (specifically the **God Nodes** and **Community** sections) to locate relevant modules.
- **Querying the graph:** Use CLI commands via bash tool for targeted structural lookups instead of full-file reads:
  - `graphify query "<question>"` — traverse relationships and find context around a topic.
  - `graphify explain "<NodeName>"` — inspect a specific class, function, or module and its direct neighbors.
  - `graphify path "<NodeA>" "<NodeB>"` — trace how two components connect.
- **Freshness check:** If `graphify-out/needs_update` exists (meaning docs or images changed since the last semantic build), notify the user or run `/graphify . --update` if documentation context is critical for the current task.
- **Ignore build artifacts:** Do not manually read or edit `graphify-out/graph.json` directly (it is large and auto-managed by git hooks); rely on `GRAPH_REPORT.md` and the `graphify` CLI commands above.

## Tooling policy (uv and layered checks)

- **Replacement rule:** replace a tool only when the new one is a strict superset. `uv ⊃ pip` (same install/resolve interface plus environment and interpreter management) → the project uses `uv venv`, `uv pip install --no-build` and `uv run`; bare `pip`/`venv` are legacy.
- **Complement rule:** `pytest` is the test runner, not a competing tool. Hypothesis (properties), mypy (types), bandit (security), vulture (dead code), pip-audit (CVEs), ruff (lint) and xdist (parallel execution) cover different axes — they complement pytest, they never replace it.
- **Lockfile trade-off:** this repository intentionally does **not** commit `uv.lock`. The source of truth is `requirements.txt` (runtime) + `requirements-dev.txt` (dev), so Dependabot's pip ecosystem can keep opening update PRs for both. Deterministic production pinning with `uv.lock` is a separate future decision; when adopted, disable Dependabot-for-pip and move updates to `uv lock --upgrade-package X` in CI.
- Environments: `uv venv --python 3.12`, `uv pip install --no-build -r requirements.txt [-r requirements-dev.txt]`, `uv run ...`.

<!-- agents:start -->

## Subagents (portable)

Canonical bodies live in `agents/` and are the single source of truth:

- [architect](agents/architect.md) — read-only analysis and step-by-step plans.
- [coder](agents/coder.md) — implementation and tests after an approved plan.
- [reviewer](agents/reviewer.md) — read-only audit and verdict.

Shared guardrails: [skills/stormlab-dev.md](skills/stormlab-dev.md).
Model selection is delegated to the provider/router on the API side — there is no `model` field and no models.json.

Workflow: **architect → coder → reviewer**. The architect must finish and get the plan approved before the coder writes code; the coder commits only after tests pass; the reviewer audits the diff and returns APPROVE or REQUEST CHANGES.

Regenerate the platform adapters with `python scripts/sync_agents.py` after editing any file in `agents/`. Do not edit `.claude/agents/*.md` or `.opencode/agent/*.md` by hand.
<!-- agents:end -->
