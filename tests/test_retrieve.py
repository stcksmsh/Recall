import frontmatter

from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.index.build import build
from src.index.flush import flush
from src.retrieve.entity_scope import by_entity_or_scope
from src.retrieve.graph_expand import expand
from src.retrieve.hybrid import search
from src.retrieve.sufficiency import check


def _write_fact(brain_root, content, entity="unsorted", scope=None, capture_id="c1"):
    result = ClassificationResult("new", 0.9, "no overlap", None)
    decision = decide(result, capture_id=capture_id, confidence_threshold=0.75)
    return flush(
        decision, capture_content=content, captured_at="2026-01-01", brain_root=brain_root, entity=entity, scope=scope
    )


def test_hybrid_search_finds_matching_fact_by_keyword(tmp_path):
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, "User's primary language at work is Kotlin.")
    _write_fact(brain_root, "User enjoys hiking on weekends.")
    index_db = build(brain_root=brain_root)

    results = search(index_db, "what language does the user use at work")

    assert results
    assert any("Kotlin" in r.body for r in results)


def test_hybrid_search_returns_empty_on_empty_index(tmp_path):
    brain_root = tmp_path / "brain"
    index_db = build(brain_root=brain_root)

    results = search(index_db, "anything")

    assert results == []


def _invalidate(fact_path):
    post = frontmatter.load(fact_path)
    post["invalid_at"] = "2026-06-01T00:00:00+00:00"
    fact_path.write_bytes(frontmatter.dumps(post).encode("utf-8"))


def test_hybrid_search_never_returns_an_invalidated_fact(tmp_path):
    """Regression: eval/DOGFOOD_FINDINGS.md — the BM25 path (_bm25_candidates, querying
    semantic_facts_fts) didn't filter invalid_at, unlike the vector path, so an invalidated fact
    that ranked well on exact keyword match could still come back as "ground truth"."""
    brain_root = tmp_path / "brain"
    # distinctive keyword that only this fact contains, so it dominates the BM25 rank
    stale_path = _write_fact(brain_root, "Zorblatt is the codename for the payments migration.")
    _write_fact(brain_root, "Unrelated fact about hiking.")
    _invalidate(stale_path)
    index_db = build(brain_root=brain_root)

    results = search(index_db, "What is Zorblatt the codename for?")

    assert all("Zorblatt" not in r.body for r in results)
    assert all(r.id != frontmatter.load(stale_path)["id"] for r in results)


def test_entity_scope_filters_by_scope(tmp_path):
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, "Uses Kotlin at work.", scope="work")
    _write_fact(brain_root, "Learning Python for fun.", scope="personal")
    index_db = build(brain_root=brain_root)

    work_facts = by_entity_or_scope(index_db, scope="work")

    assert len(work_facts) == 1
    assert "Kotlin" in work_facts[0].body


def test_entity_scope_returns_nothing_without_filters(tmp_path):
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, "Some fact.")
    index_db = build(brain_root=brain_root)

    assert by_entity_or_scope(index_db) == []


def test_graph_expand_pulls_in_linked_fact(tmp_path):
    brain_root = tmp_path / "brain"
    old_path = _write_fact(brain_root, "Old address: 12 Birch Lane.", capture_id="c1")
    import frontmatter

    old_id = frontmatter.load(old_path)["id"]

    supersede_result = ClassificationResult("update", 0.9, "moved", old_id)
    supersede_decision = decide(supersede_result, capture_id="c2", confidence_threshold=0.75)
    new_path = flush(
        supersede_decision, capture_content="New address: 45 Oak Street.", captured_at="2026-02-01", brain_root=brain_root
    )
    new_id = frontmatter.load(new_path)["id"]

    index_db = build(brain_root=brain_root)
    from src.retrieve.hybrid import RetrievedFact

    seed = [RetrievedFact(id=new_id, body="New address: 45 Oak Street.", score=1.0)]

    expanded = expand(index_db, seed)

    # The old fact is invalidated (invalid_at set), so it should NOT be pulled in as active.
    assert len(expanded) == 1


def test_sufficiency_flags_empty_results():
    result = check(entity_matches=[], similarity_matches=[])
    assert result.sufficient is False


def test_sufficiency_passes_with_entity_match():
    from src.retrieve.hybrid import RetrievedFact

    result = check(entity_matches=[RetrievedFact(id="f1", body="x", score=1.0)], similarity_matches=[])
    assert result.sufficient is True
