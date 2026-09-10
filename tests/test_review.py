import frontmatter

from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.consolidate.review import accept, list_pending, override
from src.index.flush import flush


def _make_review_item(brain_root, classification="contradiction", confidence=0.99, conflicting_fact_id="f1"):
    result = ClassificationResult(classification, confidence, "reasoning text", conflicting_fact_id)
    decision = decide(result, capture_id="c1", confidence_threshold=0.75)
    candidate_facts = [{"id": "f1", "valid_at": "2026-01-01", "content": "existing fact content"}]
    path = flush(
        decision,
        capture_content="disputed capture content",
        captured_at="2026-08-01",
        brain_root=brain_root,
        candidate_facts=candidate_facts,
    )
    return frontmatter.load(path)["id"]


def test_list_pending_shows_unresolved_items(tmp_path):
    brain_root = tmp_path / "brain"
    review_id = _make_review_item(brain_root)

    items = list_pending(brain_root=brain_root)

    assert len(items) == 1
    assert items[0].id == review_id
    assert items[0].classification_given == "contradiction"
    assert items[0].candidate_facts == [{"id": "f1", "valid_at": "2026-01-01", "content": "existing fact content"}]


def test_accept_contradiction_writes_no_fact_but_resolves_item(tmp_path):
    brain_root = tmp_path / "brain"
    review_id = _make_review_item(brain_root, classification="contradiction")

    fact_path = accept(review_id, brain_root=brain_root)

    assert fact_path is None
    assert list_pending(brain_root=brain_root) == []
    facts = list((brain_root / "semantic" / "facts").rglob("*.md"))
    assert facts == []


def test_accept_update_applies_supersede_action(tmp_path):
    brain_root = tmp_path / "brain"
    # First write a real fact to be superseded.
    new_result = ClassificationResult("new", 0.9, "no overlap", None)
    new_decision = decide(new_result, capture_id="c0", confidence_threshold=0.75)
    old_fact_path = flush(new_decision, capture_content="old fact", captured_at="2026-01-01", brain_root=brain_root)
    old_fact_id = frontmatter.load(old_fact_path)["id"]

    review_id = _make_review_item(
        brain_root, classification="update", confidence=0.4, conflicting_fact_id=old_fact_id
    )

    fact_path = accept(review_id, brain_root=brain_root)

    assert fact_path is not None
    old_post = frontmatter.load(old_fact_path)
    assert old_post["invalid_at"] is not None


def test_override_writes_correction_record(tmp_path):
    brain_root = tmp_path / "brain"
    review_id = _make_review_item(brain_root, classification="update", confidence=0.4, conflicting_fact_id=None)

    override(review_id, "new", brain_root=brain_root)

    corrections = list((brain_root / "semantic" / "corrections").glob("*.md"))
    assert len(corrections) == 1
    correction = frontmatter.load(corrections[0])
    assert correction["classification_given"] == "update"
    assert correction["correct_classification"] == "new"
    assert correction["review_item_id"] == review_id


def test_accept_also_records_a_correction_as_a_confirmation_label(tmp_path):
    brain_root = tmp_path / "brain"
    review_id = _make_review_item(brain_root, classification="contradiction")

    accept(review_id, brain_root=brain_root)

    corrections = list((brain_root / "semantic" / "corrections").glob("*.md"))
    assert len(corrections) == 1
    correction = frontmatter.load(corrections[0])
    assert correction["classification_given"] == "contradiction"
    assert correction["correct_classification"] == "contradiction"
