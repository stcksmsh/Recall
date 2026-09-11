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

# eval/RETRIEVAL_PRECISION_AT_SCALE.md: with no stopword filtering, near-universal words like
# "user" (present in ~every fact once bodies are phrased "User's ...") turn BM25's OR-match into
# an almost-unconditional candidate filter, and RRF's rank-only fusion then gives every one of
# those spurious candidates a score within a few percent of the top result. Filtering common
# function words before either signal sees the query (and the indexed documents, for TF-IDF) is
# the cheapest fix that addresses the actual mechanism rather than papering over its output.
_STOPWORDS = frozenset(
    """
    a an the this that these those is are was were be been being to of and or in on at for with
    about what does do did doesn't don't use uses used using user users it its as by from has have
    had will would can could should shall i you your yours he she they them their our not no if so
    but than then there here how when where which who whom me my mine tell know much many
    """.split()
)


@dataclass
class RetrievedFact:
    id: str
    body: str
    score: float
    valid_at: str | None = None
    scope: str | None = None


def _tokenize(text: str) -> list[str]:
    # len(tok) >= 2 drops single-character tokens too -- "user's" splits into "user", "s" on this
    # regex, and a bare "s" is exactly as near-universal a false signal as "user" itself.
    return [tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= 2 and tok not in _STOPWORDS]


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
    # semantic_facts_fts (src/index/build.py) indexes every fact's body unconditionally —
    # invalidated ones included, it carries no invalid_at column of its own. It is NOT
    # pre-filtered like semantic_facts is elsewhere in this pipeline; every query against it
    # must JOIN back to semantic_facts and filter invalid_at here. (This is exactly how an
    # invalidated fact leaked through as "ground truth" — see eval/DOGFOOD_FINDINGS.md.)
    tokens = _tokenize(query)
    if not tokens:
        return []
    # OR of individual tokens, not a phrase match — we want recall across matching terms, not
    # exact adjacency. Each token individually quoted so FTS5 doesn't choke on stray syntax.
    match_query = " OR ".join(f'"{tok}"' for tok in tokens)
    rows = conn.execute(
        "SELECT semantic_facts_fts.id, bm25(semantic_facts_fts) AS rank FROM semantic_facts_fts "
        "JOIN semantic_facts ON semantic_facts.id = semantic_facts_fts.id "
        "WHERE semantic_facts_fts MATCH ? AND semantic_facts.invalid_at IS NULL "
        "ORDER BY rank LIMIT ?",
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
    # A zero-similarity doc shares no vocabulary with the query at all (common once stopwords are
    # stripped and the query has little content left) -- it is not a "weak match", it is not a
    # match, and must not occupy a rank slot that RRF would then treat as meaningfully better than
    # an equally-zero doc ranked lower only by argsort tie-breaking.
    nonzero = np.flatnonzero(similarities > 0)
    ranked = nonzero[np.argsort(-similarities[nonzero])][:k]
    return [(ids[i], rank) for rank, i in enumerate(ranked)]


# eval/RETRIEVAL_PRECISION_AT_SCALE.md: RRF's rank-only fusion means a fact that only barely
# qualified as a candidate (e.g. rank 9 of a noisy pool) still scores within ~15% of a fact ranked
# 0 in both signals -- there is no floor in the fused score itself that reflects "this wasn't a
# real match, it just wasn't the worst candidate available." Once the stopword fix above removes
# the mass of spurious candidates, genuine hits and padding separate into a real score gap; this
# cutoff keeps only the cluster around the top score instead of padding out to k regardless.
RESULT_SCORE_FLOOR = 0.5  # fraction of the top fused score a result must clear to survive


def search(index_db: Path, query: str, *, k: int = 10, rrf_constant: int = 60) -> list[RetrievedFact]:
    """Fuse BM25 rank and TF-IDF-cosine rank via Reciprocal Rank Fusion, return top-k active facts
    scoring at least RESULT_SCORE_FLOOR of the top result -- never padded out to k with dregs."""
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

        ranked_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
        cutoff = fused_scores[ranked_ids[0]] * RESULT_SCORE_FLOOR
        top_ids = [fid for fid in ranked_ids if fused_scores[fid] >= cutoff][:k]
        placeholders = ",".join("?" for _ in top_ids)
        rows = conn.execute(
            f"SELECT id, body, valid_at, scope FROM semantic_facts "
            f"WHERE id IN ({placeholders}) AND invalid_at IS NULL",
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
