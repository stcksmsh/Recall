"""BM25 (exact tokens) + a lightweight vector signal, fused via Reciprocal Rank Fusion.

Deliberate v1 simplification, flagged like blast_radius.py's recency placeholder: BUILD_PLAN.md
§3 specifies a local sentence-transformer embedding model for the vector half. That pulls in a
heavy dependency (torch) for a personal-scale corpus that doesn't need it yet. This module uses a
hand-rolled TF-IDF cosine similarity instead — genuinely a vector similarity signal, just lexical
rather than semantic. Upgrade to real embeddings when eval shows TF-IDF misses paraphrases that
matter; the RRF fusion contract here doesn't change either way.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class RetrievedFact:
    id: str
    body: str
    score: float
    valid_at: str | None = None
    scope: str | None = None


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _tfidf_matrix(documents: list[str]) -> np.ndarray:
    """Tiny hand-rolled TF-IDF, L2-normalized rows, so cosine similarity is a dot product."""
    tokenized = [_tokenize(doc) for doc in documents]
    vocab: dict[str, int] = {}
    for tokens in tokenized:
        for tok in tokens:
            vocab.setdefault(tok, len(vocab))

    n_docs = len(documents)
    doc_freq = np.zeros(len(vocab))
    for tokens in tokenized:
        for tok in set(tokens):
            doc_freq[vocab[tok]] += 1
    idf = np.log((n_docs + 1) / (doc_freq + 1)) + 1

    matrix = np.zeros((n_docs, len(vocab)))
    for i, tokens in enumerate(tokenized):
        counts = Counter(tokens)
        for tok, count in counts.items():
            matrix[i, vocab[tok]] = count * idf[vocab[tok]]

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


def _bm25_candidates(conn: sqlite3.Connection, query: str, k: int) -> list[tuple[str, float]]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    # OR of individual tokens, not a phrase match — we want recall across matching terms, not
    # exact adjacency. Each token individually quoted so FTS5 doesn't choke on stray syntax.
    match_query = " OR ".join(f'"{tok}"' for tok in tokens)
    rows = conn.execute(
        "SELECT id, bm25(semantic_facts_fts) AS rank FROM semantic_facts_fts "
        "WHERE semantic_facts_fts MATCH ? ORDER BY rank LIMIT ?",
        (match_query, k),
    ).fetchall()
    # SQLite's bm25() returns *lower is better*; rank position is what RRF actually wants.
    return [(row[0], i) for i, row in enumerate(rows)]


def _vector_candidates(conn: sqlite3.Connection, query: str, k: int) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT id, body FROM semantic_facts WHERE invalid_at IS NULL"
    ).fetchall()
    if not rows:
        return []

    ids = [row[0] for row in rows]
    documents = [row[1] for row in rows] + [query]
    tfidf = _tfidf_matrix(documents)
    query_vec = tfidf[-1]
    doc_vecs = tfidf[:-1]

    similarities = doc_vecs @ query_vec
    ranked = np.argsort(-similarities)[:k]
    return [(ids[i], rank) for rank, i in enumerate(ranked)]


def search(index_db: Path, query: str, *, k: int = 10, rrf_constant: int = 60) -> list[RetrievedFact]:
    """Fuse BM25 rank and TF-IDF-cosine rank via Reciprocal Rank Fusion, return top-k active facts."""
    conn = sqlite3.connect(index_db)
    try:
        bm25_ranks = dict(_bm25_candidates(conn, query, k * 2))
        vector_ranks = dict(_vector_candidates(conn, query, k * 2))

        fused_scores: dict[str, float] = {}
        for fact_id, rank in bm25_ranks.items():
            fused_scores[fact_id] = fused_scores.get(fact_id, 0.0) + 1.0 / (rrf_constant + rank)
        for fact_id, rank in vector_ranks.items():
            fused_scores[fact_id] = fused_scores.get(fact_id, 0.0) + 1.0 / (rrf_constant + rank)

        if not fused_scores:
            return []

        top_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)[:k]
        placeholders = ",".join("?" for _ in top_ids)
        rows = conn.execute(
            f"SELECT id, body, valid_at, scope FROM semantic_facts WHERE id IN ({placeholders})",
            top_ids,
        ).fetchall()
        by_id = {row[0]: row for row in rows}
    finally:
        conn.close()

    return [
        RetrievedFact(id=fid, body=by_id[fid][1], score=fused_scores[fid], valid_at=by_id[fid][2], scope=by_id[fid][3])
        for fid in top_ids
        if fid in by_id
    ]
