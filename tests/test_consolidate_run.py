from src.capture.capture import capture
from src.consolidate.classifier import ClassificationResult
import src.consolidate.run as run_module


def test_run_processes_unconsolidated_captures_and_flushes(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    capture("first capture, no conflicts", brain_root=brain_root)

    def fake_classify(new_capture, existing_facts, **kwargs):
        return ClassificationResult(
            classification="new", confidence=0.95, reasoning="no overlap", conflicting_fact_id=None
        )

    monkeypatch.setattr(run_module, "classify", fake_classify)

    summary = run_module.run(brain_root=brain_root)

    assert summary.processed == 1
    assert summary.by_action == {"write_new": 1}

    facts = list((brain_root / "semantic" / "facts").rglob("*.md"))
    assert len(facts) == 1


def test_run_is_idempotent_once_captures_are_consolidated(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    capture("only capture", brain_root=brain_root)

    def fake_classify(new_capture, existing_facts, **kwargs):
        return ClassificationResult(
            classification="new", confidence=0.95, reasoning="no overlap", conflicting_fact_id=None
        )

    monkeypatch.setattr(run_module, "classify", fake_classify)

    first_summary = run_module.run(brain_root=brain_root)
    second_summary = run_module.run(brain_root=brain_root)

    assert first_summary.processed == 1
    assert second_summary.processed == 0


def test_run_routes_low_confidence_to_review_queue(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    capture("ambiguous capture", brain_root=brain_root)

    def fake_classify(new_capture, existing_facts, **kwargs):
        return ClassificationResult(
            classification="update", confidence=0.3, reasoning="unsure", conflicting_fact_id="f1"
        )

    monkeypatch.setattr(run_module, "classify", fake_classify)

    summary = run_module.run(brain_root=brain_root, confidence_threshold=0.75)

    assert summary.by_action == {"review": 1}
    review_items = list((brain_root / "semantic" / "review_queue").glob("*.md"))
    assert len(review_items) == 1
