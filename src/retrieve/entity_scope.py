"""Entity/scope-anchored retrieval — the primary path per BUILD_PLAN.md §2.3, similarity search
supplements it rather than replacing it.

Currently a thin, honest pass-through: nothing in the pipeline extracts a real `entity` value yet
(src/index/flush.py defaults every fact to entity="unsorted" — see ARCHITECTURE.md §5,
"incremental entity resolution" is explicitly not built yet). So this only does real work once a
caller supplies an explicit entity/scope filter (e.g. from a future entity-extraction step); until
then it correctly returns nothing and src/retrieve/hybrid.py carries retrieval on its own.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.retrieve.hybrid import RetrievedFact


def by_entity_or_scope(
    index_db: Path, *, entity: str | None = None, scope: str | None = None
) -> list[RetrievedFact]:
    if entity is None and scope is None:
        return []

    conditions = ["invalid_at IS NULL"]
    params: list[str] = []
    if entity is not None:
        conditions.append("entity = ?")
        params.append(entity)
    if scope is not None:
        conditions.append("scope = ?")
        params.append(scope)

    conn = sqlite3.connect(index_db)
    try:
        rows = conn.execute(
            f"SELECT id, body, valid_at, scope FROM semantic_facts WHERE {' AND '.join(conditions)}",
            params,
        ).fetchall()
    finally:
        conn.close()

    return [
        RetrievedFact(id=row[0], body=row[1], score=1.0, valid_at=row[2], scope=row[3])
        for row in rows
    ]
