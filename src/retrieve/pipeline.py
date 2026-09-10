"""Wires entity/scope + hybrid + graph expansion + sufficiency into one retrieval call, then
hands the result to src/inject/format.py. This is the `recall retrieve` entry point."""

from __future__ import annotations

from pathlib import Path

from src.index.build import build
from src.inject.format import format_facts
from src.retrieve.entity_scope import by_entity_or_scope
from src.retrieve.graph_expand import expand
from src.retrieve.hybrid import search
from src.retrieve.sufficiency import check

BRAIN_ROOT = Path("brain")


def retrieve_and_format(
    query: str, *, brain_root: Path = BRAIN_ROOT, k: int = 10, entity: str | None = None, scope: str | None = None
) -> str:
    index_db = build(brain_root=brain_root)

    entity_matches = by_entity_or_scope(index_db, entity=entity, scope=scope)
    similarity_matches = search(index_db, query, k=k)

    sufficiency = check(entity_matches=entity_matches, similarity_matches=similarity_matches)

    combined_by_id = {f.id: f for f in entity_matches}
    for f in similarity_matches:
        combined_by_id.setdefault(f.id, f)
    combined = list(combined_by_id.values())

    expanded = expand(index_db, combined)

    formatted = format_facts(expanded, repo_root=Path("."))
    if not sufficiency.sufficient:
        formatted += f"\n\n[sufficiency check: INSUFFICIENT — {sufficiency.reason}]"

    return formatted
