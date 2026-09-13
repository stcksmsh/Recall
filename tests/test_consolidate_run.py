from src.capture.capture import capture
from src.consolidate.classifier import ClassificationResult
from src.index.build import build
from src.retrieve.entity_scope import by_entity_or_scope
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


def test_verifier_reroutes_flagged_supersede_to_review(tmp_path, monkeypatch):
    from src.verify import VerificationResult

    brain_root = tmp_path / "brain"
    capture("seed fact", brain_root=brain_root)

    calls = {"n": 0}

    def fake_classify(new_capture, existing_facts, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ClassificationResult("new", 0.95, "seed", None)
        return ClassificationResult("update", 0.95, "looks like supersession", "f1")

    monkeypatch.setattr(run_module, "classify", fake_classify)
    monkeypatch.setattr(
        run_module, "verify",
        lambda *a, **k: VerificationResult(True, "deterministic", "retraction cue", {"cues": ["x"]}),
    )

    capture("actually the seed fact was wrong from the start", brain_root=brain_root)
    summary = run_module.run(brain_root=brain_root)

    assert summary.verifier_flagged == 1
    assert summary.by_action.get("review") == 1
    assert summary.by_action.get("supersede") is None


def test_verify_decisions_false_skips_the_check(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    capture("seed fact", brain_root=brain_root)

    calls = {"n": 0}

    def fake_classify(new_capture, existing_facts, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ClassificationResult("new", 0.95, "seed", None)
        return ClassificationResult("update", 0.95, "supersession", "f1")

    def boom(*a, **k):  # must not be called
        raise AssertionError("verify() called when verify_decisions=False")

    monkeypatch.setattr(run_module, "classify", fake_classify)
    monkeypatch.setattr(run_module, "verify", boom)

    capture("second capture", brain_root=brain_root)
    summary = run_module.run(brain_root=brain_root, verify_decisions=False)

    assert summary.verifier_flagged == 0
    assert summary.by_action.get("supersede") == 1


def test_cross_project_same_entity_name_separated_by_scope(tmp_path, monkeypatch):
    """Regression for the audit finding: entity/scope were never populated, so two facts about
    a same-named thing in different projects returned pooled/undifferentiated on lookup. Same
    entity name ("the_database"), two different projects -- must come back separated by scope,
    not pooled."""
    brain_root = tmp_path / "brain"
    capture("the_database now uses SQLite for local dev.", brain_root=brain_root, project="project_a")
    capture("the_database now uses PostgreSQL in production.", brain_root=brain_root, project="project_b")

    def fake_classify(new_capture, existing_facts, **kwargs):
        return ClassificationResult("new", 0.95, "no overlap", None)

    monkeypatch.setattr(run_module, "classify", fake_classify)

    summary = run_module.run(brain_root=brain_root)
    assert summary.processed == 2
    assert summary.by_action == {"write_new": 2}

    index_db = build(brain_root=brain_root)
    a_matches = by_entity_or_scope(index_db, entity="thedatabase", scope="project_a")
    b_matches = by_entity_or_scope(index_db, entity="thedatabase", scope="project_b")

    assert len(a_matches) == 1
    assert len(b_matches) == 1
    assert a_matches[0].id != b_matches[0].id
    assert "SQLite" in a_matches[0].body
    assert "PostgreSQL" in b_matches[0].body


def test_ambiguous_entity_extraction_reroutes_to_review(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    capture(
        "Compared the_database against other_service and picked neither yet.",
        brain_root=brain_root, project="project_a",
    )

    def fake_classify(new_capture, existing_facts, **kwargs):
        return ClassificationResult("new", 0.95, "no overlap", None)

    monkeypatch.setattr(run_module, "classify", fake_classify)

    summary = run_module.run(brain_root=brain_root)

    assert summary.by_action == {"review": 1}
    facts = list((brain_root / "semantic" / "facts").rglob("*.md"))
    assert facts == []


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
