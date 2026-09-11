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
    had will would can could should shall i you your yours he she they them their our we us ours
    myself yourself himself herself itself ourselves yourselves themselves not no if so
    but than then there here how why when where which who whom whose whether me my mine tell know
    much many
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


# eval/RETRIEVAL_PRECISION_AT_SCALE.md (revisited against the real corpus, not just a synthetic
# fixture): a floor on the *fused RRF score* does not work, because RRF fuses by rank position
# only, and adjacent ranks are always within a few percent of each other by construction of
# 1/(rrf_constant+rank) -- regardless of how large the real relevance gap is. On the real store, a
# query with a single true match showed raw BM25 -15.3 vs -5.3 for the #2 candidate (3x) and raw
# cosine 0.27 vs 0.12 (2.2x) -- a large, genuine gap -- but converting both to rank-0/rank-1 before
# fusion flattened that into a ~2% RRF score difference. The floor has to act on each signal's raw
# magnitude, before rank/fusion erases it, or it has nothing real to act on.
RAW_RELATIVE_FLOOR = 0.5  # a candidate must be at least half as strong (by raw magnitude) as the best candidate on that signal to be considered at all


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
        "SELECT semantic_facts_fts.id, bm25(semantic_facts_fts) AS raw FROM semantic_facts_fts "
        "JOIN semantic_facts ON semantic_facts.id = semantic_facts_fts.id "
        "WHERE semantic_facts_fts MATCH ? AND semantic_facts.invalid_at IS NULL "
        "ORDER BY raw LIMIT ?",
        (match_query, k),
    ).fetchall()
    if not rows:
        return []
    # SQLite's bm25() returns *lower (more negative) is better*; magnitude reflects real match
    # strength (see module-level comment), so filter on it before collapsing to rank position.
    best_magnitude = abs(rows[0][1])
    floor = best_magnitude * RAW_RELATIVE_FLOOR
    kept = [row for row in rows if abs(row[1]) >= floor]
    return [(row[0], i) for i, row in enumerate(kept)]


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
    # an equally-zero doc ranked lower only by argsort tie-breaking. Beyond that, a real relevance
    # floor: a candidate must be within RAW_RELATIVE_FLOOR of the single best cosine similarity, so
    # a weak echo of the query doesn't ride along just because it wasn't literally zero.
    nonzero = np.flatnonzero(similarities > 0)
    if nonzero.size == 0:
        return []
    best_sim = similarities[nonzero].max()
    strong = nonzero[similarities[nonzero] >= best_sim * RAW_RELATIVE_FLOOR]
    ranked = strong[np.argsort(-similarities[strong])][:k]
    return [(ids[i], rank) for rank, i in enumerate(ranked)]


def search(index_db: Path, query: str, *, k: int = 10, rrf_constant: int = 60) -> list[RetrievedFact]:
    """Fuse BM25 rank and TF-IDF-cosine rank via Reciprocal Rank Fusion, over candidate pools each
    already floored to RAW_RELATIVE_FLOOR of that signal's own best raw match -- so a fact absent
    from both real-relevance pools never gets a rank slot to be padded in with."""
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
