"""Correction data loop (ARCHITECTURE.md §7). Every human accept/override of a review-queue item
is a labeled training example: (facts_in, classification_given, confidence_given,
correct_classification). Structural from v0, local-only — no aggregate/hosted contribution wired
up here, and none should be added without an explicit opt-in per the architecture doc.
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
    post["recorded_at"] = datetime.now(timezone.utc).isoformat()

    path = directory / f"{correction_id}.md"
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path
