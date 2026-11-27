## Knowledge Graph Navigation (Graphify)

This repository maintains a pre-built architectural knowledge graph in `graphify-out/`.

- **Start here first:** Before running broad `grep`/`glob` searches or reading multiple files to understand architecture, dependencies, or data flows, read `graphify-out/GRAPH_REPORT.md` (specifically the **God Nodes** and **Community** sections) to locate relevant modules.
- **Querying the graph:** Use CLI commands via bash tool for targeted structural lookups instead of full-file reads:
  - `graphify query "<question>"` — traverse relationships and find context around a topic.
  - `graphify explain "<NodeName>"` — inspect a specific class, function, or module and its direct neighbors.
  - `graphify path "<NodeA>" "<NodeB>"` — trace how two components connect.
- **Freshness check:** If `graphify-out/needs_update` exists (meaning docs or images changed since the last semantic build), notify the user or run `/graphify . --update` if documentation context is critical for the current task.
- **Ignore build artifacts:** Do not manually read or edit `graphify-out/graph.json` directly (it is large and auto-managed by git hooks); rely on `GRAPH_REPORT.md` and the `graphify` CLI commands above.
