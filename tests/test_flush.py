import frontmatter

from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.index.build import build
from src.index.flush import flush


def _result(classification, confidence, conflicting_fact_id=None):
    return ClassificationResult(
        classification=classification,
        confidence=confidence,
        reasoning="because",
        conflicting_fact_id=conflicting_fact_id,
    )


def test_write_new_creates_active_semantic_fact(tmp_path):
    brain_root = tmp_path / "brain"
    decision = decide(_result("new", 0.9), capture_id="c1", confidence_threshold=0.75)

    path = flush(decision, capture_content="new fact body", captured_at="2026-08-01", brain_root=brain_root)

    post = frontmatter.load(path)
    assert post.content == "new fact body"
    assert post["invalid_at"] is None
    assert post["source_capture_id"] == "c1"


def test_supersede_invalidates_old_fact_and_writes_new_one(tmp_path):
    brain_root = tmp_path / "brain"
    new_decision = decide(_result("new", 0.9), capture_id="c1", confidence_threshold=0.75)
    old_fact_path = flush(new_decision, capture_content="old fact", captured_at="2026-01-01", brain_root=brain_root)
    old_fact_id = frontmatter.load(old_fact_path)["id"]

    supersede_decision = decide(
        _result("update", 0.9, old_fact_id), capture_id="c2", confidence_threshold=0.75
    )
    new_fact_path = flush(
        supersede_decision, capture_content="new fact", captured_at="2026-08-01", brain_root=brain_root
    )

    old_post = frontmatter.load(old_fact_path)
    assert old_post["invalid_at"] is not None
    assert old_post["expired_at"] is not None

    new_post = frontmatter.load(new_fact_path)
    assert new_post["invalid_at"] is None
    assert old_fact_id in new_post["links"]


def test_review_writes_pending_item_not_a_fact(tmp_path):
    brain_root = tmp_path / "brain"
    decision = decide(_result("contradiction", 0.99, "f1"), capture_id="c1", confidence_threshold=0.75)

    path = flush(decision, capture_content="disputed content", captured_at="2026-08-01", brain_root=brain_root)

    post = frontmatter.load(path)
    assert post["status"] == "pending"
    assert path.parent.name == "review_queue"


def test_flushed_facts_and_review_items_are_indexable(tmp_path):
    brain_root = tmp_path / "brain"
    new_decision = decide(_result("new", 0.9), capture_id="c1", confidence_threshold=0.75)
    flush(new_decision, capture_content="fact body", captured_at="2026-08-01", brain_root=brain_root)

    review_decision = decide(_result("contradiction", 0.99, "f1"), capture_id="c2", confidence_threshold=0.75)
    flush(review_decision, capture_content="disputed", captured_at="2026-08-01", brain_root=brain_root)

    db_path = build(brain_root=brain_root)
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        fact_count = conn.execute("SELECT COUNT(*) FROM semantic_facts").fetchone()[0]
        review_count = conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0]
    finally:
        conn.close()

    assert fact_count == 1
    assert review_count == 1
