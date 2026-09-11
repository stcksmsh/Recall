"""Read-only session-start context (decision 0006 / BUILD_PLAN.md §4 boundary).

Every other path into src/inject/ goes through src/retrieve/pipeline.py, which rebuilds the
derived index first (a write to brain/.brainindex/, cheap but real) and runs a query. A
session-start hook must not do either: no query yet to run, and no write is acceptable on a path
an agent's session boots through. So this reads brain/semantic/facts/ Markdown directly — no
SQLite index, no build(), no model or network call anywhere in this module.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from src.inject.format import format_facts
from src.retrieve.hybrid import RetrievedFact

from src.config import BRAIN_ROOT


def active_facts(*, brain_root: Path = BRAIN_ROOT) -> list[RetrievedFact]:
    """Every semantic fact not yet invalidated. Path order (stable) — nothing here is scored or
    ranked; that's what the query-time retrieve path is for."""
    facts_dir = brain_root / "semantic" / "facts"
    if not facts_dir.exists():
        return []
    out = []
    for path in sorted(facts_dir.rglob("*.md")):
        post = frontmatter.load(path)
        if post.get("invalid_at"):
            continue
        out.append(RetrievedFact(
            id=post.get("id"), body=post.content, score=0.0,
            valid_at=post.get("valid_at"), scope=post.get("scope"),
        ))
    return out


def render_for_session(*, brain_root: Path = BRAIN_ROOT, repo_root: Path | None = None) -> str:
    """The full injection-formatted context for a fresh session: every active fact, XML-tagged
    and authority-framed, exactly like a retrieve result — just unfiltered by any query.

    repo_root defaults to brain_root, not cwd: brain/ is its own git repo (split out per
    .ai/decisions/0009), so that's where the provenance commit hash actually comes from."""
    return format_facts(active_facts(brain_root=brain_root), repo_root=repo_root or brain_root)
