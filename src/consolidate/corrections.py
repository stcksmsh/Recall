"""Correction data loop (ARCHITECTURE.md §7). Every human accept/override of a review-queue item
is a labeled training example: (facts_in, classification_given, confidence_given,
correct_classification). Structural from v0, local-only — no aggregate/hosted contribution wired
up here, and none should be added without an explicit opt-in per the architecture doc.

`reviewer_note` is an optional fifth field: the human's own reason for the call, free text. It
exists on the correction record only (not mirrored onto the resolved review-queue item) — this
is the compounding-asset side of the loop (future retraining signal), not an audit trail of the
queue itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

BRAIN_ROOT = Path("brain")


def record_correction(
    *,
    review_item_id: str,
    capture_id: str,
    facts_in: list[dict],
    new_capture_content: str,
    classification_given: str,
    confidence_given: float,
    correct_classification: str,
    reviewer_note: str | None = None,
    brain_root: Path = BRAIN_ROOT,
) -> Path:
    directory = brain_root / "semantic" / "corrections"
    directory.mkdir(parents=True, exist_ok=True)
    correction_id = str(uuid.uuid4())

    post = frontmatter.Post(new_capture_content)
    post["id"] = correction_id
    post["review_item_id"] = review_item_id
    post["capture_id"] = capture_id
    post["facts_in"] = facts_in
    post["classification_given"] = classification_given
    post["confidence_given"] = confidence_given
    post["correct_classification"] = correct_classification
    post["reviewer_note"] = reviewer_note
    post["recorded_at"] = datetime.now(timezone.utc).isoformat()

    path = directory / f"{correction_id}.md"
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path
