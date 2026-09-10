"""Phase 7 confirmation: `recall review accept` / `recall review override` (the actual CLI
entry points, not just the review module) append a fully-labelled example to the correction log
on disk — facts_in, classification_given, confidence_given, correct_classification.
"""

import frontmatter
from typer.testing import CliRunner

from src.cli import app
from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.index.flush import flush

runner = CliRunner()

CANDIDATES = [{"id": "f1", "valid_at": "2026-01-01", "content": "the original claim"}]


def _seed_review_item(brain_root, *, classification="update", confidence=0.42):
    decision = decide(
        ClassificationResult(classification, confidence, "reasoning", "f1"), capture_id="c1"
    )
    path = flush(
        decision,
        capture_content="the capture that disputes the original claim",
        captured_at="2026-08-01",
        brain_root=brain_root,
        candidate_facts=CANDIDATES,
    )
    return frontmatter.load(path)["id"]


def _only_correction(brain_root):
    files = list((brain_root / "semantic" / "corrections").glob("*.md"))
    assert len(files) == 1, files
    return frontmatter.load(files[0])


def test_cli_review_override_appends_labelled_correction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    review_id = _seed_review_item(brain_root, classification="update", confidence=0.42)

    result = runner.invoke(app, ["review", "override", review_id, "contradiction"])
    assert result.exit_code == 0, result.output

    c = _only_correction(brain_root)
    assert c["facts_in"] == CANDIDATES
    assert c["classification_given"] == "update"
    assert c["confidence_given"] == 0.42
    assert c["correct_classification"] == "contradiction"


def test_cli_review_accept_appends_labelled_correction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    review_id = _seed_review_item(brain_root, classification="context_dependent_both", confidence=0.7)

    result = runner.invoke(app, ["review", "accept", review_id])
    assert result.exit_code == 0, result.output

    c = _only_correction(brain_root)
    assert c["facts_in"] == CANDIDATES
    assert c["classification_given"] == "context_dependent_both"
    assert c["confidence_given"] == 0.7
    assert c["correct_classification"] == "context_dependent_both"  # accept = confirmation label
