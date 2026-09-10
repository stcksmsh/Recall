"""Executor (Tier 3, deterministic). Pure lookup table — no model calls, no judgment.

Given a classifier ClassificationResult and a confidence threshold, decides the mechanical
consequence per BUILD_PLAN.md §2.2. Produces a Decision describing what should happen; this
module does not write anything — src/index/flush.py turns a Decision into Markdown writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from src.consolidate.classifier import ClassificationResult

# Phase 2 eval (eval/PHASE2_FINDINGS.md, 46 real cases, claude-sonnet-5): raised from 0.75.
# At 0.75, three "expected=contradiction, predicted=update, high confidence" cases auto-applied
# — i.e. silently corrupted the semantic tier, the exact failure this project exists to prevent.
# 0.90 is the highest usable value: wrong gated auto-applies drop to their floor (1 of 46) while
# 6 correct ones still clear the gate; at 0.95 nothing clears it and the gate just means
# "auto-apply off". The remaining error (ex_044, 0.93-confident contradiction→update) is NOT
# catchable by any usable threshold — the classifier's confidence signal does not separate that
# class of mistake. The real backstops are a prompt revision targeting the
# "retracted-as-error vs. aged-out" boundary and Phase 6 verification, not this number.
DEFAULT_CONFIDENCE_THRESHOLD = 0.90


class Action(str, Enum):
    WRITE_NEW = "write_new"
    SUPERSEDE = "supersede"
    DUAL_RETAIN = "dual_retain"
    REVIEW = "review"


@dataclass
class Decision:
    action: Action
    capture_id: str
    conflicting_fact_id: str | None
    justification: dict


def decide(
    result: ClassificationResult,
    *,
    capture_id: str,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Decision:
    """Deterministic lookup table. See BUILD_PLAN.md §2.2 for the exact rules:

    - new (any confidence) -> auto-write.
    - contradiction -> never auto-resolved, always goes to review, regardless of confidence.
    - update / context_dependent_both -> auto-apply if confidence >= threshold, else review.
    - Anything below threshold -> review, regardless of classification.
    """
    justification = {
        "classification": result.classification,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "threshold_used": confidence_threshold,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "capture_id": capture_id,
        "conflicting_fact_id": result.conflicting_fact_id,
    }

    if result.classification == "new":
        return Decision(Action.WRITE_NEW, capture_id, None, justification)

    if result.classification == "contradiction":
        justification["review_reason"] = "contradiction is never auto-resolved"
        return Decision(Action.REVIEW, capture_id, result.conflicting_fact_id, justification)

    if result.classification not in ("update", "context_dependent_both"):
        raise ValueError(f"Unhandled classification: {result.classification!r}")

    if result.confidence < confidence_threshold:
        justification["review_reason"] = (
            f"confidence {result.confidence:.2f} below threshold {confidence_threshold:.2f}"
        )
        return Decision(Action.REVIEW, capture_id, result.conflicting_fact_id, justification)

    action = Action.SUPERSEDE if result.classification == "update" else Action.DUAL_RETAIN
    return Decision(action, capture_id, result.conflicting_fact_id, justification)


def resolved_action_for(classification: str) -> Action | None:
    """The mechanical action for a *confirmed* classification (human accept/override), bypassing
    the confidence gate — there's nothing left to be uncertain about once a human confirms it.

    contradiction has no auto-resolution action even when confirmed: per BUILD_PLAN.md §2.2 it is
    never auto-resolved, full stop. A human confirming "yes, contradiction" doesn't produce a
    fact write on its own — that requires a further human decision (a new capture, a manual edit)
    that this system doesn't infer. Returns None in that case.
    """
    return {
        "new": Action.WRITE_NEW,
        "update": Action.SUPERSEDE,
        "context_dependent_both": Action.DUAL_RETAIN,
        "contradiction": None,
    }[classification]
