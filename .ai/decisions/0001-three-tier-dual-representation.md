# 0001 — Three-tier architecture with dual-representation semantic tier

## Decision
Recall has three tiers:
1. **Episodic** (`brain/episodic/`) — immutable, append-only raw captures. No model call on write.
2. **Semantic** (`brain/semantic/`) — consolidated facts. **Dual representation**: plaintext
   Markdown + frontmatter is the **source of truth**; the SQLite index (`brain/.brainindex/`,
   gitignored) is a **derived, fully rebuildable view**. Never the other way around — the index
   must never hold anything not recoverable from the Markdown.
3. **Consolidation loop** (`src/consolidate/`) — offline batch process that reconciles episodic
   captures into the semantic tier.

DuckDB is named as an acceptable index backend alternative in the original framing; only SQLite
(with FTS5) is implemented and there is no current reason to add DuckDB.

## Rationale
`brain/` is the product from the user's perspective — "cat it if we vanish". The index is
disposable tooling. Proving `rm -rf brain/.brainindex && recall index build` reproduces a
query-equivalent index is a build milestone, not an assumption.

## Status in codebase — MATCHES
- `src/index/build.py` docstring: "the *only* way it gets created".
- `brain/.brainindex/` is gitignored; `tests/test_index_build.py::test_rebuild_is_query_equivalent`
  passes.
- `brain/semantic/SCHEMA.md` documents the MD frontmatter as authoritative.

## Conflicts / gaps
None. Constraint is fully reflected in code.
