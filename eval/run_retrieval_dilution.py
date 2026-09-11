"""Before/after for task retrieval-precision-at-scale (eval/RETRIEVAL_PRECISION_AT_SCALE.md).

Question this answers: once the store is topically varied (>=50 facts across disparate topics),
does src.retrieve.hybrid.search() pad its top-k with near-zero-relevance facts, or does it return
only genuinely-matching facts with a real score gap over the rest?

"Before" reruns the pre-fix algorithm frozen here (unfiltered tokenizer, no result-score floor) --
git history has the real removed code; this is a standalone copy so the comparison survives future
edits to src/retrieve/hybrid.py. "After" calls the shipped src.retrieve.hybrid.search() directly.

Usage:
    .venv/bin/python eval/run_retrieval_dilution.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.consolidate.classifier import ClassificationResult  # noqa: E402
from src.consolidate.executor import decide  # noqa: E402
from src.index.build import build  # noqa: E402
from src.index.flush import flush  # noqa: E402
from src.retrieve.hybrid import search as fixed_search  # noqa: E402

# ---- fixture: >=50 facts across 5 disparate topics, matching tests/test_retrieve_precision.py ----

TOPICS = {
    "finance": [
        "User's primary brokerage account is at Fidelity.",
        "User contributes 15 percent of salary to a 401k.",
        "User's emergency fund target is six months of expenses.",
        "User pays off the credit card balance in full every month.",
        "User's mortgage rate is 4.2 percent fixed for 30 years.",
        "User tracks spending using a Google Sheet budget.",
        "User's Roth IRA is invested in a total market index fund.",
        "User's annual bonus goes straight into taxable brokerage.",
        "User refinanced the car loan in March for a lower rate.",
        "User's rent increased by 200 dollars this year.",
    ],
    "music": [
        "User plays acoustic guitar, mostly fingerstyle.",
        "User's favorite band growing up was Radiohead.",
        "User is learning jazz piano chords on weekends.",
        "User went to three concerts last summer.",
        "User has a vinyl collection focused on 70s rock.",
        "User sings baritone in a community choir.",
        "User built a home studio with an audio interface.",
        "User prefers vintage tube amps over solid state.",
        "User is composing a short EP of ambient tracks.",
        "User practices drums for thirty minutes most days.",
    ],
    "cognitive-architecture": [
        "The consolidation loop reconciles episodic and semantic tiers offline.",
        "The classifier only proposes; the executor is the sole writer.",
        "Confidence below 0.90 always routes to human review.",
        "The episodic tier is immutable and append-only.",
        "SQLite index must be fully rebuildable from markdown.",
        "Corrections are new captures referencing the old one, never mutations.",
        "Expensive reasoning never runs in the live query path.",
        "Graph expansion pulls in linked facts via supersede edges.",
        "The verifier is deterministic and runs after the classifier.",
        "brain/ is a separate private git repo from the Recall codebase.",
    ],
    "personal": [
        "User's dog is a border collie named Scout.",
        "User moved apartments in February.",
        "User is training for a half marathon in the fall.",
        "User's sister lives in Portland.",
        "User cooks a big batch of soup every Sunday.",
        "User is learning to bake sourdough bread.",
        "User's favorite hiking trail is near the reservoir.",
        "User keeps a small herb garden on the balcony.",
        "User volunteers at the animal shelter twice a month.",
        "User is reading a biography of Marie Curie.",
    ],
    "work": [
        "User's team ships on a two week sprint cadence.",
        "User's manager prefers async updates over standups.",
        "User is the on-call engineer this week.",
        "User's main project uses a Postgres backend.",
        "User presented the quarterly roadmap on Tuesday.",
        "User is mentoring a new hire on the platform team.",
        "User's laptop was replaced after a hardware failure.",
        "User uses a standing desk in the office.",
        "User's performance review is scheduled for next month.",
        "User prefers code review over pair programming.",
    ],
}

QUERIES = [
    ("what brokerage does the user use for investing", "finance"),
    ("tell me about the user's dog", "personal"),
    ("what does the classifier do in the consolidation pipeline", "cognitive-architecture"),
    # no fact in the fixture actually matches this one lexically -- before the fix, RRF still
    # padded 10 arbitrary low-similarity facts; after, search() correctly returns nothing.
    ("what instrument does the user play", None),
]


def build_fixture(brain_root: Path) -> None:
    capture_id = 0
    for topic, facts in TOPICS.items():
        for content in facts:
            capture_id += 1
            result = ClassificationResult("new", 0.9, "no overlap", None)
            decision = decide(result, capture_id=f"c{capture_id}", confidence_threshold=0.75)
            flush(
                decision,
                capture_content=content,
                captured_at="2026-01-01",
                brain_root=brain_root,
                entity="unsorted",
                scope=topic,
            )
    assert capture_id >= 50


# ---- frozen pre-fix implementation (src/retrieve/hybrid.py before this task) ----

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


def _old_bm25_candidates(conn, query: str, k: int) -> list[tuple[str, float]]:
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


def _old_vector_candidates(conn, query: str, k: int) -> list[tuple[str, float]]:
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
            f"SELECT id, body, scope FROM semantic_facts "
            f"WHERE id IN ({placeholders}) AND invalid_at IS NULL",
            top_ids,
        ).fetchall()
        by_id = {row[0]: row for row in rows}
    finally:
        conn.close()
    return [(fused_scores[fid], by_id[fid][2], by_id[fid][1]) for fid in top_ids if fid in by_id]


def main() -> None:
    brain_root = Path(tempfile.mkdtemp()) / "brain"
    build_fixture(brain_root)
    index_db = build(brain_root=brain_root)

    for query, relevant_scope in QUERIES:
        print(f"\n=== query: {query!r}  (relevant scope: {relevant_scope}) ===")

        before = old_search(index_db, query, k=10)
        print(f"BEFORE ({len(before)} results):")
        for score, scope, body in before:
            flag = "" if scope == relevant_scope else "  <-- off-topic padding"
            print(f"  {score:.5f}  {scope:25s} {body}{flag}")

        after = fixed_search(index_db, query, k=10)
        print(f"AFTER ({len(after)} results):")
        for r in after:
            flag = "" if r.scope == relevant_scope else "  <-- off-topic padding"
            print(f"  {r.score:.5f}  {r.scope:25s} {r.body}{flag}")
        if not after:
            print("  (empty — correctly returns nothing rather than padding)")


if __name__ == "__main__":
    main()
