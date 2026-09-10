"""1-hop link expansion over the `links` field in semantic fact frontmatter.

Bounded at 1 hop per BUILD_PLAN.md §2.3 — unbounded hops amplify noise. Extend to 2 only if eval
shows it's needed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.retrieve.hybrid import RetrievedFact


def expand(index_db: Path, facts: list[RetrievedFact]) -> list[RetrievedFact]:
    """Return `facts` plus any active facts they link to, deduplicated, links given a lower
    score than the facts that pulled them in (they're one step removed, not a direct match)."""
    if not facts:
        return facts

    conn = sqlite3.connect(index_db)
    try:
        seen_ids = {f.id for f in facts}
        linked_ids: set[str] = set()
        for fact in facts:
            row = conn.execute(
                "SELECT links_json FROM semantic_facts WHERE id = ?", (fact.id,)
            ).fetchone()
            if row is None:
                continue
            for linked_id in json.loads(row[0]):
                if linked_id not in seen_ids:
                    linked_ids.add(linked_id)

        if not linked_ids:
            return facts

        placeholders = ",".join("?" for _ in linked_ids)
        rows = conn.execute(
            f"SELECT id, body, valid_at, scope FROM semantic_facts WHERE invalid_at IS NULL AND id IN ({placeholders})",
            list(linked_ids),
        ).fetchall()
    finally:
        conn.close()

    min_score = min((f.score for f in facts), default=1.0)
    expanded = [
        RetrievedFact(id=row[0], body=row[1], score=min_score * 0.5, valid_at=row[2], scope=row[3])
        for row in rows
    ]
    return facts + expanded
