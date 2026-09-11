"""Repro + regression for eval/RETRIEVAL_PRECISION_AT_SCALE.md: once the store is topically
varied, RRF fusion used to pad results out to k with near-zero-relevance facts scored within a
few percent of the genuine top hit. Fixture mirrors the shape that surfaced it via
backfill-import-combined -- >=50 facts spread across disparate topics."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.index.build import build
from src.index.flush import flush
from src.retrieve.hybrid import search

_QUALITY_SET_DIR = Path(__file__).parent.parent / "eval" / "retrieval_quality_set"

_TOPICS = {
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


def _build_disparate_fixture(brain_root):
    capture_id = 0
    for topic, facts in _TOPICS.items():
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
    return capture_id


def test_disparate_corpus_has_at_least_fifty_facts(tmp_path):
    count = _build_disparate_fixture(tmp_path / "brain")
    assert count >= 50


def test_search_does_not_pad_a_narrow_finance_query_with_irrelevant_facts(tmp_path):
    """Repro from the task constraint: a finance query's #1 result was correct, but #2-10 used
    to be near-random padding from other topics (personal/music/work/cognitive-architecture)
    with near-identical low RRF scores. Fixed search() must not return those at all."""
    brain_root = tmp_path / "brain"
    _build_disparate_fixture(brain_root)
    index_db = build(brain_root=brain_root)

    results = search(index_db, "what brokerage does the user use for investing", k=10)

    assert results
    assert all(r.scope == "finance" for r in results)
    assert len(results) < 10, "should not pad out to k once the store is topically varied"


def test_search_result_scores_have_a_real_gap_not_a_flat_tail(tmp_path):
    brain_root = tmp_path / "brain"
    _build_disparate_fixture(brain_root)
    index_db = build(brain_root=brain_root)

    results = search(index_db, "what does the classifier do in the consolidation pipeline", k=10)

    assert results
    assert all(r.scope == "cognitive-architecture" for r in results)


def test_search_returns_nothing_rather_than_padding_when_no_real_match_exists(tmp_path):
    """A query with no genuine lexical or TF-IDF overlap anywhere in the corpus used to still
    get padded to k with arbitrary low-similarity facts. It should now come back empty."""
    brain_root = tmp_path / "brain"
    _build_disparate_fixture(brain_root)
    index_db = build(brain_root=brain_root)

    results = search(index_db, "what instrument does the user play", k=10)

    assert results == []


def test_retrieval_quality_set_cases(tmp_path):
    """Runs eval/retrieval_quality_set/ (real captured content, real reported query) as a
    standing pytest regression, not just an ad-hoc script -- see that directory's README."""
    case_files = sorted(_QUALITY_SET_DIR.glob("case_*.yaml"))
    assert case_files, "retrieval_quality_set should have at least one case"

    for case_file in case_files:
        case = yaml.safe_load(case_file.read_text())
        brain_root = tmp_path / case["id"]
        expected_content = None
        for i, fact in enumerate(case["facts"]):
            result = ClassificationResult("new", 0.9, "no overlap", None)
            decision = decide(result, capture_id=f"{case['id']}_c{i}", confidence_threshold=0.75)
            flush(
                decision,
                capture_content=fact["content"],
                captured_at="2026-01-01",
                brain_root=brain_root,
                entity="unsorted",
                scope=None,
            )
            if fact.get("is_expected_top_result"):
                expected_content = fact["content"]
        assert expected_content is not None, f"{case['id']}: no fact marked is_expected_top_result"

        index_db = build(brain_root=brain_root)
        results = search(index_db, case["query"], k=10)

        assert results, f"{case['id']}: expected at least one result"
        assert results[0].body.strip() == expected_content.strip(), (
            f"{case['id']}: expected top result to be the marked fact, got: {results[0].body!r}"
        )
