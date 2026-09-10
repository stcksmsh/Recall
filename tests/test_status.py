from src.capture.capture import capture
from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.consolidate.review import override
from src.index.flush import flush
from src.status import gather, render


def test_status_empty_store(tmp_path):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()

    s = gather(brain_root=brain_root)

    assert s.captures == 0
    assert s.unconsolidated == 0
    assert s.facts_active == 0
    assert s.review_pending == 0
    assert s.corrections == 0
    assert "LIMITATIONS.md" in render(s)


def test_status_counts_captures_facts_review_and_corrections(tmp_path):
    brain_root = tmp_path / "brain"

    # two captures, one still unconsolidated
    capture("first thing", brain_root=brain_root)
    capture("second thing", brain_root=brain_root)

    # one active fact
    new_decision = decide(ClassificationResult("new", 0.95, "no overlap", None), capture_id="c0")
    flush(new_decision, capture_content="a fact", captured_at="2026-01-01", brain_root=brain_root)

    # one pending review item that we then resolve -> logs a correction
    review_decision = decide(
        ClassificationResult("update", 0.4, "low confidence", "f1"), capture_id="c1"
    )
    review_path = flush(
        review_decision,
        capture_content="disputed",
        captured_at="2026-02-01",
        brain_root=brain_root,
        candidate_facts=[{"id": "f1", "valid_at": "2026-01-01", "content": "old"}],
    )
    import frontmatter

    s = gather(brain_root=brain_root)
    assert s.captures == 2
    assert s.unconsolidated == 2  # captures aren't linked to the hand-built fact
    assert s.facts_active == 1
    assert s.review_pending == 1
    assert s.review_by_classification == {"update": 1}

    review_id = frontmatter.load(review_path)["id"]
    override(review_id, "contradiction", brain_root=brain_root)

    s = gather(brain_root=brain_root)
    assert s.review_pending == 0
    assert s.corrections == 1

    out = render(s)
    assert "review queue" in out
    assert "corrections logged      1" in out
