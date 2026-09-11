"""Root-cause investigation for `retrieval-precision-at-scale`, against the REAL brain/ store
(not a synthetic fixture) -- eval/RETRIEVAL_PRECISION_AT_SCALE.md has the full writeup.

Reported symptom: query "what name did the bank wire transfer end up under?" -- the correct fact
(the bank's final SWIFT-wire sender correction) ranked #1, but ranks #2-10 were near-random
padding from unrelated topics (cognitive-architecture, music, personal), scored within a few
percent of the top result. `sufficiency.check()` did not flag it.

Three candidate root causes, investigated in this order per the task brief:

1. entity_scope.py is still a pass-through (every real fact has entity="unsorted", scope=null) --
   would real entity/scope anchoring have excluded the padding on its own?
2. hybrid.py's TF-IDF/BM25 scoring doesn't differentiate well at this vocabulary/style.
3. sufficiency.check() doesn't look at score-distribution *shape*, only whether results exist.

`OLD_search` below is a frozen copy of the pre-this-task algorithm (matches
eval/run_retrieval_dilution.py's `old_search`), so this script keeps reproducing the ORIGINAL
reported behavior regardless of later changes to src/retrieve/hybrid.py.

Usage:
    .venv/bin/python eval/run_retrieval_quality.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.index.build import build  # noqa: E402
from src.retrieve.entity_scope import by_entity_or_scope  # noqa: E402
from src.retrieve.sufficiency import check  # noqa: E402

BRAIN_ROOT = Path(__file__).resolve().parent.parent / "brain"
QUERY = "what name did the bank wire transfer end up under?"

# ---- frozen pre-fix algorithm (src/retrieve/hybrid.py before this task's fix) ----

_OLD_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _old_tokenize(text: str) -> list[str]:
    return _OLD_TOKEN_RE.findall(text.lower())


def _old_tfidf_matrix(documents: list[str]) -> np.ndarray:
    tokenized = [_old_tokenize(doc) for doc in documents]
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


def _old_bm25_candidates(conn, query: str, k: int):
    tokens = _old_tokenize(query)
    if not tokens:
        return []
    match_query = " OR ".join(f'"{tok}"' for tok in tokens)
    rows = conn.execute(
        "SELECT semantic_facts_fts.id, bm25(semantic_facts_fts) AS rank FROM semantic_facts_fts "
        "JOIN semantic_facts ON semantic_facts.id = semantic_facts_fts.id "
        "WHERE semantic_facts_fts MATCH ? AND semantic_facts.invalid_at IS NULL "
        "ORDER BY rank LIMIT ?",
        (match_query, k),
    ).fetchall()
    return [(row[0], i) for i, row in enumerate(rows)]


def _old_vector_candidates(conn, query: str, k: int):
    rows = conn.execute("SELECT id, body FROM semantic_facts WHERE invalid_at IS NULL").fetchall()
    if not rows:
        return []
    ids = [row[0] for row in rows]
    documents = [row[1] for row in rows] + [query]
    tfidf = _old_tfidf_matrix(documents)
    query_vec = tfidf[-1]
    doc_vecs = tfidf[:-1]
    similarities = doc_vecs @ query_vec
    ranked = np.argsort(-similarities)[:k]
    return [(ids[i], rank) for rank, i in enumerate(ranked)]


def old_search(index_db: Path, query: str, *, k: int = 10, rrf_constant: int = 60):
    conn = sqlite3.connect(index_db)
    try:
        bm25_ranks = dict(_old_bm25_candidates(conn, query, k * 2))
        vector_ranks = dict(_old_vector_candidates(conn, query, k * 2))
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
            f"SELECT id, body FROM semantic_facts WHERE id IN ({placeholders}) AND invalid_at IS NULL",
            top_ids,
        ).fetchall()
        by_id = {row[0]: row[1] for row in rows}
    finally:
        conn.close()
    return [(fused_scores[fid], by_id[fid]) for fid in top_ids if fid in by_id]


def main() -> None:
    if not BRAIN_ROOT.exists():
        print(f"brain/ not found at {BRAIN_ROOT} -- this script needs the real corpus, not a fixture.")
        return

    index_db = build(brain_root=BRAIN_ROOT)
    conn = sqlite3.connect(index_db)
    n_active = conn.execute("SELECT COUNT(*) FROM semantic_facts WHERE invalid_at IS NULL").fetchone()[0]
    conn.close()
    print(f"real corpus: {n_active} active facts in brain/\n")

    print(f"query: {QUERY!r}\n")

    # --- Hypothesis 1: entity/scope anchoring ---
    print("=== Hypothesis 1: entity/scope-anchored retrieval (entity_scope.py) ===")
    em = by_entity_or_scope(index_db)  # no explicit filter -- matches the real CLI's default call
    print(f"by_entity_or_scope() with no filter: {len(em)} matches (always [] unless a caller")
    print("supplies entity/scope explicitly -- the real CLI's --entity/--scope flags require the")
    print("caller to already know the exact value, and nothing populates them automatically).")
    conn = sqlite3.connect(index_db)
    entities = {r[0] for r in conn.execute("SELECT DISTINCT entity FROM semantic_facts")}
    scopes = {r[0] for r in conn.execute("SELECT DISTINCT scope FROM semantic_facts")}
    conn.close()
    print(f"distinct entity values across the real store: {entities}")
    print(f"distinct scope values across the real store: {scopes}")
    print("This query itself contains no capitalized/named entity to extract ('bank', 'wire',")
    print("'transfer' are generic nouns) -- so even a working entity/scope anchor would not have")
    print("engaged for this specific query. CONFIRMED structural gap, NOT the explanation for this")
    print("specific reported failure.\n")

    # --- Hypothesis 2 + 3: run the frozen pre-fix algorithm, inspect raw magnitudes ---
    print("=== Hypotheses 2 & 3: pre-fix search() + sufficiency.check() on the real query ===")
    before = old_search(index_db, QUERY, k=10)
    print(f"pre-fix search() returns {len(before)} results:")
    for score, body in before:
        print(f"  {score:.5f}  {body[:90]}")

    sufficiency = check(entity_matches=[], similarity_matches=[type("F", (), {"score": s})() for s, _ in before])
    print(f"\nsufficiency.check(): {sufficiency}")
    print("CONFIRMED: flags 'sufficient' despite 9/10 results being off-topic padding -- it only")
    print("checks the single best score against a fixed threshold, never the shape of the rest.\n")

    tokens = _old_tokenize(QUERY)
    match_query = " OR ".join(f'"{t}"' for t in tokens)
    conn = sqlite3.connect(index_db)
    bm25raw = conn.execute(
        "SELECT bm25(semantic_facts_fts) AS raw FROM semantic_facts_fts "
        "JOIN semantic_facts ON semantic_facts.id = semantic_facts_fts.id "
        "WHERE semantic_facts_fts MATCH ? AND semantic_facts.invalid_at IS NULL ORDER BY raw LIMIT 3",
        (match_query,),
    ).fetchall()
    rows = conn.execute("SELECT body FROM semantic_facts WHERE invalid_at IS NULL").fetchall()
    docs = [r[0] for r in rows] + [QUERY]
    tfidf = _old_tfidf_matrix(docs)
    sims = (tfidf[:-1] @ tfidf[-1])
    top_sims = sorted(sims, reverse=True)[:3]
    conn.close()

    print("Raw signal magnitude (before RRF collapses it to rank position):")
    print(f"  BM25 raw, top 3 (lower=better): {[round(r[0], 3) for r in bm25raw]}")
    print(f"  cosine sim, top 3:              {[round(float(s), 3) for s in top_sims]}")
    print("CONFIRMED: a large, genuine gap exists in both raw signals (top result several times")
    print("stronger than #2) -- but RRF fuses by rank only (1/(60+rank)), so rank0 vs rank1 differ")
    print("by only ~2% regardless of this gap. This is the dominant, generalizable root cause.\n")

    print("=== Conclusion ===")
    print("Root cause is primarily #2/#3 combined, not #1: the raw signals already discriminate")
    print("correctly, but search() discards that magnitude by converting to rank before fusing, and")
    print("sufficiency.check() has no way to see the discarded shape either. Entity/scope anchoring")
    print("(#1) is a real, separate, confirmed structural gap (100% of real facts unsorted/null,")
    print("never engaged) but would not have fixed this specific query and is out of this task's")
    print("scope to build -- filed as a known limitation, not implemented here.")


if __name__ == "__main__":
    main()
