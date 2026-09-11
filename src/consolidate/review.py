"""Review queue interaction: list pending items, accept the classifier's original call, or
override it with a human-supplied classification. Both accept and override are the "human, or a
second stronger-model pass" resolution path referenced in ARCHITECTURE.md §2, and both always
record a correction (§7) — accept is a confirmation label, not a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from src.consolidate.classifier import VALID_CLASSIFICATIONS
from src.consolidate.corrections import record_correction
from src.consolidate.executor import Decision, resolved_action_for
from src.index.flush import flush

BRAIN_ROOT = Path("brain")


@dataclass
class ReviewItem:
    id: str
    capture_id: str
    captured_at: str
    content: str
    classification_given: str
    confidence_given: float
    conflicting_fact_id: str | None
    candidate_facts: list[dict]
    path: Path


def _review_queue_dir(brain_root: Path) -> Path:
    return brain_root / "semantic" / "review_queue"


def _load_review_item(path: Path) -> ReviewItem:
    post = frontmatter.load(path)
    justification = post.get("justification", {})
    return ReviewItem(
        id=post["id"],
        capture_id=post.get("capture_id"),
        captured_at=post.get("captured_at"),
        content=post.content,
        classification_given=justification.get("classification"),
        confidence_given=justification.get("confidence"),
        conflicting_fact_id=justification.get("conflicting_fact_id"),
        candidate_facts=post.get("candidate_facts", []),
        path=path,
    )


def list_pending(*, brain_root: Path = BRAIN_ROOT) -> list[ReviewItem]:
    directory = _review_queue_dir(brain_root)
    if not directory.exists():
        return []
    items = [_load_review_item(p) for p in sorted(directory.glob("*.md"))]
    return [item for item in items if frontmatter.load(item.path).get("status") == "pending"]


def _find_pending(review_id: str, brain_root: Path) -> ReviewItem:
    for item in list_pending(brain_root=brain_root):
        if item.id == review_id:
            return item
    raise ValueError(f"No pending review item with id {review_id!r}")


def _resolve(
    item: ReviewItem,
    *,
    correct_classification: str,
    status: str,
    brain_root: Path,
    reviewer_note: str | None = None,
) -> Path | None:
    record_correction(
        review_item_id=item.id,
        capture_id=item.capture_id,
        facts_in=item.candidate_facts,
        new_capture_content=item.content,
        classification_given=item.classification_given,
        confidence_given=item.confidence_given,
        correct_classification=correct_classification,
        reviewer_note=reviewer_note,
        brain_root=brain_root,
    )

    fact_path = None
    action = resolved_action_for(correct_classification)
    if action is not None:
        justification = {
            "classification": correct_classification,
            "confidence": 1.0,
            "reasoning": f"human-{status} from review queue (originally: {item.classification_given})",
            "capture_id": item.capture_id,
            "conflicting_fact_id": item.conflicting_fact_id,
            "review_item_id": item.id,
        }
        decision = Decision(action, item.capture_id, item.conflicting_fact_id, justification)
        fact_path = flush(
            decision,
            capture_content=item.content,
            captured_at=item.captured_at,
            brain_root=brain_root,
            candidate_facts=item.candidate_facts,
        )

    post = frontmatter.load(item.path)
    post["status"] = status
    post["correct_classification"] = correct_classification
    post["resolved_at"] = datetime.now(timezone.utc).isoformat()
    item.path.write_bytes(frontmatter.dumps(post).encode("utf-8"))

    return fact_path


def accept(
    review_id: str, *, reviewer_note: str | None = None, brain_root: Path = BRAIN_ROOT
) -> Path | None:
    """Confirm the classifier's original classification was correct and apply its action.
    reviewer_note is optional free text recorded on the correction only -- why this was right,
    if that's worth writing down."""
    item = _find_pending(review_id, brain_root)
    return _resolve(
        item, correct_classification=item.classification_given, status="accepted",
        brain_root=brain_root, reviewer_note=reviewer_note,
    )


def override(
    review_id: str, correct_classification: str, *, reviewer_note: str | None = None,
    brain_root: Path = BRAIN_ROOT,
) -> Path | None:
    """Supply the classification the classifier should have given, and apply its action instead.
    reviewer_note is optional free text recorded on the correction only -- why the classifier
    was wrong, if that's worth writing down."""
    if correct_classification not in VALID_CLASSIFICATIONS:
        raise ValueError(f"Invalid classification: {correct_classification!r}")
    item = _find_pending(review_id, brain_root)
    return _resolve(
        item, correct_classification=correct_classification, status="overridden",
        brain_root=brain_root, reviewer_note=reviewer_note,
    )
