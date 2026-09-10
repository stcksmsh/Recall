from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import Action, decide


def _result(classification, confidence, conflicting_fact_id=None):
    return ClassificationResult(
        classification=classification,
        confidence=confidence,
        reasoning="because",
        conflicting_fact_id=conflicting_fact_id,
    )


def test_new_always_auto_writes_regardless_of_confidence():
    decision = decide(_result("new", 0.1), capture_id="c1", confidence_threshold=0.75)
    assert decision.action == Action.WRITE_NEW


def test_update_above_threshold_supersedes():
    decision = decide(_result("update", 0.9, "f1"), capture_id="c1", confidence_threshold=0.75)
    assert decision.action == Action.SUPERSEDE
    assert decision.conflicting_fact_id == "f1"


def test_update_below_threshold_goes_to_review():
    decision = decide(_result("update", 0.5, "f1"), capture_id="c1", confidence_threshold=0.75)
    assert decision.action == Action.REVIEW
    assert "review_reason" in decision.justification


def test_contradiction_always_goes_to_review_even_at_high_confidence():
    decision = decide(_result("contradiction", 0.99, "f1"), capture_id="c1", confidence_threshold=0.75)
    assert decision.action == Action.REVIEW
    assert decision.justification["review_reason"] == "contradiction is never auto-resolved"


def test_context_dependent_both_above_threshold_dual_retains():
    decision = decide(
        _result("context_dependent_both", 0.8, "f1"), capture_id="c1", confidence_threshold=0.75
    )
    assert decision.action == Action.DUAL_RETAIN


def test_context_dependent_both_below_threshold_goes_to_review():
    decision = decide(
        _result("context_dependent_both", 0.4, "f1"), capture_id="c1", confidence_threshold=0.75
    )
    assert decision.action == Action.REVIEW


def test_justification_carries_provenance():
    decision = decide(_result("new", 0.9), capture_id="c1", confidence_threshold=0.75)
    j = decision.justification
    assert j["capture_id"] == "c1"
    assert j["classification"] == "new"
    assert j["confidence"] == 0.9
    assert j["reasoning"] == "because"
