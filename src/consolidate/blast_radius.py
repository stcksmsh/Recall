"""Candidate-neighborhood bounding for the classifier (ARCHITECTURE.md §5).

Never a full-graph scan — hard-capped at top-K. This is a deliberately simple v1: recency-capped,
not similarity-ranked, because embeddings aren't wired up yet (that's Phase 4 retrieval work, see
BUILD_PLAN.md §3) and at near-zero fact counts any candidate-selection strategy behaves the same.
Replace the ranking here with entity/scope-anchored + embedding similarity once retrieval exists —
the K-cap and "never scan everything" contract should not change.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.consolidate.classifier import ExistingFact

DEFAULT_K = 10


def candidate_facts(index_db: Path, *, k: int = DEFAULT_K) -> list[ExistingFact]:
    """Return up to k currently-valid (invalid_at IS NULL) semantic facts, most recent first."""
    conn = sqlite3.connect(index_db)
    try:
        rows = conn.execute(
            "SELECT id, valid_at, body FROM semantic_facts "
            "WHERE invalid_at IS NULL ORDER BY valid_at DESC LIMIT ?",
            (k,),
        ).fetchall()
    finally:
        conn.close()

    return [ExistingFact(id=row[0], valid_at=row[1] or "", content=row[2]) for row in rows]
