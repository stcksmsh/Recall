"""Display-only enrichment for one review item: fields ReviewItem doesn't carry (reasoning,
extractor_note, the conflicting fact's live scope) but that must show up in the TUI. Read-only —
never writes anything, and doesn't change src/consolidate/review.py's stored schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frontmatter

from src.consolidate.review import ReviewItem
from src.index.flush import _find_fact_path

BRAIN_ROOT = Path("brain")


@dataclass
class ConflictingFact:
    id: str
    content: str
    valid_at: str | None
    scope: str | None


@dataclass
class ReviewDetail:
    item: ReviewItem
    reasoning: str
    extractor_note: str | None
    conflicting_fact: ConflictingFact | None


def _find_episodic_capture(brain_root: Path, capture_id: str | None) -> dict | None:
    if not capture_id:
        return None
    episodic_dir = brain_root / "episodic"
    if not episodic_dir.exists():
        return None
    for path in episodic_dir.rglob("*.md"):
        post = frontmatter.load(path)
        if post.get("id") == capture_id:
            return dict(post.metadata)
    return None


def load_detail(item: ReviewItem, *, brain_root: Path = BRAIN_ROOT) -> ReviewDetail:
    post = frontmatter.load(item.path)
    justification = post.get("justification", {}) or {}
    reasoning = justification.get("reasoning") or "(no reasoning recorded)"

    capture_meta = _find_episodic_capture(brain_root, item.capture_id)
    extractor_note = capture_meta.get("extractor_note") if capture_meta else None

    conflicting_fact = None
    if item.conflicting_fact_id:
        candidate = next(
            (f for f in item.candidate_facts if f.get("id") == item.conflicting_fact_id), None
        )
        content = candidate.get("content") if candidate else None
        valid_at = candidate.get("valid_at") if candidate else None
        scope = None
        # candidate_facts (captured at classification time) carries no scope field at all;
        # look the live fact up for it, and refresh content/valid_at from the source of truth
        # while we're there rather than trusting a possibly-stale snapshot.
        fact_path = _find_fact_path(brain_root, item.conflicting_fact_id)
        if fact_path is not None:
            fact_post = frontmatter.load(fact_path)
            content = fact_post.content or content
            valid_at = fact_post.get("valid_at") or valid_at
            scope = fact_post.get("scope")
        conflicting_fact = ConflictingFact(
            id=item.conflicting_fact_id, content=content or "(fact text unavailable)",
            valid_at=valid_at, scope=scope,
        )

    return ReviewDetail(
        item=item, reasoning=reasoning, extractor_note=extractor_note,
        conflicting_fact=conflicting_fact,
    )
